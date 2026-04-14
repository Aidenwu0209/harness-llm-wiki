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
from docos.models.patch import Change, ChangeType, Patch
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
from docos.wiki.compiler import WikiCompiler

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
        self._parser_registry.register(BasicTextFallbackParser())

    @property
    def source_registry(self) -> SourceRegistry:
        return self._registry

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
            )
            result.gate_passed = gate_passed
            result.gate_reasons = gate_reasons

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
        """Stage 6: Compile wiki pages and generate patches."""
        try:
            manifest.mark_stage("compile", StageStatus.RUNNING)
            self._run_store.update(manifest)

            compiler = WikiCompiler(self._base / "wiki")
            patches: list[Patch] = []

            # Compile source page
            fm, body, page_path = compiler.compile_source_page(source, docir, entities, claims)
            page_content = compiler.render_page(fm, body)

            # Generate patch for the source page
            from docos.wiki.compiler import CompiledPage

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

            # Save wiki page state
            from docos.artifact_stores import WikiPageState

            wiki_state = WikiPageState(
                page_path=str(page_path),
                run_id=manifest.run_id,
                frontmatter=fm.model_dump(),
                body=body,
            )
            self._wiki_store.save(wiki_state)

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

            if patches:
                manifest.patch_artifact_path = str(self._base / "patches" / patches[0].patch_id)

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
            patch = patches[0] if patches else None
            findings = linter.lint(
                pages=pages,
                claims=claims,
                entities=entities,
                docir=docir,
                patch=patch,
                page_bodies=page_bodies,
            )

            # Persist lint findings as artifact
            lint_artifact_path = self._persist_lint_findings(manifest.run_id, findings)
            manifest.lint_artifact_path = str(lint_artifact_path)

            # Record lint observability (US-034)
            severity_counts: dict[str, int] = {}
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
            patch = patches[0] if patches else None
            report = runner.run(
                run_id=manifest.run_id,
                source_id=manifest.source_id,
                docir=docir,
                claims=claims if claims else None,
                entities=entities if entities else None,
                patch=patch,
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
    ) -> tuple[bool, list[str]]:
        """Stage 10: Release gate decision."""
        try:
            manifest.mark_stage("gate", StageStatus.RUNNING)
            self._run_store.update(manifest)

            gate = ReleaseGate(config=config)
            harness_passed = harness_report.overall_passed if harness_report else None
            can_merge, reasons = gate.check(
                findings=findings,
                harness_passed=harness_passed,
            )

            # Record gate observability (US-034)
            manifest.gate_decision = "passed" if can_merge else "blocked"

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
