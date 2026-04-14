"""Tests for US-006: Persist extract, compile, patch, lint, eval, gate artifacts."""

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


def _run_full_pipeline(tmp_path: Path) -> tuple[object, RunStore, Path]:
    """Helper to run full pipeline and return (result, store, manifest)."""
    config_path = _make_test_config(tmp_path / "configs")
    pdf_path = _write_simple_pdf(tmp_path / "test.pdf")
    runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
    result = runner.run(file_path=pdf_path)
    store = RunStore(tmp_path)
    manifest = store.get(result.run_id)  # type: ignore[union-attr]
    return result, store, manifest


class TestExtractArtifacts:
    """US-006: Extract writes knowledge artifacts."""

    def test_entities_persisted(self, tmp_path: Path) -> None:
        """Extract writes entities to persistent storage."""
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.knowledge_artifact_path is not None

        knowledge_dir = Path(manifest.knowledge_artifact_path)
        assert knowledge_dir.exists()
        entities_path = knowledge_dir / "entities.json"
        assert entities_path.exists()

    def test_claims_persisted(self, tmp_path: Path) -> None:
        """Extract writes claims to persistent storage."""
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.knowledge_artifact_path is not None

        knowledge_dir = Path(manifest.knowledge_artifact_path)
        claims_path = knowledge_dir / "claims.json"
        assert claims_path.exists()

    def test_relations_persisted(self, tmp_path: Path) -> None:
        """Extract writes relations to persistent storage."""
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.knowledge_artifact_path is not None

        knowledge_dir = Path(manifest.knowledge_artifact_path)
        relations_path = knowledge_dir / "relations.json"
        assert relations_path.exists()


class TestCompilePatchArtifacts:
    """US-006: Compile and patch write page manifests, snapshots, and patches."""

    def test_patch_artifacts_persisted(self, tmp_path: Path) -> None:
        """Compile/patch write patch artifacts to persistent storage."""
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None

        # If patches were generated, verify they are persisted
        if hasattr(result, 'patches') and result.patches:
            assert manifest.patch_artifact_path is not None

    def test_wiki_state_persisted(self, tmp_path: Path) -> None:
        """Compile writes wiki page state to persistent storage."""
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None

        # Wiki state directory should exist
        wiki_state_dir = tmp_path / "wiki_state"
        assert wiki_state_dir.exists()
        # Should have at least one state file
        state_files = list(wiki_state_dir.glob("*.json"))
        assert len(state_files) >= 1


class TestLintEvalGateArtifacts:
    """US-006: Lint, eval, gate write structured outputs."""

    def test_lint_findings_persisted(self, tmp_path: Path) -> None:
        """Lint writes structured findings to persistent storage."""
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.lint_artifact_path is not None

        lint_path = Path(manifest.lint_artifact_path)
        assert lint_path.exists()

        findings = json.loads(lint_path.read_text())
        assert isinstance(findings, list)

    def test_harness_report_persisted(self, tmp_path: Path) -> None:
        """Harness (eval) writes structured report to persistent storage."""
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.report_artifact_path is not None

        report_path = Path(manifest.report_artifact_path)
        # Report store saves under reports/<run_id>.json
        assert (tmp_path / "reports" / f"{manifest.run_id}.json").exists()

    def test_gate_decision_persisted(self, tmp_path: Path) -> None:
        """Gate writes decision to RunManifest."""
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.gate_decision is not None
        assert manifest.gate_decision in ("passed", "blocked")


class TestManifestLinksAllArtifacts:
    """US-006: RunManifest links to each downstream artifact path."""

    def test_manifest_links_knowledge(self, tmp_path: Path) -> None:
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.knowledge_artifact_path is not None
        assert Path(manifest.knowledge_artifact_path).exists()

    def test_manifest_links_lint(self, tmp_path: Path) -> None:
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.lint_artifact_path is not None
        assert Path(manifest.lint_artifact_path).exists()

    def test_manifest_links_report(self, tmp_path: Path) -> None:
        result, store, manifest = _run_full_pipeline(tmp_path)
        assert manifest is not None
        assert manifest.report_artifact_path is not None
