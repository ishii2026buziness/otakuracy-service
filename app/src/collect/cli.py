"""Click CLI entry point for tools.collect."""

import json
import re
import sys
from pathlib import Path

import click

from .animate import AnimateClient
from .official_site import OfficialSiteClient
from .anilist import AniListClient
from .eplus import EplusClient
from .eventernote import EventernoteClient
from .vtuber import VTuberClient
from .whitelist import extract_ip_names, load_whitelist, lookup_official_url, save_whitelist, update_whitelist
from .dedup import dedup_events


@click.group()
def main():
    """Otakuracy data collection tools (Eventernote, e+, AniList, アニメイト, VTuber)."""


@main.command()
@click.option("--pages", default=10, show_default=True, help="Number of event listing pages to scrape.")
def whitelist(pages: int):
    """
    Scrape active actors from Eventernote event listings.

    Fetches today's event listing pages and aggregates unique actors.
    Outputs JSON array to stdout: [{id, name, slug}, ...]
    """
    client = EventernoteClient()
    try:
        actors = client.collect_whitelist(pages=pages)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(json.dumps(actors, ensure_ascii=False, indent=2))


@main.command()
@click.option("--actor-id", required=True, help="Eventernote actor numeric ID.")
@click.option("--actor-slug", required=True, help="Eventernote actor slug (URL-safe name).")
@click.option("--max-pages", default=5, show_default=True, help="Maximum number of pages to fetch.")
def events(actor_id: str, actor_slug: str, max_pages: int):
    """
    Fetch event list for a specific actor.

    Outputs JSON array to stdout:
    [{id, title, url, date, time, venue, venue_url, actor_id}, ...]
    """
    client = EventernoteClient()
    try:
        evs = client.collect_actor_events(
            actor_id=actor_id,
            actor_slug=actor_slug,
            max_pages=max_pages,
        )
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(json.dumps(evs, ensure_ascii=False, indent=2))


@main.command("eplus-events")
@click.option("--max-pages", default=5, show_default=True, help="Number of listing pages to scrape (50 events/page).")
def eplus_events(max_pages: int):
    """
    Fetch Tokyo anime events from e+ (eplus.jp) by scraping /sf/event/anime/tokyo.

    Outputs JSON array to stdout:
    [{title, dates, time, venue, prefecture, accept_type, status, url}, ...]
    """
    client = EplusClient()
    try:
        evs = client.collect_events(max_pages=max_pages)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(json.dumps(evs, ensure_ascii=False, indent=2))


@main.command("eplus-whitelist")
@click.option("--max-pages", default=5, show_default=True, help="Number of listing pages to scrape.")
def eplus_whitelist(max_pages: int):
    """
    Generate a unique event whitelist from e+ (eplus.jp).

    Outputs JSON array to stdout:
    [{title, venue, url}, ...]
    """
    client = EplusClient()
    try:
        items = client.collect_whitelist(max_pages=max_pages)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(json.dumps(items, ensure_ascii=False, indent=2))


@main.command("anilist-whitelist")
@click.option("--pages", default=2, show_default=True, help="Pages per media type (50 titles/page).")
def anilist_whitelist(pages: int):
    """
    Fetch popular anime/manga titles from AniList API.

    Outputs JSON array to stdout: [{title, ip_name}, ...]
    """
    client = AniListClient()
    try:
        items = client.collect_popular(pages=pages)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(json.dumps(items, ensure_ascii=False, indent=2))


@main.command("animate-whitelist")
@click.option("--max-pages", default=3, show_default=True, help="Number of ranking pages to scrape.")
def animate_whitelist(max_pages: int):
    """
    Scrape IP names from アニメイト product ranking.

    Outputs JSON array to stdout: [{title, ip_name}, ...]
    """
    client = AnimateClient()
    try:
        items = client.collect_whitelist(max_pages=max_pages)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(json.dumps(items, ensure_ascii=False, indent=2))


@main.command("vtuber-whitelist")
def vtuber_whitelist():
    """
    Fetch VTuber talent names from ホロライブ and にじさんじ official pages.

    Outputs JSON array to stdout: [{title, ip_name}, ...]
    """
    client = VTuberClient()
    try:
        items = client.collect_all()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(json.dumps(items, ensure_ascii=False, indent=2))


@main.command("whitelist-update")
@click.option("--max-pages", default=5, show_default=True, help="Number of listing pages to scrape (e+/アニメイト).")
@click.option("--output", default="data/whitelist.json", show_default=True, help="Path to whitelist JSON file.")
@click.option("--sources", default="all", show_default=True,
              help="Comma-separated sources: eplus,anilist,animate,vtuber or 'all'.")
def whitelist_update(max_pages: int, output: str, sources: str):
    """
    Update whitelist JSON from multiple IP sources.

    Sources: e+ (event titles → claude -p), AniList (popular anime/manga),
    アニメイト (product ranking → claude -p), VTuber (ホロライブ/にじさんじ talent names).
    """
    active = {s.strip() for s in sources.split(",")} if sources != "all" else {"eplus", "anilist", "animate", "vtuber"}

    total_added = 0
    total_count = 0

    # --- e+ ---
    if "eplus" in active:
        click.echo("▶ e+: イベントタイトル収集中...", err=True)
        try:
            eplus = EplusClient()
            items = eplus.collect_whitelist(max_pages=max_pages)
            titles = [item["title"] for item in items if item.get("title")]
            click.echo(f"  {len(titles)}件取得 → claude -p でIP抽出...", err=True)
            extracted = extract_ip_names(titles)
            added, total_count = update_whitelist(output, extracted)
            total_added += added
            click.echo(f"  追加: {added}件", err=True)
        except Exception as e:
            click.echo(f"  エラー (スキップ): {e}", err=True)

    # --- AniList ---
    if "anilist" in active:
        click.echo("▶ AniList: 人気アニメ/マンガ取得中...", err=True)
        try:
            anilist = AniListClient()
            items = anilist.collect_popular(pages=2)
            click.echo(f"  {len(items)}件取得", err=True)
            added, total_count = update_whitelist(output, items)
            total_added += added
            click.echo(f"  追加: {added}件", err=True)
        except Exception as e:
            click.echo(f"  エラー (スキップ): {e}", err=True)

    # --- アニメイト ---
    if "animate" in active:
        click.echo("▶ アニメイト: ランキング収集中...", err=True)
        try:
            animate = AnimateClient()
            items = animate.collect_whitelist(max_pages=max_pages)
            click.echo(f"  {len(items)}件取得", err=True)
            added, total_count = update_whitelist(output, items)
            total_added += added
            click.echo(f"  追加: {added}件", err=True)
        except Exception as e:
            click.echo(f"  エラー (スキップ): {e}", err=True)

    # --- VTuber ---
    if "vtuber" in active:
        click.echo("▶ VTuber: ホロライブ/にじさんじ取得中...", err=True)
        try:
            vtuber = VTuberClient()
            items = vtuber.collect_all()
            click.echo(f"  {len(items)}件取得", err=True)
            added, total_count = update_whitelist(output, items)
            total_added += added
            click.echo(f"  追加: {added}件", err=True)
        except Exception as e:
            click.echo(f"  エラー (スキップ): {e}", err=True)

    click.echo(f"\n完了: 追加 {total_added}件 / 合計 {total_count}件", err=True)


@main.command("whitelist-fill-urls")
@click.option("--input", "input_path", default="data/whitelist.json", show_default=True)
@click.option("--overwrite", is_flag=True, default=False, help="Re-fill already-set URLs too.")
def whitelist_fill_urls(input_path: str, overwrite: bool):
    """
    Auto-fill official_url for whitelisted IPs using claude -p.

    Processes IPs with null official_url in batches.
    """
    whitelist = load_whitelist(input_path)

    targets = [
        name for name, entry in whitelist.items()
        if overwrite or not entry.get("official_url")
    ]

    if not targets:
        click.echo("全IPにofficial_urlが設定済みです。", err=True)
        return

    click.echo(f"{len(targets)}件のIPにofficial_urlを補完します (Wikidata)...", err=True)

    filled = 0
    for i, ip_name in enumerate(targets, 1):
        url = lookup_official_url(ip_name)
        status = url if url else "-"
        click.echo(f"  [{i}/{len(targets)}] {ip_name} → {status}", err=True)
        if url:
            whitelist[ip_name]["official_url"] = url
            filled += 1

    save_whitelist(input_path, whitelist)
    click.echo(f"完了: {filled}件にURL設定 / 対象 {len(targets)}件", err=True)


@main.command("fetch-events")
@click.option("--ip", "ip_name", required=True, help="IP name (must exist in whitelist).")
@click.option("--whitelist", "whitelist_path", default="data/whitelist.json", show_default=True)
@click.option("--output-dir", default="data/events", show_default=True)
def fetch_events(ip_name: str, whitelist_path: str, output_dir: str):
    """
    Fetch events for one IP from its official site.

    Saves to data/events/{ip_slug}.json
    """
    whitelist = load_whitelist(whitelist_path)
    entry = whitelist.get(ip_name)
    if not entry:
        click.echo(f"IP '{ip_name}' not found in whitelist.", err=True)
        sys.exit(1)
    url = entry.get("official_url")
    if not url:
        click.echo(f"No official_url for '{ip_name}'.", err=True)
        sys.exit(1)

    client = OfficialSiteClient()
    events = client.collect_ip_events(ip_name, url)

    slug = re.sub(r"[^\w\-]", "_", ip_name)
    out_path = Path(output_dir) / f"{slug}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

    click.echo(f"{len(events)}件 → {out_path}", err=True)
    click.echo(json.dumps(events, ensure_ascii=False, indent=2))


@main.command("fetch-all-events")
@click.option("--whitelist", "whitelist_path", default="data/whitelist.json", show_default=True)
@click.option("--output-dir", default="data/events", show_default=True)
@click.option("--limit", default=0, show_default=True, help="Max IPs to process (0=all).")
@click.option("--workers", default=5, show_default=True, help="Parallel workers.")
@click.option("--skip-existing", is_flag=True, default=False, help="Skip IPs that already have output file.")
def fetch_all_events(whitelist_path: str, output_dir: str, limit: int, workers: int, skip_existing: bool):
    """
    Fetch events for all IPs with official_url in the whitelist (parallel).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    whitelist = load_whitelist(whitelist_path)
    targets = [(k, v["official_url"]) for k, v in whitelist.items() if v.get("official_url")]
    if limit:
        targets = targets[:limit]

    if skip_existing:
        out_dir = Path(output_dir)
        targets = [
            (k, u) for k, u in targets
            if not (out_dir / f"{re.sub(r'[^\w]', '_', k)}.json").exists()
        ]

    total_ips = len(targets)
    click.echo(f"{total_ips}件のIPからイベント収集開始 (workers={workers})...", err=True)

    client = OfficialSiteClient()
    completed = 0
    total_events = 0

    def process(ip_name: str, url: str) -> tuple[str, int]:
        events = client.collect_ip_events(ip_name, url)
        slug = re.sub(r"[^\w\-]", "_", ip_name)
        out_path = Path(output_dir) / f"{slug}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        return ip_name, len(events)

    if workers == 1:
        for k, u in targets:
            completed += 1
            try:
                ip_name, count = process(k, u)
                total_events += count
                click.echo(f"[{completed}/{total_ips}] {ip_name} → {count}件", err=True)
            except Exception as e:
                click.echo(f"[{completed}/{total_ips}] {k} エラー: {e}", err=True)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process, k, u): k for k, u in targets}
            for future in as_completed(futures):
                completed += 1
                try:
                    ip_name, count = future.result()
                    total_events += count
                    click.echo(f"[{completed}/{total_ips}] {ip_name} → {count}件", err=True)
                except Exception as e:
                    ip_name = futures[future]
                    click.echo(f"[{completed}/{total_ips}] {ip_name} エラー: {e}", err=True)

    click.echo(f"\n完了: 合計{total_events}件のイベントを収集", err=True)


@main.command("build-processed")
@click.option("--events-dir", default="data/events", show_default=True)
@click.option("--output", default="data/events_processed.json", show_default=True)
def build_processed(events_dir: str, output: str):
    """Deduplicate raw events and write to a single processed file."""
    events = dedup_events(events_dir)
    Path(output).write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"{len(events)}件 → {output}")


if __name__ == "__main__":
    main()
