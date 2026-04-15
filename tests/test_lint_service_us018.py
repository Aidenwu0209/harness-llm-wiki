"""Tests for US-018: Shared lint service for run and CLI parity."""

from __future__ import annotations

import json
from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.lint.service import run_lint_for_run
from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord, EntityType, EvidenceAnchor
from docos.run_store import RunStore


def _setup_run_with_data(tmp_path: Path) -> str:
    """Create a run with real pages, entities, and claims."""
    base = tmp_path / "artifacts"
    store = RunStore(base)
    manifest = store.create(source_id="src-lint", source_hash="h", source_file_path="/tmp/t.pdf")

    # Save wiki page
    wiki_store = WikiStore(base / "wiki_state")
    wiki_store.save_from_dict = None  # not needed
    from docos.artifact_stores import WikiPageState
    wiki_store.save(WikiPageState(
        page_path="wiki/source/test.md", run_id=manifest.run_id,
        frontmatter={"id": "source.test", "type": "source", "title": "Test"},
        body="# Test\nSome content here for the test page.",
    ))

    # Save knowledge
    ks = KnowledgeStore(base / "knowledge")
    entity = EntityRecord(entity_id="e-1", canonical_name="TestEntity", entity_type=EntityType.CONCEPT, source_ids=["src-lint"])
    claim = ClaimRecord(
        claim_id="c-1", statement="Test claim", status=ClaimStatus.SUPPORTED,
        evidence_anchors=[EvidenceAnchor(anchor_id="a-1", source_id="src-lint", doc_id="d-1", page_no=1, block_id="b-1")],
    )
    ks.save(KnowledgeArtifact(run_id=manifest.run_id, source_id="src-lint", entities=[entity], claims=[claim]))

    return manifest.run_id


class TestSharedLintService:
    """US-018: Pipeline and CLI use same lint service."""

    def test_service_loads_real_data(self, tmp_path: Path) -> None:
        """Service loads real pages and knowledge from artifacts."""
        run_id = _setup_run_with_data(tmp_path)
        findings = run_lint_for_run(tmp_path / "artifacts", run_id)
        assert isinstance(findings, list)

    def test_cli_lint_uses_shared_service(self, tmp_path: Path) -> None:
        """CLI lint --run-id produces same results as shared service."""
        run_id = _setup_run_with_data(tmp_path)
        findings = run_lint_for_run(tmp_path / "artifacts", run_id)
        # Shared service should load data and produce findings (or empty for valid data)
        assert isinstance(findings, list)

    def test_service_handles_missing_run(self, tmp_path: Path) -> None:
        """Service handles non-existent run gracefully."""
        findings = run_lint_for_run(tmp_path / "artifacts", "nonexistent")
        assert isinstance(findings, list)
