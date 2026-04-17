"""
Pipeline: fetch all months in parallel first, then dedup+persist to DB.
Phase 1 (network): all months fetched concurrently.
Phase 2 (DB): process months sequentially, commit per month.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from common.contracts import FailureCode, JobResult, JobStatus, StageResult, StageStatus

from collect.base import RawEventRecord
from collect.eplus import EplusClient
from collect.eventernote import EventernoteClient
from collect.dedup_v2 import dedup_within_source, merge_across_sources
from db.repository import (
    init_db, get_connection,
    EventSourceRecordRepo, EventRepo,
)

JOB_NAME = "otakuracy_v2"
DB_PATH_DEFAULT = Path("/data/otakuracy.db")


def _generate_months(months_ahead: int) -> list[tuple[int, int]]:
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
    """Fetch eplus + eventernote for a month in parallel."""
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
    raw_by_source: dict[str, list[RawEventRecord]],
) -> tuple[int, int]:
    """Dedup and persist one month. Returns (discovered, saved)."""
    all_records = [r for recs in raw_by_source.values() for r in recs]
    if not all_records:
        return 0, 0

    deduped = {}
    for source_id, recs in raw_by_source.items():
        deduped[source_id] = dedup_within_source(recs, ip_map={})
    merged = merge_across_sources(deduped, ip_map={})

    src_repo = EventSourceRecordRepo(conn)
    event_repo = EventRepo(conn)
    saved = 0

    for dedup_ev in merged:
        primary_exists = src_repo.exists_by_url(dedup_ev.primary.source_url)
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
        if not primary_exists:
            event_repo.insert({
                "title": dedup_ev.primary.raw_title,
                "official_url": dedup_ev.primary.source_url,
                "source_confidence": dedup_ev.merge_score,
                "raw_date_text": dedup_ev.primary.raw_date_text,
                "raw_venue_text": dedup_ev.primary.raw_venue_text,
                "category": "other",
            })
            saved += 1

    conn.commit()
    return len(all_records), saved


async def run_pipeline_v2(
    db_path: Path = DB_PATH_DEFAULT,
    months_ahead: int = 6,
    eplus_pages: int = 0,
    eventernote_pages: int = 0,
) -> JobResult:
    import uuid
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    start = time.monotonic()

    months = _generate_months(months_ahead)
    raw_data: dict[tuple[int, int], dict[str, list[RawEventRecord]]] = {}
    fetch_errors: dict[tuple[int, int], Exception] = {}

    # Phase 1: fetch all months in parallel (max 4 months at once = 8 connections)
    print(f"[fetch] fetching {len(months)} months...", flush=True)
    fetch_t = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(months)) as pool:
        futures = {pool.submit(_fetch_month, y, m): (y, m) for y, m in months}
        for f in as_completed(futures):
            ym = futures[f]
            month_label = f"{ym[0]}-{ym[1]:02d}"
            try:
                raw_data[ym] = f.result()
                total = sum(len(v) for v in raw_data[ym].values())
                print(f"[fetch] {month_label}: {total} records", flush=True)
            except Exception as e:
                fetch_errors[ym] = e
                print(f"[fetch] {month_label} ERROR: {e}", flush=True)
    print(f"[fetch] done in {time.monotonic()-fetch_t:.1f}s", flush=True)

    # Phase 2: process into DB
    init_db(db_path)
    conn = get_connection(db_path)
    total_discovered = 0
    total_saved = 0
    stages: list[StageResult] = []

    try:
        for year, month in months:
            month_label = f"{year}-{month:02d}"
            t = time.monotonic()
            if (year, month) in fetch_errors:
                e = fetch_errors[(year, month)]
                stages.append(StageResult(
                    status=StageStatus.FAILED,
                    stage=f"month_{month_label}",
                    input_count=0,
                    output_count=0,
                    warnings=[str(e)],
                    failure_code=FailureCode.SOURCE_EMPTY,
                    duration_ms=int((time.monotonic() - t) * 1000),
                ))
                continue
            try:
                raw_by_source = raw_data.get((year, month), {})
                discovered, saved = _process_month(conn, raw_by_source)
                total_discovered += discovered
                total_saved += saved
                stages.append(StageResult(
                    status=StageStatus.SUCCESS,
                    stage=f"month_{month_label}",
                    input_count=discovered,
                    output_count=saved,
                    duration_ms=int((time.monotonic() - t) * 1000),
                ))
                print(f"[db] {month_label}: {discovered} → {saved} saved", flush=True)
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
                print(f"[db] {month_label} ERROR: {e}", flush=True)
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
