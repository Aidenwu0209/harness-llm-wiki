"""Unified pipeline runner — orchestrates the full DocOS pipeline.

Provides a single entry point that executes all pipeline stages in order,
persists artifacts at each stage, and updates the RunManifest throughout.
If any stage fails, subsequent stages are skipped and the failure is recorded.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from docos.artifact_stores import PatchStore, ReportStore, WikiStore
from docos.debug_store import DebugAssetStore
from docos.ir_store import IRStore
from docos.knowledge.extractor import KnowledgeExtractionPipeline
from docos.knowledge_store import KnowledgeStore
from docos.lint.checker import ReleaseGate, WikiLinter
from docos.models.config import AppConfig
from docos.models.docir import DocIR
from docos.models.knowledge import ClaimRecord, EntityRecord, KnowledgeRelation
from docos.models.patch import BlastRadius, Change, ChangeType, Patch
from docos.models.run import RunManifest, RunStatus, StageStatus
from docos.models.source import SourceRecord
from docos.pipeline.normalizer import GlobalRepair, PageLocalNormalizer, RepairLog
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserRegistry
from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser
from docos.pipeline.router import DocumentSignals, ParserRouter, RouteDecision
from docos.pipeline.signal_extractor import SignalExtractor
from docos.registry import SourceRegistry
from docos.run_store import RunStore
from docos.source_store import RawStorage
from docos.wiki.compiler import WikiCompiler, _is_valid_page_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Final result of a complete pipeline run."""

    run_id: str
    source_id: str
    status: RunStatus
    failed_stage: str | None = None
    error_detail: str | None = None
    elapsed_seconds: float = 0.0

    # Stage outputs (populated as stages complete)
    route_decision: RouteDecision | None = None
    docir: DocIR | None = None
    entities: list[EntityRecord] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    relations: list[KnowledgeRelation] = field(default_factory=list)
    patches: list[Patch] = field(default_factory=list)
    lint_findings_count: int = 0
    harness_passed: bool | None = None
    gate_passed: bool | None = None
    gate_reasons: list[str] = field(default_factory=list)
    review_status: str | None = None


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


class PipelineRunner:
    """Orchestrates the complete DocOS pipeline from ingest to report.

    Usage::

        runner = PipelineRunner(base_dir=Path("."))
        result = runner.run(file_path=Path("document.pdf"))
    """

    def __init__(self, base_dir: Path, config_path: Path | None = None) -> None:
        self._base = base_dir

        # Resolve config
        if config_path is None:
            config_path = base_dir / "configs" / "router.yaml"
        self._config_path = config_path

        # Initialize stores
        self._raw = RawStorage(base_dir / "raw")
        self._registry = SourceRegistry(base_dir / "registry", self._raw)
        self._run_store = RunStore(base_dir)
        self._ir_store = IRStore(base_dir / "ir")
        self._knowledge_store = KnowledgeStore(base_dir / "knowledge")
        self._patch_store = PatchStore(base_dir / "patches")
        self._report_store = ReportStore(base_dir / "reports")
        self._wiki_store = WikiStore(base_dir / "wiki_state")
        self._debug_store = DebugAssetStore(base_dir / "debug")

        # Parser registry — register available parsers
        self._parser_registry = ParserRegistry()
        self._parser_registry.register(StdlibPDFParser())
        fallback_parser = BasicTextFallbackParser()
        self._parser_registry.register(fallback_parser)
        # Register alias for backward compat (old configs use "basic_text")
        self._parser_registry._backends["basic_text"] = fallback_parser

    @property
    def source_registry(self) -> SourceRegistry:
        return self._registry

    def validate_config(self) -> list[str]:
        """Validate that all parser names in config routes exist in the registry.

        Returns a list of unresolved parser names. Empty list means all OK.
        """
        config = self._load_config()
        registered = set(self._parser_registry.list_parsers())
        unresolved: set[str] = set()
        for route in config.router.routes:
            if route.primary_parser not in registered:
                unresolved.add(route.primary_parser)
            for fb in route.fallback_parsers:
                if fb not in registered:
                    unresolved.add(fb)
        return sorted(unresolved)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, file_path: Path, origin: str = "cli", tags: list[str] | None = None) -> PipelineResult:
        """Execute the full pipeline for a single document.

        Stages: ingest → route → parse → normalize → extract → compile → patch → lint → harness → gate
        """
        start_time = time.monotonic()
        result = PipelineResult(
            run_id="",
            source_id="",
            status=RunStatus.RUNNING,
        )
        manifest: RunManifest | None = None

        try:
            # -- Load config --
            config = self._load_config()

            # -- Validate parser config (fail fast) --
            if config.router.routes:
                unresolved = self.validate_config()
                if unresolved:
                    raise ValueError(
                        f"Unresolved parsers in config: {', '.join(unresolved)}. "
                        f"Available: {', '.join(self._parser_registry.list_parsers())}"
                    )

            # -- Stage 1: Ingest --
            source, manifest = self._stage_ingest(file_path, origin, tags, result)
            if source is None or manifest is None:
                return result

            result.run_id = manifest.run_id
            result.source_id = source.source_id

            # Mark run-level start time
            manifest.started_at = datetime.now()
            manifest.status = RunStatus.RUNNING
            self._run_store.update(manifest)

            # -- Stage 2: Route --
            route_decision = self._stage_route(source, manifest, config, result)
            if route_decision is None:
                self._finalize_failure(manifest, result)
                return result
            result.route_decision = route_decision

            # -- Stage 3: Parse --
            docir = self._stage_parse(source, manifest, route_decision, result)
            if docir is None:
                self._finalize_failure(manifest, result)
                return result

            # -- Stage 4: Normalize --
            docir = self._stage_normalize(source, manifest, docir, result)
            if docir is None:
                self._finalize_failure(manifest, result)
                return result
            result.docir = docir

            # -- Stage 5: Extract --
            entities, claims, relations = self._stage_extract(source, manifest, docir, result)
            result.entities = entities
            result.claims = claims
            result.relations = relations

            # -- Stage 6: Compile --
            patches = self._stage_compile(source, manifest, docir, entities, claims, result)
            result.patches = patches

            # -- Stage 7: Patch (persist + evaluate risk) --
            self._stage_patch(manifest, patches, result)

            # -- Stage 8: Lint --
            findings = self._stage_lint(manifest, entities, claims, docir, patches, result)
            result.lint_findings_count = len(findings)

            # -- Stage 9: Harness (eval) --
            harness_report = self._stage_harness(manifest, docir, entities, claims, patches, result)
            result.harness_passed = harness_report.overall_passed if harness_report else None

            # -- Stage 10: Gate --
            gate_passed, gate_reasons = self._stage_gate(
                manifest, config, findings, harness_report, result,
                patches=patches,
            )
            result.gate_passed = gate_passed
            result.gate_reasons = gate_reasons

            # -- Stage 11: Review --
            self._stage_review(
                manifest, gate_passed, gate_reasons, patches, result,
            )

            # -- Finalize --
            result.status = RunStatus.COMPLETED
            manifest.status = RunStatus.COMPLETED
            manifest.finished_at = datetime.now()
            self._run_store.update(manifest)

        except Exception as e:
            logger.exception("Pipeline failed with unexpected error")
            result.status = RunStatus.FAILED
            if result.failed_stage is None:
                result.failed_stage = "unknown"
            result.error_detail = str(e)
            self._finalize_failure(manifest, result)

        result.elapsed_seconds = time.monotonic() - start_time
        return result

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _stage_ingest(
        self,
        file_path: Path,
        origin: str,
        tags: list[str] | None,
        result: PipelineResult,
    ) -> tuple[SourceRecord | None, RunManifest | None]:
        """Stage 1: Register source and create run manifest."""
        manifest: RunManifest | None = None
        try:
            source = self._registry.register(
                source_file=file_path,
                origin=origin,
                tags=tags or [],
            )
            manifest = self._run_store.create(
                source_id=source.source_id,
                source_hash=source.source_hash,
                source_file_path=str(file_path.resolve()),
            )
            manifest.mark_stage("ingest", StageStatus.RUNNING)
            self._run_store.update(manifest)
            manifest.mark_stage("ingest", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return source, manifest
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "ingest"
            result.error_detail = str(e)
            if manifest is not None:
                manifest.mark_stage("ingest", StageStatus.FAILED, error_detail=str(e))
                self._run_store.update(manifest)
            return None, None

    def _stage_route(
        self,
        source: SourceRecord,
        manifest: RunManifest,
        config: AppConfig,
        result: PipelineResult,
    ) -> RouteDecision | None:
        """Stage 2: Route document to best parser."""
        try:
            manifest.mark_stage("route", StageStatus.RUNNING)
            self._run_store.update(manifest)

            source_file_path = source.raw_storage_path or source.file_name
            extractor = SignalExtractor()
            signals = extractor.extract(Path(source_file_path))

            router = ParserRouter(config, log_dir=self._base / "route_logs")
            decision = router.route(source, signals)

            # Persist route decision as artifact
            route_artifact_path = self._persist_route_decision(manifest.run_id, decision)
            manifest.route_artifact_path = str(route_artifact_path)

            # Record route observability (US-034)
            manifest.selected_route = decision.selected_route
            manifest.parser_chain = [decision.primary_parser] + list(decision.fallback_parsers)

            manifest.mark_stage("route", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return decision
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "route"
            result.error_detail = str(e)
            manifest.mark_stage("route", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)
            return None

    def _stage_parse(
        self,
        source: SourceRecord,
        manifest: RunManifest,
        route_decision: RouteDecision,
        result: PipelineResult,
    ) -> DocIR | None:
        """Stage 3: Parse document using orchestrator."""
        try:
            manifest.mark_stage("parse", StageStatus.RUNNING)
            self._run_store.update(manifest)

            file_path = Path(source.raw_storage_path or source.file_name)
            orchestrator = PipelineOrchestrator(
                parser_registry=self._parser_registry,
                debug_dir=self._base / "debug",
                debug_store=self._debug_store,
            )
            parse_result = orchestrator.execute(
                run_id=manifest.run_id,
                source_id=source.source_id,
                file_path=file_path,
                route_decision=route_decision,
            )

            if not parse_result.success:
                raise RuntimeError(
                    f"Parse failed: {parse_result.failure_reason or 'all parsers failed'}"
                )

            docir = parse_result.docir
            if docir is None:
                raise RuntimeError("Parse succeeded but no DocIR produced")

            # Persist DocIR
            self._ir_store.save(docir, manifest.run_id)

            # Update manifest with parse metadata
            ir_path = self._base / "ir" / f"{manifest.run_id}.json"
            manifest.ir_artifact_path = str(ir_path)
            if parse_result.debug_assets_dir:
                manifest.debug_artifact_path = parse_result.debug_assets_dir

            # Record parse observability (US-034)
            manifest.fallback_used = parse_result.fallback_used
            manifest.mark_stage("parse", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return docir
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "parse"
            result.error_detail = str(e)
            manifest.mark_stage("parse", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)
            return None

    def _stage_normalize(
        self,
        source: SourceRecord,
        manifest: RunManifest,
        docir: DocIR,
        result: PipelineResult,
    ) -> DocIR | None:
        """Stage 4: Normalize DocIR (page-local + global repair)."""
        try:
            manifest.mark_stage("normalize", StageStatus.RUNNING)
            self._run_store.update(manifest)

            repair_log = RepairLog(
                source_id=source.source_id,
                run_id=manifest.run_id,
            )
            repaired = GlobalRepair().repair(docir, repair_log)

            # Persist repaired DocIR
            self._ir_store.save(repaired, manifest.run_id)

            manifest.mark_stage("normalize", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return repaired
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "normalize"
            result.error_detail = str(e)
            manifest.mark_stage("normalize", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)
            return None

    def _stage_extract(
        self,
        source: SourceRecord,
        manifest: RunManifest,
        docir: DocIR,
        result: PipelineResult,
    ) -> tuple[list[EntityRecord], list[ClaimRecord], list[KnowledgeRelation]]:
        """Stage 5: Extract entities, claims, and relations."""
        try:
            manifest.mark_stage("extract", StageStatus.RUNNING)
            self._run_store.update(manifest)

            pipeline = KnowledgeExtractionPipeline()
            entities, claims, relations = pipeline.extract(docir)

            # Persist knowledge artifacts
            from docos.knowledge_store import KnowledgeArtifact

            artifact = KnowledgeArtifact(
                run_id=manifest.run_id,
                source_id=source.source_id,
                entities=entities,
                claims=claims,
                relations=relations,
            )
            self._knowledge_store.save(artifact)

            manifest.knowledge_artifact_path = str(self._base / "knowledge" / manifest.run_id)
            manifest.mark_stage("extract", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return entities, claims, relations
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "extract"
            result.error_detail = str(e)
            manifest.mark_stage("extract", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)
            return [], [], []

    def _stage_compile(
        self,
        source: SourceRecord,
        manifest: RunManifest,
        docir: DocIR,
        entities: list[EntityRecord],
        claims: list[ClaimRecord],
        result: PipelineResult,
    ) -> list[Patch]:
        """Stage 6: Compile wiki pages and generate patches via unified page loop."""
        try:
            manifest.mark_stage("compile", StageStatus.RUNNING)
            self._run_store.update(manifest)

            compiler = WikiCompiler(self._base / "wiki")
            from docos.artifact_stores import WikiPageState
            from docos.wiki.compiler import CompiledPage

            patches: list[Patch] = []
            page_types: list[str] = []
            _dropped_empty_slug: int = 0
            _dropped_unreadable_title: int = 0
            _dropped_unreadable_entity: int = 0
            _dropped_unreadable_concept: int = 0

            from docos.slugify import is_readable_title

            # --- Unified page loop ---
            # 1. Source page
            fm, body, page_path = compiler.compile_source_page(source, docir, entities, claims)
            if not _is_valid_page_path(page_path):
                _dropped_empty_slug += 1
            else:
                compiled = CompiledPage(
                    frontmatter=fm,
                    body=body,
                    page_path=page_path,
                    run_id=manifest.run_id,
                )
                patch = compiled.compute_patch(
                    run_id=manifest.run_id,
                    source_id=source.source_id,
                )
                if patch is not None:
                    patches.append(patch)
                page_types.append("source")
                self._wiki_store.save(WikiPageState(
                    page_path=str(page_path),
                    run_id=manifest.run_id,
                    frontmatter=fm.model_dump(),
                    body=body,
                ))

            # 2. Entity pages
            for entity in entities:
                if not is_readable_title(entity.canonical_name):
                    _dropped_unreadable_title += 1
                    _dropped_unreadable_entity += 1
                    continue
                efm, ebody, epath = compiler.compile_entity_page(entity, claims)
                if not _is_valid_page_path(epath):
                    _dropped_empty_slug += 1
                    continue
                ecompiled = CompiledPage(
                    frontmatter=efm,
                    body=ebody,
                    page_path=epath,
                    run_id=manifest.run_id,
                )
                epatch = ecompiled.compute_patch(
                    run_id=manifest.run_id,
                    source_id=source.source_id,
                )
                if epatch is not None:
                    patches.append(epatch)
                page_types.append("entity")
                self._wiki_store.save(WikiPageState(
                    page_path=str(epath),
                    run_id=manifest.run_id,
                    frontmatter=efm.model_dump(),
                    body=ebody,
                ))

            # 3. Concept pages (derived from entities and claims)
            concept_names: set[str] = set()
            for entity in entities:
                if entity.entity_type in ("concept", "topic", "theme"):
                    concept_names.add(entity.canonical_name)
            for concept_name in concept_names:
                if not is_readable_title(concept_name):
                    _dropped_unreadable_title += 1
                    _dropped_unreadable_concept += 1
                    continue
                related_entities = [e for e in entities if e.canonical_name == concept_name]
                related_claims = [c for c in claims if
                    concept_name in c.statement]
                cfm, cbody, cpath = compiler.compile_concept_page(
                    concept_name=concept_name,
                    source_ids=[source.source_id],
                    related_claims=related_claims,
                    related_entities=related_entities,
                )
                if not _is_valid_page_path(cpath):
                    _dropped_empty_slug += 1
                    continue
                ccompiled = CompiledPage(
                    frontmatter=cfm,
                    body=cbody,
                    page_path=cpath,
                    run_id=manifest.run_id,
                )
                cpatch = ccompiled.compute_patch(
                    run_id=manifest.run_id,
                    source_id=source.source_id,
                )
                if cpatch is not None:
                    patches.append(cpatch)
                page_types.append("concept")
                self._wiki_store.save(WikiPageState(
                    page_path=str(cpath),
                    run_id=manifest.run_id,
                    frontmatter=cfm.model_dump(),
                    body=cbody,
                ))

            # 4. Generate delete patches for stale entity and concept pages
            current_paths = {
                str(page_path),  # source
            }
            for entity in entities:
                _, _, epath2 = compiler.compile_entity_page(entity, [])
                if _is_valid_page_path(epath2):
                    current_paths.add(str(epath2))
            for concept_name in concept_names:
                _, _, cpath2 = compiler.compile_concept_page(
                    concept_name=concept_name,
                    source_ids=[],
                    related_claims=[],
                    related_entities=[],
                )
                if _is_valid_page_path(cpath2):
                    current_paths.add(str(cpath2))

            prior_paths = set(self._wiki_store.list_page_paths())
            stale_entity_concept_paths = {
                p for p in prior_paths - current_paths
                if "/entities/" in p or "/concepts/" in p
            }
            for stale_path in stale_entity_concept_paths:
                stale_slug = stale_path.replace("/", "-").replace(" ", "-")[:50]
                del_patch = Patch(
                    patch_id=f"del-{manifest.run_id}-{stale_slug}",
                    run_id=manifest.run_id,
                    source_id=source.source_id,
                    changes=[Change(type=ChangeType.DELETE_PAGE, target=stale_path)],
                    risk_score=0.3,
                    blast_radius=BlastRadius(pages=1),
                )
                patches.append(del_patch)
                page_types.append("delete")

            # Record compile summary in manifest
            manifest.compiled_page_count = len(page_types)
            manifest.compiled_page_types = page_types
            manifest.compiled_patch_count = len(patches)
            manifest.compiled_created_count = len([t for t in page_types if t != "delete"])
            manifest.compiled_updated_count = 0  # Updated pages tracked via patch change types
            manifest.compiled_deleted_count = page_types.count("delete")
            manifest.dropped_empty_slug_count = _dropped_empty_slug
            manifest.dropped_unreadable_title_count = _dropped_unreadable_title
            manifest.dropped_unreadable_entity_count = _dropped_unreadable_entity
            manifest.dropped_unreadable_concept_count = _dropped_unreadable_concept

            manifest.mark_stage("compile", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return patches
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "compile"
            result.error_detail = str(e)
            manifest.mark_stage("compile", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)
            return []

    def _stage_patch(
        self,
        manifest: RunManifest,
        patches: list[Patch],
        result: PipelineResult,
    ) -> None:
        """Stage 7: Persist patches and stage them."""
        try:
            manifest.mark_stage("patch", StageStatus.RUNNING)
            self._run_store.update(manifest)

            for p in patches:
                p.stage()
                self._patch_store.save(p)

            # Persist PatchSet for run-level access (US-014)
            from docos.models.patch_set import PatchSet

            patch_set = PatchSet.from_patches(
                run_id=manifest.run_id,
                source_id=manifest.source_id,
                patches=patches,
            )
            self._patch_store.save_patch_set(patch_set)

            if patches:
                manifest.patch_artifact_path = str(self._base / "patches" / f"patchset-{manifest.run_id}")

            manifest.mark_stage("patch", StageStatus.COMPLETED)
            self._run_store.update(manifest)
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "patch"
            result.error_detail = str(e)
            manifest.mark_stage("patch", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)

    def _stage_lint(
        self,
        manifest: RunManifest,
        entities: list[EntityRecord],
        claims: list[ClaimRecord],
        docir: DocIR | None,
        patches: list[Patch],
        result: PipelineResult,
    ) -> list[Any]:
        """Stage 8: Run lint checks."""
        try:
            manifest.mark_stage("lint", StageStatus.RUNNING)
            self._run_store.update(manifest)

            # Load real wiki page data from wiki store
            from docos.models.page import Frontmatter

            pages: list[Frontmatter] = []
            page_bodies: dict[str, str] = {}
            for path in (self._base / "wiki_state").glob("*.json"):
                state = self._wiki_store.get(path.stem)
                if state is not None and state.frontmatter:
                    try:
                        pages.append(Frontmatter.model_validate(state.frontmatter))
                        page_id = state.frontmatter.get("id", "")
                        if page_id:
                            page_bodies[page_id] = state.body
                    except Exception:
                        pass

            linter = WikiLinter()
            findings = linter.lint(
                pages=pages,
                claims=claims,
                entities=entities,
                docir=docir,
                patches=patches,
                page_bodies=page_bodies,
            )

            # Persist lint findings as artifact
            lint_artifact_path = self._persist_lint_findings(manifest.run_id, findings)
            manifest.lint_artifact_path = str(lint_artifact_path)

            # Record lint observability (US-034)
            severity_counts: dict[str, int] = {"total": len(findings)}
            for f in findings:
                sev = f.severity.value
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
            manifest.lint_summary = severity_counts

            manifest.mark_stage("lint", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return findings
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "lint"
            result.error_detail = str(e)
            manifest.mark_stage("lint", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)
            return []

    def _stage_harness(
        self,
        manifest: RunManifest,
        docir: DocIR | None,
        entities: list[EntityRecord],
        claims: list[ClaimRecord],
        patches: list[Patch],
        result: PipelineResult,
    ) -> Any:
        """Stage 9: Run harness evaluation."""
        try:
            manifest.mark_stage("harness", StageStatus.RUNNING)
            self._run_store.update(manifest)

            from docos.harness.runner import HarnessRunner

            runner = HarnessRunner()
            report = runner.run(
                run_id=manifest.run_id,
                source_id=manifest.source_id,
                docir=docir,
                claims=claims if claims else None,
                entities=entities if entities else None,
                patches=patches,
            )

            self._report_store.save(report)
            manifest.report_artifact_path = str(self._base / "reports" / manifest.run_id)

            # Record harness observability (US-034)
            manifest.harness_summary = {
                "overall_passed": report.overall_passed,
                "release_decision": report.release_decision,
            }

            manifest.mark_stage("harness", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return report
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "harness"
            result.error_detail = str(e)
            manifest.mark_stage("harness", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)
            return None

    def _stage_gate(
        self,
        manifest: RunManifest,
        config: AppConfig,
        findings: list[Any],
        harness_report: Any,
        result: PipelineResult,
        patches: list[Any] | None = None,
    ) -> tuple[bool, list[str]]:
        """Stage 10: Release gate decision."""
        try:
            manifest.mark_stage("gate", StageStatus.RUNNING)
            self._run_store.update(manifest)

            gate = ReleaseGate(config=config)
            harness_passed = harness_report.overall_passed if harness_report else None

            # Patch-set aware gate metrics (US-017)
            patch_count = len(patches) if patches else 0
            total_pages_changed = len({c.target for p in (patches or []) for c in p.changes}) if patches else 0
            aggregate_risk = max((p.risk_score for p in (patches or [])), default=0.0)
            delete_markers = sum(1 for p in (patches or []) for c in p.changes if c.type == ChangeType.DELETE_PAGE)
            review_markers = sum(1 for p in (patches or []) if getattr(p, "review_required", False))

            can_merge, reasons = gate.check(
                findings=findings,
                harness_passed=harness_passed,
                patch_count=patch_count,
                total_pages_changed=total_pages_changed,
                aggregate_risk=aggregate_risk,
                delete_page_markers=delete_markers,
                review_required_markers=review_markers,
            )

            # Record gate observability (US-034)
            manifest.gate_decision = "passed" if can_merge else "blocked"
            manifest.gate_blockers = reasons if not can_merge else []
            manifest.release_reasoning = reasons if reasons else ["All gates passed"]

            # Update review_status based on gate result
            if can_merge:
                manifest.review_status = "none"
            else:
                manifest.review_status = "pending"

            # Persist gate decision as structured artifact
            gate_artifact_path = self._persist_gate_decision(
                manifest.run_id, can_merge, reasons, harness_report,
            )

            manifest.mark_stage("gate", StageStatus.COMPLETED)
            self._run_store.update(manifest)
            return can_merge, reasons
        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "gate"
            result.error_detail = str(e)
            manifest.mark_stage("gate", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)
            return False, [str(e)]

    # ------------------------------------------------------------------
    # Stage 11: Review
    # ------------------------------------------------------------------

    def _stage_review(
        self,
        manifest: RunManifest,
        gate_passed: bool,
        gate_reasons: list[str],
        patches: list[Any],
        result: PipelineResult,
    ) -> None:
        """Stage 11: Review stage — records review status based on gate outcome.

        For auto-merge eligible runs, stages and auto-merges all patches
        through PatchService and writes a structured review artifact.
        For blocked runs, records a pending-review status.
        """
        try:
            manifest.mark_stage("review", StageStatus.RUNNING)
            self._run_store.update(manifest)

            if gate_passed and not any(p.review_required for p in patches):
                # Auto-merge path: stage and auto-merge all patches through PatchService
                from docos.wiki.patch_service import PatchService
                from docos.patch_apply import PatchApplyService

                patch_svc = PatchService(
                    patch_dir=self._base / "patches",
                    wiki_dir=self._base / "wiki_state",
                )
                for p in patches:
                    patch_svc.auto_merge(p)

                # Apply wiki state for all merged patches
                apply_svc = PatchApplyService(
                    wiki_dir=self._base / "wiki",
                    wiki_store=self._wiki_store,
                )
                apply_svc.apply_batch(patches)

                manifest.review_status = "auto_merged"
                manifest.release_reasoning = gate_reasons if gate_reasons else ["All gates passed — auto-merged"]
                result.review_status = "auto_merged"
            else:
                # Pending review path: create a run-level pending review item (idempotent)
                from docos.review.queue import ReviewItem, ReviewItemType, ReviewQueue

                queue = ReviewQueue(self._base / "review_queue")

                # Idempotency check: reuse existing review item for this run
                existing_item = queue.find_by_run_id(manifest.run_id)
                if existing_item is not None:
                    review_id = existing_item.review_id
                else:
                    review_id = f"rv-{manifest.run_id}"
                    review_item = ReviewItem(
                        review_id=review_id,
                        item_type=ReviewItemType.PATCH,
                        target_object_id=manifest.run_id,
                        run_id=manifest.run_id,
                        source_id=manifest.source_id,
                        patch_ids=[p.patch_id for p in patches],
                        gate_reasons=gate_reasons,
                        lint_summary=manifest.lint_summary,
                        harness_summary=manifest.harness_summary,
                        reason="; ".join(gate_reasons) if gate_reasons else "Gate blocked auto-merge",
                    )
                    queue.add(review_item)

                manifest.review_status = "pending"
                manifest.review_ids = [review_id]
                manifest.release_reasoning = gate_reasons
                result.review_status = "pending"

            # Persist review artifact
            review_dir = self._base / "review"
            review_dir.mkdir(parents=True, exist_ok=True)
            review_artifact = review_dir / f"{manifest.run_id}.json"
            review_data: dict[str, Any] = {
                "run_id": manifest.run_id,
                "source_id": manifest.source_id,
                "review_status": manifest.review_status,
                "release_decision": "auto_merge" if gate_passed else "blocked",
                "gate_passed": gate_passed,
                "gate_reasons": gate_reasons,
                "patch_count": len(patches),
                "patch_ids": [p.patch_id for p in patches],
                "release_reasoning": manifest.release_reasoning,
            }
            review_artifact.write_text(
                json.dumps(review_data, indent=2, default=str),
                encoding="utf-8",
            )
            manifest.review_artifact_path = str(review_artifact)

            manifest.mark_stage("review", StageStatus.COMPLETED)
            self._run_store.update(manifest)

        except Exception as e:
            result.status = RunStatus.FAILED
            result.failed_stage = "review"
            result.error_detail = str(e)
            manifest.mark_stage("review", StageStatus.FAILED, error_detail=str(e))
            self._run_store.update(manifest)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> AppConfig:
        """Load and validate app configuration."""
        with open(self._config_path) as f:
            return AppConfig.model_validate(yaml.safe_load(f))

    def _finalize_failure(self, manifest: RunManifest | None, result: PipelineResult) -> None:
        """Persist failure state to the run manifest."""
        if manifest is None or not result.run_id:
            return
        try:
            manifest.status = RunStatus.FAILED
            manifest.finished_at = datetime.now()
            self._run_store.update(manifest)
        except Exception:
            pass

    def _persist_route_decision(self, run_id: str, decision: RouteDecision) -> Path:
        """Persist route decision as a JSON artifact."""
        route_dir = self._base / "routes"
        route_dir.mkdir(parents=True, exist_ok=True)
        path = route_dir / f"{run_id}.json"
        path.write_text(
            json.dumps({
                "selected_route": decision.selected_route,
                "primary_parser": decision.primary_parser,
                "fallback_parsers": decision.fallback_parsers,
                "expected_risks": decision.expected_risks,
                "review_policy": decision.review_policy,
                "matched_signals": decision.matched_signals,
                "decision_reason": decision.decision_reason,
            }, indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def _persist_lint_findings(self, run_id: str, findings: list[Any]) -> Path:
        """Persist lint findings as a JSON artifact."""
        lint_dir = self._base / "lint_results"
        lint_dir.mkdir(parents=True, exist_ok=True)
        path = lint_dir / f"{run_id}.json"
        findings_data = [
            {
                "code": f.code,
                "message": f.message,
                "severity": f.severity.value,
                "page_id": f.page_id,
                "block_id": f.block_id,
            }
            for f in findings
        ]
        path.write_text(
            json.dumps(findings_data, indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def _persist_gate_decision(
        self,
        run_id: str,
        can_merge: bool,
        reasons: list[str],
        harness_report: Any,
    ) -> Path:
        """Persist gate decision as a structured JSON artifact."""
        gate_dir = self._base / "gate_decisions"
        gate_dir.mkdir(parents=True, exist_ok=True)
        path = gate_dir / f"{run_id}.json"

        gate_data: dict[str, Any] = {
            "run_id": run_id,
            "release_decision": "auto_merge" if can_merge else "blocked",
            "can_merge": can_merge,
            "gate_blockers": reasons if not can_merge else [],
            "release_reasoning": reasons if reasons else ["All gates passed"],
            "harness_passed": harness_report.overall_passed if harness_report else None,
            "harness_release_decision": harness_report.release_decision if harness_report else None,
            "harness_release_reasoning": harness_report.release_reasoning if harness_report else [],
        }
        path.write_text(
            json.dumps(gate_data, indent=2, default=str),
            encoding="utf-8",
        )
        return path
