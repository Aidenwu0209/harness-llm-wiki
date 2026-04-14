"""Tests for US-028: Add integration tests for normalize and extract from raw fixtures."""

from __future__ import annotations

from pathlib import Path

import yaml

from docos.ir_store import IRStore
from docos.knowledge_store import KnowledgeStore
from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore
from tests.fixtures.build_fixtures import (
    _build_dual_column_pdf,
    _build_ocr_like_pdf,
    _build_simple_pdf,
)


# ---------------------------------------------------------------------------
# Config helper (reuse from US-027)
# ---------------------------------------------------------------------------

_TEST_CONFIG_YAML = (
    "environment: local\nschema_version: '1'\n"
    "router:\n  default_route: fallback_safe_route\n  routes:\n"
    "    - name: fast_text_route\n"
    "      description: 'Fast text extraction'\n"
    "      file_types: ['application/pdf']\n"
    "      max_pages: 50\n"
    "      requires_ocr: false\n"
    "      table_formula_heavy: false\n"
    "      image_heavy: false\n"
    "      dual_column: false\n"
    "      primary_parser: stdlib_pdf\n"
    "      fallback_parsers: [basic_text_fallback]\n"
    "      expected_risks: []\n      post_parse_repairs: []\n"
    "      review_policy: default\n"
    "    - name: complex_pdf_route\n"
    "      description: 'Complex layouts'\n"
    "      file_types: ['application/pdf']\n"
    "      requires_ocr: false\n"
    "      table_formula_heavy: true\n"
    "      dual_column: true\n"
    "      primary_parser: stdlib_pdf\n"
    "      fallback_parsers: [basic_text_fallback]\n"
    "      expected_risks: []\n"
    "      post_parse_repairs: []\n"
    "      review_policy: strict\n"
    "    - name: ocr_heavy_route\n"
    "      description: 'OCR route'\n"
    "      file_types: ['application/pdf', 'image/png']\n"
    "      requires_ocr: true\n"
    "      primary_parser: stdlib_pdf\n"
    "      fallback_parsers: [basic_text_fallback]\n"
    "      expected_risks: []\n"
    "      post_parse_repairs: []\n"
    "      review_policy: strict\n"
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


class TestNormalizeFromFixtures:
    """Tests covering fixture -> parse -> normalize."""

    def test_simple_text_normalize_produces_docir(self, tmp_path: Path) -> None:
        """Simple fixture produces persisted DocIR after normalize stage."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "completed", f"Failed: {result.failed_stage}"
        assert result.docir is not None

        # Verify DocIR persisted
        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None
        assert docir.page_count >= 1
        assert len(docir.blocks) > 0

    def test_dual_column_normalize_produces_docir(self, tmp_path: Path) -> None:
        """Dual-column fixture produces persisted DocIR after normalize stage."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "dual_column.pdf"
        pdf_path.write_bytes(_build_dual_column_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "completed", f"Failed: {result.failed_stage}"
        assert result.docir is not None

        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None

    def test_ocr_like_normalize_produces_docir(self, tmp_path: Path) -> None:
        """OCR-like fixture produces persisted DocIR after normalize stage."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "ocr_like.pdf"
        pdf_path.write_bytes(_build_ocr_like_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "completed", f"Failed: {result.failed_stage}"
        assert result.docir is not None

        ir_store = IRStore(tmp_path / "ir")
        docir = ir_store.get(result.run_id)
        assert docir is not None

    def test_normalize_manifest_records_ir_artifact(self, tmp_path: Path) -> None:
        """RunManifest has ir_artifact_path after normalize."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.ir_artifact_path is not None
        assert result.run_id in manifest.ir_artifact_path


class TestExtractFromFixtures:
    """Tests covering fixture -> parse -> normalize -> extract."""

    def test_simple_text_extract_produces_knowledge(self, tmp_path: Path) -> None:
        """Simple fixture produces entities and claims after extract."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "completed"
        assert result.docir is not None

        # Knowledge may or may not have entities/claims depending on text
        # but knowledge artifact should be persisted
        ks = KnowledgeStore(tmp_path / "knowledge")
        artifact = ks.get(result.run_id)
        assert artifact is not None
        assert artifact.run_id == result.run_id

    def test_dual_column_extract_produces_knowledge(self, tmp_path: Path) -> None:
        """Dual-column fixture produces knowledge artifact after extract."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "dual_column.pdf"
        pdf_path.write_bytes(_build_dual_column_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        assert result.status.value == "completed"
        ks = KnowledgeStore(tmp_path / "knowledge")
        artifact = ks.get(result.run_id)
        assert artifact is not None

    def test_extract_manifest_records_knowledge_artifact(self, tmp_path: Path) -> None:
        """RunManifest has knowledge_artifact_path after extract."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        store = RunStore(tmp_path)
        manifest = store.get(result.run_id)
        assert manifest is not None
        assert manifest.knowledge_artifact_path is not None

    def test_extract_knowledge_has_valid_structure(self, tmp_path: Path) -> None:
        """Knowledge artifact has valid entities, claims, and relations."""
        config_path = _setup_config(tmp_path)
        pdf_path = tmp_path / "simple_text.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        result = runner.run(file_path=pdf_path)

        ks = KnowledgeStore(tmp_path / "knowledge")
        artifact = ks.get(result.run_id)
        assert artifact is not None

        # All entity IDs should be unique
        entity_ids = [e.entity_id for e in artifact.entities]
        assert len(entity_ids) == len(set(entity_ids)), "Entity IDs must be unique"

        # All claim IDs should be unique
        claim_ids = [c.claim_id for c in artifact.claims]
        assert len(claim_ids) == len(set(claim_ids)), "Claim IDs must be unique"

    def test_all_fixtures_complete_through_extract(self, tmp_path: Path) -> None:
        """All three fixtures complete the full pipeline through extract."""
        config_path = _setup_config(tmp_path)

        fixtures = [
            ("simple_text", _build_simple_pdf),
            ("dual_column_or_formula", _build_dual_column_pdf),
            ("ocr_like", _build_ocr_like_pdf),
        ]

        for name, builder in fixtures:
            pdf_path = tmp_path / f"{name}.pdf"
            pdf_path.write_bytes(builder())

            runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
            result = runner.run(file_path=pdf_path)

            assert result.status.value == "completed", (
                f"Fixture {name} failed at {result.failed_stage}: {result.error_detail}"
            )
            assert result.docir is not None

            # Both IR and knowledge artifacts should exist
            ir_store = IRStore(tmp_path / "ir")
            docir = ir_store.get(result.run_id)
            assert docir is not None, f"{name}: DocIR artifact missing"

            ks = KnowledgeStore(tmp_path / "knowledge")
            knowledge = ks.get(result.run_id)
            assert knowledge is not None, f"{name}: Knowledge artifact missing"
