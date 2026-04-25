"""Tweet corpus から固有名詞（IP名候補）を抽出して event_keywords に保存する。

MeCab では辞書未登録のアニメ固有名詞が飛ぶため、Claude Gateway で抽出する。
"""
import json
import os
import sqlite3
from urllib.request import Request, urlopen

GATEWAY_URL = os.getenv("CLAUDE_GATEWAY_URL", "http://127.0.0.1:18080")
GATEWAY_CALLER = "otakuracy"
MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 10  # イベント数/バッチ

_PROMPT_TEMPLATE = """\
以下は複数のイベントに関連するXのポスト（ツイート）です。
各イベントについて、ツイート群から「アニメ・マンガ・ゲーム・VTuber・アイドル等のIP名、作品名、キャラクター名」に相当する固有名詞を抽出してください。

ルール:
- 出現頻度が高いもの・特徴的なものを優先
- 一般的な名詞（「チケット」「公演」「ライブ」等）は除外
- 同一IPの表記ゆれは代表形に統一（例: 「ラブライブ」「ラブライブ！」→「ラブライブ！」）
- 確信が持てないものは除外（誤検出より未検出を優先）

イベントデータ:
{events_json}

以下のJSON形式で返してください（イベントと同じ順序）:
[
  {{"event_id": "xxx", "keywords": [{{"keyword": "Ave Mujica", "weight": 0.9}}, ...]}},
  ...
]"""


def _call_gateway(events: list[dict]) -> list[dict]:
    """events = [{"event_id": str, "tweets": [str, ...]}]"""
    prompt = _PROMPT_TEMPLATE.format(
        events_json=json.dumps(events, ensure_ascii=False, indent=2)
    )
    payload = {
        "caller": GATEWAY_CALLER,
        "provider": "claude",
        "model": MODEL,
        "prompt": prompt,
        "response_format": "json",
        "execution_mode": "sync",
    }
    req = Request(
        f"{GATEWAY_URL.rstrip('/')}/v1/generate",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if not result.get("success"):
        raise RuntimeError(f"Gateway error: {result.get('error_message')}")

    output = result["output_text"].strip()
    start = output.find("[")
    end = output.rfind("]") + 1
    if start != -1 and end > start:
        output = output[start:end]
    return json.loads(output)


def extract_keywords(
    conn: sqlite3.Connection,
    limit: int = 100,
    dry_run: bool = False,
) -> dict:
    """event_keywords が未登録のイベントを対象にキーワード抽出する。

    Returns: {"processed": int, "inserted": int, "error": int}
    """
    rows = conn.execute(
        """
        SELECT DISTINCT e.event_id, e.title
        FROM event e
        INNER JOIN event_tweet_link etl ON e.event_id = etl.event_id
        WHERE e.event_id NOT IN (SELECT DISTINCT event_id FROM event_keywords)
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not rows:
        print("[keyword-extract] no unprocessed events", flush=True)
        return {"processed": 0, "inserted": 0, "error": 0}

    print(f"[keyword-extract] {len(rows)} events to process", flush=True)

    processed = inserted = error = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]

        events_payload = []
        tweets_by_event: dict[str, list[str]] = {}
        for row in batch:
            tweets = [
                r[0]
                for r in conn.execute(
                    """
                    SELECT t.text FROM tweets t
                    INNER JOIN event_tweet_link etl ON t.tweet_id = etl.tweet_id
                    WHERE etl.event_id = ?
                    LIMIT 30
                    """,
                    (row["event_id"],),
                ).fetchall()
            ]
            if not tweets:
                continue
            tweets_by_event[row["event_id"]] = tweets
            events_payload.append({"event_id": row["event_id"], "tweets": tweets})

        if not events_payload:
            continue

        try:
            results = _call_gateway(events_payload)
        except Exception as exc:
            print(f"[keyword-extract] gateway error batch {i}: {exc}", flush=True)
            error += len(events_payload)
            continue

        for item in results:
            event_id = item.get("event_id")
            keywords = item.get("keywords", [])
            if not event_id or not keywords:
                continue
            tweets = tweets_by_event.get(event_id, [])
            if not dry_run:
                for kw in keywords:
                    keyword = kw["keyword"]
                    # TF = そのキーワードが含まれるツイート数 / 総ツイート数
                    tf = sum(1 for t in tweets if keyword.lower() in t.lower()) / len(tweets) if tweets else 0.0
                    conn.execute(
                        "INSERT OR REPLACE INTO event_keywords (event_id, keyword, weight) VALUES (?, ?, ?)",
                        (event_id, keyword, tf),
                    )
                conn.commit()
            inserted += len(keywords)
            processed += 1
            print(f"  {event_id}: {[k['keyword'] for k in keywords[:3]]}", flush=True)

    return {"processed": processed, "inserted": inserted, "error": error}
