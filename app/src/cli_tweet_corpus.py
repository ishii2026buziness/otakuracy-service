"""CLI: Twitter tweet corpus collector."""
import pathlib
import time
import click
from db.repository import init_db, get_connection
from collect.tweet_corpus.collector import collect_tweets

_METRICS_PATH = pathlib.Path("/metrics/otakuracy_tweet_corpus.prom")


def _write_metrics(status: int) -> None:
    if not _METRICS_PATH.parent.exists():
        return
    ts = time.time()
    _METRICS_PATH.write_text(
        '# TYPE pipeline_last_run_status gauge\n'
        f'pipeline_last_run_status{{pipeline="otakuracy_tweet_corpus"}} {status}\n'
        '# TYPE pipeline_last_run_timestamp_seconds gauge\n'
        f'pipeline_last_run_timestamp_seconds{{pipeline="otakuracy_tweet_corpus"}} {ts}\n'
    )


@click.group()
def cli():
    pass


@cli.command()
@click.option("--limit", default=200, help="処理イベント数上限")
@click.option("--max-per-event", default=30, help="イベントあたり最大取得ツイート数")
@click.option("--interval", default=2.0, help="検索間隔（秒）")
@click.option("--dry-run", is_flag=True, help="DBに書き込まない")
def run(limit, max_per_event, interval, dry_run):
    """未検索イベントのツイートを収集する。"""
    try:
        init_db()
        conn = get_connection()
        result = collect_tweets(
            conn,
            limit=limit,
            max_per_event=max_per_event,
            interval_sec=interval,
            dry_run=dry_run,
        )
        print(f"[tweet-corpus] done: {result}", flush=True)
        _write_metrics(1)
    except Exception:
        _write_metrics(0)
        raise


if __name__ == "__main__":
    cli()
