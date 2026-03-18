"""Otakuracy collection pipeline."""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common.contracts import FailureCode, JobResult, JobStatus, StageResult, StageStatus

JOB_NAME = "otakuracy"
DATA_DIR = Path("/data")
WHITELIST_PATH = DATA_DIR / "whitelist.json"
EVENTS_DIR = DATA_DIR / "events"
PROCESSED_PATH = DATA_DIR / "events_processed.json"


async def run_pipeline() -> JobResult:
    import uuid
    from datetime import datetime

    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    start = time.monotonic()
    stages: list[StageResult] = []

    artifact_root = DATA_DIR / "artifacts" / run_id
    artifact_root.mkdir(parents=True, exist_ok=True)

    # --- Stage 1: fetch-all-events ---
    stage_start = time.monotonic()
    fetch_stage = _run_fetch_all(run_id, artifact_root)
    stages.append(fetch_stage)

    # --- Stage 2: build-processed ---
    if fetch_stage.status != StageStatus.FAILED:
        dedup_stage = _run_build_processed(run_id, artifact_root)
        stages.append(dedup_stage)

    total_ms = int((time.monotonic() - start) * 1000)

    failed = [s for s in stages if s.status == StageStatus.FAILED]
    if len(failed) == len(stages):
        status = JobStatus.FAILED
        failure_code = failed[0].failure_code
    elif failed:
        status = JobStatus.PARTIAL
        failure_code = None
    else:
        status = JobStatus.SUCCESS
        failure_code = None

    return JobResult(
        status=status,
        job_name=JOB_NAME,
        run_id=run_id,
        stages=stages,
        artifact_root=artifact_root,
        failure_code=failure_code,
        duration_ms=total_ms,
    )


def _run_fetch_all(run_id: str, artifact_root: Path) -> StageResult:
    from collect.official_site import OfficialSiteClient
    from collect.whitelist import load_whitelist

    start = time.monotonic()
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    if not WHITELIST_PATH.exists():
        return StageResult(
            status=StageStatus.FAILED,
            stage="fetch-all-events",
            failure_code=FailureCode.CONFIG_INVALID,
            duration_ms=int((time.monotonic() - start) * 1000),
            warnings=[f"whitelist not found: {WHITELIST_PATH}"],
        )

    try:
        whitelist = load_whitelist(str(WHITELIST_PATH))
    except Exception as e:
        return StageResult(
            status=StageStatus.FAILED,
            stage="fetch-all-events",
            failure_code=FailureCode.CONFIG_INVALID,
            duration_ms=int((time.monotonic() - start) * 1000),
            warnings=[str(e)],
        )

    targets = [(k, v["official_url"]) for k, v in whitelist.items() if v.get("official_url")]
    if not targets:
        return StageResult(
            status=StageStatus.FAILED,
            stage="fetch-all-events",
            failure_code=FailureCode.SOURCE_EMPTY,
            duration_ms=int((time.monotonic() - start) * 1000),
            warnings=["no IPs with official_url in whitelist"],
        )

    client = OfficialSiteClient()
    total_events = 0
    errors: list[str] = []
    artifact_paths: list[Path] = []

    def process(ip_name: str, url: str) -> tuple[str, int, Path]:
        import json
        events = client.collect_ip_events(ip_name, url)
        slug = re.sub(r"[^\w\-]", "_", ip_name)
        out_path = EVENTS_DIR / f"{slug}.json"
        out_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        return ip_name, len(events), out_path

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process, k, u): k for k, u in targets}
        for future in as_completed(futures):
            try:
                _, count, path = future.result()
                total_events += count
                artifact_paths.append(path)
            except Exception as e:
                errors.append(f"{futures[future]}: {e}")

    return StageResult(
        status=StageStatus.FAILED if total_events == 0 and errors else StageStatus.SUCCESS,
        stage="fetch-all-events",
        input_count=len(targets),
        output_count=total_events,
        artifact_paths=artifact_paths,
        warnings=errors,
        failure_code=FailureCode.OUTPUT_EMPTY if total_events == 0 and errors else None,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def _run_build_processed(run_id: str, artifact_root: Path) -> StageResult:
    import json

    from collect.dedup import dedup_events

    start = time.monotonic()

    try:
        events = dedup_events(str(EVENTS_DIR))
    except Exception as e:
        return StageResult(
            status=StageStatus.FAILED,
            stage="build-processed",
            failure_code=FailureCode.UNEXPECTED_ERROR,
            duration_ms=int((time.monotonic() - start) * 1000),
            warnings=[str(e)],
        )

    if not events:
        return StageResult(
            status=StageStatus.FAILED,
            stage="build-processed",
            failure_code=FailureCode.OUTPUT_EMPTY,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    PROCESSED_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

    return StageResult(
        status=StageStatus.SUCCESS,
        stage="build-processed",
        input_count=0,
        output_count=len(events),
        artifact_paths=[PROCESSED_PATH],
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def smoke_check() -> dict:
    """Lightweight connectivity check: hit eventernote top page."""
    import requests
    try:
        r = requests.get("https://www.eventernote.com", timeout=10)
        return {"ok": r.status_code < 500, "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def config_check() -> dict:
    """Verify whitelist exists and claude CLI is available."""
    import shutil
    issues = []
    if not WHITELIST_PATH.exists():
        issues.append(f"whitelist missing: {WHITELIST_PATH}")
    if not shutil.which("claude"):
        issues.append("claude CLI not found in PATH")
    return {"ok": len(issues) == 0, "issues": issues}
