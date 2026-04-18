"""CLI: populate ip_registry from manami-project anime-offline-database."""
import argparse
import sys
from pathlib import Path

from collect.populate_manami import populate
from db.repository import DB_PATH_DEFAULT


def main():
    parser = argparse.ArgumentParser(prog="cli_manami_populate")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="populate ip_registry from manami-project")
    p.add_argument("--db", default=str(DB_PATH_DEFAULT))
    p.add_argument("--force-refresh", action="store_true", help="re-download even if cache exists")
    p.add_argument("--dry-run", action="store_true", help="print sample, skip DB write")

    args = parser.parse_args()
    sys.exit(populate(Path(args.db), force_refresh=args.force_refresh, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
