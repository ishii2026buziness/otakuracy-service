"""e+ (eplus.jp) HTML scraping client for anime event collection."""

import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from .base import EventSource, RawEventRecord

BASE_URL = "https://eplus.jp"
ANIME_TOKYO_URL = f"{BASE_URL}/sf/event/anime/tokyo"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class EplusClient(EventSource):
    SOURCE_ID = "eplus"
    TIER = 1
    COLLECTION_METHOD = "requests"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def _parse_event(self, a_tag) -> dict:
        """Parse a single ticket-item anchor tag into an event dict."""
        title_el = a_tag.select_one("h3.ticket-item__title")
        title = title_el.get_text(strip=True) if title_el else ""
        # strip leading label like "先着" "抽選"
        label_el = title_el.select_one("span.label-ticket") if title_el else None
        accept_type = label_el.get_text(strip=True) if label_el else ""
        if label_el:
            label_el.extract()
            title = title_el.get_text(strip=True)

        venue_el = a_tag.select_one("div.ticket-item__venue > p")
        venue_raw = venue_el.get_text(strip=True) if venue_el else ""
        # "会場名(東京都)" → split
        venue_match = re.match(r"^(.+?)\(([^)]+)\)$", venue_raw)
        venue = venue_match.group(1) if venue_match else venue_raw
        prefecture = venue_match.group(2) if venue_match else ""

        date_els = a_tag.select("p.ticket-item__date")
        dates = []
        for p in date_els:
            yyyy = p.select_one("span.ticket-item__yyyy")
            mmdd = p.select_one("span.ticket-item__mmdd")
            if yyyy and mmdd:
                dates.append(f"{yyyy.get_text(strip=True)}{mmdd.get_text(strip=True)}")

        text_el = a_tag.select_one("div.ticket-item__text > p")
        time_str = text_el.get_text(strip=True) if text_el else ""

        status_el = a_tag.select_one("span.ticket-status__item--accepting")
        if not status_el:
            status_el = a_tag.select_one("span.ticket-status__item--before")
        if not status_el:
            status_el = a_tag.select_one("span.ticket-status__item--end")
        status = status_el.get_text(strip=True) if status_el else ""

        href = a_tag.get("href", "")
        url = BASE_URL + href if href.startswith("/") else href

        return {
            "title": title,
            "dates": dates,
            "time": time_str,
            "venue": venue,
            "prefecture": prefecture,
            "accept_type": accept_type,
            "status": status,
            "url": url,
        }

    def _fetch_page(self, page: int) -> list[dict]:
        """Fetch one page of anime/tokyo event listing."""
        url = ANIME_TOKYO_URL if page == 1 else f"{ANIME_TOKYO_URL}/p{page}"
        try:
            resp = self._get(url)
        except requests.HTTPError as e:
            print(f"HTTP error fetching {url}: {e}", file=sys.stderr)
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("a.ticket-item.ticket-item--kouen")
        return [self._parse_event(a) for a in items]

    def _total_pages(self) -> int:
        """Get total number of pages from the first page."""
        try:
            resp = self._get(ANIME_TOKYO_URL)
        except requests.HTTPError:
            return 1
        soup = BeautifulSoup(resp.text, "html.parser")
        status = soup.select_one("p.block-paginator__status")
        if not status:
            return 1
        # "1313件中　1～50件表示"
        m = re.search(r"(\d+)件中", status.get_text())
        if not m:
            return 1
        total = int(m.group(1))
        return (total + 49) // 50  # 50件/ページ

    def collect_events(self, max_pages: int = 5) -> list[dict]:
        """
        Return anime/tokyo events from e+.

        Output: [{
            title, dates, time, venue, prefecture,
            accept_type, status, url
        }, ...]
        """
        events = []
        for page in range(1, max_pages + 1):
            items = self._fetch_page(page)
            if not items:
                break
            events.extend(items)
        return events

    def collect_whitelist(self, max_pages: int = 5) -> list[dict]:
        """
        Return unique events (by title) as IP whitelist candidates.

        Output: [{title, venue, url}, ...]
        """
        events = self.collect_events(max_pages=max_pages)
        seen: dict[str, dict] = {}
        for ev in events:
            key = ev["title"]
            if key and key not in seen:
                seen[key] = {
                    "title": ev["title"],
                    "venue": ev["venue"],
                    "url": ev["url"],
                }
        return list(seen.values())

    def collect_raw(self, max_pages: int = 5) -> list[RawEventRecord]:
        """Fetch raw events from e+ and return as RawEventRecord list."""
        events = self.collect_events(max_pages)
        records = []
        for ev in events:
            records.append(
                RawEventRecord(
                    source_id="eplus",
                    source_url=ev["url"],
                    fetched_at=datetime.now(timezone.utc),
                    raw_title=ev["title"],
                    raw_date_text=" / ".join(ev["dates"]) if ev.get("dates") else None,
                    raw_venue_text=f"{ev.get('venue', '')} ({ev.get('prefecture', '')})" if ev.get("venue") else None,
                    raw_price_text=None,
                    raw_body=ev.get("time"),
                    structured_fields={
                        "accept_type": ev.get("accept_type", ""),
                        "status": ev.get("status", ""),
                        "prefecture": ev.get("prefecture", ""),
                        "dates": ev.get("dates", []),
                    },
                )
            )
        return records
