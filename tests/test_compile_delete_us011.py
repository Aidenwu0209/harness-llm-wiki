"""Tests for US-011: Generate delete patches for stale entity and concept pages."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import WikiPageState, WikiStore
from docos.models.docir import DocIR
from docos.models.knowledge import EntityRecord, EntityType
from docos.models.patch import ChangeType
from docos.models.run import RunStatus, StageStatus
from docos.models.source import SourceRecord
from docos.pipeline.runner import PipelineResult, PipelineRunner
from docos.run_store import RunStore
from docos.wiki.compiler import WikiCompiler


def _make_docir() -> DocIR:
    return DocIR(doc_id="doc-1", source_id="src-new", parser="test", page_count=0, pages=[])


def _make_source() -> SourceRecord:
    return SourceRecord(
        source_id="src-new", file_name="test.pdf",
        source_hash="hash123", origin="test", byte_size=100,
    )


class TestDeletePatches:
    """US-011: Missing pages generate DELETE_PAGE patches."""

    def test_stale_entity_page_generates_delete_patch(self, tmp_path: Path) -> None:
        """Entity page from prior run not in current run gets DELETE_PAGE patch."""
        base = tmp_path / "artifacts"
        wiki_store = WikiStore(base / "wiki_state")
        # Use same wiki dir as runner would
        compiler = WikiCompiler(base / "wiki")

        entity = EntityRecord(
            entity_id="e-old", canonical_name="Old Entity",
            entity_type=EntityType.CONCEPT, source_ids=["src-old"],
        )
        fm, body, epath = compiler.compile_entity_page(entity, [])
        wiki_store.save(WikiPageState(
            page_path=str(epath), run_id="run-old",
            frontmatter={"id": "entity.old-entity"}, body=body,
        ))

        # Run compile with no entities — old entity should get DELETE patch
        store = RunStore(base)
        manifest = store.create(source_id="src-new", source_hash="hash123", source_file_path="/tmp/test.pdf")
        manifest.status = RunStatus.RUNNING
        manifest.started_at = manifest.created_at
        for stage_name in ("ingest", "route", "parse", "normalize", "extract"):
            manifest.mark_stage(stage_name, StageStatus.COMPLETED)
        store.update(manifest)

        result = PipelineResult(run_id=manifest.run_id, source_id="src-new", status=RunStatus.RUNNING)
        runner = PipelineRunner.__new__(PipelineRunner)
        runner._base = base
        runner._run_store = store
        runner._wiki_store = wiki_store

        patches = runner._stage_compile(_make_source(), manifest, _make_docir(), [], [], result)

        delete_patches = [p for p in patches if any(c.type == ChangeType.DELETE_PAGE for c in p.changes)]
        assert len(delete_patches) >= 1
        delete_targets = [c.target for p in delete_patches for c in p.changes]
        assert any("old-entity" in t.lower() for t in delete_targets)

    def test_stale_concept_page_generates_delete_patch(self, tmp_path: Path) -> None:
        """Concept page from prior run not in current run gets DELETE_PAGE patch."""
        base = tmp_path / "artifacts"
        wiki_store = WikiStore(base / "wiki_state")
        compiler = WikiCompiler(base / "wiki")

        cfm, cbody, cpath = compiler.compile_concept_page(
            concept_name="Obsolete Concept", source_ids=["src-old"],
            related_claims=[], related_entities=[],
        )
        wiki_store.save(WikiPageState(
            page_path=str(cpath), run_id="run-old",
            frontmatter={"id": "concept.obsolete-concept"}, body=cbody,
        ))

        store = RunStore(base)
        manifest = store.create(source_id="src-new", source_hash="hash123", source_file_path="/tmp/test.pdf")
        manifest.status = RunStatus.RUNNING
        manifest.started_at = manifest.created_at
        for stage_name in ("ingest", "route", "parse", "normalize", "extract"):
            manifest.mark_stage(stage_name, StageStatus.COMPLETED)
        store.update(manifest)

        result = PipelineResult(run_id=manifest.run_id, source_id="src-new", status=RunStatus.RUNNING)
        runner = PipelineRunner.__new__(PipelineRunner)
        runner._base = base
        runner._run_store = store
        runner._wiki_store = wiki_store

        patches = runner._stage_compile(_make_source(), manifest, _make_docir(), [], [], result)

        delete_patches = [p for p in patches if any(c.type == ChangeType.DELETE_PAGE for c in p.changes)]
        assert len(delete_patches) >= 1

    def test_no_delete_for_source_pages(self, tmp_path: Path) -> None:
        """DELETE patches only target entity and concept pages, not source pages."""
        base = tmp_path / "artifacts"
        wiki_store = WikiStore(base / "wiki_state")

        wiki_store.save(WikiPageState(
            page_path="wiki/source/old-source.md", run_id="run-old",
            frontmatter={"id": "source.old-source"}, body="old content",
        ))

        store = RunStore(base)
        manifest = store.create(source_id="src-new", source_hash="hash123", source_file_path="/tmp/test.pdf")
        manifest.status = RunStatus.RUNNING
        manifest.started_at = manifest.created_at
        for stage_name in ("ingest", "route", "parse", "normalize", "extract"):
            manifest.mark_stage(stage_name, StageStatus.COMPLETED)
        store.update(manifest)

        result = PipelineResult(run_id=manifest.run_id, source_id="src-new", status=RunStatus.RUNNING)
        runner = PipelineRunner.__new__(PipelineRunner)
        runner._base = base
        runner._run_store = store
        runner._wiki_store = wiki_store

        patches = runner._stage_compile(_make_source(), manifest, _make_docir(), [], [], result)

        delete_patches = [p for p in patches if any(c.type == ChangeType.DELETE_PAGE for c in p.changes)]
        for dp in delete_patches:
            for c in dp.changes:
                assert "/entities/" in c.target or "/concepts/" in c.target
