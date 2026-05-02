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

def search_events(
    q: str = "",
    tag: str = "",
    page: int = 1,
    limit: int = 24,
) -> tuple[list[dict[str, Any]], int]:
    """Full-text + tag search. Returns (items, total)."""
    conn = get_conn()
    params: list[Any] = []
    where_clauses: list[str] = []

    if q:
        like = f"%{q}%"
        where_clauses.append(
            "(e.title LIKE ? OR e.summary LIKE ?)"
        )
        params += [like, like]

    if tag:
        where_clauses.append(
            "e.event_id IN (SELECT event_id FROM event_keywords WHERE keyword = ?)"
        )
        params.append(tag)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_sql = f"""
        SELECT COUNT(*) FROM event e
        LEFT JOIN venue v ON e.venue_id = v.venue_id
        {where_sql}
    """
    total = conn.execute(count_sql, params).fetchone()[0]

    offset = (page - 1) * limit
    data_sql = f"""
        SELECT
            e.event_id,
            e.title,
            e.summary,
            e.start_at,
            e.end_at,
            e.area_code,
            e.official_url,
            e.primary_ticket_url,
            e.hero_image_url,
            e.price_min,
            e.price_max,
            e.status,
            e.is_online,
            v.name AS venue_name
        FROM event e
        LEFT JOIN venue v ON e.venue_id = v.venue_id
        {where_sql}
        ORDER BY e.start_at ASC NULLS LAST
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

    # keywords
    kw_rows = conn.execute(
        "SELECT keyword, weight FROM event_keywords WHERE event_id = ? ORDER BY weight DESC",
        (event_id,),
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
    conn = get_conn()
    params: list[Any] = []
    where = ""
    if q:
        where = "WHERE keyword LIKE ?"
        params.append(f"%{q}%")
    rows = conn.execute(
        f"""
        SELECT keyword, COUNT(*) AS event_count, SUM(weight) AS total_weight
        FROM event_keywords
        {where}
        GROUP BY keyword
        ORDER BY event_count DESC, total_weight DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    conn.close()
    return rows_to_dicts(rows)


def get_events_for_tag(tag: str, page: int = 1, limit: int = 24) -> tuple[list[dict], int]:
    return search_events(tag=tag, page=page, limit=limit)
