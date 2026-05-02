"""Twitter raw tweet corpus collector.

イベントタイトルで完全一致検索し、ツイートをDBに保存する。
分析（BoW抽出）は別ステップで行う。
"""
import json
import sqlite3
import subprocess
import time

# スクレイピング元HTMLに混入しがちな特殊文字 → twitter-cli クォート破壊防止
_QUERY_TRANS = str.maketrans({
    '\xa0': ' ',    # NO-BREAK SPACE
    '‘': "'",  # LEFT SINGLE QUOTATION MARK
    '’': "'",  # RIGHT SINGLE QUOTATION MARK
    '“': '',   # LEFT DOUBLE QUOTATION MARK（クォート境界破壊のため除去）
    '”': '',   # RIGHT DOUBLE QUOTATION MARK
})


def _normalize_title(title: str) -> str:
    return title.translate(_QUERY_TRANS).strip()


def _twitter_search(query: str, max_count: int = 30) -> list[dict]:
    """完全一致フレーズ検索。tweet_id と text を返す。"""
    q = f'"{query}"'
    try:
        r = subprocess.run(
            ["twitter", "search", q, "-t", "Latest", f"--max={max_count}", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(r.stdout)
        return [
            {"tweet_id": t["id"], "text": t["text"]}
            for t in data.get("data", [])
            if t.get("id") and t.get("text")
        ]
    except Exception as exc:
        print(f"  [twitter error] {exc}", flush=True)
        return []


def collect_tweets(
    conn: sqlite3.Connection,
    limit: int = 200,
    max_per_event: int = 30,
    interval_sec: float = 2.0,
    dry_run: bool = False,
) -> dict:
    """未検索イベントのツイートを収集してDBに保存する。

    同一タイトル×会場のグループを1回だけ検索し、グループ内の全event_idに結果を紐付ける。
    limit はユニークな検索クエリ数（グループ数）の上限。

    Returns: {"collected": int, "empty": int, "skipped": int}
    """
    # 未ログのevent_idを (normalized_title, venue_id) でグループ化して取得
    rows = conn.execute(
        """
        SELECT e.event_id, e.title, COALESCE(e.venue_id, '') AS vkey
        FROM event e
        WHERE e.event_id NOT IN (SELECT event_id FROM tweet_search_log)
        ORDER BY e.start_at DESC
        """,
    ).fetchall()

    if not rows:
        print("[tweet-corpus] no uncrawled events", flush=True)
        return {"collected": 0, "empty": 0, "skipped": 0}

    # (normalized_title, vkey) → [event_ids] にグループ化
    groups: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        key = (_normalize_title(row["title"]), row["vkey"])
        groups.setdefault(key, []).append(row["event_id"])

    # limit はグループ数の上限
    group_items = list(groups.items())[:limit]
    print(f"[tweet-corpus] {len(group_items)} unique queries ({len(rows)} event_ids total)", flush=True)

    collected = empty = 0

    for (norm_title, _vkey), event_ids in group_items:
        tweets = _twitter_search(norm_title, max_count=max_per_event)

        if not dry_run:
            for t in tweets:
                conn.execute(
                    "INSERT OR IGNORE INTO tweets (tweet_id, text) VALUES (?, ?)",
                    (t["tweet_id"], t["text"]),
                )
            for eid in event_ids:
                for t in tweets:
                    conn.execute(
                        "INSERT OR IGNORE INTO event_tweet_link (event_id, tweet_id) VALUES (?, ?)",
                        (eid, t["tweet_id"]),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO tweet_search_log (event_id, tweet_count) VALUES (?, ?)",
                    (eid, len(tweets)),
                )
            conn.commit()

        label = norm_title[:40]
        n_ids = len(event_ids)
        if tweets:
            collected += 1
            print(f"  {label} → {len(tweets)} tweets ({n_ids} ids logged)", flush=True)
        else:
            empty += 1
            print(f"  {label} → 0 tweets ({n_ids} ids logged)", flush=True)

        time.sleep(interval_sec)

    return {"collected": collected, "empty": empty, "skipped": 0}
