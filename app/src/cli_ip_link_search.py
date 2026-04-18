"""CLI: ip_registry 部分一致で event_ip_link を埋めるジョブ。

Claude 不要。ヒットしなかったイベントは event_ip_link にレコードを作らない
（= ip-link-agent ジョブが後続で処理する）。
"""
import argparse
import sys
from pathlib import Path

from collect.ip_link.searcher import IpSearcher
from db.repository import DB_PATH_DEFAULT, EventIpLinkRepo, get_connection, init_db


def run(db_path: Path, limit: int = 2000, dry_run: bool = False) -> int:
    init_db(db_path)
    conn = get_connection(db_path)

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
        print("[ip-link-search] no unlinked events", flush=True)
        conn.close()
        return 0

    print(f"[ip-link-search] {len(rows)} unlinked events", flush=True)

    searcher = IpSearcher(conn)
    ip_link_repo = EventIpLinkRepo(conn)

    hit = miss = 0
    for row in rows:
        ip_id = searcher.search(row["title"])
        if ip_id:
            if not dry_run:
                ip_link_repo.link(row["event_id"], ip_id, relation_type="primary", confidence=0.9)
            hit += 1
        else:
            miss += 1

    conn.close()
    print(
        f"[ip-link-search] done: hit={hit} miss={miss} (miss → ip-link-agent へ)",
        flush=True,
    )
    return 0


def main():
    parser = argparse.ArgumentParser(prog="cli_ip_link_search")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run")
    p.add_argument("--db", default=str(DB_PATH_DEFAULT))
    p.add_argument("--limit", type=int, default=2000)
    p.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    sys.exit(run(Path(args.db), limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
