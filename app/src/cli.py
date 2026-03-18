"""Service CLI entry point."""
import sys

from common.job_cli import run_job_cli
from pipeline import config_check, run_pipeline, smoke_check


def main():
    sys.exit(run_job_cli(
        "otakuracy",
        run_fn=run_pipeline,
        smoke_fn=smoke_check,
        check_fn=config_check,
    ))


if __name__ == "__main__":
    main()
