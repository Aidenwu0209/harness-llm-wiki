"""Tests for US-034: Expand run observability and debug summaries."""

from __future__ import annotations

import json
from pathlib import Path

from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore
from tests.fixtures.build_fixtures import _build_simple_pdf


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

_TEST_CONFIG_YAML = (
    "environment: local\nschema_version: '1'\n"
    "router:\n  default_route: fallback_safe_route\n  routes:\n"
    "    - name: fallback_safe_route\n"
    "      description: 'Safe fallback'\n"
    "      file_types: ['application/pdf']\n"
    "      primary_parser: stdlib_pdf\n"
    "      fallback_parsers: [basic_text_fallback]\n"
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


def _setup_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "router.yaml"
    config_path.write_text(_TEST_CONFIG_YAML)
    return config_path


class TestObservability:
    """RunManifest records core run trace fields."""

    def test_manifest_records_selected_route(self, tmp_path: Path) -> None:
        """RunManifest records the selected route."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.selected_route is not None
        assert manifest.selected_route != ""

    def test_manifest_records_parser_chain(self, tmp_path: Path) -> None:
        """RunManifest records the parser chain (primary + fallbacks)."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert len(manifest.parser_chain) > 0
        assert "stdlib_pdf" in manifest.parser_chain or "basic_text_fallback" in manifest.parser_chain

    def test_manifest_records_fallback_used(self, tmp_path: Path) -> None:
        """RunManifest records whether fallback parser was used."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        # fallback_used should be a boolean (either True or False)
        assert isinstance(manifest.fallback_used, bool)

    def test_manifest_records_lint_summary(self, tmp_path: Path) -> None:
        """RunManifest records lint findings summary by severity."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        # lint_summary should be a dict (may be empty if no findings)
        assert isinstance(manifest.lint_summary, dict)

    def test_manifest_records_harness_summary(self, tmp_path: Path) -> None:
        """RunManifest records harness evaluation summary."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert isinstance(manifest.harness_summary, dict)
        if manifest.harness_summary:
            assert "overall_passed" in manifest.harness_summary

    def test_manifest_records_gate_decision(self, tmp_path: Path) -> None:
        """RunManifest records gate pass/block decision."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.gate_decision in ("passed", "blocked")

    def test_manifest_records_review_status(self, tmp_path: Path) -> None:
        """RunManifest records review status field."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        # review_status field exists (may be None if no review triggered)
        assert hasattr(manifest, "review_status")

    def test_stage_durations_recorded(self, tmp_path: Path) -> None:
        """Each stage records duration_seconds when completed."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        for stage in manifest.stages:
            if stage.status.value == "completed":
                assert stage.duration_seconds is not None, (
                    f"Stage {stage.name} completed but has no duration_seconds"
                )
                assert stage.duration_seconds >= 0

    def test_observability_fields_in_report_output(self, tmp_path: Path) -> None:
        """Report output can display observability fields from persisted data."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Route decision
        assert manifest.route_artifact_path is not None
        route_data = json.loads(Path(manifest.route_artifact_path).read_text())
        assert "selected_route" in route_data
        assert "primary_parser" in route_data

        # Lint findings
        assert manifest.lint_artifact_path is not None
        lint_data = json.loads(Path(manifest.lint_artifact_path).read_text())
        assert isinstance(lint_data, list)

        # Gate decision from manifest
        assert manifest.gate_decision is not None
