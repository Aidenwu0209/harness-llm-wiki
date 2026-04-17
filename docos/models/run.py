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
    "review",
]


class PipelineStage(BaseModel):
    """A single stage in the pipeline execution."""

    name: str
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_detail: str | None = None
    duration_seconds: float | None = Field(default=None, description="Stage duration in seconds")
    warnings: list[str] = Field(default_factory=list, description="Warnings recorded during this stage")


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
    review_artifact_path: str | None = Field(default=None, description="Path to persisted review artifact")
    review_ids: list[str] = Field(default_factory=list, description="IDs of review items created for this run")

    # Temporal
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = Field(default=None, description="When the pipeline run started")
    finished_at: datetime | None = Field(default=None, description="When the pipeline run finished")

    # Observability fields (US-034)
    selected_route: str | None = Field(default=None, description="Route selected by the router")
    parser_chain: list[str] = Field(default_factory=list, description="Ordered list of parsers attempted")
    fallback_used: bool = Field(default=False, description="Whether a fallback parser was used")
    lint_summary: dict[str, int] = Field(default_factory=dict, description="Lint findings count by severity")
    harness_summary: dict[str, object] = Field(default_factory=dict, description="Harness evaluation summary")
    gate_decision: str | None = Field(default=None, description="Gate pass/block decision")
    gate_blockers: list[str] = Field(default_factory=list, description="Reasons the gate blocked auto-merge")
    release_reasoning: list[str] = Field(default_factory=list, description="Reasoning for the release decision")
    review_status: str | None = Field(default=None, description="Current review status (pending/approved/rejected/none)")

    # Compile summary fields (US-008, US-012)
    compiled_page_count: int = Field(default=0, description="Total number of compiled pages")
    compiled_page_types: list[str] = Field(default_factory=list, description="Types of compiled pages (source, entity, concept)")
    compiled_patch_count: int = Field(default=0, description="Number of patches generated during compile")
    compiled_created_count: int = Field(default=0, description="Number of newly created pages")
    compiled_updated_count: int = Field(default=0, description="Number of updated pages")
    compiled_deleted_count: int = Field(default=0, description="Number of pages marked for deletion")
    dropped_empty_slug_count: int = Field(default=0, description="Number of candidates dropped due to empty slug/filename")
    dropped_unreadable_title_count: int = Field(default=0, description="Number of entity/concept candidates dropped due to unreadable title")

    # Manual override audit fields (US-026)
    override_reviewer: str | None = Field(default=None, description="Identity of the reviewer who overrode the gate")
    override_reason: str | None = Field(default=None, description="Required reason for the manual override")
    override_timestamp: datetime | None = Field(default=None, description="When the override was applied")
    overridden_checks: list[str] = Field(default_factory=list, description="Which gate checks were overridden")

    def mark_stage(self, name: str, status: StageStatus, error_detail: str | None = None) -> None:
        """Update a stage's status by name."""
        for stage in self.stages:
            if stage.name == name:
                stage.status = status
                if status == StageStatus.RUNNING:
                    stage.started_at = datetime.now()
                if status in (StageStatus.COMPLETED, StageStatus.FAILED):
                    stage.completed_at = datetime.now()
                    if stage.started_at is not None:
                        delta = stage.completed_at - stage.started_at
                        stage.duration_seconds = delta.total_seconds()
                if error_detail is not None:
                    stage.error_detail = error_detail
                self.updated_at = datetime.now()
                return

        msg = f"Unknown stage: {name}"
        raise ValueError(msg)

    def add_stage_warning(self, name: str, warning: str) -> None:
        """Append a warning to the specified stage."""
        for stage in self.stages:
            if stage.name == name:
                stage.warnings.append(warning)
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
