"""Tests for US-028: Low-risk auto-merge golden scenario."""

from __future__ import annotations

from pathlib import Path

from docos.artifact_stores import PatchStore, WikiStore, WikiPageState
from docos.harness.runner import HarnessRunner
from docos.knowledge_store import KnowledgeArtifact, KnowledgeStore
from docos.lint.checker import ReleaseGate, WikiLinter
from docos.models.docir import DocIR
from docos.models.knowledge import EntityRecord, EntityType
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.models.patch_set import PatchSet
from docos.patch_apply import PatchApplyService
from docos.run_store import RunStore


class TestGoldenAutoMerge:
    """US-028: Golden scenario proving auto-merge from compile through wiki apply."""

    def test_low_risk_auto_merge_golden_path(self, tmp_path: Path) -> None:
        """A low-risk fixture run passes lint, harness, gate, and auto-merges wiki state."""
        base = tmp_path / "artifacts"
        run_store = RunStore(base)
        manifest = run_store.create(source_id="src-golden", source_hash="h", source_file_path="/tmp/golden.pdf")
        run_id = manifest.run_id

        # 1. DocIR
        ir_store_path = base / "ir"
        from docos.ir_store import IRStore
        ir_store = IRStore(ir_store_path)
        docir = DocIR(doc_id="d-golden", source_id="src-golden", parser="test", page_count=1, pages=[])
        ir_store.save(docir, run_id)

        # 2. Knowledge (entity + concept)
        ks = KnowledgeStore(base / "knowledge")
        entities = [
            EntityRecord(entity_id="e-1", canonical_name="GoldenEntity", entity_type=EntityType.CONCEPT, source_ids=["src-golden"]),
        ]
        ks.save(KnowledgeArtifact(run_id=run_id, source_id="src-golden", entities=entities, claims=[]))

        # 3. Compile pages — generate patches
        wiki_store = WikiStore(base / "wiki_state")

        # Entity page
        from docos.wiki.compiler import WikiCompiler
        compiler = WikiCompiler(base / "wiki")
        entity = entities[0]
        efm, ebody, epath = compiler.compile_entity_page(entity, [])
        wiki_store.save(WikiPageState(
            page_path=str(epath), run_id=run_id,
            frontmatter=efm.model_dump(), body=ebody,
        ))

        # Concept page (entity is CONCEPT type)
        concept_names = {e.canonical_name for e in entities if e.entity_type.value in ("concept", "topic", "theme")}
        concept_pages = []
        for cn in concept_names:
            cfm, cbody, cpath = compiler.compile_concept_page(
                concept_name=cn, source_ids=["src-golden"],
                related_claims=[], related_entities=[entity],
            )
            wiki_store.save(WikiPageState(
                page_path=str(cpath), run_id=run_id,
                frontmatter=cfm.model_dump(), body=cbody,
            ))
            concept_pages.append((cfm, cbody, cpath))

        # 4. Generate patches
        from docos.wiki.compiler import CompiledPage
        patches = []

        ecompiled = CompiledPage(frontmatter=efm, body=ebody, page_path=epath, run_id=run_id)
        epatch = ecompiled.compute_patch(run_id=run_id, source_id="src-golden")
        if epatch is not None:
            patches.append(epatch)

        for cfm, cbody, cpath in concept_pages:
            ccompiled = CompiledPage(frontmatter=cfm, body=cbody, page_path=cpath, run_id=run_id)
            cpatch = ccompiled.compute_patch(run_id=run_id, source_id="src-golden")
            if cpatch is not None:
                patches.append(cpatch)

        # 5. Save patch set
        patch_store = PatchStore(base / "patches")
        ps = PatchSet.from_patches(run_id, "src-golden", patches)
        for p in patches:
            patch_store.save(p)
        patch_store.save_patch_set(ps)

        # Verify low risk
        assert ps.summary.max_risk_score <= 0.3, f"Expected low risk, got {ps.summary.max_risk_score}"
        assert not ps.summary.any_review_required

        # 6. Lint
        linter = WikiLinter()
        findings = linter.lint(pages=[], claims=[], entities=entities, patches=patches)
        lint_passed = len(findings) == 0 or not any(f.severity.value == "error" for f in findings)

        # 7. Harness
        runner = HarnessRunner()
        report = runner.run(
            run_id=run_id, source_id="src-golden",
            docir=docir, entities=entities, patches=patches,
        )
        assert report.overall_passed

        # 8. Gate
        gate = ReleaseGate()
        gate_passed, gate_reasons = gate.check(
            findings=findings,
            harness_passed=report.overall_passed,
            patch_count=ps.summary.total_patches,
            total_pages_changed=ps.summary.total_pages_changed,
            aggregate_risk=ps.summary.max_risk_score,
        )

        # 9. Auto-merge (low risk should pass)
        assert gate_passed, f"Gate blocked: {gate_reasons}"
        assert not any(p.review_required for p in patches)

        # 10. Apply wiki state
        wiki_dir = base / "wiki"
        apply_svc = PatchApplyService(wiki_dir, wiki_store)
        results = apply_svc.apply_batch(patches)
        assert all(r.applied for r in results)
        assert any(r.changes_applied > 0 for r in results)

        # Verify wiki files exist
        assert (wiki_dir / str(epath)).exists()
        for _, _, cpath in concept_pages:
            assert (wiki_dir / str(cpath)).exists()
