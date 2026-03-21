"""EventSource base class and RawEventRecord dataclass."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawEventRecord:
    """Raw data captured immediately after scraping.

    Fields:
        source_id: Identifies the source ("eplus", "eventernote", etc.)
        source_url: Canonical URL of the scraped page.
        fetched_at: UTC timestamp when the data was fetched.
        raw_title: Raw event title text.
        raw_date_text: Raw date/time string as it appears on the source page.
        raw_venue_text: Raw venue string.
        raw_price_text: Raw price string.
        raw_body: Full body text for AI-based extraction later.
        structured_fields: Already-parsed fields (title, date, venue, etc.)
            if the source provides structured data directly.
    """

    source_id: str
    source_url: str
    fetched_at: datetime
    raw_title: str
    raw_date_text: Optional[str] = None
    raw_venue_text: Optional[str] = None
    raw_price_text: Optional[str] = None
    raw_body: Optional[str] = None
    structured_fields: dict = field(default_factory=dict)


@dataclass
class SourceHealth:
    """Result of a connectivity/health check for a source."""

    source_id: str
    ok: bool
    latency_ms: int
    error: Optional[str] = None


class EventSource(ABC):
    """Base class for all event collection sources.

    Class attributes (must be defined on each subclass):
        SOURCE_ID: Unique identifier string, e.g. "eplus" or "eventernote".
        TIER: Priority tier.
            1 = primary (e+, Eventernote)
            2 = auxiliary (official sites via Playwright/Agent)
            3 = IP discovery (AniList, animate, VTuber registries)
        COLLECTION_METHOD: One of "requests", "playwright", "api", "agent".

    Subclasses implement collect_raw() to fetch and return RawEventRecord
    objects. No structuring or AI processing should happen inside collect_raw.
    """

    SOURCE_ID: str
    TIER: int
    COLLECTION_METHOD: str  # "requests" | "playwright" | "api" | "agent"

    @abstractmethod
    def collect_raw(self) -> list[RawEventRecord]:
        """Fetch raw events from the source.

        Returns a list of RawEventRecord instances. Implementations must:
        - Always populate source_id, source_url, fetched_at, raw_title.
        - Populate raw_date_text, raw_venue_text, raw_price_text when available.
        - Populate raw_body when the page contains unstructured text useful
          for downstream AI extraction.
        - Populate structured_fields when the source provides machine-readable
          data (e.g. JSON-LD, structured API response) to avoid unnecessary
          AI calls.
        - NOT perform AI calls or entity resolution.
        - NOT write to the database.
        """
        ...

    def health_check(self) -> SourceHealth:
        """Connectivity check. Default: try collect_raw and measure latency.

        Override this method if a lighter-weight probe is available (e.g. a
        dedicated ping endpoint or fetching a single page instead of all pages).
        """
        import time

        start = time.monotonic()
        try:
            self.collect_raw()
            return SourceHealth(
                source_id=self.SOURCE_ID,
                ok=True,
                latency_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            return SourceHealth(
                source_id=self.SOURCE_ID,
                ok=False,
                latency_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
            )
