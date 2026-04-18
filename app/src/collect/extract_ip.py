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
    category: str = "other"


def _call_gateway(titles: list[str], gateway_url: str) -> list[IpExtraction]:
    """
    Haiku にバッチでタイトルを送り IP 名を抽出する。
    戻り値は titles と同じ順序の IpExtraction リスト。
    """
    prompt = f"""以下のイベントタイトルリストを解析し、各イベントのIPとカテゴリを返してください。

IPの定義（これに該当するもののみ ip_name を返す）:
- 広く知られたアニメ・マンガ・ゲーム・小説などの商業作品タイトル
- 全国流通レベルの音楽アーティスト・バンド・声優
- 有名VTuber・全国区アイドルグループ

ip_name を null にすべきケース:
- 小規模・インディーズ・無名のアーティスト（知名度が判断できない場合も含む）
- イベント固有のサブタイトルや企画名
- 会場名・主催者名・スポンサー名
- 演劇・朗読劇のタイトル（商業IPでない場合）
- 確信が持てない場合（誤検出より未検出を優先）

categoryの値（必ずいずれか1つ）:
- "anime" : アニメ・マンガ・ゲーム作品関連
- "music" : 音楽ライブ・コンサート・リリイベ
- "voice_actor" : 声優イベント
- "idol" : アイドル・VTuber
- "stage" : 舞台・ミュージカル・朗読劇
- "sport" : スポーツ
- "other" : 上記に当てはまらない、または判断できない

ルール:
- 複数IPが含まれる場合はメインのものを1つだけ
- 正式な作品名・アーティスト名の表記を使う

タイトルリスト:
{json.dumps(titles, ensure_ascii=False)}

JSON配列で返してください（タイトルと同じ順序）:
[
  {{"ip_name": "推しの子", "confidence": 0.95, "category": "anime"}},
  {{"ip_name": null, "confidence": 0.0, "category": "other"}},
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
            category=item.get("category", "other"),
        )
        for i, item in enumerate(parsed)
    ]


def extract_ip_batch(
    records: list,  # list[RawEventRecord]
    ip_repo,        # IpRegistryRepo
    gateway_url: str = GATEWAY_URL_DEFAULT,
    batch_size: int = 20,
) -> dict[str, tuple[str | None, float, str]]:
    """
    RawEventRecord リストの各タイトルから IP とカテゴリを抽出する。

    戦略:
    1. ip_registry の display_name / aliases と文字列マッチ（コスト0）
    2. マッチしなかったものだけ Gateway（Haiku）でバッチ処理
    3. 抽出結果を ip_registry に candidate として upsert

    Returns: {source_url: (ip_id or None, confidence, category)}
    """
    result: dict[str, tuple[str | None, float, str]] = {}
    unmatched: list = []

    # 1. 文字列マッチ（ip_registry + ip_alias）
    from collect.ip_link.searcher import IpSearcher
    searcher = IpSearcher(ip_repo.conn)

    for rec in records:
        matched_id = searcher.search(rec.raw_title or "")
        if matched_id:
            result[rec.source_url] = (matched_id, 1.0, "other")
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
            for rec in batch:
                result[rec.source_url] = (None, 0.0, "other")
            continue

        for rec, ext in zip(batch, extractions):
            if ext.ip_name:
                ip_id = ip_repo.upsert(ext.ip_name, status="candidate")
                result[rec.source_url] = (ip_id, ext.confidence, ext.category)
            else:
                result[rec.source_url] = (None, 0.0, ext.category)

    return result
