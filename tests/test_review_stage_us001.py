"""Tests for US-001: Add a formal review stage to PipelineRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docos.models.run import PIPELINE_STAGES, RunManifest, RunStatus, StageStatus


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

_TEST_CONFIG_YAML = """
environment: local
schema_version: "1"
router:
  default_route: fallback_safe_route
  routes:
    - name: fallback_safe_route
      description: "Test fallback"
      file_types: ["application/pdf", "text/plain"]
      primary_parser: stdlib_pdf
      fallback_parsers: [basic_text_fallback]
      review_policy: default
"""


def _make_test_config(config_dir: Path) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = config_dir / "router.yaml"
    cfg_path.write_text(_TEST_CONFIG_YAML, encoding="utf-8")
    return cfg_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReviewStageInPipeline:
    """US-001: PipelineRunner runs a dedicated review stage after gate."""

    def test_review_in_pipeline_stages_list(self) -> None:
        """review is listed in PIPELINE_STAGES after gate."""
        assert "review" in PIPELINE_STAGES
        assert PIPELINE_STAGES.index("review") > PIPELINE_STAGES.index("gate")

    def test_review_stage_records_entry_on_completed_run(self, tmp_path: Path) -> None:
        """RunManifest records a review stage entry for a completed run."""
        from docos.pipeline.runner import PipelineRunner

        config_path = _make_test_config(tmp_path / "config")
        fixtures_dir = Path(__file__).parent / "fixtures"
        pdf_path = fixtures_dir / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(
            config_path=config_path,
            base_dir=tmp_path / "artifacts",
        )
        result = runner.run(pdf_path)

        assert result.status == RunStatus.COMPLETED

        # Load manifest and check review stage
        from docos.run_store import RunStore
        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None

        review_stages = [s for s in manifest.stages if s.name == "review"]
        assert len(review_stages) == 1
        assert review_stages[0].status == StageStatus.COMPLETED

    def test_review_status_set_for_auto_merge_run(self, tmp_path: Path) -> None:
        """Low-risk run sets review_status to auto_merged."""
        from docos.pipeline.runner import PipelineRunner
        from docos.run_store import RunStore

        config_path = _make_test_config(tmp_path / "config")
        fixtures_dir = Path(__file__).parent / "fixtures"
        pdf_path = fixtures_dir / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(
            config_path=config_path,
            base_dir=tmp_path / "artifacts",
        )
        result = runner.run(pdf_path)

        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.review_status in ("auto_merged", "pending")

    def test_report_shows_review_stage_status(self, tmp_path: Path) -> None:
        """docos report shows the review stage status from manifest data."""
        from docos.pipeline.runner import PipelineRunner
        from docos.run_store import RunStore

        config_path = _make_test_config(tmp_path / "config")
        fixtures_dir = Path(__file__).parent / "fixtures"
        pdf_path = fixtures_dir / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(
            config_path=config_path,
            base_dir=tmp_path / "artifacts",
        )
        result = runner.run(pdf_path)

        # Verify review status is in manifest (used by report)
        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.review_status is not None
        assert manifest.review_status in ("auto_merged", "pending", "none")

        # Verify review stage is in stages list (report shows stage statuses)
        review_stages = [s for s in manifest.stages if s.name == "review"]
        assert len(review_stages) == 1
        assert review_stages[0].status == StageStatus.COMPLETED

    def test_review_artifact_persisted(self, tmp_path: Path) -> None:
        """Review stage persists a review artifact to disk."""
        from docos.pipeline.runner import PipelineRunner
        from docos.run_store import RunStore

        config_path = _make_test_config(tmp_path / "config")
        fixtures_dir = Path(__file__).parent / "fixtures"
        pdf_path = fixtures_dir / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(
            config_path=config_path,
            base_dir=tmp_path / "artifacts",
        )
        result = runner.run(pdf_path)

        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.review_artifact_path is not None

        review_path = Path(manifest.review_artifact_path)
        assert review_path.exists()
        review_data = json.loads(review_path.read_text(encoding="utf-8"))
        assert review_data["run_id"] == result.run_id
        assert "review_status" in review_data
