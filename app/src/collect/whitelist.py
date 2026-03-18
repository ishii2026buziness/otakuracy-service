"""IP name extraction from event titles using claude -p CLI."""

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


def extract_ip_names(titles: list[str]) -> list[dict]:
    """
    Use `claude -p` to extract IP names from event titles.

    Returns a list of dicts: [{"title": "...", "ip_name": "..." or None}, ...]
    """
    if not titles:
        return []

    titles_text = "\n".join(f"- {t}" for t in titles)
    prompt = f"""以下はイベントタイトルの一覧です。各タイトルからアニメ・漫画・ゲーム・VTuberのIP名を抽出してください。

ルール:
- IP名はアニメ・漫画・ゲーム・VTuberの作品名・グループ名のみ
- 「体験展」「コラボカフェ」「ポップアップ」等のイベント種別は含めない
- 声優・アーティスト個人名はIPとみなさない
- IPが判別できない場合はnullにする
- 出力はJSON配列のみ（説明文不要）: [{{"title": "...", "ip_name": "..." or null}}, ...]

イベントタイトル一覧:
{titles_text}"""

    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"claude -p error: {result.stderr}", file=sys.stderr)
        return [{"title": t, "ip_name": None} for t in titles]

    output = result.stdout.strip()

    # Try to extract JSON from ```json ... ``` block first
    json_block = re.search(r"```json\s*([\s\S]*?)\s*```", output)
    if json_block:
        json_str = json_block.group(1)
    else:
        # Try to extract raw JSON array
        json_match = re.search(r"\[[\s\S]*\]", output)
        if json_match:
            json_str = json_match.group(0)
        else:
            print(f"Could not find JSON in claude output: {output[:200]}", file=sys.stderr)
            return [{"title": t, "ip_name": None} for t in titles]

    try:
        parsed = json.loads(json_str)
        return parsed
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}\nRaw: {json_str[:200]}", file=sys.stderr)
        return [{"title": t, "ip_name": None} for t in titles]


WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_wikidata_session = None


def _get_wikidata_session() -> requests.Session:
    global _wikidata_session
    if _wikidata_session is None:
        import requests as _req
        _wikidata_session = _req.Session()
        _wikidata_session.headers.update({"User-Agent": "otakuracy-whitelist/1.0"})
    return _wikidata_session


def lookup_official_url(ip_name: str) -> str | None:
    """
    Look up official website for an IP via Wikidata P856.

    1. wbsearchentities to find entity ID
    2. wbgetentities to fetch P856 (official website)
    Returns URL string or None.
    """
    import requests as _req
    session = _get_wikidata_session()

    try:
        # Step 1: search for entity
        import time as _time
        _time.sleep(0.5)
        r = session.get(WIKIDATA_API, params={
            "action": "wbsearchentities",
            "search": ip_name,
            "language": "ja",
            "limit": 1,
            "format": "json",
        }, timeout=10)
        r.raise_for_status()
        results = r.json().get("search", [])
        if not results:
            return None

        entity_id = results[0]["id"]

        # Step 2: fetch P856 (official website)
        _time.sleep(0.5)
        r2 = session.get(WIKIDATA_API, params={
            "action": "wbgetentities",
            "ids": entity_id,
            "props": "claims",
            "format": "json",
        }, timeout=10)
        r2.raise_for_status()
        claims = r2.json().get("entities", {}).get(entity_id, {}).get("claims", {})
        p856 = claims.get("P856", [])
        if p856:
            return p856[0]["mainsnak"]["datavalue"]["value"]
        return None

    except Exception as e:
        print(f"Wikidata lookup failed for '{ip_name}': {e}", file=sys.stderr)
        return None


def load_whitelist(path: str) -> dict:
    """Load whitelist JSON from path. Returns empty dict if file doesn't exist."""
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_whitelist(path: str, data: dict):
    """Save whitelist dict to JSON file, creating parent dirs as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_whitelist(whitelist_path: str, new_items: list[dict]) -> tuple[int, int]:
    """
    Merge new_items into the whitelist at whitelist_path.

    new_items: [{"title": "...", "ip_name": "..." or None, "official_url": "..." (optional)}, ...]

    Returns (added_count, total_count).

    whitelist.json format:
    {
      "推しの子": {
        "ip_name": "推しの子",
        "first_seen": "2026-03-16",
        "source_titles": ["TV アニメ【推しの子】体験展..."],
        "official_url": null
      }
    }
    """
    whitelist = load_whitelist(whitelist_path)
    today = date.today().isoformat()
    added = 0

    for item in new_items:
        ip_name = item.get("ip_name")
        title = item.get("title", "")

        if not ip_name:
            continue

        official_url = item.get("official_url")

        if ip_name not in whitelist:
            whitelist[ip_name] = {
                "ip_name": ip_name,
                "first_seen": today,
                "source_titles": [title] if title else [],
                "official_url": official_url,
            }
            added += 1
        else:
            # Append source title if not already present
            existing_titles = whitelist[ip_name].get("source_titles", [])
            if title and title not in existing_titles:
                existing_titles.append(title)
                whitelist[ip_name]["source_titles"] = existing_titles
            # Fill official_url if not yet set
            if official_url and not whitelist[ip_name].get("official_url"):
                whitelist[ip_name]["official_url"] = official_url

    save_whitelist(whitelist_path, whitelist)
    return added, len(whitelist)
