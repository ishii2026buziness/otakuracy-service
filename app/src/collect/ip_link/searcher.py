"""IP名検索: イベントタイトルに含まれる IP を ip_registry から部分一致で探す。

Claude 不要。DB 検索のみで完結する独立ジョブ。
見つからなかったイベントは event_ip_link にレコードを作らず、
後続の ip-link-agent ジョブに委ねる。
"""
import sqlite3
from typing import Optional


_SEARCH_SQL = """
SELECT ip_id FROM (
    SELECT ip_id, display_name AS name
    FROM ip_registry
    WHERE length(display_name) >= 3 AND status != 'blocked'
    UNION ALL
    SELECT a.ip_id, a.alias AS name
    FROM ip_alias a
    JOIN ip_registry r ON r.ip_id = a.ip_id
    WHERE length(a.alias) >= 3 AND r.status != 'blocked'
)
WHERE instr(:title, name) > 0
ORDER BY length(name) DESC
LIMIT 1
"""


class IpSearcher:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def search(self, event_title: str) -> Optional[str]:
        """イベントタイトルに部分一致する ip_id を返す。ヒットなしは None。"""
        row = self.conn.execute(_SEARCH_SQL, {"title": event_title}).fetchone()
        return row[0] if row else None

    def search_batch(self, events: list[dict]) -> dict[str, Optional[str]]:
        """events: [{"event_id": ..., "title": ...}] → {event_id: ip_id or None}"""
        return {e["event_id"]: self.search(e["title"]) for e in events}
