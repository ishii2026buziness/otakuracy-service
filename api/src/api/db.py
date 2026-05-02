"""Read-only SQLite access for otakuracy API."""
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("/data/otakuracy.db")


def get_conn() -> sqlite3.Connection:
    # immutable=1 avoids WAL shm file creation (required for read-only hostPath)
    conn = sqlite3.connect(f"file:{DB_PATH}?immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

# Dedup CTE: 同タイトル×同会場の重複行をまとめ、1行に絞る。
# 優先順位: キーワード抽出済み > 画像あり > 最初に収集した行
_DEDUP_CTE = """
WITH deduped AS (
    SELECT e.*,
        ROW_NUMBER() OVER (
            PARTITION BY e.title, COALESCE(e.venue_id, '')
            ORDER BY
                (ek.event_id IS NOT NULL) DESC,
                (e.hero_image_url IS NOT NULL) DESC,
                e.first_seen_at ASC
        ) AS rn
    FROM event e
    LEFT JOIN (SELECT DISTINCT event_id FROM event_keywords) ek
        ON e.event_id = ek.event_id
)
"""

# ソート: 開催予定イベント（start_at >= 今日）を先頭に近い順、
# 過去イベントはその後に新しい順。日付なしは末尾。
_ORDER_SQL = """
ORDER BY
    CASE
        WHEN start_at IS NULL THEN 2
        WHEN start_at >= DATE('now') THEN 0
        ELSE 1
    END,
    CASE WHEN start_at >= DATE('now') THEN start_at END ASC,
    start_at DESC
"""


def search_events(
    q: str = "",
    tag: str = "",
    page: int = 1,
    limit: int = 24,
) -> tuple[list[dict[str, Any]], int]:
    """Full-text + tag search with dedup. Returns (items, total)."""
    conn = get_conn()
    params: list[Any] = []
    filter_clauses: list[str] = ["d.rn = 1"]

    if q:
        like = f"%{q}%"
        filter_clauses.append("(d.title LIKE ? OR d.summary LIKE ?)")
        params += [like, like]

    if tag:
        # タグ検索: 同グループ内のどれかがキーワードを持っていればOK
        filter_clauses.append(
            """(d.title, COALESCE(d.venue_id, '')) IN (
                SELECT e2.title, COALESCE(e2.venue_id, '')
                FROM event e2
                JOIN event_keywords ek2 ON e2.event_id = ek2.event_id
                WHERE ek2.keyword = ?
            )"""
        )
        params.append(tag)

    where_sql = "WHERE " + " AND ".join(filter_clauses)

    base_sql = f"""
        {_DEDUP_CTE}
        SELECT d.*, v.name AS venue_name
        FROM deduped d
        LEFT JOIN venue v ON d.venue_id = v.venue_id
        {where_sql}
    """

    total = conn.execute(f"SELECT COUNT(*) FROM ({base_sql})", params).fetchone()[0]

    offset = (page - 1) * limit
    data_sql = f"""
        SELECT
            event_id, title, summary, start_at, end_at, area_code,
            official_url, primary_ticket_url, hero_image_url,
            price_min, price_max, status, is_online, venue_name
        FROM ({base_sql})
        {_ORDER_SQL}
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(data_sql, params + [limit, offset]).fetchall()
    conn.close()
    return rows_to_dicts(rows), total


def get_event(event_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT
            e.*,
            v.name AS venue_name,
            v.area_code AS venue_area_code
        FROM event e
        LEFT JOIN venue v ON e.venue_id = v.venue_id
        WHERE e.event_id = ?
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        conn.close()
        return None
    result = dict(row)

    # keywords: このevent_idに加え、同タイトル×同会場グループ全体のキーワードを集約
    kw_rows = conn.execute(
        """
        SELECT ek.keyword, MAX(ek.weight) AS weight
        FROM event_keywords ek
        JOIN event e2 ON ek.event_id = e2.event_id
        WHERE e2.title = (SELECT title FROM event WHERE event_id = ?)
          AND COALESCE(e2.venue_id, '') = COALESCE(
                (SELECT venue_id FROM event WHERE event_id = ?), '')
        GROUP BY ek.keyword
        ORDER BY weight DESC
        """,
        (event_id, event_id),
    ).fetchall()
    result["keywords"] = [dict(r) for r in kw_rows]

    # linked IPs
    ip_rows = conn.execute(
        """
        SELECT ir.display_name, eil.confidence
        FROM event_ip_link eil
        JOIN ip_registry ir ON eil.ip_id = ir.ip_id
        WHERE eil.event_id = ?
        ORDER BY eil.confidence DESC
        """,
        (event_id,),
    ).fetchall()
    result["ips"] = [dict(r) for r in ip_rows]

    conn.close()
    return result


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def list_tags(q: str = "", limit: int = 50) -> list[dict]:
    # deduped イベント数でカウント（重複行を除外）
    conn = get_conn()
    params: list[Any] = []
    kw_where = ""
    if q:
        kw_where = "AND ek.keyword LIKE ?"
        params.append(f"%{q}%")
    rows = conn.execute(
        f"""
        WITH deduped_events AS (
            SELECT MIN(event_id) AS event_id, title, COALESCE(venue_id, '') AS vkey
            FROM event
            GROUP BY title, COALESCE(venue_id, '')
        )
        SELECT ek.keyword,
               COUNT(DISTINCT de.event_id) AS event_count,
               SUM(ek.weight) AS total_weight
        FROM event_keywords ek
        JOIN deduped_events de ON ek.event_id = de.event_id
        WHERE 1=1 {kw_where}
        GROUP BY ek.keyword
        ORDER BY event_count DESC, total_weight DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    conn.close()
    return rows_to_dicts(rows)


def get_events_for_tag(tag: str, page: int = 1, limit: int = 24) -> tuple[list[dict], int]:
    return search_events(tag=tag, page=page, limit=limit)
