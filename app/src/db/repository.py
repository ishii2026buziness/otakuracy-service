"""SQLite repository layer for otakuracy."""
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _parse_date(raw_date_text: str | None) -> str | None:
    """'2026/4/12(日)' or '2026-04-12' → 'YYYY-MM-DD'. Takes first date if multiple."""
    if not raw_date_text:
        return None
    m = re.search(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", raw_date_text)
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _make_event_id(title: str, start_date: str | None) -> str:
    """Deterministic event_id from title + start_date to prevent duplicate inserts."""
    key = f"{title}|{start_date or ''}"
    h = hashlib.sha1(key.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _json_field(value) -> str:
    """Serialize a list/dict to JSON string, pass through str as-is."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value if value is not None else "[]"

DB_PATH_DEFAULT = Path("/data/otakuracy.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(db_path: Path = DB_PATH_DEFAULT) -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode and row_factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DB_PATH_DEFAULT) -> None:
    """Initialize the database schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()


class IpAliasRepo:
    """CRUD for ip_alias table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def set_aliases(self, ip_id: str, aliases: list[str], source: str) -> None:
        """指定 source の aliases を洗い替えする。"""
        self.conn.execute(
            "DELETE FROM ip_alias WHERE ip_id = ? AND source = ?",
            (ip_id, source),
        )
        self.conn.executemany(
            "INSERT OR IGNORE INTO ip_alias (ip_id, alias, source) VALUES (?, ?, ?)",
            [(ip_id, a, source) for a in aliases if a],
        )

    def add(self, ip_id: str, alias: str, source: str, lang: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO ip_alias (ip_id, alias, lang, source) VALUES (?, ?, ?, ?)",
            (ip_id, alias, lang, source),
        )

    def list_for_ip(self, ip_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM ip_alias WHERE ip_id = ? ORDER BY alias",
            (ip_id,),
        ).fetchall()


class IpRegistryRepo:
    """CRUD for ip_registry table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, display_name: str, **kwargs) -> str:
        """Insert or update by display_name. Returns ip_id."""
        now = datetime.now(timezone.utc).isoformat()

        existing = self.get_by_name(display_name)
        if existing is not None:
            ip_id = existing["ip_id"]
            allowed = {
                "official_url", "status", "activation_score",
                "last_event_seen_at", "last_verified_at", "domain_tags",
            }
            updates = {k: v for k, v in kwargs.items() if k in allowed}
            updates["updated_at"] = now
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            params = {**updates, "ip_id": ip_id}
            self.conn.execute(
                f"UPDATE ip_registry SET {set_clause} WHERE ip_id = :ip_id",
                params,
            )
            self.conn.commit()
            return ip_id

        ip_id = str(uuid.uuid4())
        row = {
            "ip_id": ip_id,
            "display_name": display_name,
            "official_url": kwargs.get("official_url"),
            "status": kwargs.get("status", "candidate"),
            "activation_score": kwargs.get("activation_score", 0.0),
            "last_event_seen_at": kwargs.get("last_event_seen_at"),
            "last_verified_at": kwargs.get("last_verified_at"),
            "domain_tags": _json_field(kwargs.get("domain_tags", "[]")),
            "created_at": now,
            "updated_at": now,
        }
        self.conn.execute(
            """
            INSERT INTO ip_registry
                (ip_id, display_name, official_url, status, activation_score,
                 last_event_seen_at, last_verified_at, domain_tags,
                 created_at, updated_at)
            VALUES
                (:ip_id, :display_name, :official_url, :status, :activation_score,
                 :last_event_seen_at, :last_verified_at, :domain_tags,
                 :created_at, :updated_at)
            """,
            row,
        )
        self.conn.commit()
        return ip_id

    def get_by_name(self, display_name: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM ip_registry WHERE display_name = ?",
            (display_name,),
        )
        return cur.fetchone()

    def get_by_id(self, ip_id: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM ip_registry WHERE ip_id = ?",
            (ip_id,),
        )
        return cur.fetchone()

    def list_active(self) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM ip_registry WHERE status = 'active' ORDER BY display_name"
        )
        return cur.fetchall()

    def list_by_status(self, status: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM ip_registry WHERE status = ? ORDER BY display_name",
            (status,),
        )
        return cur.fetchall()


class EventSourceRecordRepo:
    """CRUD for event_source_record table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, record: dict) -> str:
        """Insert a raw event record. Returns source_record_id."""
        source_record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "source_record_id": source_record_id,
            "source_id": record["source_id"],
            "source_url": record["source_url"],
            "fetched_at": record.get("fetched_at", now),
            "raw_title": record.get("raw_title"),
            "raw_date_text": record.get("raw_date_text"),
            "raw_venue_text": record.get("raw_venue_text"),
            "raw_price_text": record.get("raw_price_text"),
            "raw_body": record.get("raw_body"),
            "extracted_by": record.get("extracted_by", "scraping"),
            "confidence": record.get("confidence", 1.0),
            "parse_version": record.get("parse_version", "1"),
            "event_id": record.get("event_id"),
            "created_at": now,
        }
        self.conn.execute(
            """
            INSERT INTO event_source_record
                (source_record_id, source_id, source_url, fetched_at,
                 raw_title, raw_date_text, raw_venue_text, raw_price_text,
                 raw_body, extracted_by, confidence, parse_version,
                 event_id, created_at)
            VALUES
                (:source_record_id, :source_id, :source_url, :fetched_at,
                 :raw_title, :raw_date_text, :raw_venue_text, :raw_price_text,
                 :raw_body, :extracted_by, :confidence, :parse_version,
                 :event_id, :created_at)
            """,
            row,
        )
        self.conn.commit()
        return source_record_id

    def exists_by_url(self, source_url: str) -> bool:
        """Check if a source URL has already been collected."""
        cur = self.conn.execute(
            "SELECT 1 FROM event_source_record WHERE source_url = ? LIMIT 1",
            (source_url,),
        )
        return cur.fetchone() is not None

    def get_unresolved(self, source_id: Optional[str] = None) -> list[sqlite3.Row]:
        """Return records where event_id is NULL (not yet resolved)."""
        if source_id:
            cur = self.conn.execute(
                "SELECT * FROM event_source_record WHERE event_id IS NULL AND source_id = ?",
                (source_id,),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM event_source_record WHERE event_id IS NULL"
            )
        return cur.fetchall()

    def link_to_event(self, source_record_id: str, event_id: str) -> None:
        """Set event_id on a source record after resolution."""
        self.conn.execute(
            "UPDATE event_source_record SET event_id = ? WHERE source_record_id = ?",
            (event_id, source_record_id),
        )
        self.conn.commit()


class EventRepo:
    """CRUD for event table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, record: dict) -> str:
        """Insert event if not exists (idempotent). Returns event_id."""
        title = record["title"]
        start_at = record.get("start_at") or _parse_date(record.get("raw_date_text"))
        event_id = _make_event_id(title, start_at)
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "event_id": event_id,
            "title": title,
            "summary": record.get("summary"),
            "category": record.get("category"),
            "status": record.get("status", "announced"),
            "start_at": start_at,
            "end_at": record.get("end_at"),
            "tz": record.get("tz", "Asia/Tokyo"),
            "venue_id": record.get("venue_id"),
            "area_code": record.get("area_code"),
            "is_online": record.get("is_online", 0),
            "official_url": record.get("official_url"),
            "primary_ticket_url": record.get("primary_ticket_url"),
            "hero_image_url": record.get("hero_image_url"),
            "price_min": record.get("price_min"),
            "price_max": record.get("price_max"),
            "currency": record.get("currency", "JPY"),
            "ticketing_type": record.get("ticketing_type", "unknown"),
            "source_confidence": record.get("source_confidence", 0.5),
            "first_seen_at": record.get("first_seen_at", now),
            "last_seen_at": now,
        }
        self.conn.execute(
            """
            INSERT INTO event
                (event_id, title, summary, category, status, start_at, end_at, tz,
                 venue_id, area_code, is_online, official_url, primary_ticket_url,
                 hero_image_url, price_min, price_max, currency, ticketing_type,
                 source_confidence, first_seen_at, last_seen_at)
            VALUES
                (:event_id, :title, :summary, :category, :status, :start_at, :end_at, :tz,
                 :venue_id, :area_code, :is_online, :official_url, :primary_ticket_url,
                 :hero_image_url, :price_min, :price_max, :currency, :ticketing_type,
                 :source_confidence, :first_seen_at, :last_seen_at)
            ON CONFLICT(event_id) DO UPDATE SET
                category = excluded.category,
                last_seen_at = excluded.last_seen_at
            """,
            row,
        )
        self.conn.commit()
        return event_id

    def get_by_id(self, event_id: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM event WHERE event_id = ?", (event_id,)
        )
        return cur.fetchone()

    def update_last_seen(self, event_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE event SET last_seen_at = ? WHERE event_id = ?",
            (now, event_id),
        )
        self.conn.commit()

    def list_upcoming(
        self,
        category: Optional[str] = None,
        area_code: Optional[str] = None,
    ) -> list[sqlite3.Row]:
        """Return events with start_at >= now, optionally filtered."""
        now = datetime.now(timezone.utc).isoformat()
        clauses = ["start_at >= ?"]
        params: list = [now]
        if category:
            clauses.append("category = ?")
            params.append(category)
        if area_code:
            clauses.append("area_code = ?")
            params.append(area_code)
        where = " AND ".join(clauses)
        cur = self.conn.execute(
            f"SELECT * FROM event WHERE {where} ORDER BY start_at",
            params,
        )
        return cur.fetchall()


class EventIpLinkRepo:
    """CRUD for event_ip_link table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def link(
        self,
        event_id: str,
        ip_id: str,
        relation_type: str = "primary",
        confidence: float = 1.0,
    ) -> None:
        """Insert or replace an event-IP link."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO event_ip_link (event_id, ip_id, relation_type, confidence)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, ip_id, relation_type, confidence),
        )
        self.conn.commit()

    def get_ips_for_event(self, event_id: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM event_ip_link WHERE event_id = ?", (event_id,)
        )
        return cur.fetchall()

    def get_events_for_ip(self, ip_id: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM event_ip_link WHERE ip_id = ?", (ip_id,)
        )
        return cur.fetchall()
