"""
New unified pipeline: discover -> dedup -> persist
Replaces the old whitelist-based pipeline.
"""
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from common.contracts import FailureCode, JobResult, JobStatus, StageResult, StageStatus

from collect.base import RawEventRecord
from collect.eplus import EplusClient
from collect.eventernote import EventernoteClient
from collect.dedup_v2 import DeduplicatedEvent, dedup_within_source, merge_across_sources
from db.repository import (
    init_db, get_connection,
    EventSourceRecordRepo, EventRepo, EventIpLinkRepo, IpRegistryRepo,
)

JOB_NAME = "otakuracy_v2"
DB_PATH_DEFAULT = Path("/data/otakuracy.db")


# ---------------------------------------------------------------------------
# Stage result carriers (StageResult has no metadata field)
# ---------------------------------------------------------------------------

class _DiscoverOutput(NamedTuple):
    stage: StageResult
    raw_by_source: dict[str, list[RawEventRecord]]


class _ExtractIpOutput(NamedTuple):
    stage: StageResult
    ip_map: dict[str, tuple[str | None, float]]  # {source_url: (ip_id, confidence)}


class _DedupOutput(NamedTuple):
    stage: StageResult
    merged_events: list[DeduplicatedEvent]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_pipeline_v2(
    db_path: Path = DB_PATH_DEFAULT,
    eplus_pages: int = 5,
    eventernote_pages: int = 10,
) -> JobResult:
    """Main entry point for the new pipeline."""
    import uuid
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    start = time.monotonic()
    stages: list[StageResult] = []

    # Ensure DB exists
    init_db(db_path)
    conn = get_connection(db_path)

    try:
        # Stage 1: discover_events
        discover_out = _stage_discover(eplus_pages, eventernote_pages)
        stages.append(discover_out.stage)
        if discover_out.stage.status == StageStatus.FAILED:
            return _build_result(run_id, stages, start)

        # Stage 2: extract_ip (Claude Gateway)
        extract_ip_out = _stage_extract_ip(conn, discover_out.raw_by_source)
        stages.append(extract_ip_out.stage)

        # Stage 3: dedup (source-internal + cross-source)
        dedup_out = _stage_dedup(discover_out.raw_by_source, extract_ip_out.ip_map)
        stages.append(dedup_out.stage)

        # Stage 4: persist to DB
        persist_stage = _stage_persist(conn, dedup_out.merged_events, extract_ip_out.ip_map)
        stages.append(persist_stage)

    finally:
        conn.close()

    return _build_result(run_id, stages, start)


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

def _stage_discover(eplus_pages: int, eventernote_pages: int) -> _DiscoverOutput:
    """Stage 1: Collect raw events from all primary sources."""
    start = time.monotonic()
    raw_by_source: dict[str, list[RawEventRecord]] = {}
    total = 0
    errors: list[str] = []

    for source_cls, kwargs in [
        (EplusClient, {"max_pages": eplus_pages}),
        (EventernoteClient, {"pages": eventernote_pages}),
    ]:
        src = source_cls()
        try:
            records = src.collect_raw(**kwargs)
            raw_by_source[src.SOURCE_ID] = records
            total += len(records)
        except Exception as e:
            errors.append(f"{src.SOURCE_ID}: {e}")

    if total == 0:
        stage = StageResult(
            status=StageStatus.FAILED,
            stage="discover_events",
            output_count=0,
            warnings=errors,
            failure_code=FailureCode.SOURCE_EMPTY,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    else:
        stage = StageResult(
            status=StageStatus.SUCCESS,
            stage="discover_events",
            output_count=total,
            warnings=errors,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    return _DiscoverOutput(stage=stage, raw_by_source=raw_by_source)


def _stage_extract_ip(
    conn,
    raw_by_source: dict[str, list[RawEventRecord]],
) -> _ExtractIpOutput:
    """Stage 2: IP extraction via Claude Gateway."""
    from collect.extract_ip import extract_ip_batch
    import os

    start = time.monotonic()
    all_records = [r for recs in raw_by_source.values() for r in recs]
    ip_repo = IpRegistryRepo(conn)
    gateway_url = os.getenv("CLAUDE_GATEWAY_URL", "http://127.0.0.1:18080")

    ip_map = extract_ip_batch(all_records, ip_repo, gateway_url=gateway_url)
    identified = sum(1 for v in ip_map.values() if v[0] is not None)

    stage = StageResult(
        status=StageStatus.SUCCESS,
        stage="extract_ip",
        input_count=len(all_records),
        output_count=identified,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return _ExtractIpOutput(stage=stage, ip_map=ip_map)


def _stage_dedup(
    raw_by_source: dict[str, list[RawEventRecord]],
    ip_map: dict[str, tuple[str | None, float]] | None = None,
) -> _DedupOutput:
    """Stage 3: Dedup within source then merge across sources."""
    start = time.monotonic()
    input_count = sum(len(v) for v in raw_by_source.values())

    # Flatten ip_map from (ip_id, confidence) tuples to {url: ip_id}
    flat_ip_map: dict[str, str | None] = {}
    if ip_map:
        flat_ip_map = {url: ip_id for url, (ip_id, _conf) in ip_map.items()}

    deduped_by_source = {}
    for source_id, records in raw_by_source.items():
        deduped_by_source[source_id] = dedup_within_source(records, ip_map=flat_ip_map)

    merged = merge_across_sources(deduped_by_source, ip_map=flat_ip_map)

    stage = StageResult(
        status=StageStatus.SUCCESS,
        stage="dedup",
        input_count=input_count,
        output_count=len(merged),
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return _DedupOutput(stage=stage, merged_events=merged)


def _stage_persist(
    conn,
    merged_events: list[DeduplicatedEvent],
    ip_map: dict[str, tuple[str | None, float]] | None = None,
) -> StageResult:
    """Stage 4: Persist deduplicated events and source records to SQLite."""
    start = time.monotonic()
    src_repo = EventSourceRecordRepo(conn)
    event_repo = EventRepo(conn)
    ip_link_repo = EventIpLinkRepo(conn)
    if ip_map is None:
        ip_map = {}
    saved = 0

    for dedup_ev in merged_events:
        recs = [dedup_ev.primary] + list(dedup_ev.merged)
        for rec in recs:
            if src_repo.exists_by_url(rec.source_url):
                continue
            src_repo.insert({
                "source_id": rec.source_id,
                "source_url": rec.source_url,
                "fetched_at": rec.fetched_at.isoformat(),
                "raw_title": rec.raw_title,
                "raw_date_text": rec.raw_date_text,
                "raw_venue_text": rec.raw_venue_text,
                "raw_price_text": rec.raw_price_text,
                "raw_body": rec.raw_body,
            })
        # Insert normalized event from primary record
        event_id = event_repo.insert({
            "title": dedup_ev.primary.raw_title,
            "official_url": dedup_ev.primary.source_url,
            "source_confidence": dedup_ev.merge_score,
            "raw_date_text": dedup_ev.primary.raw_date_text,
            "raw_venue_text": dedup_ev.primary.raw_venue_text,
        })
        saved += 1

        # Link event to IP via event_ip_link
        for rec in recs:
            entry = ip_map.get(rec.source_url)
            if entry is not None:
                ip_id, conf = entry
                if ip_id:
                    ip_link_repo.link(event_id, ip_id, confidence=conf)

    return StageResult(
        status=StageStatus.SUCCESS,
        stage="persist",
        input_count=len(merged_events),
        output_count=saved,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_result(run_id: str, stages: list[StageResult], start: float) -> JobResult:
    failed = [s for s in stages if s.status == StageStatus.FAILED]
    if len(failed) == len(stages):
        status, fc = JobStatus.FAILED, failed[0].failure_code
    elif failed:
        status, fc = JobStatus.PARTIAL, None
    else:
        status, fc = JobStatus.SUCCESS, None
    return JobResult(
        status=status,
        job_name=JOB_NAME,
        run_id=run_id,
        stages=stages,
        artifact_root=Path("/data"),
        failure_code=fc,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def smoke_check_v2() -> dict:
    """Lightweight connectivity check."""
    import requests
    try:
        r = requests.get("https://eplus.jp/sf/event/anime/tokyo", timeout=10)
        return {"ok": r.status_code < 500, "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}
