"""Tests for Review Queue, Knowledge Ops, and CLI (US-027~032)."""

from pathlib import Path

import pytest

from docos.review.queue import ReviewDecision, ReviewItem, ReviewItemType, ReviewQueue
from docos.knowledge.ops import (
    DedupCandidate,
    DeprecationRecord,
    generate_dedup_candidates,
    mark_conflict,
    deprecate_claim,
)
from docos.models.knowledge import (
    ClaimRecord, ClaimStatus, EntityRecord, EntityType, EvidenceAnchor,
)


# ---------------------------------------------------------------------------
# US-027: Review queue
# ---------------------------------------------------------------------------

class TestReviewQueue:
    def test_add_and_get(self, tmp_path: Path) -> None:
        queue = ReviewQueue(tmp_path / "reviews")
        item = ReviewItem(
            review_id="rev_001",
            item_type=ReviewItemType.PATCH,
            target_object_id="patch_001",
            reason="High blast radius",
            risk_score=0.85,
        )
        queue.add(item)
        fetched = queue.get("rev_001")
        assert fetched is not None
        assert fetched.target_object_id == "patch_001"

    def test_list_pending(self, tmp_path: Path) -> None:
        queue = ReviewQueue(tmp_path / "reviews")
        queue.add(ReviewItem(review_id="r1", item_type=ReviewItemType.PATCH, target_object_id="p1"))
        queue.add(ReviewItem(review_id="r2", item_type=ReviewItemType.CONFLICT_CLAIM, target_object_id="c1"))
        pending = queue.list_pending()
        assert len(pending) == 2

    def test_approve_item(self, tmp_path: Path) -> None:
        queue = ReviewQueue(tmp_path / "reviews")
        queue.add(ReviewItem(review_id="r1", item_type=ReviewItemType.PATCH, target_object_id="p1"))
        result = queue.resolve("r1", "approve", reviewer="alice", reason="Looks good")
        assert result is not None
        assert result.status == ReviewDecision.APPROVED
        assert len(result.actions) == 1
        assert result.actions[0].reviewer == "alice"

    def test_reject_item(self, tmp_path: Path) -> None:
        queue = ReviewQueue(tmp_path / "reviews")
        queue.add(ReviewItem(review_id="r2", item_type=ReviewItemType.ENTITY_DEDUP, target_object_id="e1"))
        result = queue.resolve("r2", "reject", reviewer="bob", reason="Not the same entity")
        assert result.status == ReviewDecision.REJECTED

    def test_request_changes(self, tmp_path: Path) -> None:
        queue = ReviewQueue(tmp_path / "reviews")
        queue.add(ReviewItem(review_id="r3", item_type=ReviewItemType.PATCH, target_object_id="p2"))
        result = queue.resolve("r3", "request_changes", reviewer="carol")
        assert result.status == ReviewDecision.REQUEST_CHANGES

    def test_resolved_not_in_pending(self, tmp_path: Path) -> None:
        queue = ReviewQueue(tmp_path / "reviews")
        queue.add(ReviewItem(review_id="r1", item_type=ReviewItemType.PATCH, target_object_id="p1"))
        queue.resolve("r1", "approve", reviewer="alice")
        assert len(queue.list_pending()) == 0

    def test_nonexistent_resolve(self, tmp_path: Path) -> None:
        queue = ReviewQueue(tmp_path / "reviews")
        assert queue.resolve("nonexistent", "approve", reviewer="x") is None

    def test_all_review_types(self) -> None:
        for rt in ReviewItemType:
            item = ReviewItem(review_id="r", item_type=rt, target_object_id="x")
            assert item.item_type == rt


# ---------------------------------------------------------------------------
# US-031: Conflict / Dedup / Deprecation
# ---------------------------------------------------------------------------

class TestConflictManagement:
    def test_mark_conflict(self) -> None:
        claims = [
            ClaimRecord(claim_id="c1", statement="A is true",
                        status=ClaimStatus.SUPPORTED,
                        evidence_anchors=[EvidenceAnchor(anchor_id="a1", source_id="s1", doc_id="d1", page_no=1, block_id="b1")],
                        supporting_sources=["s1"]),
            ClaimRecord(claim_id="c2", statement="A is false",
                        status=ClaimStatus.SUPPORTED,
                        evidence_anchors=[EvidenceAnchor(anchor_id="a2", source_id="s2", doc_id="d2", page_no=1, block_id="b2")],
                        supporting_sources=["s2"]),
        ]
        conflict, updated_claims = mark_conflict(claims, description="Contradictory conclusions")
        assert len(conflict.claim_ids) == 2
        assert "s1" in conflict.source_ids
        assert "s2" in conflict.source_ids
        assert conflict.resolved is False
        # Verify claims updated to CONFLICTED status
        assert all(c.status == ClaimStatus.CONFLICTED for c in updated_claims)
        for c in updated_claims:
            assert "s1" in c.conflicting_sources
            assert "s2" in c.conflicting_sources

    def test_resolve_conflict(self) -> None:
        conflict, _ = mark_conflict([
            ClaimRecord(claim_id="c1", statement="X", status=ClaimStatus.SUPPORTED,
                        evidence_anchors=[EvidenceAnchor(anchor_id="a1", source_id="s1", doc_id="d1", page_no=1, block_id="b1")],
                        supporting_sources=["s1"]),
            ClaimRecord(claim_id="c2", statement="Y", status=ClaimStatus.SUPPORTED,
                        evidence_anchors=[EvidenceAnchor(anchor_id="a2", source_id="s2", doc_id="d2", page_no=1, block_id="b2")],
                        supporting_sources=["s2"]),
        ])
        conflict.resolve("Source s1 is more reliable")
        assert conflict.resolved is True
        assert conflict.resolution_note is not None


class TestEntityDedup:
    def test_generate_candidates(self) -> None:
        entities = [
            EntityRecord(entity_id="e1", canonical_name="READOC Benchmark", entity_type=EntityType.BENCHMARK),
            EntityRecord(entity_id="e2", canonical_name="READOC", entity_type=EntityType.BENCHMARK),
            EntityRecord(entity_id="e3", canonical_name="SQuAD Dataset", entity_type=EntityType.DATASET),
        ]
        candidates = generate_dedup_candidates(entities)
        # READOC Benchmark vs READOC should be a candidate
        assert len(candidates) >= 1
        ids = {(c.entity_a_id, c.entity_b_id) for c in candidates}
        assert ("e1", "e2") in ids or ("e2", "e1") in ids

    def test_no_candidates_for_different_types(self) -> None:
        entities = [
            EntityRecord(entity_id="e1", canonical_name="Test", entity_type=EntityType.BENCHMARK),
            EntityRecord(entity_id="e2", canonical_name="Test", entity_type=EntityType.DATASET),
        ]
        candidates = generate_dedup_candidates(entities)
        assert len(candidates) == 0

    def test_candidate_merge(self) -> None:
        cand = DedupCandidate(candidate_id="d1", entity_a_id="e1", entity_b_id="e2", similarity_score=0.8)
        assert cand.status == "pending"
        cand.merge(reviewer="alice")
        assert cand.status == "merged"
        assert cand.reviewed_by == "alice"

    def test_candidate_keep_separate(self) -> None:
        cand = DedupCandidate(candidate_id="d1", entity_a_id="e1", entity_b_id="e2", similarity_score=0.6)
        cand.keep_separate(reviewer="bob")
        assert cand.status == "kept_separate"


class TestDeprecation:
    def test_deprecate_claim(self) -> None:
        claim = ClaimRecord(
            claim_id="c1", statement="Old conclusion",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[EvidenceAnchor(anchor_id="a1", source_id="s1", doc_id="d1", page_no=1, block_id="b1")],
            supporting_sources=["s1"],
        )
        updated, deprecation = deprecate_claim(
            claim, reason="Superseded by newer evidence",
            replacement_claim_id="c2", deprecated_by="reviewer_alice",
        )
        assert updated.status == ClaimStatus.DEPRECATED
        assert deprecation.target_id == "c1"
        assert deprecation.replacement_id == "c2"
        assert deprecation.preserved is True  # History always preserved

    def test_deprecation_without_replacement(self) -> None:
        claim = ClaimRecord(
            claim_id="c2", statement="Wrong claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[EvidenceAnchor(anchor_id="a1", source_id="s1", doc_id="d1", page_no=1, block_id="b1")],
        )
        _, deprecation = deprecate_claim(claim, reason="No longer relevant")
        assert deprecation.replacement_id is None


# ---------------------------------------------------------------------------
# US-032: CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_help(self) -> None:
        from click.testing import CliRunner
        from docos.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ingest" in result.output
        assert "route" in result.output
        assert "lint" in result.output
        assert "review" in result.output

    def test_review_help(self) -> None:
        from click.testing import CliRunner
        from docos.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["review", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "approve" in result.output
        assert "reject" in result.output

    def test_ingest_missing_file(self) -> None:
        from click.testing import CliRunner
        from docos.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["ingest", "/nonexistent/file.pdf"])
        assert result.exit_code != 0

    def test_lint_command(self) -> None:
        from click.testing import CliRunner
        from docos.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["lint"])
        assert result.exit_code == 0
