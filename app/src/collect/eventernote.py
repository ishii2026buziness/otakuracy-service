"""Eventernote scraping client."""

import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .base import EventSource, RawEventRecord

BASE_URL = "https://www.eventernote.com"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class EventernoteClient(EventSource):
    SOURCE_ID = "eventernote"
    TIER = 1
    COLLECTION_METHOD = "requests"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def _extract_crumb(self, html: str) -> Optional[str]:
        """Extract CSRF crumb from HTML: meta tag first, then JS variable."""
        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        if meta and meta.get("content"):
            return meta["content"]
        # Fallback: JS variable
        match = re.search(r'csrf[_-]?token["\']?\s*[:=]\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _parse_actors_from_li(self, li) -> list[dict]:
        """Extract actor info from an event list item."""
        actors = []
        for a in li.select("div.event > div.actor > ul > li > a"):
            href = a.get("href", "")
            # href pattern: /actors/{slug}/{id}
            m = re.match(r"/actors/([^/]+)/(\d+)", href)
            if m:
                actors.append({
                    "slug": m.group(1),
                    "id": m.group(2),
                    "name": a.get_text(strip=True),
                })
        return actors

    def _parse_event_from_li(self, li, actor_id: str) -> Optional[dict]:
        """Parse a single event list item into a dict."""
        title_a = li.select_one("div.event > h4 > a")
        if not title_a:
            return None
        title = title_a.get_text(strip=True)
        event_href = title_a.get("href", "")
        event_url = BASE_URL + event_href if event_href.startswith("/") else event_href

        # Extract event ID from href e.g. /events/12345
        eid_match = re.search(r"/events/(\d+)", event_href)
        event_id = eid_match.group(1) if eid_match else ""

        venue_a = li.select_one("div.event > div.place > a")
        venue = venue_a.get_text(strip=True) if venue_a else ""
        venue_href = venue_a.get("href", "") if venue_a else ""
        venue_url = BASE_URL + venue_href if venue_href.startswith("/") else venue_href

        time_span = li.select_one("div.event > div.place > span.s")
        time_str = time_span.get_text(strip=True) if time_span else ""

        # class is day0-day6 depending on day of week
        date_p = li.select_one("div.date > p[class^='day']")
        date_str = date_p.get_text(strip=True) if date_p else ""

        return {
            "id": event_id,
            "title": title,
            "url": event_url,
            "date": date_str,
            "time": time_str,
            "venue": venue,
            "venue_url": venue_url,
            "actor_id": actor_id,
        }

    def fetch_event_list_page(self, date_str: str, page: int) -> list:
        """
        Fetch one page of the event list.
        date_str: 'YYYY-M-D' format (e.g. '2026-3-16')
        Returns list of li BeautifulSoup elements.
        """
        url = f"{BASE_URL}/events/month/{date_str}/{page}?facet=1&limit=30"
        try:
            resp = self._get(url)
        except requests.HTTPError as e:
            print(f"HTTP error fetching {url}: {e}", file=sys.stderr)
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        return soup.select("div.gb_event_list > ul > li.clearfix")

    def collect_whitelist(self, pages: int = 10) -> list[dict]:
        """
        Scrape N pages of event listings starting from today and collect
        unique actors. Returns list of {id, name, slug}.
        """
        today = date.today()
        date_str = f"{today.year}-{today.month}-{today.day}"

        actors_seen: dict[str, dict] = {}

        for page in range(1, pages + 1):
            items = self.fetch_event_list_page(date_str, page)
            if not items:
                break
            for li in items:
                for actor in self._parse_actors_from_li(li):
                    aid = actor["id"]
                    if aid not in actors_seen:
                        actors_seen[aid] = {
                            "id": aid,
                            "name": actor["name"],
                            "slug": actor["slug"],
                        }

        return list(actors_seen.values())

    def fetch_actor_events_page(self, actor_id: str, actor_slug: str, page: int) -> list:
        """
        Fetch one page of events for a given actor.
        Returns list of li BeautifulSoup elements.
        """
        url = (
            f"{BASE_URL}/actors/{actor_slug}/{actor_id}/events"
            f"?actor_id={actor_id}&limit=20&page={page}"
        )
        try:
            resp = self._get(url)
        except requests.HTTPError as e:
            print(f"HTTP error fetching {url}: {e}", file=sys.stderr)
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        return soup.select("div.gb_event_list > ul > li.clearfix")

    def collect_actor_events(
        self, actor_id: str, actor_slug: str, max_pages: int = 5
    ) -> list[dict]:
        """
        Collect all events for an actor up to max_pages.
        Returns list of event dicts.
        """
        events = []
        for page in range(1, max_pages + 1):
            items = self.fetch_actor_events_page(actor_id, actor_slug, page)
            if not items:
                break
            for li in items:
                ev = self._parse_event_from_li(li, actor_id)
                if ev:
                    events.append(ev)
        return events

    def collect_raw(self, pages: int = 10) -> list[RawEventRecord]:
        """Fetch raw events from Eventernote and return as RawEventRecord list."""
        today = date.today()
        date_str = f"{today.year}-{today.month}-{today.day}"
        records = []
        for page in range(1, pages + 1):
            items = self.fetch_event_list_page(date_str, page)
            if not items:
                break
            for li in items:
                ev = self._parse_event_from_li(li, actor_id="")
                if not ev:
                    continue
                records.append(
                    RawEventRecord(
                        source_id="eventernote",
                        source_url=ev["url"],
                        fetched_at=datetime.now(timezone.utc),
                        raw_title=ev["title"],
                        raw_date_text=ev.get("date"),
                        raw_venue_text=ev.get("venue"),
                        raw_price_text=None,
                        raw_body=ev.get("time"),
                        structured_fields={
                            "eventernote_id": ev.get("id", ""),
                            "venue_url": ev.get("venue_url", ""),
                            "actor_ids": [],
                        },
                    )
                )
        return records
