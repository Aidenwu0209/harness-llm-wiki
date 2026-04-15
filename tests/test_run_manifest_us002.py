"""Tests for US-002: RunManifest persistence and reload."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from docos.models.run import PIPELINE_STAGES, RunManifest, RunStatus, StageStatus
from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore


def _make_test_config(config_dir: Path) -> Path:
    """Write a minimal router config and return its path."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "router.yaml"
    config_path.write_text(
        "environment: local\nschema_version: '1'\n"
        "router:\n  default_route: fallback_safe_route\n  routes:\n"
        "    - name: fallback_safe_route\n      description: 'test'\n"
        "      file_types: ['application/pdf']\n"
        "      primary_parser: stdlib_pdf\n      fallback_parsers: [basic_text]\n"
        "      expected_risks: []\n      post_parse_repairs: []\n"
        "      review_policy: default\n"
        "risk_thresholds:\n  high_risk_score: 0.7\n  medium_risk_score: 0.4\n"
        "  high_blast_pages: 5\n  high_blast_claims: 10\n  high_blast_links: 15\n"
        "  auto_merge_max_risk: 0.3\n  auto_merge_max_pages: 3\n"
        "release_gates:\n  block_on_p0_lint: true\n  block_on_p1_lint: true\n"
        "  block_on_unsupported_claim_increase: true\n  block_on_missing_harness: true\n"
        "  block_on_regression_exceeded: true\n  block_on_fallback_low_confidence: true\n"
        "  fallback_confidence_threshold: 0.5\n"
        "  regression_max_claim_change_pct: 10.0\n  regression_max_link_break_count: 0\n"
        "review_policies:\n  default_policy: default\n  policies:\n"
        "    - name: default\n      description: 'test'\n"
        "      require_review_on_fallback: true\n      require_review_on_high_risk: true\n"
        "      require_review_on_high_blast: true\n      require_review_on_conflict: true\n"
        "      require_review_on_entity_merge: true\n"
        "      auto_assign_reviewer: false\n      min_reviewers: 1\n"
        "lint_policy:\n  p0_blocks_merge: true\n  p1_blocks_merge: true\n"
    )
    return config_path


def _write_simple_pdf(path: Path) -> Path:
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 80 >>\nstream\n"
        b"BT /F1 12 Tf 100 700 Td (Introduction) Tj ET\n"
        b"BT /F1 10 Tf 100 680 Td (This is a test document body.) Tj ET\n"
        b"endstream\nendobj\n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n%%EOF"
    )
    path.write_bytes(pdf)
    return path


class TestRunManifestPersistence:
    """US-002: Each run creates a durable RunManifest."""

    def test_run_id_is_real_and_deterministic(self, tmp_path: Path) -> None:
        """Run ID follows run_<hash_prefix>_<time_hex> format."""
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_abc123",
            source_hash="a" * 64,
            source_file_path="/tmp/test.pdf",
        )
        assert manifest.run_id.startswith("run_")
        assert "src_" not in manifest.run_id  # run_id derived from hash, not source_id
        assert manifest.source_id == "src_abc123"

    def test_manifest_persisted_to_disk(self, tmp_path: Path) -> None:
        """RunManifest is written to disk and can be reloaded."""
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_test",
            source_hash="b" * 64,
            source_file_path="/tmp/test.pdf",
        )

        # Verify file exists on disk
        manifest_path = tmp_path / "manifests" / f"{manifest.run_id}.json"
        assert manifest_path.exists()

        # Reload in a new store instance (simulating new process)
        store2 = RunStore(tmp_path)
        reloaded = store2.get(manifest.run_id)
        assert reloaded is not None
        assert reloaded.run_id == manifest.run_id
        assert reloaded.source_id == manifest.source_id

    def test_manifest_has_all_pipeline_stages(self, tmp_path: Path) -> None:
        """RunManifest contains all expected pipeline stages."""
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_stages",
            source_hash="c" * 64,
            source_file_path="/tmp/test.pdf",
        )
        stage_names = [s.name for s in manifest.stages]
        assert stage_names == PIPELINE_STAGES

    def test_per_stage_status_tracking(self, tmp_path: Path) -> None:
        """Each stage's status, started_at, completed_at, error_detail are tracked."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # All stages should be completed with timestamps
        for stage in manifest.stages:
            assert stage.status == StageStatus.COMPLETED, f"{stage.name} is {stage.status}"
            assert stage.started_at is not None, f"{stage.name} missing started_at"
            assert stage.completed_at is not None, f"{stage.name} missing completed_at"

    def test_run_level_start_finish_times(self, tmp_path: Path) -> None:
        """Run-level started_at and finished_at are set."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.started_at is not None
        assert manifest.finished_at is not None
        assert manifest.finished_at >= manifest.started_at

    def test_failed_run_records_error_in_manifest(self, tmp_path: Path) -> None:
        """A failing run records the failing stage and error detail."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "router.yaml"
        # Use valid parser but no fallback, so parse failure causes pipeline to fail
        config_path.write_text(
            "environment: local\nschema_version: '1'\n"
            "router:\n  default_route: fallback_safe_route\n  routes:\n"
            "    - name: fallback_safe_route\n      description: 'test'\n"
            "      file_types: ['application/pdf']\n"
            "      primary_parser: stdlib_pdf\n      fallback_parsers: []\n"
            "      expected_risks: []\n      post_parse_repairs: []\n"
            "      review_policy: default\n"
            "risk_thresholds:\n  high_risk_score: 0.7\n  medium_risk_score: 0.4\n"
            "  high_blast_pages: 5\n  high_blast_claims: 10\n  high_blast_links: 15\n"
            "  auto_merge_max_risk: 0.3\n  auto_merge_max_pages: 3\n"
            "release_gates:\n  block_on_p0_lint: true\n  block_on_p1_lint: true\n"
            "  block_on_unsupported_claim_increase: true\n  block_on_missing_harness: true\n"
            "  block_on_regression_exceeded: true\n  block_on_fallback_low_confidence: true\n"
            "  fallback_confidence_threshold: 0.5\n"
            "  regression_max_claim_change_pct: 10.0\n  regression_max_link_break_count: 0\n"
            "review_policies:\n  default_policy: default\n  policies:\n"
            "    - name: default\n      description: 'test'\n"
            "      require_review_on_fallback: true\n      require_review_on_high_risk: true\n"
            "      require_review_on_high_blast: true\n      require_review_on_conflict: true\n"
            "      require_review_on_entity_merge: true\n"
            "      auto_assign_reviewer: false\n      min_reviewers: 1\n"
            "lint_policy:\n  p0_blocks_merge: true\n  p1_blocks_merge: true\n"
        )
        # Use a corrupted PDF (no %PDF header) so stdlib_pdf fails at parse stage
        corrupted_pdf = b"CORRUPTED-HEADER\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(corrupted_pdf)
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "failed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.status == RunStatus.FAILED

        # Find the failed stage
        failed_stages = [s for s in manifest.stages if s.status == StageStatus.FAILED]
        assert len(failed_stages) >= 1
        assert failed_stages[0].error_detail is not None

    def test_manifest_reload_after_process_exit(self, tmp_path: Path) -> None:
        """Simulate process restart — reload manifest from disk."""
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_reload",
            source_hash="d" * 64,
            source_file_path="/tmp/test.pdf",
        )
        manifest.mark_stage("ingest", StageStatus.COMPLETED)
        manifest.mark_stage("route", StageStatus.FAILED, error_detail="route config missing")
        store.update(manifest)

        # Simulate new process
        new_store = RunStore(tmp_path)
        reloaded = new_store.get(manifest.run_id)
        assert reloaded is not None
        assert reloaded.status == RunStatus.CREATED

        # Check stage states persisted
        ingest_stage = next(s for s in reloaded.stages if s.name == "ingest")
        assert ingest_stage.status == StageStatus.COMPLETED

        route_stage = next(s for s in reloaded.stages if s.name == "route")
        assert route_stage.status == StageStatus.FAILED
        assert route_stage.error_detail == "route config missing"
