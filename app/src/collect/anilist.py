"""AniList GraphQL API client for popular anime/manga IP collection."""

import sys
import time

import requests

GRAPHQL_URL = "https://graphql.anilist.co"

POPULAR_QUERY = """
query ($page: Int, $type: MediaType) {
  Page(page: $page, perPage: 50) {
    media(type: $type, sort: POPULARITY_DESC, isAdult: false) {
      title {
        native
        romaji
      }
      externalLinks {
        url
        site
        type
      }
    }
  }
}
"""

SEARCH_QUERY = """
query ($search: String) {
  anime: Media(search: $search, type: ANIME) {
    title { native romaji }
    externalLinks { url site type }
  }
  manga: Media(search: $search, type: MANGA) {
    title { native romaji }
    externalLinks { url site type }
  }
}
"""


class AniListClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _post(self, query: str, variables: dict) -> dict | None:
        """Execute a GraphQL query. Returns parsed JSON or None on error."""
        try:
            resp = self.session.post(
                GRAPHQL_URL,
                json={"query": query, "variables": variables},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(f"HTTP error querying AniList: {e}", file=sys.stderr)
            return None
        try:
            return resp.json()
        except ValueError as e:
            print(f"JSON parse error from AniList: {e}", file=sys.stderr)
            return None

    def _extract_official_url(self, external_links: list[dict]) -> str | None:
        """Extract official site URL from externalLinks list."""
        for link in external_links or []:
            if link.get("site") == "Official Site" and link.get("type") == "INFO":
                return link["url"]
        return None

    def lookup_official_url(self, ip_name: str) -> str | None:
        """
        Search AniList for ip_name and return its official site URL.
        Tries anime first, then manga. Returns None if not found.
        """
        data = self._post(SEARCH_QUERY, {"search": ip_name})
        if not data:
            return None

        for media_type in ("anime", "manga"):
            media = data.get("data", {}).get(media_type)
            if not media:
                continue
            url = self._extract_official_url(media.get("externalLinks", []))
            if url:
                return url
        return None

    def _fetch_page(self, media_type: str, page: int) -> list[dict]:
        """Fetch one page of popular media and return whitelist-format dicts."""
        data = self._post(POPULAR_QUERY, {"page": page, "type": media_type})
        if data is None:
            return []

        media_list = (
            data.get("data", {})
            .get("Page", {})
            .get("media", [])
        )

        results = []
        for media in media_list:
            title_obj = media.get("title") or {}
            ip_name = title_obj.get("native") or title_obj.get("romaji")
            if ip_name:
                official_url = self._extract_official_url(media.get("externalLinks", []))
                results.append({"title": ip_name, "ip_name": ip_name, "official_url": official_url})
        return results

    def collect_popular(self, pages: int = 2) -> list[dict]:
        """
        Fetch top popular anime and manga from AniList.

        Fetches `pages` pages of each type (anime + manga), 50 items per page.
        Returns deduplicated whitelist-format dicts: [{"title": ip_name, "ip_name": ip_name}, ...]
        """
        items: list[dict] = []
        seen: set[str] = set()

        for media_type in ("ANIME", "MANGA"):
            for page in range(1, pages + 1):
                page_items = self._fetch_page(media_type, page)
                for item in page_items:
                    ip_name = item["ip_name"]
                    if ip_name not in seen:
                        seen.add(ip_name)
                        items.append(item)
                time.sleep(0.5)

        return items
