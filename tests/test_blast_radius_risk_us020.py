"""Tests for US-020: Compute blast radius and risk from real diffs."""

from datetime import date
from pathlib import Path

from docos.models.page import Frontmatter, PageStatus, PageType, ReviewStatus
from docos.models.patch import ChangeType
from docos.wiki.compiler import CompiledPage


def _make_frontmatter(
    page_id: str = "source.test",
    related_claims: list[str] | None = None,
    related_entities: list[str] | None = None,
) -> Frontmatter:
    return Frontmatter(
        id=page_id,
        type=PageType.SOURCE,
        title="Test Page",
        status=PageStatus.AUTO,
        created_at=date(2026, 4, 15),
        updated_at=date(2026, 4, 15),
        review_status=ReviewStatus.PENDING,
        related_claims=related_claims or [],
        related_entities=related_entities or [],
    )


class TestBlastRadiusFromRealData:
    """US-020: Blast radius is computed from actual page/knowledge changes."""

    def test_create_page_blast_radius_pages(self) -> None:
        """Create patch has pages=1 in blast radius."""
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="# New page",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert patch.blast_radius.pages == 1

    def test_blast_radius_claims_from_frontmatter(self) -> None:
        """Blast radius claims count comes from related_claims in frontmatter."""
        claims = ["claim_1", "claim_2", "claim_3"]
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(related_claims=claims),
            body="# Page with claims",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert patch.blast_radius.claims == 3

    def test_blast_radius_links_from_frontmatter(self) -> None:
        """Blast radius links count comes from related_entities in frontmatter."""
        entities = ["entity_a", "entity_b"]
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(related_entities=entities),
            body="# Page with entities",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert patch.blast_radius.links == 2

    def test_blast_radius_zero_when_no_claims_or_entities(self) -> None:
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="Simple page",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert patch.blast_radius.claims == 0
        assert patch.blast_radius.links == 0


class TestRiskScoreFromRealDiffs:
    """US-020: Risk score is derived from real diff data."""

    def test_create_page_low_risk(self) -> None:
        """A small new page has low risk."""
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body="# Small page\nHello",
            page_path=Path("wiki/sources/test.md"),
            existing_body=None,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert 0.0 < patch.risk_score < 0.4

    def test_delete_page_higher_risk_than_create(self) -> None:
        """Deletion has higher risk than creation."""
        fm = _make_frontmatter()
        create = CompiledPage(
            frontmatter=fm,
            body="# Page",
            page_path=Path("wiki/test.md"),
            existing_body=None,
        )
        delete = CompiledPage(
            frontmatter=fm,
            body="",
            page_path=Path("wiki/test.md"),
            existing_body="old content",
            deleted=True,
        )
        create_patch = create.compute_patch(run_id="r", source_id="s")
        delete_patch = delete.compute_patch(run_id="r", source_id="s")
        assert delete_patch.risk_score > create_patch.risk_score

    def test_small_update_lower_risk_than_large_update(self) -> None:
        """A small content change produces lower risk than a large change."""
        fm = _make_frontmatter()
        small_change = CompiledPage(
            frontmatter=fm,
            body="Line 1\nLine 2\nLine 3\nLine 4 modified",
            page_path=Path("wiki/test.md"),
            existing_body="Line 1\nLine 2\nLine 3\nLine 4 original",
        )
        big_change = CompiledPage(
            frontmatter=fm,
            body="Completely different content\nNew stuff everywhere\nNothing remains",
            page_path=Path("wiki/test.md"),
            existing_body="Line 1\nLine 2\nLine 3\nLine 4 original\nLine 5\nLine 6",
        )
        small_patch = small_change.compute_patch(run_id="r", source_id="s")
        big_patch = big_change.compute_patch(run_id="r", source_id="s")
        assert small_patch.risk_score < big_patch.risk_score

    def test_risk_not_constant_placeholder(self) -> None:
        """Risk varies across different scenarios (not a constant placeholder)."""
        fm = _make_frontmatter()
        scenarios = [
            CompiledPage(frontmatter=fm, body="short", page_path=Path("wiki/a.md"), existing_body=None),
            CompiledPage(frontmatter=fm, body="short", page_path=Path("wiki/a.md"), existing_body="longer old content here"),
            CompiledPage(frontmatter=fm, body="", page_path=Path("wiki/a.md"), existing_body="old", deleted=True),
        ]
        risks = [s.compute_patch(run_id="r", source_id="s").risk_score for s in scenarios]
        assert len(set(risks)) > 1, "Risk scores should vary, not be constant"

    def test_no_change_low_risk(self) -> None:
        """Identical content update should have very low risk."""
        same_content = "Identical body content"
        compiled = CompiledPage(
            frontmatter=_make_frontmatter(),
            body=same_content,
            page_path=Path("wiki/test.md"),
            existing_body=same_content,
        )
        patch = compiled.compute_patch(run_id="r", source_id="s")
        assert patch.risk_score <= 0.15  # near-zero change

    def test_delete_with_claims_increases_risk(self) -> None:
        """Deleting a page with associated claims has higher risk than one without."""
        delete_no_claims = CompiledPage(
            frontmatter=_make_frontmatter(related_claims=[]),
            body="",
            page_path=Path("wiki/a.md"),
            existing_body="content",
            deleted=True,
        )
        delete_with_claims = CompiledPage(
            frontmatter=_make_frontmatter(related_claims=["c1", "c2", "c3"]),
            body="",
            page_path=Path("wiki/b.md"),
            existing_body="content",
            deleted=True,
        )
        patch_no = delete_no_claims.compute_patch(run_id="r", source_id="s")
        patch_with = delete_with_claims.compute_patch(run_id="r", source_id="s")
        assert patch_with.risk_score > patch_no.risk_score


class TestBlastRadiusConsumable:
    """US-020: Review-required decisions can consume the real blast radius and risk."""

    def test_stage_uses_real_blast_radius_for_review(self) -> None:
        """stage() uses real blast_radius.pages > 2 to trigger review."""
        from docos.models.patch import Patch, Change, ChangeType
        patch = Patch(
            patch_id="p1",
            run_id="r1",
            source_id="s1",
            changes=[Change(type=ChangeType.UPDATE_PAGE, target="t")],
            blast_radius={"pages": 3, "claims": 0, "links": 0},
            risk_score=0.1,
        )
        patch.stage()
        assert patch.review_required is True  # pages > 2

    def test_stage_uses_real_risk_for_review(self) -> None:
        """stage() uses real risk_score > 0.3 to trigger review."""
        from docos.models.patch import Patch, Change, ChangeType
        patch = Patch(
            patch_id="p2",
            run_id="r2",
            source_id="s2",
            changes=[Change(type=ChangeType.UPDATE_PAGE, target="t")],
            blast_radius={"pages": 1, "claims": 0, "links": 0},
            risk_score=0.6,
        )
        patch.stage()
        assert patch.review_required is True  # risk > 0.3
