"""アニメイト (animate.co.jp) product ranking scraper for IP whitelist collection."""

import sys

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

RANKING_URLS = [
    "https://www.animate.co.jp/catalog/rank/",
    "https://www.animate.co.jp/rank/goods/",
]

TITLE_SELECTORS = [
    '[class*="item__name"]',
    '[class*="product__name"]',
    '[class*="goods__name"]',
    '[class*="rank__title"]',
    "h2.item-name",
    "p.item-name",
    "a[class*='item'] span",
    ".item-list li a",
]


class AnimateClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def _extract_titles_from_page(self, html: str) -> list[str]:
        """Try each CSS selector in order and return titles from the first that yields results."""
        soup = BeautifulSoup(html, "html.parser")
        for selector in TITLE_SELECTORS:
            elements = soup.select(selector)
            if elements:
                titles = [el.get_text(strip=True) for el in elements if el.get_text(strip=True)]
                if titles:
                    return titles
        return []

    def _page_url(self, base_url: str, page: int) -> str:
        """Build paginated URL by appending ?page=N or &page=N."""
        if page == 1:
            return base_url
        if "?" in base_url:
            return f"{base_url}&page={page}"
        return f"{base_url}?page={page}"

    def collect_ranking(self, max_pages: int = 3) -> list[str]:
        """
        Scrape product titles from animate ranking pages.

        Tries each URL in RANKING_URLS in order, paginating up to max_pages.
        Stops paginating when a page returns no titles.
        Returns a deduplicated list of title strings.
        """
        titles: list[str] = []
        seen: set[str] = set()

        for base_url in RANKING_URLS:
            url_titles: list[str] = []
            for page in range(1, max_pages + 1):
                url = self._page_url(base_url, page)
                try:
                    resp = self._get(url)
                except requests.HTTPError as e:
                    print(f"HTTP error fetching {url}: {e}", file=sys.stderr)
                    break
                except requests.RequestException as e:
                    print(f"Request error fetching {url}: {e}", file=sys.stderr)
                    break
                page_titles = self._extract_titles_from_page(resp.text)
                if not page_titles:
                    break
                url_titles.extend(page_titles)

            for t in url_titles:
                if t not in seen:
                    seen.add(t)
                    titles.append(t)

        return titles

    def collect_whitelist(self, max_pages: int = 3) -> list[dict]:
        """
        Collect product titles from animate rankings and extract IP names via claude -p.

        Returns a list of dicts: [{"title": "...", "ip_name": "..." or None}, ...]
        """
        from .whitelist import extract_ip_names

        titles = self.collect_ranking(max_pages=max_pages)
        if not titles:
            return []
        return extract_ip_names(titles)
