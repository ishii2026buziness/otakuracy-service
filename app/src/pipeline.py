"""Service pipeline."""
from common.contracts import JobResult, StageResult, FailureCode
from common.artifacts import ArtifactStore


def run_pipeline(run_id: str, artifacts: ArtifactStore) -> JobResult:
    """Main pipeline logic. Replace with actual implementation."""
    stages = []

    # TODO: implement stages
    stage = StageResult(name="example", success=True, count=0)
    stages.append(stage)

    return JobResult(
        pipeline="otakuracy",
        run_id=run_id,
        success=True,
        stages=stages,
    )
