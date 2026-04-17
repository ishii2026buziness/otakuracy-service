"""e+ (eplus.jp) scraping client — monthly collection."""

import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from .base import EventSource, RawEventRecord

BASE_URL = "https://eplus.jp"
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
        title_el = a_tag.select_one("h3.ticket-item__title")
        title = title_el.get_text(strip=True) if title_el else ""
        label_el = title_el.select_one("span.label-ticket") if title_el else None
        if label_el:
            label_el.extract()
            title = title_el.get_text(strip=True)

        venue_el = a_tag.select_one("div.ticket-item__venue > p")
        venue_raw = venue_el.get_text(strip=True) if venue_el else ""
        venue_match = re.match(r"^(.+?)\(([^)]+)\)$", venue_raw)
        venue = venue_match.group(1) if venue_match else venue_raw
        prefecture = venue_match.group(2) if venue_match else ""

        dates = []
        for p in a_tag.select("p.ticket-item__date"):
            yyyy = p.select_one("span.ticket-item__yyyy")
            mmdd = p.select_one("span.ticket-item__mmdd")
            if yyyy and mmdd:
                dates.append(f"{yyyy.get_text(strip=True)}{mmdd.get_text(strip=True)}")

        text_el = a_tag.select_one("div.ticket-item__text > p")
        href = a_tag.get("href", "")
        return {
            "title": title,
            "dates": dates,
            "time": text_el.get_text(strip=True) if text_el else "",
            "venue": venue,
            "prefecture": prefecture,
            "url": BASE_URL + href if href.startswith("/") else href,
        }

    def _fetch_page_items(self, url: str) -> list:
        """Fetch a single page, return parsed list items (empty on error/no content)."""
        try:
            resp = self._get(url)
        except requests.HTTPError as e:
            print(f"eplus HTTP error {url}: {e}", file=sys.stderr)
            return []
        return BeautifulSoup(resp.text, "html.parser").select("a.ticket-item.ticket-item--kouen")

    def collect_month(self, year: int, month: int, max_pages: int = 100, page_batch: int = 5) -> list[RawEventRecord]:
        """Fetch all events for a given month via /sf/event/month-MM, pages fetched in parallel batches."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        base_url = f"{BASE_URL}/sf/event/month-{month:02d}"
        seen_urls: set[str] = set()
        records = []

        for batch_start in range(1, max_pages + 1, page_batch):
            batch_pages = list(range(batch_start, min(batch_start + page_batch, max_pages + 1)))
            urls = [base_url if p == 1 else f"{base_url}/p{p}" for p in batch_pages]

            with ThreadPoolExecutor(max_workers=len(batch_pages)) as pool:
                futures = {pool.submit(self._fetch_page_items, u): p for u, p in zip(urls, batch_pages)}
                page_items = {futures[f]: f.result() for f in as_completed(futures)}

            stop = False
            for p in batch_pages:
                items = page_items[p]
                if not items:
                    stop = True
                    break
                for a in items:
                    ev = self._parse_event(a)
                    if not ev["url"] or ev["url"] in seen_urls:
                        continue
                    seen_urls.add(ev["url"])
                    records.append(RawEventRecord(
                        source_id="eplus",
                        source_url=ev["url"],
                        fetched_at=datetime.now(timezone.utc),
                        raw_title=ev["title"],
                        raw_date_text=" / ".join(ev["dates"]) if ev.get("dates") else None,
                        raw_venue_text=f"{ev['venue']} ({ev['prefecture']})" if ev.get("venue") else None,
                        raw_price_text=None,
                        raw_body=ev["time"],
                        structured_fields={"dates": ev.get("dates", [])},
                    ))
            if stop:
                break
        return records

    def collect_raw(self, months_ahead: int = 6) -> list[RawEventRecord]:
        """Collect current month + next months_ahead months."""
        from datetime import date
        today = date.today()
        records = []
        year, month = today.year, today.month
        for _ in range(months_ahead + 1):
            records.extend(self.collect_month(year, month))
            month += 1
            if month > 12:
                month, year = 1, year + 1
        return records
