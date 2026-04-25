"""CLI: Tweet corpus からキーワード（固有名詞）抽出。"""
import click
from db.repository import init_db, get_connection
from collect.tweet_corpus.keyword_extractor import extract_keywords


@click.group()
def cli():
    pass


@cli.command()
@click.option("--limit", default=100, help="処理イベント数上限")
@click.option("--dry-run", is_flag=True, help="DBに書き込まない")
def run(limit, dry_run):
    """未処理イベントのツイートから固有名詞を抽出して event_keywords に保存する。"""
    init_db()
    conn = get_connection()
    result = extract_keywords(conn, limit=limit, dry_run=dry_run)
    print(f"[keyword-extract] done: {result}", flush=True)


if __name__ == "__main__":
    cli()
