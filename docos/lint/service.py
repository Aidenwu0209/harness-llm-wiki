"""Shared lint service — single entrypoint for pipeline and CLI.

Both the pipeline runner and ``docos lint --run-id`` call this service
so that lint output is consistent between unified runs and stage replay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docos.lint.checker import LintFinding, WikiLinter
from docos.models.knowledge import ClaimRecord, EntityRecord
from docos.models.page import Frontmatter
from docos.models.patch import Patch


def run_lint_for_run(
    base_dir: Path,
    run_id: str,
) -> list[LintFinding]:
    """Run lint checks using persisted artifacts for a given run.

    Loads real pages, claims, entities, DocIR, and patches from stores.
    Falls back to empty lists if artifacts are missing.
    """
    from docos.artifact_stores import WikiStore
    from docos.knowledge_store import KnowledgeStore
    from docos.ir_store import IRStore
    from docos.run_store import RunStore

    # Load manifest
    run_store = RunStore(base_dir)
    manifest = run_store.get(run_id)

    # Load wiki pages
    wiki_store = WikiStore(base_dir / "wiki_state")
    pages: list[Frontmatter] = []
    page_bodies: dict[str, str] = {}
    for path in (base_dir / "wiki_state").glob("*.json"):
        state = wiki_store.get(path.stem)
        if state is not None and state.frontmatter:
            try:
                pages.append(Frontmatter.model_validate(state.frontmatter))
                page_id = state.frontmatter.get("id", "")
                if page_id:
                    page_bodies[page_id] = state.body
            except Exception:
                pass

    # Load knowledge artifacts
    ks = KnowledgeStore(base_dir / "knowledge")
    knowledge = ks.get(run_id)
    claims: list[ClaimRecord] = knowledge.claims if knowledge else []
    entities: list[EntityRecord] = knowledge.entities if knowledge else []

    # Load DocIR
    ir_store = IRStore(base_dir / "ir")
    docir = ir_store.get(run_id)

    # Load patches
    from docos.artifact_stores import PatchStore

    patch_store = PatchStore(base_dir / "patches")
    patches: list[Patch] = []
    if manifest and manifest.patch_artifact_path:
        # Try loading patchset
        ps = patch_store.get_patch_set(run_id)
        if ps is not None:
            patches = ps.patches

    # Run lint with full data
    linter = WikiLinter()
    findings = linter.lint(
        pages=pages,
        claims=claims,
        entities=entities,
        docir=docir,
        patches=patches if patches else None,
        page_bodies=page_bodies,
    )

    return findings
