"""Pipeline orchestrator — executes parse with automatic fallback.

When the primary parser fails, the orchestrator automatically tries
fallback parsers in order, recording every attempt for audit.
Fallback results enter a stricter review policy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.debug_store import DebugAssetStore
from docos.models.docir import DocIR
from docos.pipeline.parser import DebugConfig, ParseResult, ParserBackend, ParserRegistry
from docos.pipeline.router import RouteDecision

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parser-name → optional-dependency-group mapping
# ---------------------------------------------------------------------------

_PARSER_EXTRAS: dict[str, str] = {
    "pymupdf": "parser",
    "pdfplumber": "parser",
    "marker": "parser",
    "paddleocr": "ocr",
    "tesseract": "ocr",
}


def _missing_parser_message(parser_name: str) -> str:
    """Return a helpful error message for an unresolvable parser name."""
    extra = _PARSER_EXTRAS.get(parser_name)
    if extra:
        return (
            f"Parser '{parser_name}' is not registered in the parser registry. "
            f"Install it with: pip install docos[{extra}]"
        )
    return (
        f"Parser '{parser_name}' is not registered in the parser registry. "
        f"Check pyproject.toml [project.optional-dependencies] for available extras."
    )


# ---------------------------------------------------------------------------
# Pipeline run result
# ---------------------------------------------------------------------------

@dataclass
class PipelineRunResult:
    """Result of a full parse pipeline run (with fallback if needed)."""

    run_id: str
    source_id: str
    success: bool
    final_parser: str = ""
    primary_succeeded: bool = True
    fallback_used: bool = False
    fallback_parser: str | None = None
    failure_reason: str | None = None

    # Final DocIR (from whichever parser succeeded)
    docir: DocIR | None = None

    # All parse attempts (primary + fallbacks)
    attempts: list[ParseResult] = field(default_factory=list)

    # Timing
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    total_elapsed_seconds: float = 0.0

    # Debug
    debug_assets: dict[str, Path] = field(default_factory=dict)

    # Asset paths written to disk (for run manifest linking)
    parse_log_path: str | None = None
    debug_assets_dir: str | None = None

    # Failed attempt tracking
    failed_attempt_paths: list[str] = field(default_factory=list)
    parser_unavailable: list[str] = field(default_factory=list)

    @property
    def review_policy_override(self) -> str | None:
        """Fallback results should use stricter review policy."""
        if self.fallback_used:
            return "strict"
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class PipelineOrchestrator:
    """Orchestrates parse execution with automatic fallback.

    Flow:
    1. Execute primary parser.
    2. If primary fails, record failure and try fallbacks in order.
    3. Mark fallback_used if a fallback parser was needed.
    4. Export debug assets for all attempts.
    5. Return a PipelineRunResult with full history.
    """

    def __init__(
        self,
        parser_registry: ParserRegistry,
        debug_dir: Path | None = None,
        debug_store: DebugAssetStore | None = None,
    ) -> None:
        self._registry = parser_registry
        self._debug_dir = debug_dir
        self._debug_store = debug_store

    def execute(
        self,
        run_id: str,
        source_id: str,
        file_path: Path,
        route_decision: RouteDecision,
    ) -> PipelineRunResult:
        """Execute the parse pipeline with fallback support.

        Args:
            run_id: Unique run identifier.
            source_id: Source document identifier.
            file_path: Path to the file to parse.
            route_decision: Route decision from the router.

        Returns:
            PipelineRunResult with attempt history and final DocIR.
        """
        result = PipelineRunResult(
            run_id=run_id,
            source_id=source_id,
            success=False,
        )

        # Build parser list: primary first, then fallbacks
        parser_names = [route_decision.primary_parser] + list(route_decision.fallback_parsers)

        for i, parser_name in enumerate(parser_names):
            is_primary = i == 0
            backend = self._registry.get(parser_name)

            if backend is None:
                logger.warning("Parser '%s' not found in registry, skipping", parser_name)
                result.parser_unavailable.append(parser_name)
                # Persist unavailable status
                if self._debug_store is not None:
                    unavailable_log = self._persist_unavailable(parser_name, run_id, source_id)
                    result.failed_attempt_paths.append(unavailable_log)
                if is_primary:
                    result.primary_succeeded = False
                    result.failure_reason = _missing_parser_message(parser_name)
                continue

            logger.info(
                "Attempting parse with %s (primary=%s) for %s",
                parser_name, is_primary, source_id,
            )

            attempt = self._run_single(backend, file_path, run_id, source_id)
            result.attempts.append(attempt)

            if attempt.success:
                result.success = True
                result.final_parser = parser_name
                result.docir = attempt.docir

                if not is_primary:
                    result.fallback_used = True
                    result.fallback_parser = parser_name
                    result.primary_succeeded = False

                # Persist debug assets via DebugAssetStore
                self._persist_success(result, backend, attempt, run_id, source_id)

                break
            else:
                if is_primary:
                    result.primary_succeeded = False
                    result.failure_reason = attempt.error
                    logger.warning(
                        "Primary parser '%s' failed: %s",
                        parser_name, attempt.error,
                    )
                # Persist failed attempt log
                if self._debug_store is not None:
                    fail_log = self._persist_failure(parser_name, attempt, run_id, source_id)
                    result.failed_attempt_paths.append(fail_log)

        result.finished_at = datetime.now()
        result.total_elapsed_seconds = sum(a.elapsed_seconds for a in result.attempts)

        if not result.success:
            logger.error("All parsers failed for %s", source_id)

        return result

    def _run_single(
        self,
        backend: ParserBackend,
        file_path: Path,
        run_id: str,
        source_id: str,
    ) -> ParseResult:
        """Run a single parser backend."""
        start = datetime.now()

        try:
            # Step 1: Parse
            parse_result = backend.parse(file_path)
            parse_result.elapsed_seconds = (datetime.now() - start).total_seconds()

            if not parse_result.success:
                return parse_result

            # Step 2: Normalize to DocIR
            docir = backend.normalize(parse_result)
            parse_result.docir = docir

            return parse_result

        except Exception as e:
            elapsed = (datetime.now() - start).total_seconds()
            logger.exception("Parser '%s' threw exception", backend.name)
            return ParseResult(
                parser_name=backend.name,
                parser_version=backend.version,
                success=False,
                error=str(e),
                elapsed_seconds=elapsed,
            )

    def _persist_success(
        self,
        run_result: PipelineRunResult,
        backend: ParserBackend,
        parse_result: ParseResult,
        run_id: str,
        source_id: str,
    ) -> None:
        """Persist debug assets and parse log for a successful attempt."""
        if self._debug_store is not None:
            # Use DebugAssetStore for structured persistence
            assets = self._debug_store.persist_run_result(
                source_id=source_id,
                run_id=run_id,
                parser_name=backend.name,
                result=parse_result,
            )
            for name, path in assets.items():
                parse_result.debug_assets[name] = path
                run_result.debug_assets[name] = path

            # Record paths for run manifest linking
            run_dir = self._debug_store._run_dir(source_id, run_id, backend.name)
            parse_log_path = run_dir / "parse_log.json"
            if parse_log_path.exists():
                run_result.parse_log_path = str(parse_log_path)
                run_result.debug_assets_dir = str(run_dir)
        else:
            # Fallback to simple debug export
            self._export_debug(backend, parse_result, run_id, source_id)

    def _persist_failure(
        self,
        parser_name: str,
        parse_result: ParseResult,
        run_id: str,
        source_id: str,
    ) -> str:
        """Persist a failed parser attempt log. Returns path to log file."""
        assert self._debug_store is not None  # caller guarantees non-None
        log_path = self._debug_store.persist_parse_log(
            source_id=source_id,
            run_id=run_id,
            parser_name=parser_name,
            result=parse_result,
        )
        logger.info("Persisted failure log for %s at %s", parser_name, log_path)
        return str(log_path)

    def _persist_unavailable(
        self,
        parser_name: str,
        run_id: str,
        source_id: str,
    ) -> str:
        """Persist a parser-unavailable status. Returns path to log file."""
        assert self._debug_store is not None  # caller guarantees non-None
        # Create a synthetic ParseResult for the unavailable state
        unavailable_result = ParseResult(
            parser_name=parser_name,
            parser_version="unavailable",
            success=False,
            error=f"Parser '{parser_name}' is not registered in the parser registry",
        )
        log_path = self._debug_store.persist_parse_log(
            source_id=source_id,
            run_id=run_id,
            parser_name=parser_name,
            result=unavailable_result,
        )
        logger.info("Persisted unavailable log for %s at %s", parser_name, log_path)
        return str(log_path)

    def _export_debug(
        self,
        backend: ParserBackend,
        result: ParseResult,
        run_id: str,
        source_id: str,
    ) -> None:
        """Export debug assets if debug_dir is configured."""
        if self._debug_dir is None:
            return

        debug_dir = self._debug_dir / source_id / run_id / backend.name
        config = DebugConfig(
            output_dir=debug_dir,
            save_raw_output=True,
            save_page_images=True,
        )
        assets = backend.export_debug_assets(result, config)
        for name, path in assets.items():
            result.debug_assets[name] = path
