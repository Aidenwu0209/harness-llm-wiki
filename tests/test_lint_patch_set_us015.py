"""Tests for US-015: Make WikiLinter patch-set aware."""

from __future__ import annotations

from docos.lint.checker import LintSeverity, WikiLinter
from docos.models.patch import BlastRadius, Change, ChangeType, Patch


def _make_patch(
    patch_id: str,
    target: str = "page.md",
    change_type: ChangeType = ChangeType.CREATE_PAGE,
) -> Patch:
    return Patch(
        patch_id=patch_id,
        run_id="run-001",
        source_id="src-001",
        changes=[Change(type=change_type, target=target)],
        risk_score=0.2,
        blast_radius=BlastRadius(pages=1),
    )


class TestPatchSetAwareLinter:
    """US-015: WikiLinter inspects full patch collection."""

    def test_lint_accepts_patches_list(self) -> None:
        """WikiLinter accepts a patches list instead of single patch."""
        linter = WikiLinter()
        patches = [_make_patch("p-001"), _make_patch("p-002")]
        findings = linter.lint(
            pages=[], claims=[], entities=[], patches=patches,
        )
        assert isinstance(findings, list)

    def test_detects_path_conflicts(self) -> None:
        """Lint detects multiple patches targeting the same page."""
        linter = WikiLinter()
        patches = [
            _make_patch("p-001", target="same-page.md"),
            _make_patch("p-002", target="same-page.md"),
        ]
        findings = linter.lint(
            pages=[], claims=[], entities=[], patches=patches,
        )
        conflict = [f for f in findings if f.code == "PATCH_PATH_CONFLICT"]
        assert len(conflict) == 1
        assert conflict[0].severity == LintSeverity.P1

    def test_detects_conflicting_create_and_delete(self) -> None:
        """Lint detects CREATE + DELETE for same target."""
        linter = WikiLinter()
        patches = [
            _make_patch("p-001", target="page-a.md", change_type=ChangeType.CREATE_PAGE),
            _make_patch("p-002", target="page-a.md", change_type=ChangeType.DELETE_PAGE),
        ]
        findings = linter.lint(
            pages=[], claims=[], entities=[], patches=patches,
        )
        conflict = [f for f in findings if f.code == "CONFLICTING_CREATE_DELETE"]
        assert len(conflict) == 1
        assert conflict[0].severity == LintSeverity.P0

    def test_detects_conflicting_update_and_delete(self) -> None:
        """Lint detects UPDATE + DELETE for same target."""
        linter = WikiLinter()
        patches = [
            _make_patch("p-001", target="page-b.md", change_type=ChangeType.UPDATE_PAGE),
            _make_patch("p-002", target="page-b.md", change_type=ChangeType.DELETE_PAGE),
        ]
        findings = linter.lint(
            pages=[], claims=[], entities=[], patches=patches,
        )
        conflict = [f for f in findings if f.code == "CONFLICTING_UPDATE_DELETE"]
        assert len(conflict) == 1
        assert conflict[0].severity == LintSeverity.P0

    def test_no_conflict_for_different_targets(self) -> None:
        """No conflict when patches target different pages."""
        linter = WikiLinter()
        patches = [
            _make_patch("p-001", target="page-x.md"),
            _make_patch("p-002", target="page-y.md"),
        ]
        findings = linter.lint(
            pages=[], claims=[], entities=[], patches=patches,
        )
        conflicts = [f for f in findings if "CONFLICT" in f.code or "conflict" in f.code.lower()]
        assert len(conflicts) == 0

    def test_backward_compat_with_single_patch(self) -> None:
        """Single patch parameter still works via backward compat."""
        linter = WikiLinter()
        patch = _make_patch("p-001")
        findings = linter.lint(
            pages=[], claims=[], entities=[], patch=patch,
        )
        assert isinstance(findings, list)
