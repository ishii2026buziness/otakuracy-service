"""Agent-based IP linking via Claude Gateway.

extract_ip.pyと同じGatewayプロトコルを使用。
ip-link-searchで未ヒットのイベントを対象に、Claudeでip_registryを特定・候補追加する。
"""
import json
import os
import sqlite3
from urllib.error import URLError
from urllib.request import Request, urlopen

GATEWAY_URL = os.getenv("CLAUDE_GATEWAY_URL", "http://127.0.0.1:18080")
GATEWAY_CALLER = "otakuracy"
MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 20

_PROMPT_TEMPLATE = """以下のイベントタイトルリストを解析し、各イベントが何のIP（知的財産）に関連しているか特定してください。

対象とするIP:
- アニメ・マンガ・ゲーム・VTuber・アイドルグループ・声優など

ip_nameをnullにすべきケース:
- 特定のIPに紐付かない一般イベント（例: 抽象的なコスプレイベント、同人即売会全般）
- 小規模・無名のコンテンツで確信が持てない場合（誤検出より未検出を優先）

domain_tagsの値: anime / manga / game / vtuber / idol / voice_actor / stage / other

タイトルリスト:
{titles_json}

JSON配列で返してください（タイトルと同じ順序）:
[
  {{"ip_name": "ラブライブ！", "aliases": ["ラブライブ", "Love Live!"], "domain_tags": ["anime"], "confidence": 0.95}},
  {{"ip_name": null, "reason": "特定不能"}},
  ...
]"""


def _call_gateway(titles: list[str]) -> list[dict]:
    prompt = _PROMPT_TEMPLATE.format(titles_json=json.dumps(titles, ensure_ascii=False))
    payload = {
        "caller": GATEWAY_CALLER,
        "provider": "claude",
        "model": MODEL,
        "prompt": prompt,
        "response_format": "json",
        "execution_mode": "sync",
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{GATEWAY_URL.rstrip('/')}/v1/generate",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if not result.get("success"):
        raise RuntimeError(f"Gateway error: {result.get('error_message')}")

    output = result["output_text"].strip()
    # Claudeが前置き文を書いてからJSONブロックを返す場合に対応
    start = output.find("[")
    end = output.rfind("]") + 1
    if start != -1 and end > start:
        output = output[start:end]
    return json.loads(output)


def run_agent(
    conn: sqlite3.Connection,
    ip_registry_repo,
    ip_alias_repo,
    event_ip_link_repo,
    limit: int = 500,
    dry_run: bool = False,
) -> dict:
    """ip-link-searchで未ヒットのイベントを対象にGatewayでIP特定する。

    Returns: {"hit": int, "unresolvable": int, "error": int}
    """
    rows = conn.execute(
        """
        SELECT e.event_id, e.title
        FROM event e
        WHERE e.event_id NOT IN (SELECT event_id FROM event_ip_link)
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not rows:
        return {"hit": 0, "unresolvable": 0, "error": 0}

    print(f"[ip-link-agent] {len(rows)} unlinked events", flush=True)

    hit = unresolvable = error = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        titles = [r["title"] for r in batch]
        try:
            results = _call_gateway(titles)
        except (URLError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"[ip-link-agent] gateway error batch {i}: {exc}", flush=True)
            error += len(batch)
            continue

        for row, item in zip(batch, results):
            event_id = row["event_id"]
            ip_name = item.get("ip_name")
            if ip_name:
                if not dry_run:
                    aliases = item.get("aliases", [])
                    domain_tags = item.get("domain_tags", [])
                    ip_id = ip_registry_repo.upsert(
                        ip_name,
                        status="candidate",
                        domain_tags=json.dumps(domain_tags, ensure_ascii=False),
                    )
                    for alias in aliases:
                        ip_alias_repo.add(ip_id, alias, source="agent")
                    conn.commit()
                    event_ip_link_repo.link(
                        event_id, ip_id, relation_type="primary", confidence=item.get("confidence", 0.7)
                    )
                hit += 1
            else:
                if not dry_run:
                    event_ip_link_repo.link(event_id, "unresolvable", relation_type="primary", confidence=1.0)
                unresolvable += 1

    return {"hit": hit, "unresolvable": unresolvable, "error": error}
