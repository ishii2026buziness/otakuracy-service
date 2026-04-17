"""
New unified pipeline: discover -> dedup -> persist, one month at a time.
Both sources fetched in parallel per month, committed per month.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
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


def _generate_months(months_ahead: int) -> list[tuple[int, int]]:
    """Return (year, month) tuples from current month for months_ahead months."""
    today = date.today()
    year, month = today.year, today.month
    result = []
    for _ in range(months_ahead + 1):
        result.append((year, month))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return result


def _fetch_month(year: int, month: int) -> dict[str, list[RawEventRecord]]:
    """Fetch both sources for a given month in parallel threads."""
    eplus = EplusClient()
    eventernote = EventernoteClient()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_eplus = pool.submit(eplus.collect_month, year, month)
        f_en = pool.submit(eventernote.collect_month, year, month)
        eplus_recs = f_eplus.result()
        en_recs = f_en.result()

    return {"eplus": eplus_recs, "eventernote": en_recs}


def _process_month(
    conn,
    year: int,
    month: int,
    raw_by_source: dict[str, list[RawEventRecord]],
) -> tuple[int, int]:
    """Extract IP, dedup, persist one month. Returns (discovered, saved)."""
    import os
    from collect.extract_ip import extract_ip_batch

    all_records = [r for recs in raw_by_source.values() for r in recs]
    if not all_records:
        return 0, 0

    ip_repo = IpRegistryRepo(conn)
    gateway_url = os.getenv("CLAUDE_GATEWAY_URL", "http://127.0.0.1:18080")
    ip_map = extract_ip_batch(all_records, ip_repo, gateway_url=gateway_url)

    # dedup
    flat_ip = {url: ip_id for url, (ip_id, _c, _cat) in ip_map.items()}
    deduped = {}
    for source_id, recs in raw_by_source.items():
        deduped[source_id] = dedup_within_source(recs, ip_map=flat_ip)
    merged = merge_across_sources(deduped, ip_map=flat_ip)

    # persist
    src_repo = EventSourceRecordRepo(conn)
    event_repo = EventRepo(conn)
    ip_link_repo = EventIpLinkRepo(conn)
    saved = 0

    for dedup_ev in merged:
        for rec in [dedup_ev.primary] + list(dedup_ev.merged):
            if not src_repo.exists_by_url(rec.source_url):
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
        primary_entry = ip_map.get(dedup_ev.primary.source_url)
        category = primary_entry[2] if primary_entry else "other"
        event_id = event_repo.insert({
            "title": dedup_ev.primary.raw_title,
            "official_url": dedup_ev.primary.source_url,
            "source_confidence": dedup_ev.merge_score,
            "raw_date_text": dedup_ev.primary.raw_date_text,
            "raw_venue_text": dedup_ev.primary.raw_venue_text,
            "category": category,
        })
        saved += 1
        for rec in [dedup_ev.primary] + list(dedup_ev.merged):
            entry = ip_map.get(rec.source_url)
            if entry and entry[0]:
                ip_link_repo.link(event_id, entry[0], confidence=entry[1])

    conn.commit()
    return len(all_records), saved


async def run_pipeline_v2(
    db_path: Path = DB_PATH_DEFAULT,
    months_ahead: int = 6,
    # legacy params ignored but accepted for compat
    eplus_pages: int = 0,
    eventernote_pages: int = 0,
) -> JobResult:
    import uuid
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    start = time.monotonic()

    init_db(db_path)
    conn = get_connection(db_path)

    months = _generate_months(months_ahead)
    total_discovered = 0
    total_saved = 0
    stages: list[StageResult] = []

    try:
        for year, month in months:
            month_label = f"{year}-{month:02d}"
            t = time.monotonic()
            try:
                raw_by_source = _fetch_month(year, month)
                discovered, saved = _process_month(conn, year, month, raw_by_source)
                total_discovered += discovered
                total_saved += saved
                stages.append(StageResult(
                    status=StageStatus.SUCCESS,
                    stage=f"month_{month_label}",
                    input_count=discovered,
                    output_count=saved,
                    duration_ms=int((time.monotonic() - t) * 1000),
                ))
                print(f"[{month_label}] {discovered} → {saved} saved", flush=True)
            except Exception as e:
                stages.append(StageResult(
                    status=StageStatus.FAILED,
                    stage=f"month_{month_label}",
                    input_count=0,
                    output_count=0,
                    warnings=[str(e)],
                    failure_code=FailureCode.SOURCE_EMPTY,
                    duration_ms=int((time.monotonic() - t) * 1000),
                ))
                print(f"[{month_label}] ERROR: {e}", flush=True)
    finally:
        conn.close()

    failed = [s for s in stages if s.status == StageStatus.FAILED]
    if len(failed) == len(stages):
        job_status, fc = JobStatus.FAILED, failed[0].failure_code
    elif failed:
        job_status, fc = JobStatus.PARTIAL, None
    else:
        job_status, fc = JobStatus.SUCCESS, None

    return JobResult(
        status=job_status,
        job_name=JOB_NAME,
        run_id=run_id,
        stages=stages,
        artifact_root=db_path.parent,
        failure_code=fc,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def smoke_check_v2() -> dict:
    import requests
    try:
        r = requests.get("https://eplus.jp/sf/event/month-04", timeout=10)
        return {"ok": r.status_code < 500, "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}
