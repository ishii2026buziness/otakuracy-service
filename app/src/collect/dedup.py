"""Post-processing: deduplicate raw event records across all IPs."""

import json
from pathlib import Path


def dedup_events(events_dir: str = "data/events") -> list[dict]:
    """
    Load all raw event files and deduplicate by (canonical_url, start_date).

    Returns deduplicated list of event records.
    """
    seen: set[tuple] = set()
    result: list[dict] = []

    for f in sorted(Path(events_dir).glob("*.json")):
        data = json.load(open(f, encoding="utf-8"))
        events = data if isinstance(data, list) else data.get("events", [])
        for e in events:
            key = (e.get("canonical_url") or "", e.get("start_date") or "")
            if key in seen:
                continue
            seen.add(key)
            result.append(e)

    return result
