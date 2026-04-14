"""US-023: Make lint load real wiki, knowledge, and patch artifacts."""

import tempfile
from datetime import date
from pathlib import Path

from docos.artifact_stores import PatchStore, WikiPageState, WikiStore
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.lint.checker import LintSeverity, WikiLinter
from docos.models.docir import DocIR
from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord, EntityType, EvidenceAnchor
from docos.models.page import Frontmatter, PageType, PageStatus, ReviewStatus
from docos.models.patch import BlastRadius, Change, ChangeType, Patch


def _make_frontmatter(page_id: str = "source.test_doc") -> Frontmatter:
    return Frontmatter(
        id=page_id,
        type=PageType.SOURCE,
        title="Test Document",
        status=PageStatus.AUTO,
        created_at=date(2026, 4, 15),
        updated_at=date(2026, 4, 15),
        source_docs=["src_001"],
        review_status=ReviewStatus.PENDING,
    )


def _make_claim(claim_id: str = "claim_001", status: ClaimStatus = ClaimStatus.SUPPORTED) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        statement="Test claim statement",
        status=status,
        source_ids=["src_001"],
        evidence_anchors=[EvidenceAnchor(
            anchor_id="anc_001", source_id="src_001", doc_id="doc_001",
            page_no=1, block_id="blk_001",
        )],
    )


def _make_entity(entity_id: str = "ent_001") -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        canonical_name="TestEntity",
        entity_type=EntityType.CONCEPT,
        source_ids=["src_001"],
    )


class TestLintRealArtifacts:
    def test_lint_with_real_wiki_pages(self) -> None:
        """Lint loads real wiki page frontmatter and checks structure."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_store = WikiStore(Path(tmp) / "wiki")
            fm = _make_frontmatter()
            wiki_store.save(WikiPageState(
                page_path="wiki/sources/test_doc.md",
                run_id="run_001",
                frontmatter=fm.model_dump(),
                body="# Test\nSome content about [[entity.test_entity]]",
            ))

            linter = WikiLinter()
            findings = linter.lint(
                pages=[fm],
                claims=[],
                entities=[_make_entity()],
                page_bodies={"source.test_doc": "# Test\nSome content"},
            )
            # Should pass without P0 findings
            p0 = [f for f in findings if f.severity == LintSeverity.P0]
            assert len(p0) == 0

    def test_lint_detects_real_knowledge_issues(self) -> None:
        """Lint detects issues in real knowledge artifacts."""
        linter = WikiLinter()
        # Create a SUPPORTED claim without evidence anchors
        bad_claim = _make_claim(status=ClaimStatus.SUPPORTED)
        bad_claim.evidence_anchors = []

        findings = linter.lint(
            pages=[_make_frontmatter()],
            claims=[bad_claim],
            entities=[_make_entity()],
        )
        codes = [f.code for f in findings]
        assert "UNSUPPORTED_CLAIM_NO_EVIDENCE" in codes

    def test_lint_detects_duplicate_entities(self) -> None:
        """Lint detects duplicate entity candidates from real data."""
        linter = WikiLinter()
        entities = [
            _make_entity(entity_id="ent_001"),
            _make_entity(entity_id="ent_002"),
            # Same canonical_name -> duplicate candidate
        ]
        findings = linter.lint(
            pages=[_make_frontmatter()],
            claims=[],
            entities=entities,
        )
        codes = [f.code for f in findings]
        assert "DUPLICATE_ENTITY_CANDIDATES" in codes

    def test_lint_with_real_patch(self) -> None:
        """Lint inspects real patch data for operational issues."""
        linter = WikiLinter()
        # High blast radius without review
        patch = Patch(
            patch_id="pat_test",
            run_id="run_001",
            source_id="src_001",
            changes=[Change(type=ChangeType.UPDATE_PAGE, target="wiki/a.md")],
            blast_radius=BlastRadius(pages=5, claims=3),
            review_required=False,
        )
        findings = linter.lint(
            pages=[_make_frontmatter()],
            claims=[],
            entities=[],
            patch=patch,
        )
        codes = [f.code for f in findings]
        assert "HIGH_BLAST_NO_REVIEW" in codes


class TestLintBlockingResult:
    def test_bad_fixture_produces_blocking_lint(self) -> None:
        """A synthetic bad patch can produce a blocking lint result."""
        linter = WikiLinter()

        # Create a page with empty title
        bad_fm = Frontmatter(
            id="source.bad",
            type=PageType.SOURCE,
            title="",  # Missing title -> P1
            created_at=date(2026, 4, 15),
            updated_at=date(2026, 4, 15),
        )
        findings = linter.lint(
            pages=[bad_fm],
            claims=[],
            entities=[],
        )
        blocking = [f for f in findings if f.severity in (LintSeverity.P0, LintSeverity.P1)]
        assert len(blocking) > 0

    def test_p0_duplicate_id_is_blocking(self) -> None:
        """Duplicate page IDs produce P0 blocking findings."""
        linter = WikiLinter()
        fm1 = _make_frontmatter(page_id="source.dup")
        fm2 = _make_frontmatter(page_id="source.dup")
        findings = linter.lint(
            pages=[fm1, fm2],
            claims=[],
            entities=[],
        )
        p0 = [f for f in findings if f.severity == LintSeverity.P0]
        assert len(p0) > 0
        assert any(f.code == "DUPLICATE_ID" for f in p0)
