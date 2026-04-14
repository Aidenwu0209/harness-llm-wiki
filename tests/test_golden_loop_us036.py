"""Tests for US-036: Validate the golden closed loop from raw fixture to stable rerun.

This story provides the final closed-loop validation: run a raw PDF fixture
through the full pipeline, verify every artifact is persisted, confirm the
report CLI can read them back, re-run the same fixture, and assert that
stable identifiers are preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from docos.artifact_stores import PatchStore, ReportStore
from docos.cli.main import cli
from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeStore
from docos.models.run import RunStatus, StageStatus
from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore
from tests.fixtures.build_fixtures import _build_simple_pdf


# ---------------------------------------------------------------------------
# Config helper (inline YAML pattern used across the test-suite)
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
# Test class
# ---------------------------------------------------------------------------


class TestGoldenClosedLoop:
    """US-036: Golden closed loop from raw fixture to stable rerun."""

    # -- AC-1: All artifacts are persisted after a single golden run --

    def test_golden_run_persists_all_artifacts(self, tmp_path: Path) -> None:
        """Running the golden fixture produces route, parse, DocIR, knowledge,
        patch, lint, harness, and report artifacts on disk."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        # Pipeline completed successfully
        assert result.status == RunStatus.COMPLETED, (
            f"Pipeline failed at {result.failed_stage}: {result.error_detail}"
        )

        # Load manifest for artifact path checks
        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None

        # All 10 stages completed
        for stage in manifest.stages:
            assert stage.status == StageStatus.COMPLETED, (
                f"Stage {stage.name} is {stage.status.value}"
            )

        # 1. Route artifact
        assert manifest.route_artifact_path is not None
        route_path = Path(manifest.route_artifact_path)
        assert route_path.exists(), f"Route artifact missing at {route_path}"
        route_data = json.loads(route_path.read_text())
        assert "selected_route" in route_data
        assert "primary_parser" in route_data

        # 2. Parse/DocIR artifact
        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None, "DocIR artifact not persisted"
        assert docir.page_count >= 1
        assert docir.parser in ("stdlib_pdf", "basic_text_fallback")

        # 3. Knowledge artifact (entities, claims, relations)
        ks = KnowledgeStore(tmp_path / "knowledge")
        knowledge = ks.get(result.run_id)
        assert knowledge is not None, "Knowledge artifact not persisted"
        assert isinstance(knowledge.entities, list)
        assert isinstance(knowledge.claims, list)

        # 4. Patch artifact
        assert manifest.patch_artifact_path is not None, "Patch artifact path not set"
        patch_dir = Path(manifest.patch_artifact_path).parent
        assert patch_dir.exists(), f"Patch artifact directory missing at {patch_dir}"

        # 5. Lint artifact
        assert manifest.lint_artifact_path is not None
        lint_path = Path(manifest.lint_artifact_path)
        assert lint_path.exists(), f"Lint artifact missing at {lint_path}"
        lint_data = json.loads(lint_path.read_text())
        assert isinstance(lint_data, list)

        # 6. Harness report artifact
        assert manifest.report_artifact_path is not None
        rs = ReportStore(tmp_path / "reports")
        harness_report = rs.get(result.run_id)
        assert harness_report is not None, "Harness report not persisted"
        assert harness_report.overall_passed is not None

        # 7. Wiki state artifact
        wiki_state_dir = tmp_path / "wiki_state"
        assert wiki_state_dir.exists(), "Wiki state directory missing"
        wiki_state_files = list(wiki_state_dir.glob("*.json"))
        assert len(wiki_state_files) >= 1, "No wiki state files persisted"

        # 8. Route log (route_logs directory from router)
        route_logs_dir = tmp_path / "route_logs"
        assert route_logs_dir.exists(), "Route logs directory missing"

        # Pipeline result aggregates
        assert result.route_decision is not None
        assert result.harness_passed is not None
        assert result.gate_passed is not None
        assert result.elapsed_seconds > 0

    # -- AC-2: docos report shows route, parser chain, gate decision, artifact locations --

    def test_report_cli_shows_golden_run_info(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`docos report <run_id>` shows final route, parser chain, gate
        decision, and artifact locations for the golden run."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status == RunStatus.COMPLETED

        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", result.run_id])
        assert output.exit_code == 0, f"Report CLI failed: {output.output}"

        data = json.loads(output.output)

        # Route information
        assert "selected_route" in data
        assert data["selected_route"] is not None

        # Parser chain
        parser_chain = data.get("parser_chain")
        assert parser_chain is not None, "parser_chain missing from report"
        # parser_chain is a list (from manifest) or dict
        if isinstance(parser_chain, list):
            assert "stdlib_pdf" in parser_chain, f"stdlib_pdf not in parser chain: {parser_chain}"
        elif isinstance(parser_chain, dict):
            assert "primary" in parser_chain or "stdlib_pdf" in str(parser_chain)

        # Gate decision
        assert "gate_decision" in data, "gate_decision missing from report"

        # Artifact locations
        assert data.get("ir_artifact") != "not-generated-yet", "IR artifact not linked"
        assert data.get("knowledge_artifact") != "not-generated-yet", "Knowledge artifact not linked"
        assert data.get("patch_artifact") != "not-generated-yet", "Patch artifact not linked"
        assert data.get("lint_artifact") is not None, "Lint artifact not linked"
        assert data.get("harness_status") != "not-generated-yet", "Harness status not available"

        # Stage list includes all stages
        stages = data.get("stages", [])
        stage_names = [s["name"] for s in stages]
        assert "route" in stage_names
        assert "parse" in stage_names
        assert "gate" in stage_names

    # -- AC-3: Re-run preserves stable identifiers --

    def test_rerun_preserves_stable_entity_ids(self, tmp_path: Path) -> None:
        """Re-running the same unchanged golden fixture preserves stable
        entity identifiers."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        ks1 = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks1.get(result1.run_id)
        assert artifact1 is not None

        # Run 2 (same file, same config)
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        ks2 = KnowledgeStore(tmp_path / "knowledge")
        artifact2 = ks2.get(result2.run_id)
        assert artifact2 is not None

        # Entity IDs are stable (deterministic from content)
        ids1 = sorted(e.entity_id for e in artifact1.entities)
        ids2 = sorted(e.entity_id for e in artifact2.entities)
        assert ids1 == ids2, (
            f"Entity IDs not stable between runs.\nRun 1: {ids1}\nRun 2: {ids2}"
        )

    def test_rerun_preserves_stable_claim_ids(self, tmp_path: Path) -> None:
        """Re-running the same unchanged golden fixture preserves stable
        claim identifiers."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        ks1 = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks1.get(result1.run_id)
        assert artifact1 is not None

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        ks2 = KnowledgeStore(tmp_path / "knowledge")
        artifact2 = ks2.get(result2.run_id)
        assert artifact2 is not None

        ids1 = sorted(c.claim_id for c in artifact1.claims)
        ids2 = sorted(c.claim_id for c in artifact2.claims)
        assert ids1 == ids2, (
            f"Claim IDs not stable between runs.\nRun 1: {ids1}\nRun 2: {ids2}"
        )

    def test_rerun_preserves_stable_relation_ids(self, tmp_path: Path) -> None:
        """Re-running the same unchanged golden fixture preserves stable
        relation identifiers."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        ks1 = KnowledgeStore(tmp_path / "knowledge")
        artifact1 = ks1.get(result1.run_id)
        assert artifact1 is not None

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        ks2 = KnowledgeStore(tmp_path / "knowledge")
        artifact2 = ks2.get(result2.run_id)
        assert artifact2 is not None

        rel_ids1 = sorted(r.relation_id for r in artifact1.relations)
        rel_ids2 = sorted(r.relation_id for r in artifact2.relations)
        assert rel_ids1 == rel_ids2, (
            f"Relation IDs not stable between runs.\nRun 1: {rel_ids1}\nRun 2: {rel_ids2}"
        )

    def test_rerun_preserves_artifact_structure(self, tmp_path: Path) -> None:
        """Re-running produces the same artifact directory structure and
        same number of pages, blocks, entities, and claims."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        # Run 1
        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        # Run 2
        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        # DocIR structure is the same
        ir_store = IRStore(tmp_path / "ir")
        docir1 = ir_store.get(result1.run_id)
        docir2 = ir_store.get(result2.run_id)
        assert docir1 is not None and docir2 is not None
        assert docir1.page_count == docir2.page_count
        assert len(docir1.blocks) == len(docir2.blocks)

        # Knowledge structure is the same
        ks = KnowledgeStore(tmp_path / "knowledge")
        k1 = ks.get(result1.run_id)
        k2 = ks.get(result2.run_id)
        assert k1 is not None and k2 is not None
        assert len(k1.entities) == len(k2.entities)
        assert len(k1.claims) == len(k2.claims)
        assert len(k1.relations) == len(k2.relations)

        # Route decision is the same
        assert result1.route_decision is not None and result2.route_decision is not None
        assert result1.route_decision.selected_route == result2.route_decision.selected_route
        assert result1.route_decision.primary_parser == result2.route_decision.primary_parser

    def test_rerun_does_not_regress_golden_path(self, tmp_path: Path) -> None:
        """Re-running the golden fixture does not change gate decision or
        harness pass/fail status — the golden-path remains stable."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner1 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result1 = runner1.run(file_path=pdf_path)
        assert result1.status == RunStatus.COMPLETED

        runner2 = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result2 = runner2.run(file_path=pdf_path)
        assert result2.status == RunStatus.COMPLETED

        # Gate decision stable
        assert result1.gate_passed == result2.gate_passed
        # Harness result stable
        assert result1.harness_passed == result2.harness_passed
        # Lint findings count stable
        assert result1.lint_findings_count == result2.lint_findings_count

    def test_golden_report_shows_all_artifact_locations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report output includes paths to every persisted artifact."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)
        assert result.status == RunStatus.COMPLETED

        monkeypatch.chdir(tmp_path)
        cli_runner = CliRunner()
        output = cli_runner.invoke(cli, ["report", result.run_id])
        assert output.exit_code == 0

        data = json.loads(output.output)

        # Verify key artifact paths are present
        assert data.get("ir_artifact") is not None
        assert data.get("knowledge_artifact") is not None
        assert data.get("patch_artifact") is not None
        assert data.get("lint_artifact") is not None

        # IR pages and blocks are populated
        assert data.get("ir_pages") is not None
        assert data.get("ir_blocks") is not None

        # Knowledge counts are populated
        assert isinstance(data.get("entity_count"), int)
        assert isinstance(data.get("claim_count"), int)

        # Harness and gate are populated
        assert data.get("harness_status") is not None
        assert data.get("harness_passed") is not None
        assert data.get("gate_decision") is not None
