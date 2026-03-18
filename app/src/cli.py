"""Service CLI entry point."""
import sys
from job_cli import run_job_cli
from pipeline import run_pipeline


def main():
    run_job_cli(run_pipeline)


if __name__ == "__main__":
    main()
