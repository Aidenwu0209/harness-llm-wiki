"""Tests for US-034: Expand run observability and debug summaries.

Verifies that:
1. RunManifest records selected_route, parser_chain, fallback_used,
   lint_summary, harness_summary, gate_decision, review_status.
2. Each stage records duration_seconds via mark_stage.
3. Warnings can be recorded per stage via add_stage_warning.
4. The manifest serializes/deserializes all observability fields.
5. Report output reads these fields from persisted data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from docos.cli.main import cli
from docos.models.run import PIPELINE_STAGES, RunManifest, StageStatus
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


# ---------------------------------------------------------------------------
# 1. Observability fields recorded in manifest from pipeline execution
# ---------------------------------------------------------------------------


class TestObservabilityFields:
    """RunManifest records core run trace fields from pipeline execution."""

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

    def test_manifest_has_review_status_field(self, tmp_path: Path) -> None:
        """RunManifest has review_status field."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert hasattr(manifest, "review_status")


# ---------------------------------------------------------------------------
# 2. Stage duration recording
# ---------------------------------------------------------------------------


class TestStageDuration:
    """Verify that mark_stage records duration_seconds on completion."""

    def test_duration_recorded_on_complete(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        stage = m.stages[0]
        assert stage.duration_seconds is None

        m.mark_stage("ingest", StageStatus.RUNNING)
        assert stage.duration_seconds is None

        m.mark_stage("ingest", StageStatus.COMPLETED)
        assert stage.duration_seconds is not None
        assert stage.duration_seconds >= 0

    def test_duration_recorded_on_failure(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        m.mark_stage("route", StageStatus.RUNNING)
        m.mark_stage("route", StageStatus.FAILED, error_detail="routing failed")

        stage = m.stages[1]
        assert stage.duration_seconds is not None
        assert stage.duration_seconds >= 0
        assert stage.error_detail == "routing failed"

    def test_all_stages_have_duration_in_pipeline(self, tmp_path: Path) -> None:
        """Each completed stage records duration_seconds after full pipeline."""
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

    def test_skipped_stage_no_duration(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        stage = m.stages[2]
        assert stage.duration_seconds is None


# ---------------------------------------------------------------------------
# 3. Stage warnings
# ---------------------------------------------------------------------------


class TestStageWarnings:
    """Verify warnings can be recorded per stage."""

    def test_add_single_warning(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        m.add_stage_warning("ingest", "Large file detected")
        stage = m.stages[0]
        assert stage.warnings == ["Large file detected"]

    def test_add_multiple_warnings(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        m.add_stage_warning("parse", "Slow parse")
        m.add_stage_warning("parse", "Missing fonts")
        stage = m.stages[2]
        assert len(stage.warnings) == 2
        assert "Slow parse" in stage.warnings
        assert "Missing fonts" in stage.warnings

    def test_warning_on_nonexistent_stage_raises(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        with pytest.raises(ValueError, match="Unknown stage"):
            m.add_stage_warning("nonexistent_stage", "should fail")

    def test_warnings_across_different_stages(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        m.add_stage_warning("ingest", "warn1")
        m.add_stage_warning("parse", "warn2")
        m.add_stage_warning("lint", "warn3")

        ingest = next(s for s in m.stages if s.name == "ingest")
        parse = next(s for s in m.stages if s.name == "parse")
        lint = next(s for s in m.stages if s.name == "lint")

        assert ingest.warnings == ["warn1"]
        assert parse.warnings == ["warn2"]
        assert lint.warnings == ["warn3"]


# ---------------------------------------------------------------------------
# 4. Serialization / deserialization round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify manifest with observability fields survives JSON round-trip."""

    def test_round_trip_observability_fields(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        m.selected_route = "pdf_stdlib"
        m.parser_chain = ["stdlib_pdf", "basic_text_fallback"]
        m.fallback_used = True
        m.lint_summary = {"error": 1, "warning": 3}
        m.harness_summary = {"overall_passed": False, "release_decision": "block"}
        m.gate_decision = "blocked"
        m.review_status = "pending"
        m.add_stage_warning("parse", "Used fallback parser")

        json_str = m.model_dump_json(indent=2)
        restored = RunManifest.model_validate_json(json_str)

        assert restored.selected_route == "pdf_stdlib"
        assert restored.parser_chain == ["stdlib_pdf", "basic_text_fallback"]
        assert restored.fallback_used is True
        assert restored.lint_summary == {"error": 1, "warning": 3}
        assert restored.harness_summary["overall_passed"] is False
        assert restored.gate_decision == "blocked"
        assert restored.review_status == "pending"

        parse_stage = next(s for s in restored.stages if s.name == "parse")
        assert parse_stage.warnings == ["Used fallback parser"]

    def test_round_trip_with_duration(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        m.mark_stage("ingest", StageStatus.RUNNING)
        m.mark_stage("ingest", StageStatus.COMPLETED)

        json_str = m.model_dump_json(indent=2)
        restored = RunManifest.model_validate_json(json_str)

        ingest = next(s for s in restored.stages if s.name == "ingest")
        assert ingest.duration_seconds is not None
        assert ingest.duration_seconds >= 0

    def test_round_trip_with_error_detail(self) -> None:
        m = RunManifest.create(
            run_id="run_test",
            source_id="src_test",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        m.mark_stage("route", StageStatus.RUNNING)
        m.mark_stage("route", StageStatus.FAILED, error_detail="No matching route")

        json_str = m.model_dump_json(indent=2)
        restored = RunManifest.model_validate_json(json_str)

        route = next(s for s in restored.stages if s.name == "route")
        assert route.status == StageStatus.FAILED
        assert route.error_detail == "No matching route"
        assert route.duration_seconds is not None

    def test_persist_and_reload_via_run_store(self, tmp_path: Path) -> None:
        """Verify observability fields survive RunStore persistence."""
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_obs",
            source_hash="abc123" * 6,
            source_file_path="/tmp/test.pdf",
        )

        manifest.selected_route = "pdf_stdlib"
        manifest.parser_chain = ["stdlib_pdf"]
        manifest.fallback_used = False
        manifest.lint_summary = {"info": 1}
        manifest.harness_summary = {"overall_passed": True}
        manifest.gate_decision = "passed"
        manifest.review_status = "none"
        manifest.add_stage_warning("ingest", "test warning")
        manifest.mark_stage("ingest", StageStatus.RUNNING)
        manifest.mark_stage("ingest", StageStatus.COMPLETED)

        store.update(manifest)

        loaded = store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.selected_route == "pdf_stdlib"
        assert loaded.parser_chain == ["stdlib_pdf"]
        assert loaded.fallback_used is False
        assert loaded.lint_summary == {"info": 1}
        assert loaded.harness_summary["overall_passed"] is True
        assert loaded.gate_decision == "passed"
        assert loaded.review_status == "none"

        ingest = next(s for s in loaded.stages if s.name == "ingest")
        assert ingest.warnings == ["test warning"]
        assert ingest.duration_seconds is not None


# ---------------------------------------------------------------------------
# 5. Report CLI reads observability fields from persisted data
# ---------------------------------------------------------------------------


class TestReportObservability:
    """Verify report output displays observability fields from persisted data."""

    def _run_pipeline(self, tmp_path: Path) -> str:
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status.value == "completed"
        return result.run_id

    def test_report_shows_selected_route(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        assert output.exit_code == 0
        data = json.loads(output.output)
        assert data.get("selected_route") is not None

    def test_report_shows_parser_chain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        parser_chain = data.get("parser_chain")
        assert parser_chain is not None

    def test_report_shows_fallback_used(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "fallback_used" in data
        assert isinstance(data["fallback_used"], bool)

    def test_report_shows_lint_summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "lint_summary" in data

    def test_report_shows_harness_summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "harness_summary" in data
        assert "overall_passed" in data["harness_summary"]

    def test_report_shows_gate_decision(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "gate_decision" in data
        assert data["gate_decision"] in ("passed", "blocked")

    def test_report_shows_review_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        assert "review_status" in data

    def test_report_shows_stage_durations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        stages = data["stages"]
        for stage in stages:
            if stage["status"] == "completed":
                assert stage["duration_seconds"] is not None
                assert stage["duration_seconds"] >= 0

    def test_report_shows_stage_warnings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_id = self._run_pipeline(tmp_path)
        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", run_id])
        data = json.loads(output.output)
        stages = data["stages"]
        for stage in stages:
            assert "warnings" in stage
            assert isinstance(stage["warnings"], list)

    def test_report_reads_persisted_artifacts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output can read observability from persisted artifact files."""
        run_id = self._run_pipeline(tmp_path)

        store = RunStore(tmp_path)
        manifest = store.get(run_id)
        assert manifest is not None

        # Route artifact
        assert manifest.route_artifact_path is not None
        route_data = json.loads(Path(manifest.route_artifact_path).read_text())
        assert "selected_route" in route_data
        assert "primary_parser" in route_data

        # Lint artifact
        assert manifest.lint_artifact_path is not None
        lint_data = json.loads(Path(manifest.lint_artifact_path).read_text())
        assert isinstance(lint_data, list)

        # Gate decision in manifest
        assert manifest.gate_decision is not None
