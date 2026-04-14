"""Tests for US-004: Persist ingest and route artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore


def _make_test_config(config_dir: Path) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "router.yaml"
    config_path.write_text(
        "environment: local\nschema_version: '1'\n"
        "router:\n  default_route: fallback_safe_route\n  routes:\n"
        "    - name: fallback_safe_route\n      description: 'test'\n"
        "      file_types: ['application/pdf']\n"
        "      primary_parser: stdlib_pdf\n      fallback_parsers: [basic_text_fallback]\n"
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


class TestIngestArtifacts:
    """US-004: Ingest writes source copy, source registry record, and content hash."""

    def test_raw_source_copy_persisted(self, tmp_path: Path) -> None:
        """Ingest creates an immutable raw source copy."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # Raw source should be stored under raw/<source_id>/original.pdf
        source = runner.source_registry.get(result.source_id)
        assert source is not None
        assert source.raw_storage_path is not None
        raw_path = Path(source.raw_storage_path)
        assert raw_path.exists()
        assert raw_path.stat().st_size > 0

    def test_source_registry_record_persisted(self, tmp_path: Path) -> None:
        """Ingest creates a source registry record."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # Registry record should be on disk
        record_path = tmp_path / "registry" / "records" / f"{result.source_id}.json"
        assert record_path.exists()
        record_data = json.loads(record_path.read_text())
        assert record_data["source_id"] == result.source_id
        assert record_data["source_hash"] != ""

    def test_content_hash_persisted(self, tmp_path: Path) -> None:
        """Ingest stores content hash in metadata."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # Metadata should contain the content hash
        metadata_path = tmp_path / "raw" / result.source_id / "metadata.json"
        assert metadata_path.exists()
        metadata = json.loads(metadata_path.read_text())
        assert "source_hash" in metadata
        assert len(metadata["source_hash"]) == 64  # SHA-256 hex


class TestRouteArtifacts:
    """US-004: Route writes signals, route_decision, and scoring details."""

    def test_route_decision_json_persisted(self, tmp_path: Path) -> None:
        """Route writes route_decision.json to persistent storage."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # route_artifact_path should be set and file should exist
        assert manifest.route_artifact_path is not None
        route_path = Path(manifest.route_artifact_path)
        assert route_path.exists()

        route_data = json.loads(route_path.read_text())
        assert "selected_route" in route_data
        assert "primary_parser" in route_data
        assert "fallback_parsers" in route_data

    def test_route_signals_in_route_log(self, tmp_path: Path) -> None:
        """Route writes signals to the route log."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # Route log should contain signals
        source = runner.source_registry.get(result.source_id)
        assert source is not None

        route_log_path = tmp_path / "route_logs" / f"route_{source.source_id}.json"
        assert route_log_path.exists()
        log_data = json.loads(route_log_path.read_text())
        assert "signals" in log_data
        assert "file_type" in log_data["signals"]

    def test_route_scoring_details_persisted(self, tmp_path: Path) -> None:
        """Route writes scoring details with per-route scores."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # Route artifact should contain scoring details
        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.route_artifact_path is not None

        route_path = Path(manifest.route_artifact_path)
        route_data = json.loads(route_path.read_text())
        assert "matched_signals" in route_data
        assert "decision_reason" in route_data

        # Route log should have per-route scores
        source = runner.source_registry.get(result.source_id)
        assert source is not None
        route_log_path = tmp_path / "route_logs" / f"route_{source.source_id}.json"
        log_data = json.loads(route_log_path.read_text())
        assert "route_scores" in log_data
        assert len(log_data["route_scores"]) > 0

    def test_manifest_links_ingest_artifact_paths(self, tmp_path: Path) -> None:
        """RunManifest links to ingest artifact paths."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # source_id should be linkable to the source registry
        assert manifest.source_id == result.source_id
        assert manifest.source_file_path != ""

        # Verify source registry record exists
        source = runner.source_registry.get(manifest.source_id)
        assert source is not None
        assert source.raw_storage_path is not None

    def test_manifest_links_route_artifact_paths(self, tmp_path: Path) -> None:
        """RunManifest links to route artifact paths."""
        config_path = _make_test_config(tmp_path / "configs")
        pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # route_artifact_path should be set and link to existing file
        assert manifest.route_artifact_path is not None
        assert Path(manifest.route_artifact_path).exists()
