"""CLI: Gateway（Haiku）で未リンクイベントのIPを特定するジョブ。

ip-link-searchで見つからなかったイベントを対象に、Claudeで IP 特定 → candidate 登録 → リンク。
特定不能は event_ip_link.ip_id = 'unresolvable' にリンクしてスキップ対象にする。
"""
import argparse
import sys
from pathlib import Path

from collect.ip_link.agent import run_agent
from db.repository import DB_PATH_DEFAULT, EventIpLinkRepo, IpAliasRepo, IpRegistryRepo, get_connection, init_db


def run(db_path: Path, limit: int = 500, dry_run: bool = False) -> int:
    init_db(db_path)
    conn = get_connection(db_path)

    stats = run_agent(
        conn=conn,
        ip_registry_repo=IpRegistryRepo(conn),
        ip_alias_repo=IpAliasRepo(conn),
        event_ip_link_repo=EventIpLinkRepo(conn),
        limit=limit,
        dry_run=dry_run,
    )
    conn.close()

    print(
        f"[ip-link-agent] done: hit={stats['hit']} unresolvable={stats['unresolvable']} error={stats['error']}"
        + (" (dry-run)" if dry_run else ""),
        flush=True,
    )
    return 0


def main():
    parser = argparse.ArgumentParser(prog="cli_ip_link_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run")
    p.add_argument("--db", default=str(DB_PATH_DEFAULT))
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    sys.exit(run(Path(args.db), limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
