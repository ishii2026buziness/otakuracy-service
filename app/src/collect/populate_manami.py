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


def _is_ja(s: str) -> bool:
    return any('\u3040' <= c <= '\u9fff' for c in s)


def _ja_title(title: str, synonyms: list[str]) -> tuple[str, list[str]]:
    """日本語タイトルを display_name に。なければ元タイトルをそのまま使う。
    Returns (display_name, aliases)."""
    candidates = [s for s in synonyms if _is_ja(s)]
    if candidates:
        # 漢字を含む候補を優先
        kanji = [s for s in candidates if any('\u4e00' <= c <= '\u9fff' for c in s)]
        ja_name = kanji[0] if kanji else candidates[0]
        aliases = [s for s in [title] + synonyms if s != ja_name]
    else:
        ja_name = title
        aliases = [s for s in synonyms if s != title]
    return ja_name, aliases


def _domain_tags(entry_type: str) -> list[str]:
    t = entry_type.upper()
    if t in _ANIME_TYPES:
        return ["anime"]
    if t in _MANGA_TYPES:
        return ["manga"]
    return []


def populate(db_path: Path, force_refresh: bool = False, dry_run: bool = False) -> int:
    from db.repository import IpAliasRepo, IpRegistryRepo, get_connection, init_db

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
    alias_repo = IpAliasRepo(conn)

    upserted = 0
    for e in entries:
        raw_title = e.get("title", "").strip()
        if not raw_title:
            continue
        synonyms = [s for s in e.get("synonyms", []) if s]
        display_name, aliases = _ja_title(raw_title, synonyms)
        domain_tags = _domain_tags(e.get("type", ""))
        ip_id = repo.upsert(
            display_name=display_name,
            domain_tags=json.dumps(domain_tags, ensure_ascii=False),
        )
        alias_repo.set_aliases(ip_id, aliases, source="manami")
        upserted += 1
        if upserted % 5000 == 0:
            conn.commit()
            print(f"[manami] {upserted}/{len(entries)} ...", flush=True)

    conn.commit()
    conn.close()
    print(f"[manami] done: {upserted} upserted", flush=True)
    return 0
