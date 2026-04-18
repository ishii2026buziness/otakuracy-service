"""Populate ip_registry from manami-project anime-offline-database."""
import json
import urllib.request
from pathlib import Path

_RELEASES_API = (
    "https://api.github.com/repos/manami-project/anime-offline-database/releases/latest"
)
CACHE_PATH = Path("/tmp/anime-offline-database.json")


def _latest_url() -> str:
    with urllib.request.urlopen(_RELEASES_API, timeout=15) as resp:
        release = json.load(resp)
    for asset in release.get("assets", []):
        if asset["name"] == "anime-offline-database-minified.json":
            return asset["browser_download_url"]
    raise RuntimeError("anime-offline-database-minified.json not found in latest release")

_ANIME_TYPES = {"TV", "ONA", "OVA", "MOVIE", "SPECIAL", "UNKNOWN"}
_MANGA_TYPES = {"MANGA", "ONE_SHOT", "MANHWA", "MANHUA", "NOVEL", "LIGHT_NOVEL"}


def _fetch(force_refresh: bool = False) -> list[dict]:
    if not force_refresh and CACHE_PATH.exists():
        print(f"[manami] using cache {CACHE_PATH}", flush=True)
        data = json.loads(CACHE_PATH.read_text())
    else:
        url = _latest_url()
        print(f"[manami] downloading {url} ...", flush=True)
        with urllib.request.urlopen(url, timeout=120) as resp:
            raw = resp.read()
        CACHE_PATH.write_bytes(raw)
        data = json.loads(raw)
    return data.get("data", [])


def _domain_tags(entry_type: str) -> list[str]:
    t = entry_type.upper()
    if t in _ANIME_TYPES:
        return ["anime"]
    if t in _MANGA_TYPES:
        return ["manga"]
    return []


def populate(db_path: Path, force_refresh: bool = False, dry_run: bool = False) -> int:
    from db.repository import IpRegistryRepo, get_connection, init_db

    entries = _fetch(force_refresh)
    print(f"[manami] {len(entries)} entries loaded", flush=True)

    if dry_run:
        sample = entries[:5]
        for e in sample:
            print(f"  title={e['title']!r} synonyms={e.get('synonyms', [])[:3]} type={e.get('type')}")
        print("[manami] dry-run, no DB write")
        return 0

    init_db(db_path)
    conn = get_connection(db_path)
    repo = IpRegistryRepo(conn)

    upserted = 0
    for e in entries:
        title = e.get("title", "").strip()
        if not title:
            continue
        synonyms = [s for s in e.get("synonyms", []) if s and s != title]
        domain_tags = _domain_tags(e.get("type", ""))
        repo.upsert(
            display_name=title,
            aliases=json.dumps(synonyms, ensure_ascii=False),
            domain_tags=json.dumps(domain_tags, ensure_ascii=False),
        )
        upserted += 1
        if upserted % 5000 == 0:
            print(f"[manami] {upserted}/{len(entries)} ...", flush=True)

    conn.close()
    print(f"[manami] done: {upserted} upserted", flush=True)
    return 0
