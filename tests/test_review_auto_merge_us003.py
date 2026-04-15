"""Tests for US-003: Implement the review stage auto-merge path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docos.models.patch import MergeStatus, Patch
from docos.models.run import PIPELINE_STAGES, RunManifest, RunStatus, StageStatus
from docos.run_store import RunStore


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


def _ensure_fixtures() -> None:
    """Ensure test fixtures exist on disk."""
    from tests.fixtures.build_fixtures import get_all_fixtures

    get_all_fixtures()


class TestAutoMergePath:
    """US-003: Low-risk runs auto-merge all patches through PatchService."""

    def test_auto_merge_sets_patch_status(self, tmp_path: Path) -> None:
        """Auto-merge path transitions all patches to AUTO_MERGED status."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
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
        assert result.review_status == "auto_merged"

        # Verify patches are auto-merged
        from docos.artifact_stores import PatchStore

        patch_store = PatchStore(tmp_path / "artifacts" / "patches")
        for p in result.patches:
            loaded = patch_store.get(p.patch_id)
            assert loaded is not None
            assert loaded.merge_status == MergeStatus.AUTO_MERGED

    def test_auto_merge_writes_review_artifact_with_release_decision(self, tmp_path: Path) -> None:
        """Auto-merge path writes a structured review artifact with release_decision."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
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

        assert review_data["review_status"] == "auto_merged"
        assert review_data["release_decision"] == "auto_merge"
        assert review_data["gate_passed"] is True
        assert "patch_ids" in review_data
        assert len(review_data["patch_ids"]) == len(result.patches)

    def test_manifest_shows_auto_merged_review_status(self, tmp_path: Path) -> None:
        """RunManifest records auto_merged review_status and matching release reasoning."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
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
        assert manifest.review_status == "auto_merged"
        assert manifest.release_reasoning is not None
        assert len(manifest.release_reasoning) > 0
