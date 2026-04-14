"""US-023: Make lint load real wiki, knowledge, and patch artifacts."""

import tempfile
from datetime import date, datetime
from pathlib import Path

from docos.artifact_stores import PatchStore, WikiPageState, WikiStore
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.lint.checker import LintSeverity, WikiLinter
from docos.models.docir import Block, BlockType, DocIR, Page
from docos.models.knowledge import (
    ClaimRecord,
    ClaimStatus,
    EntityRecord,
    EntityType,
    EvidenceAnchor,
)
from docos.models.page import Frontmatter, PageStatus, PageType, ReviewStatus
from docos.models.patch import BlastRadius, Change, ChangeType, Patch


def _make_docir() -> DocIR:
    return DocIR(
        doc_id="doc_001",
        source_id="src_001",
        parser="stdlib_pdf",
        parser_version="1.0",
        page_count=1,
        pages=[Page(page_no=1, width=612, height=792)],
        blocks=[
            Block(
                block_id="blk_001",
                page_no=1,
                block_type=BlockType.PARAGRAPH,
                reading_order=0,
                bbox=(0, 0, 612, 50),
                text_plain="Test content",
                source_parser="stdlib_pdf",
                source_node_id="n1",
            ),
        ],
    )


def _make_good_entities() -> list[EntityRecord]:
    return [
        EntityRecord(
            entity_id="ent_001",
            canonical_name="Test Entity",
            entity_type=EntityType.CONCEPT,
        ),
    ]


def _make_good_claims() -> list[ClaimRecord]:
    return [
        ClaimRecord(
            claim_id="clm_001",
            statement="Test claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[
                EvidenceAnchor(
                    anchor_id="anc_001",
                    source_id="src_001",
                    doc_id="doc_001",
                    page_no=1,
                    block_id="blk_001",
                ),
            ],
        ),
    ]


def _make_pages() -> list[Frontmatter]:
    return [
        Frontmatter(
            id="source.test",
            type=PageType.SOURCE,
            title="Test Page",
            status=PageStatus.AUTO,
            created_at=date(2026, 4, 15),
            updated_at=date(2026, 4, 15),
            review_status=ReviewStatus.PENDING,
        ),
    ]


def _make_patch() -> Patch:
    return Patch(
        patch_id="pat_lint_001",
        run_id="run_001",
        source_id="src_001",
        changes=[
            Change(type=ChangeType.CREATE_PAGE, target="wiki/sources/test.md"),
        ],
        risk_score=0.2,
    )


class TestLintRealArtifacts:
    def test_lint_on_real_docir_and_knowledge(self) -> None:
        """Lint on real DocIR + knowledge + pages produces no false findings for valid data."""
        linter = WikiLinter()
        docir = _make_docir()
        pages = _make_pages()
        entities = _make_good_entities()
        claims = _make_good_claims()

        findings = linter.lint(
            pages=pages,
            claims=claims,
            entities=entities,
            docir=docir,
        )
        # Good data should produce zero findings
        assert len(findings) == 0

    def test_lint_not_using_empty_placeholders(self) -> None:
        """Verify lint is not running with empty placeholder pages/knowledge for real runs."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # Persist real wiki state
            wiki_store = WikiStore(base / "wiki_state")
            fm = _make_pages()[0]
            wiki_store.save(WikiPageState(
                page_path="source.test",
                run_id="run_001",
                frontmatter=fm.model_dump(),
                body="# Test\n\nSome body content here.",
            ))

            # Persist real knowledge
            ks = KnowledgeStore(base / "knowledge")
            ks.save(KnowledgeArtifact(
                run_id="run_001",
                source_id="src_001",
                entities=_make_good_entities(),
                claims=_make_good_claims(),
            ))

            # Persist a patch
            patch_store = PatchStore(base / "patches")
            patch = _make_patch()
            patch_store.save(patch)

            # Load artifacts from disk (simulating what pipeline does)
            loaded_pages: list[Frontmatter] = []
            page_bodies: dict[str, str] = {}
            for path in (base / "wiki_state").glob("*.json"):
                state = wiki_store.get(path.stem)
                if state is not None and state.frontmatter:
                    loaded_pages.append(Frontmatter.model_validate(state.frontmatter))
                    page_id = state.frontmatter.get("id", "")
                    if page_id:
                        page_bodies[page_id] = state.body

            loaded_artifact = ks.get("run_001")
            assert loaded_artifact is not None
            loaded_entities = loaded_artifact.entities
            loaded_claims = loaded_artifact.claims
            loaded_patch = patch_store.get("pat_lint_001")
            assert loaded_patch is not None

            # Run lint with real loaded data
            linter = WikiLinter()
            findings = linter.lint(
                pages=loaded_pages,
                claims=loaded_claims,
                entities=loaded_entities,
                patch=loaded_patch,
                page_bodies=page_bodies,
            )

            # Real data should be clean
            assert len(loaded_pages) > 0
            assert len(loaded_entities) > 0
            assert len(loaded_claims) > 0
            assert len(findings) == 0

    def test_lint_detects_bad_knowledge_from_real_artifacts(self) -> None:
        """A synthetic bad claim in real artifacts can produce a blocking lint result."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # Persist wiki state
            wiki_store = WikiStore(base / "wiki_state")
            fm = _make_pages()[0]
            wiki_store.save(WikiPageState(
                page_path="source.test",
                run_id="run_001",
                frontmatter=fm.model_dump(),
                body="# Test\n\nBody content.",
            ))

            # Persist good entities via knowledge store
            ks = KnowledgeStore(base / "knowledge")
            good_claims = _make_good_claims()
            ks.save(KnowledgeArtifact(
                run_id="run_001",
                source_id="src_001",
                entities=_make_good_entities(),
                claims=good_claims,
            ))

            # Load real wiki pages from disk
            loaded_pages: list[Frontmatter] = []
            for path in (base / "wiki_state").glob("*.json"):
                state = wiki_store.get(path.stem)
                if state is not None and state.frontmatter:
                    loaded_pages.append(Frontmatter.model_validate(state.frontmatter))

            # Load real entities from disk
            loaded_artifact = ks.get("run_001")
            assert loaded_artifact is not None

            # Inject a bad claim that bypasses model validation
            # (simulates external data corruption or parser bug)
            import json
            bad_claim_data = {
                "claim_id": "clm_bad",
                "statement": "Bad claim without evidence",
                "status": ClaimStatus.SUPPORTED.value,
                "evidence_anchors": [],
                "confidence": 1.0,
            }
            bad_claim = ClaimRecord.model_construct(**bad_claim_data)
            all_claims = loaded_artifact.claims + [bad_claim]

            linter = WikiLinter()
            findings = linter.lint(
                pages=loaded_pages,
                claims=all_claims,
                entities=loaded_artifact.entities,
            )

            # Should detect the bad claim (SUPPORTED without evidence)
            bad_findings = [f for f in findings if f.code == "UNSUPPORTED_CLAIM_NO_EVIDENCE"]
            assert len(bad_findings) >= 1
            assert any(f.severity == LintSeverity.P1 for f in bad_findings)

    def test_lint_detects_duplicate_entities_from_real_data(self) -> None:
        """Lint catches duplicate entity candidates from real knowledge artifacts."""
        dup_entities = [
            EntityRecord(
                entity_id="ent_001",
                canonical_name="Duplicate Name",
                entity_type=EntityType.CONCEPT,
            ),
            EntityRecord(
                entity_id="ent_002",
                canonical_name="duplicate name",
                entity_type=EntityType.CONCEPT,
            ),
        ]

        linter = WikiLinter()
        findings = linter.lint(
            pages=_make_pages(),
            claims=_make_good_claims(),
            entities=dup_entities,
        )
        dup_findings = [f for f in findings if f.code == "DUPLICATE_ENTITY_CANDIDATES"]
        assert len(dup_findings) == 1

    def test_lint_detects_broken_wikilinks_with_bodies(self) -> None:
        """Lint checks page body content for broken wikilinks."""
        pages = _make_pages()
        page_bodies = {
            "source.test": "See [[nonexistent_page]] for details.",
        }

        linter = WikiLinter()
        findings = linter.lint(
            pages=pages,
            claims=_make_good_claims(),
            entities=_make_good_entities(),
            page_bodies=page_bodies,
        )
        broken = [f for f in findings if f.code == "BROKEN_WIKILINK"]
        assert len(broken) >= 1
