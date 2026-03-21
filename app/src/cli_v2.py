"""Service CLI v2 — runs the new unified pipeline (pipeline_v2)."""
import argparse
import asyncio
import json
import sys

from common.contracts import JobStatus
from pipeline_v2 import run_pipeline_v2, smoke_check_v2


def config_check_v2() -> dict:
    from db.repository import SCHEMA_PATH
    return {"ok": SCHEMA_PATH.exists(), "schema": str(SCHEMA_PATH)}


def main():
    parser = argparse.ArgumentParser(prog="otakuracy_v2")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("smoke")
    sub.add_parser("check")
    args = parser.parse_args()

    if args.command == "run":
        result = asyncio.run(run_pipeline_v2())
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        sys.exit(1 if result.status == JobStatus.FAILED else 0)
    elif args.command == "smoke":
        out = smoke_check_v2()
        print(json.dumps({"job": "otakuracy_v2", "command": "smoke", "result": out}, ensure_ascii=False, indent=2))
    else:
        out = config_check_v2()
        print(json.dumps({"job": "otakuracy_v2", "command": "check", "result": out}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
