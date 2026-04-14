"""Run Manifest — tracks a single pipeline execution from ingest to completion.

Each run is identified by a stable ``run_id`` and records the ordered pipeline
stages, linked source, and artifact root directory.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Stage / run status
# ---------------------------------------------------------------------------

class StageStatus(str, Enum):
    """Status of a single pipeline stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    """Overall status of a run."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Pipeline stage
# ---------------------------------------------------------------------------

# Canonical ordered pipeline stages
PIPELINE_STAGES: list[str] = [
    "ingest",
    "route",
    "parse",
    "normalize",
    "extract",
    "compile",
    "patch",
    "lint",
    "harness",
    "gate",
]


class PipelineStage(BaseModel):
    """A single stage in the pipeline execution."""

    name: str
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_detail: str | None = None


# ---------------------------------------------------------------------------
# Run manifest
# ---------------------------------------------------------------------------

class RunManifest(BaseModel):
    """A run manifest — one per pipeline execution.

    Invariants:
    - run_id must be stable and unique.
    - source_id links back to the SourceRegistry entry.
    - stages are ordered and cover the full pipeline lifecycle.
    - artifact_root is the base directory for all run artifacts.
    """

    # Identity
    run_id: str = Field(description="Stable unique run identifier")
    source_id: str = Field(description="Linked source identifier")

    # Source reference
    source_file_path: str = Field(description="Original source file path")

    # Status
    status: RunStatus = RunStatus.CREATED
    stages: list[PipelineStage] = Field(default_factory=list)

    # Artifact storage
    artifact_root: str = Field(description="Base directory for run artifacts")

    # Artifact links (populated as pipeline stages complete)
    ir_artifact_path: str | None = Field(default=None, description="Path to persisted DocIR artifact")
    knowledge_artifact_path: str | None = Field(default=None, description="Path to persisted knowledge artifact")
    patch_artifact_path: str | None = Field(default=None, description="Path to persisted patch artifact")
    report_artifact_path: str | None = Field(default=None, description="Path to persisted report artifact")
    wiki_state_path: str | None = Field(default=None, description="Path to persisted wiki state artifact")
    route_artifact_path: str | None = Field(default=None, description="Path to persisted route decision artifact")
    lint_artifact_path: str | None = Field(default=None, description="Path to persisted lint findings artifact")
    debug_artifact_path: str | None = Field(default=None, description="Path to debug assets directory")

    # Temporal
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = Field(default=None, description="When the pipeline run started")
    finished_at: datetime | None = Field(default=None, description="When the pipeline run finished")

    def mark_stage(self, name: str, status: StageStatus, error_detail: str | None = None) -> None:
        """Update a stage's status by name."""
        for stage in self.stages:
            if stage.name == name:
                stage.status = status
                if status == StageStatus.RUNNING:
                    stage.started_at = datetime.now()
                if status in (StageStatus.COMPLETED, StageStatus.FAILED):
                    stage.completed_at = datetime.now()
                if error_detail is not None:
                    stage.error_detail = error_detail
                self.updated_at = datetime.now()
                return

        msg = f"Unknown stage: {name}"
        raise ValueError(msg)

    @classmethod
    def create(
        cls,
        run_id: str,
        source_id: str,
        source_file_path: str,
        artifact_root: str,
    ) -> RunManifest:
        """Create a new run manifest with all pipeline stages set to pending."""
        stages = [PipelineStage(name=name) for name in PIPELINE_STAGES]
        return cls(
            run_id=run_id,
            source_id=source_id,
            source_file_path=source_file_path,
            artifact_root=artifact_root,
            stages=stages,
        )
