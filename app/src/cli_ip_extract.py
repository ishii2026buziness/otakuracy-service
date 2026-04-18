"""Standalone IP extraction job — processes unlinked events from DB via claude-gateway."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from collect.base import RawEventRecord
from collect.extract_ip import extract_ip_batch
from db.repository import DB_PATH_DEFAULT, EventIpLinkRepo, IpRegistryRepo, get_connection, init_db


def run(db_path: Path, gateway_url: str, batch_size: int = 20, limit: int = 500) -> int:
    init_db(db_path)
    conn = get_connection(db_path)

    rows = conn.execute(
        """
        SELECT e.event_id, e.title, e.official_url
        FROM event e
        WHERE e.event_id NOT IN (SELECT event_id FROM event_ip_link)
          AND e.official_url IS NOT NULL
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not rows:
        print("no unlinked events", flush=True)
        conn.close()
        return 0

    print(f"[ip-extract] {len(rows)} unlinked events → gateway {gateway_url}", flush=True)

    records = [
        RawEventRecord(
            source_id="db",
            source_url=row["official_url"],
            fetched_at=datetime.now(timezone.utc),
            raw_title=row["title"],
            raw_date_text=None,
            raw_venue_text=None,
            raw_price_text=None,
            raw_body=None,
        )
        for row in rows
    ]

    ip_repo = IpRegistryRepo(conn)
    ip_link_repo = EventIpLinkRepo(conn)
    url_to_event = {row["official_url"]: row["event_id"] for row in rows}

    ip_map = extract_ip_batch(records, ip_repo, gateway_url=gateway_url, batch_size=batch_size)

    linked = 0
    for source_url, (ip_id, confidence, _category) in ip_map.items():
        event_id = url_to_event.get(source_url)
        if not event_id or not ip_id:
            continue
        ip_link_repo.link(event_id, ip_id, relation_type="primary", confidence=confidence)
        linked += 1

    conn.commit()
    conn.close()
    print(f"[ip-extract] done: {linked}/{len(rows)} linked", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(prog="cli_ip_extract")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("--db", default=str(DB_PATH_DEFAULT))
    p.add_argument("--gateway", default="http://127.0.0.1:18080")
    p.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    sys.exit(run(Path(args.db), args.gateway, limit=args.limit))


if __name__ == "__main__":
    main()
