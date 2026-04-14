"""Parser Router — selects the optimal parsing route for each document.

Route selection reads from external config (configs/router.yaml) rather
than hardcoded prompt branches. Every decision is logged with the signals
used, making route selection explainable and debuggable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.models.config import AppConfig, ParserRoute
from docos.models.source import SourceRecord
from docos.pipeline.parser import ParserCapability

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document signals (router input)
# ---------------------------------------------------------------------------

@dataclass
class DocumentSignals:
    """Signals extracted from a document for route selection.

    These are the factual inputs the router uses to choose a route.
    No LLM is involved in signal extraction — these are deterministic
    file-level checks.
    """

    file_type: str = ""
    page_count: int = 0
    is_scanned: bool | None = None
    is_dual_column: bool | None = None
    is_table_heavy: bool | None = None
    is_formula_heavy: bool | None = None
    is_image_heavy: bool | None = None
    language: str = ""
    needs_ocr: bool | None = None
    has_known_failures: bool = False
    target_mode: str = "high_fidelity"  # high_fidelity | high_throughput | low_cost


# ---------------------------------------------------------------------------
# Route decision (router output)
# ---------------------------------------------------------------------------

@dataclass
class RouteDecision:
    """The result of route selection.

    Every field is explicit and logged. No hidden decisions.
    """

    selected_route: str
    primary_parser: str
    fallback_parsers: list[str]
    expected_risks: list[str]
    post_parse_repairs: list[str]
    review_policy: str

    # Why this route was chosen
    matched_signals: dict[str, Any] = field(default_factory=dict)
    decision_reason: str = ""

    # Metadata
    decided_at: datetime = field(default_factory=datetime.now)
    config_version: str = "1"


# ---------------------------------------------------------------------------
# Route log entry
# ---------------------------------------------------------------------------

@dataclass
class RouteLogEntry:
    """A logged route decision for auditing."""

    source_id: str
    decision: RouteDecision
    signals: DocumentSignals

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "selected_route": self.decision.selected_route,
            "primary_parser": self.decision.primary_parser,
            "fallback_parsers": self.decision.fallback_parsers,
            "matched_signals": self.decision.matched_signals,
            "decision_reason": self.decision.decision_reason,
            "decided_at": self.decision.decided_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class ParserRouter:
    """Selects the optimal parsing route based on document signals and config.

    Route selection is entirely config-driven. The router:
    1. Receives document signals.
    2. Matches against configured routes (ordered by specificity).
    3. Falls back to the default route if nothing matches.
    4. Logs every decision for auditability.
    """

    def __init__(self, config: AppConfig, log_dir: Path | None = None) -> None:
        self._config = config
        self._log_dir = log_dir
        self._log_entries: list[RouteLogEntry] = []

    def route(self, source: SourceRecord, signals: DocumentSignals) -> RouteDecision:
        """Select a route for the given document.

        Args:
            source: The source registry record.
            signals: Extracted document signals.

        Returns:
            A RouteDecision with explicit parser plan and review policy.
        """
        best_route = self._match_route(signals)
        assert best_route is not None  # guaranteed by config having at least default route
        decision = self._build_decision(best_route, signals)
        entry = RouteLogEntry(source_id=source.source_id, decision=decision, signals=signals)

        self._log_entries.append(entry)
        self._persist_log(entry)

        logger.info(
            "Route selected for %s: %s → %s (reason: %s)",
            source.source_id,
            decision.selected_route,
            decision.primary_parser,
            decision.decision_reason,
        )

        return decision

    def _match_route(self, signals: DocumentSignals) -> ParserRoute | None:
        """Match signals against configured routes.

        Strategy: iterate all routes, score each by how many criteria match,
        return the highest-scoring route. Tiebreak by route order in config.
        """
        routes = self._config.router.routes
        best_score = -1
        best_route: ParserRoute | None = None

        for route in routes:
            score = self._score_route(route, signals)
            if score > best_score:
                best_score = score
                best_route = route

        if best_route is None or best_score == 0:
            # Fall back to default route
            default_name = self._config.router.default_route
            for route in routes:
                if route.name == default_name:
                    return route
            # Ultimate fallback: first route
            if routes:
                return routes[0]

        return best_route

    def _score_route(self, route: ParserRoute, signals: DocumentSignals) -> int:
        """Score how well a route matches the given signals.

        Hard filters (file type) exclude a route entirely.
        Soft scores accumulate points for matching criteria.
        """
        # Hard filter: file type must match if specified
        if route.file_types and signals.file_type not in route.file_types:
            return 0

        soft_score = 0

        if route.requires_ocr is not None and signals.needs_ocr == route.requires_ocr:
            soft_score += 2  # OCR is a strong signal

        if route.table_formula_heavy is not None and signals.is_table_heavy == route.table_formula_heavy:
            soft_score += 1

        if route.image_heavy is not None and signals.is_image_heavy == route.image_heavy:
            soft_score += 1

        if route.dual_column is not None and signals.is_dual_column == route.dual_column:
            soft_score += 1

        if route.max_pages is not None and signals.page_count <= route.max_pages:
            soft_score += 1

        # Bonus for matching file type (when specified)
        if route.file_types and signals.file_type in route.file_types:
            soft_score += 1

        # Bonus signals: language, scanned state, known failures
        if signals.language == "en":
            soft_score += 0  # Neutral
        if signals.has_known_failures and route.expected_risks:
            soft_score += 1  # Route anticipates risks

        return soft_score

    def _build_decision(self, route: ParserRoute, signals: DocumentSignals) -> RouteDecision:
        """Build a RouteDecision from a matched route and signals."""
        matched: dict[str, Any] = {}
        if signals.is_table_heavy:
            matched["table_formula_heavy"] = True
        if signals.is_dual_column:
            matched["dual_column"] = True
        if signals.needs_ocr:
            matched["needs_ocr"] = True
        if signals.is_scanned:
            matched["is_scanned"] = True
        matched["page_count"] = signals.page_count
        matched["file_type"] = signals.file_type

        reason = f"Matched route '{route.name}'"
        if route.expected_risks:
            reason += f" with risks: {', '.join(route.expected_risks)}"

        return RouteDecision(
            selected_route=route.name,
            primary_parser=route.primary_parser,
            fallback_parsers=route.fallback_parsers,
            expected_risks=route.expected_risks,
            post_parse_repairs=route.post_parse_repairs,
            review_policy=route.review_policy,
            matched_signals=matched,
            decision_reason=reason,
            config_version=self._config.schema_version,
        )

    def _persist_log(self, entry: RouteLogEntry) -> None:
        """Persist route decision to log file."""
        if self._log_dir is None:
            return
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"route_{entry.source_id}.json"
        log_path.write_text(
            json.dumps(entry.to_dict(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def get_log_entries(self) -> list[RouteLogEntry]:
        """Return all logged route decisions."""
        return list(self._log_entries)
