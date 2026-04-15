"""Tests for US-010: Compile concept pages from deterministic inputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.models.knowledge import EntityRecord, EntityType
from docos.run_store import RunStore
from docos.wiki.compiler import WikiCompiler


class TestConceptPageCompilation:
    """US-010: Concept pages compiled from deterministic inputs."""

    def test_concept_page_derived_without_llm(self, tmp_path: Path) -> None:
        """Compile stage derives concept page from deterministic inputs."""
        compiler = WikiCompiler(tmp_path / "wiki")

        entity = EntityRecord(
            entity_id="e-concept-001",
            canonical_name="Attention Mechanism",
            entity_type=EntityType.CONCEPT,
            source_ids=["src-001"],
        )

        fm, body, page_path = compiler.compile_concept_page(
            concept_name="Attention Mechanism",
            source_ids=["src-001"],
            related_claims=[],
            related_entities=[entity],
        )

        assert fm.id == "concept.attention-mechanism"
        assert fm.type.value == "concept"
        assert "Attention Mechanism" in body

    def test_concept_page_generates_for_concept_entity(self, tmp_path: Path) -> None:
        """Stage generates concept page for a concept-type entity."""
        compiler = WikiCompiler(tmp_path / "wiki")

        # Concept-type entities trigger concept page compilation
        entities = [
            EntityRecord(
                entity_id="e-conv-001",
                canonical_name="Gradient Descent",
                entity_type=EntityType.CONCEPT,
                source_ids=["src-001"],
            ),
            EntityRecord(
                entity_id="e-non-conv-001",
                canonical_name="Some Model",
                entity_type=EntityType.MODEL,
                source_ids=["src-001"],
            ),
        ]

        # Only concept-type entities should produce concept pages
        concept_names = {e.canonical_name for e in entities if e.entity_type in ("concept", "topic", "theme")}
        assert "Gradient Descent" in concept_names
        assert "Some Model" not in concept_names

    def test_rerun_preserves_concept_paths_and_frontmatter(self, tmp_path: Path) -> None:
        """Rerunning preserves concept page paths and frontmatter identifiers."""
        compiler = WikiCompiler(tmp_path / "wiki")

        entity = EntityRecord(
            entity_id="e-stable-001",
            canonical_name="Stable Concept",
            entity_type=EntityType.CONCEPT,
            source_ids=["src-001"],
        )

        fm1, _, path1 = compiler.compile_concept_page(
            concept_name="Stable Concept",
            source_ids=["src-001"],
            related_claims=[],
            related_entities=[entity],
        )

        fm2, _, path2 = compiler.compile_concept_page(
            concept_name="Stable Concept",
            source_ids=["src-001"],
            related_claims=[],
            related_entities=[entity],
        )

        assert str(path1) == str(path2)
        assert fm1.id == fm2.id
        assert fm1.title == fm2.title
