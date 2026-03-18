"""Official site event collector — see docs/2026-03-16-collection-pipeline-spec.md"""

import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

EVENT_KEYWORDS = [
    "event", "live", "news", "schedule", "information", "popup", "exhibition",
    "イベント", "ライブ", "ニュース", "スケジュール", "ポップアップ", "開催", "情報",
]

# Tags that indicate boilerplate nav/footer links — skip these
SKIP_KEYWORDS = ["privacy", "cookie", "copyright", "terms", "twitter", "instagram",
                 "youtube", "facebook", "contact", "recruit", "採用", "お問い合わせ"]


class OfficialSiteClient:
    def __init__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(ignore_https_errors=True)

    def __del__(self):
        try:
            self._context.close()
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass

    def _get_html(self, url: str) -> str | None:
        """Fetch page HTML via Playwright (handles JS rendering)."""
        try:
            page = self._context.new_page()
            page.goto(url, timeout=20000, wait_until="networkidle")
            html = page.content()
            page.close()
            return html
        except PlaywrightTimeoutError:
            print(f"Timeout {url}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Fetch failed {url}: {e}", file=sys.stderr)
            return None

    def find_event_links(self, base_url: str) -> list[str]:
        """
        Visit base_url and return links likely to contain event info.

        Follows keyword patterns defined in EVENT_KEYWORDS.
        Returns deduplicated absolute URLs (same domain only).
        """
        try:
            page = self._context.new_page()
            page.goto(base_url, timeout=20000, wait_until="networkidle")
            # Get links from rendered DOM (handles JS-generated navigation)
            pairs = page.evaluate("""() =>
                Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    href: a.href,
                    text: a.innerText.trim().toLowerCase()
                }))
            """)
            page.close()
        except PlaywrightTimeoutError:
            print(f"Timeout {base_url}", file=sys.stderr)
            return [base_url]
        except Exception as e:
            print(f"Fetch failed {base_url}: {e}", file=sys.stderr)
            return [base_url]

        base_domain = urlparse(base_url).netloc
        seen: set[str] = set()
        links: list[str] = []

        for item in pairs:
            href = item["href"]
            text = item["text"]
            href_lower = href.lower()

            # Skip boilerplate
            if any(kw in href_lower or kw in text for kw in SKIP_KEYWORDS):
                continue

            # Check if link or anchor text matches event keywords
            if not any(kw in href_lower or kw in text for kw in EVENT_KEYWORDS):
                continue

            # Same domain only
            if urlparse(href).netloc != base_domain:
                continue

            if href not in seen and href != base_url:
                seen.add(href)
                links.append(href)

        # Also include base_url itself as a candidate
        if base_url not in seen:
            links.insert(0, base_url)

        return links[:10]  # cap at 10 pages per IP

    def _clean_html(self, html: str) -> str:
        """Strip boilerplate, return plain text under 4000 chars."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Collapse blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:4000]

    def extract_events(self, url: str, ip_name: str) -> list[dict]:
        """
        Fetch url, extract event records for ip_name via claude -p.

        Returns list of partial event_record dicts.
        """
        html = self._get_html(url)
        if not html:
            return []

        text = self._clean_html(html)
        if not text.strip():
            return []

        prompt = f"""以下はアニメ・ゲーム・VTuberの「{ip_name}」公式サイトのページテキストです。
イベント情報（ポップアップストア、展示、コラボカフェ、ライブ、上映、入場特典等）を抽出してください。

ルール:
- イベントが見つからない場合は空配列 []
- 日付が不明な場合はnull、会場が不明な場合はnull
- 出力はJSONのみ（説明文不要）

content_type の選択肢:
  popup=ポップアップストア, exhibition=展示・体験展, collab_cafe=コラボカフェ,
  live=ライブ・コンサート, screening=上映・試写会・舞台挨拶, novelty=入場特典・グッズ配布, other=その他

schedule_type の選択肢:
  once=単発・一回限り（舞台挨拶/ライブ等）
  period=期間中いつでも（ポップアップ/展示/コラボカフェ等）
  recurring=繰り返し・変化あり（入場特典切り替え/週替わり上映等）

出力形式:
[
  {{
    "title": "イベント名",
    "content_type": "popup|exhibition|collab_cafe|live|screening|novelty|other",
    "schedule_type": "once|period|recurring",
    "start_date": "YYYY-MM-DD or null",
    "end_date": "YYYY-MM-DD or null",
    "venue_name": "会場名 or null",
    "area_name": "エリア名 or null",
    "canonical_url": "{url}",
    "franchise_tags": ["{ip_name}"]
  }}
]

ページテキスト:
{text}"""

        result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"claude -p error: {result.stderr[:100]}", file=sys.stderr)
            return []

        output = result.stdout.strip()
        m = re.search(r"\[[\s\S]*\]", output)
        if not m:
            return []
        try:
            records = json.loads(m.group(0))
            return [r for r in records if isinstance(r, dict) and r.get("title")]
        except json.JSONDecodeError:
            return []

    def collect_ip_events(self, ip_name: str, official_url: str,
                          since_year: int = 2026) -> list[dict]:
        """
        Full pipeline for one IP: find event links → extract events from each page.

        Stops paginating when all events on a page predate since_year.
        Returns deduplicated list of event_record dicts with start_date >= since_year (or null).
        """
        print(f"  {ip_name}: リンク探索中...", file=sys.stderr)
        links = self.find_event_links(official_url)
        print(f"  {ip_name}: {len(links)}ページ対象", file=sys.stderr)

        cutoff = f"{since_year}-01-01"
        seen_titles: set[str] = set()
        events: list[dict] = []

        for link in links:
            records = self.extract_events(link, ip_name)
            if not records:
                continue

            # Check if all dated events on this page are before cutoff → stop
            dated = [r for r in records if r.get("start_date")]
            if dated and all(r["start_date"] < cutoff for r in dated):
                print(f"  {ip_name}: {link} が全件{since_year}年前 → 以降スキップ", file=sys.stderr)
                break

            for r in records:
                # Drop events clearly before cutoff
                start = r.get("start_date")
                if start and start < cutoff:
                    continue
                key = r.get("title", "")
                if key and key not in seen_titles:
                    seen_titles.add(key)
                    events.append(r)

        return events
