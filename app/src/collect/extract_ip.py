"""IP extraction from event titles via Claude Gateway."""
import json
import os
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

GATEWAY_URL_DEFAULT = os.getenv("CLAUDE_GATEWAY_URL", "http://127.0.0.1:18080")
GATEWAY_CALLER = "otakuracy"


@dataclass
class IpExtraction:
    title: str
    ip_name: str | None   # None = 不明
    confidence: float     # 0.0〜1.0


def _call_gateway(titles: list[str], gateway_url: str) -> list[IpExtraction]:
    """
    Haiku にバッチでタイトルを送り IP 名を抽出する。
    戻り値は titles と同じ順序の IpExtraction リスト。
    """
    prompt = f"""以下のイベントタイトルリストを解析し、それぞれのメインIP（アニメ・マンガ・VTuber・ゲームの作品名またはアーティスト・キャラクター名）を抽出してください。

ルール:
- IPが特定できる場合は正式な作品名・アーティスト名を返す
- 複数IPが含まれる場合はメインのものを1つ
- IPが特定できない場合は null を返す
- confidenceは0.0〜1.0で自信度を示す

タイトルリスト:
{json.dumps(titles, ensure_ascii=False)}

JSON配列で返してください（タイトルと同じ順序）:
[
  {{"ip_name": "推しの子", "confidence": 0.95}},
  {{"ip_name": null, "confidence": 0.0}},
  ...
]"""

    payload = {
        "caller": GATEWAY_CALLER,
        "provider": "claude",
        "model": "claude-haiku-4-5-20251001",
        "prompt": prompt,
        "response_format": "json",
        "execution_mode": "sync",
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{gateway_url.rstrip('/')}/v1/generate",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if not result.get("success"):
        raise RuntimeError(f"Gateway error: {result.get('error_message')}")

    output = result["output_text"].strip()
    # Haikuがコードブロック付きで返すケースを剥がす
    if output.startswith("```"):
        output = output.split("```")[1]
        if output.startswith("json"):
            output = output[4:]
        output = output.strip()
    parsed = json.loads(output)
    return [
        IpExtraction(
            title=titles[i],
            ip_name=item.get("ip_name"),
            confidence=float(item.get("confidence", 0.0)),
        )
        for i, item in enumerate(parsed)
    ]


def extract_ip_batch(
    records: list,  # list[RawEventRecord]
    ip_repo,        # IpRegistryRepo
    gateway_url: str = GATEWAY_URL_DEFAULT,
    batch_size: int = 20,
) -> dict[str, tuple[str | None, float]]:
    """
    RawEventRecord リストの各タイトルから IP を抽出する。

    戦略:
    1. ip_registry の display_name / aliases と文字列マッチ（コスト0）
    2. マッチしなかったものだけ Gateway（Haiku）でバッチ処理
    3. 抽出結果を ip_registry に candidate として upsert

    Returns: {source_url: (ip_id or None, confidence)}
    """
    result: dict[str, tuple[str | None, float]] = {}
    unmatched: list = []  # string-match で見つからなかった records

    # 1. 文字列マッチ（ip_registry の既存エントリ）
    # active/candidate 問わず全エントリを取得してマッチ
    # IpRegistryRepo に list_all がないので直接 SQL
    all_ips = ip_repo.conn.execute(
        "SELECT ip_id, display_name, aliases FROM ip_registry"
    ).fetchall()

    for rec in records:
        matched_id = None
        title_lower = rec.raw_title.lower()
        for row in all_ips:
            if row["display_name"].lower() in title_lower:
                matched_id = row["ip_id"]
                break
            # aliases は JSON 配列
            try:
                aliases = json.loads(row["aliases"] or "[]")
                if any(a.lower() in title_lower for a in aliases):
                    matched_id = row["ip_id"]
                    break
            except Exception:
                pass
        if matched_id:
            result[rec.source_url] = (matched_id, 1.0)
        else:
            unmatched.append(rec)

    if not unmatched:
        return result

    # 2. Gateway（Haiku）でバッチ処理
    for i in range(0, len(unmatched), batch_size):
        batch = unmatched[i:i + batch_size]
        titles = [r.raw_title for r in batch]
        try:
            extractions = _call_gateway(titles, gateway_url)
        except Exception:
            # Gateway が落ちていても pipeline を止めない
            for rec in batch:
                result[rec.source_url] = (None, 0.0)
            continue

        for rec, ext in zip(batch, extractions):
            if ext.ip_name:
                # ip_registry に candidate として upsert
                ip_id = ip_repo.upsert(ext.ip_name, status="candidate")
                result[rec.source_url] = (ip_id, ext.confidence)
            else:
                result[rec.source_url] = (None, 0.0)

    return result
