"""Tests for US-009: Compile entity pages in the main pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docos.models.run import RunStatus
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
    from tests.fixtures.build_fixtures import get_all_fixtures
    get_all_fixtures()


class TestEntityPageCompilation:
    """US-009: Entity pages compiled deterministically in main pipeline."""

    def test_entity_pages_have_deterministic_paths(self, tmp_path: Path) -> None:
        """Compile stage generates deterministic entity page paths from entity inputs."""
        from docos.models.knowledge import EntityRecord, EntityType
        from docos.wiki.compiler import WikiCompiler

        compiler = WikiCompiler(tmp_path / "wiki")
        entity = EntityRecord(
            entity_id="e-001",
            canonical_name="Test Entity",
            entity_type=EntityType.CONCEPT,
            source_ids=["src-001"],
        )

        fm, body, page_path = compiler.compile_entity_page(entity, [])

        # Path should be deterministic based on entity name
        assert "test-entity" in str(page_path).lower()
        assert fm.id == "entity.test-entity"

    def test_entity_page_frontmatter_fields(self, tmp_path: Path) -> None:
        """Each entity page includes required frontmatter fields."""
        from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord, EntityType, EvidenceAnchor
        from docos.wiki.compiler import WikiCompiler

        compiler = WikiCompiler(tmp_path / "wiki")
        entity = EntityRecord(
            entity_id="e-002",
            canonical_name="Alpha Model",
            entity_type=EntityType.MODEL,
            source_ids=["src-001", "src-002"],
        )
        claim = ClaimRecord(
            claim_id="c-001",
            statement="Alpha achieved 95% accuracy",
            subject_entity_id="e-002",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[EvidenceAnchor(
                anchor_id="a-001",
                source_id="src-001",
                doc_id="doc-001",
                page_no=1,
                block_id="b-001",
            )],
        )

        fm, body, page_path = compiler.compile_entity_page(entity, [claim])

        assert fm.id == "entity.alpha-model"
        assert fm.type.value == "entity"
        assert fm.source_docs == ["src-001", "src-002"]
        assert "c-001" in fm.related_claims
        assert fm.updated_at is not None

    def test_rerun_preserves_entity_paths(self, tmp_path: Path) -> None:
        """Rerunning same fixture preserves entity page paths for unchanged entities."""
        from docos.models.knowledge import EntityRecord, EntityType
        from docos.wiki.compiler import WikiCompiler

        compiler = WikiCompiler(tmp_path / "wiki")
        entity = EntityRecord(
            entity_id="e-003",
            canonical_name="Stable Entity",
            entity_type=EntityType.METHOD,
            source_ids=["src-001"],
        )

        # First compile
        fm1, _, path1 = compiler.compile_entity_page(entity, [])

        # Second compile with same entity
        fm2, _, path2 = compiler.compile_entity_page(entity, [])

        assert str(path1) == str(path2)
        assert fm1.id == fm2.id

    def test_pipeline_compiles_entity_pages(self, tmp_path: Path) -> None:
        """Pipeline run includes entity pages when entities are extracted."""
        from docos.pipeline.runner import PipelineRunner

        _ensure_fixtures()
        config_path = _make_test_config(tmp_path / "config")
        pdf_path = Path(__file__).parent / "fixtures" / "simple_text.pdf"
        if not pdf_path.exists():
            pytest.skip("simple_text.pdf fixture not found")

        runner = PipelineRunner(config_path=config_path, base_dir=tmp_path / "artifacts")
        result = runner.run(pdf_path)

        assert result.status == RunStatus.COMPLETED

        store = RunStore(tmp_path / "artifacts")
        manifest = store.get(result.run_id)
        assert manifest is not None

        # Check if entity pages were compiled (if entities were extracted)
        if result.entities:
            assert "entity" in manifest.compiled_page_types
            # Count entity pages
            entity_count = manifest.compiled_page_types.count("entity")
            assert entity_count == len(result.entities)
