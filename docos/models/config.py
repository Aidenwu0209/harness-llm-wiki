"""External configuration contracts for the Document Parsing Knowledge OS.

All system behavior that could otherwise be hardcoded in prompts is
defined here as versioned, environment-specific configuration.

Config loading priority: CLI flag → env var → config file → defaults.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

Environment = Literal["local", "dev", "staging", "prod"]


# ---------------------------------------------------------------------------
# Parser route configuration
# ---------------------------------------------------------------------------

class ParserRoute(BaseModel):
    """A single parser route definition."""

    name: str = Field(description="Route identifier, e.g. fast_text_route")
    description: str = ""

    # When to select this route
    file_types: list[str] = Field(default_factory=list, description="e.g. ['application/pdf']")
    max_pages: int | None = Field(default=None, description="Max pages for this route")
    requires_ocr: bool | None = Field(default=None, description="None = don't care")
    table_formula_heavy: bool | None = None
    image_heavy: bool | None = None
    dual_column: bool | None = None

    # Parser plan
    primary_parser: str
    fallback_parsers: list[str] = Field(default_factory=list)

    # Expected risks
    expected_risks: list[str] = Field(default_factory=list)

    # Post-parse repairs to apply
    post_parse_repairs: list[str] = Field(default_factory=list)

    # Review policy for this route
    review_policy: str = Field(default="default", description="Name of review policy to apply")


class RouterConfig(BaseModel):
    """Full router configuration."""

    routes: list[ParserRoute] = Field(default_factory=list)
    default_route: str = "fallback_safe_route"

    def get_route(self, name: str) -> ParserRoute | None:
        for r in self.routes:
            if r.name == name:
                return r
        return None


# ---------------------------------------------------------------------------
# Risk thresholds
# ---------------------------------------------------------------------------

class RiskThresholds(BaseModel):
    """Risk scoring thresholds — environment-specific."""

    # Patch risk
    high_risk_score: float = Field(default=0.7, ge=0.0, le=1.0)
    medium_risk_score: float = Field(default=0.4, ge=0.0, le=1.0)

    # Blast radius
    high_blast_pages: int = Field(default=5, ge=0)
    high_blast_claims: int = Field(default=10, ge=0)
    high_blast_links: int = Field(default=15, ge=0)

    # Auto-merge gate
    auto_merge_max_risk: float = Field(default=0.3, ge=0.0, le=1.0)
    auto_merge_max_pages: int = Field(default=3, ge=0)


# ---------------------------------------------------------------------------
# Release gates
# ---------------------------------------------------------------------------

class ReleaseGates(BaseModel):
    """Release gate configuration — what blocks an auto-merge."""

    block_on_p0_lint: bool = True
    block_on_p1_lint: bool = True
    block_on_unsupported_claim_increase: bool = True
    block_on_missing_harness: bool = True
    block_on_regression_exceeded: bool = True
    block_on_fallback_low_confidence: bool = True

    # Fallback confidence threshold
    fallback_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    # Regression tolerance
    regression_max_claim_change_pct: float = Field(default=10.0, ge=0.0)
    regression_max_link_break_count: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Review policies
# ---------------------------------------------------------------------------

class ReviewPolicy(BaseModel):
    """A named review policy."""

    name: str
    description: str = ""

    # What triggers review
    require_review_on_fallback: bool = True
    require_review_on_high_risk: bool = True
    require_review_on_high_blast: bool = True
    require_review_on_conflict: bool = True
    require_review_on_entity_merge: bool = True

    # Reviewer assignment
    auto_assign_reviewer: bool = False
    min_reviewers: int = Field(default=1, ge=1)


class ReviewPolicies(BaseModel):
    """Collection of review policies."""

    policies: list[ReviewPolicy] = Field(default_factory=list)
    default_policy: str = "default"

    def get_policy(self, name: str) -> ReviewPolicy | None:
        for p in self.policies:
            if p.name == name:
                return p
        # Fall back to default
        for p in self.policies:
            if p.name == self.default_policy:
                return p
        return None


# ---------------------------------------------------------------------------
# Lint severity policy
# ---------------------------------------------------------------------------

class LintPolicy(BaseModel):
    """Lint severity classification rules."""

    p0_blocks_merge: bool = Field(default=True, description="P0 blocks auto-merge")
    p1_blocks_merge: bool = Field(default=True, description="P1 blocks auto-merge")


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    """Top-level application configuration.

    This is the single entry point for all externalized config.
    Loaded from configs/ directory, with environment-specific overrides.
    """

    environment: Environment = "local"
    schema_version: str = "1"

    # Sub-configs
    router: RouterConfig = Field(default_factory=RouterConfig)
    risk_thresholds: RiskThresholds = Field(default_factory=RiskThresholds)
    release_gates: ReleaseGates = Field(default_factory=ReleaseGates)
    review_policies: ReviewPolicies = Field(default_factory=ReviewPolicies)
    lint_policy: LintPolicy = Field(default_factory=LintPolicy)
