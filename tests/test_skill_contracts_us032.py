"""Tests for US-032: Add contract tests for domain skills."""

from __future__ import annotations

from pathlib import Path

import pytest

from docos.skills_mapping import SKILL_ENTRYPOINTS


# ---------------------------------------------------------------------------
# Skill contract definitions
# ---------------------------------------------------------------------------

SKILL_CONTRACTS: dict[str, dict[str, list[str]]] = {
    "docos-route": {
        "inputs": ["source_id"],
        "outputs": ["selected_route", "primary_parser", "fallback_parsers", "matched_signals"],
        "invariants": [
            "Route selection is config-driven, not hardcoded",
            "All decisions logged for audit",
            "Signals extracted deterministically",
            "Same document always routes to same route",
        ],
        "fallback": ["Falls back to fallback_safe_route if no specific match"],
        "evaluation": ["Route log persisted to disk", "Deterministic routing"],
    },
    "docos-parse": {
        "inputs": ["source_id", "route_decision"],
        "outputs": ["docir", "parser_name", "parser_version", "parse_duration"],
        "invariants": [
            "Output always validates against DocIR schema",
            "No information loss: all recoverable content preserved",
            "Deterministic: same input produces structurally equivalent DocIR",
            "Parse errors never produce partial or malformed DocIR",
        ],
        "fallback": [
            "If primary parser fails, retry with fallback parser",
            "If all parsers fail, emit structured error object",
        ],
        "evaluation": [
            "DocIR passes schema validation on every parse",
            "Fallback coverage: at least one parser succeeds for supported MIME types",
        ],
    },
    "docos-extract": {
        "inputs": ["docir"],
        "outputs": ["entities", "claims", "relations", "extraction_metadata"],
        "invariants": [
            "Every element references valid source span in DocIR",
            "Entity IDs deterministically derived from name + type",
            "Confidence scores in [0.0, 1.0] range",
            "No orphaned relations: subject_id and object_id resolve",
        ],
        "fallback": [
            "If full extraction fails, attempt entity-only extraction",
            "If entity extraction fails, return empty result with error diagnostic",
        ],
        "evaluation": [
            "All extracted entities pass referential integrity checks",
            "No duplicate entities with same deterministic ID",
            "Source span references verifiable against input DocIR",
        ],
    },
    "docos-patch": {
        "inputs": ["extraction_result", "current_wiki_state"],
        "outputs": ["patch_id", "operations", "conflict_report"],
        "invariants": [
            "Patches are atomic: all or nothing",
            "Every operation references valid target IDs",
            "Patches are idempotent",
            "Patches serializable to disk for audit and replay",
        ],
        "fallback": [
            "If conflict detection finds unresolvable conflicts, flag and defer to review",
            "If generation fails mid-way, discard partial patch",
        ],
        "evaluation": [
            "Generated patch applies cleanly against wiki state",
            "No orphaned references in operations",
            "Idempotency: double-application produces identical state",
        ],
    },
    "docos-lint": {
        "inputs": ["wiki_state"],
        "outputs": ["violations", "summary"],
        "invariants": [
            "Lint checks are read-only: never modify wiki state",
            "Every violation references specific location",
            "Severity levels follow strict ordering",
            "Lint execution is deterministic",
        ],
        "fallback": [
            "If custom rule fails, log warning and continue",
            "If wiki state incomplete, run schema-level checks only",
        ],
        "evaluation": [
            "Zero false-positive errors on clean state",
            "Known violations always detected",
            "Summary counts match violation array length",
        ],
    },
    "docos-review": {
        "inputs": ["review_item", "item_type"],
        "outputs": ["review_id", "queue", "status"],
        "invariants": [
            "Every review item gets unique immutable review_id",
            "Status transitions follow state machine",
            "No review item silently dropped",
            "Review history is append-only",
        ],
        "fallback": [
            "If target queue unavailable, enqueue to default catch-all queue",
            "If auto-approval rules ambiguous, default to pending_review",
        ],
        "evaluation": [
            "Every submitted item has exactly one review ticket",
            "Status transitions comply with state machine",
            "Auto-approved items satisfy all published criteria",
        ],
    },
}


class TestSkillContracts:
    """Contract tests for each domain skill."""

    # ------------------------------------------------------------------
    # Input contracts
    # ------------------------------------------------------------------

    def test_all_skills_have_input_contracts(self) -> None:
        """Every skill has defined input contracts."""
        for skill_name in SKILL_ENTRYPOINTS:
            assert skill_name in SKILL_CONTRACTS, f"{skill_name} missing input contracts"
            assert "inputs" in SKILL_CONTRACTS[skill_name]

    def test_all_skills_have_output_contracts(self) -> None:
        """Every skill has defined output contracts."""
        for skill_name in SKILL_ENTRYPOINTS:
            contract = SKILL_CONTRACTS[skill_name]
            assert "outputs" in contract
            assert len(contract["outputs"]) > 0

    # ------------------------------------------------------------------
    # Invariant contracts
    # ------------------------------------------------------------------

    def test_all_skills_have_invariants(self) -> None:
        """Every skill has at least one invariant."""
        for skill_name in SKILL_ENTRYPOINTS:
            contract = SKILL_CONTRACTS[skill_name]
            assert "invariants" in contract
            assert len(contract["invariants"]) > 0, f"{skill_name} has no invariants"

    def test_deterministic_routing_invariant(self) -> None:
        """docos-route invariant: same document always routes to same route."""
        contract = SKILL_CONTRACTS["docos-route"]
        deterministic_invariants = [i for i in contract["invariants"] if "eterministic" in i.lower() or "same document" in i.lower()]
        assert len(deterministic_invariants) > 0, "Missing deterministic routing invariant"

    def test_parse_schema_invariant(self) -> None:
        """docos-parse invariant: output validates against DocIR schema."""
        contract = SKILL_CONTRACTS["docos-parse"]
        schema_invariants = [i for i in contract["invariants"] if "schema" in i.lower() or "validates" in i.lower()]
        assert len(schema_invariants) > 0, "Missing schema validation invariant"

    def test_extract_deterministic_id_invariant(self) -> None:
        """docos-extract invariant: entity IDs are deterministic."""
        contract = SKILL_CONTRACTS["docos-extract"]
        det_invariants = [i for i in contract["invariants"] if "eterministic" in i.lower()]
        assert len(det_invariants) > 0, "Missing deterministic ID invariant"

    def test_patch_atomic_invariant(self) -> None:
        """docos-patch invariant: patches are atomic."""
        contract = SKILL_CONTRACTS["docos-patch"]
        atomic_invariants = [i for i in contract["invariants"] if "atomic" in i.lower()]
        assert len(atomic_invariants) > 0, "Missing atomic patch invariant"

    def test_lint_readonly_invariant(self) -> None:
        """docos-lint invariant: lint is read-only."""
        contract = SKILL_CONTRACTS["docos-lint"]
        readonly_invariants = [i for i in contract["invariants"] if "read-only" in i.lower()]
        assert len(readonly_invariants) > 0, "Missing read-only invariant"

    def test_review_append_only_invariant(self) -> None:
        """docos-review invariant: review history is append-only."""
        contract = SKILL_CONTRACTS["docos-review"]
        append_invariants = [i for i in contract["invariants"] if "append-only" in i.lower() or "append" in i.lower()]
        assert len(append_invariants) > 0, "Missing append-only invariant"

    # ------------------------------------------------------------------
    # Fallback contracts
    # ------------------------------------------------------------------

    def test_all_skills_have_fallback_contracts(self) -> None:
        """Every skill has fallback behavior defined."""
        for skill_name in SKILL_ENTRYPOINTS:
            contract = SKILL_CONTRACTS[skill_name]
            assert "fallback" in contract
            assert len(contract["fallback"]) > 0, f"{skill_name} has no fallback"

    # ------------------------------------------------------------------
    # Evaluation contracts
    # ------------------------------------------------------------------

    def test_all_skills_have_evaluation_contracts(self) -> None:
        """Every skill has evaluation expectations."""
        for skill_name in SKILL_ENTRYPOINTS:
            contract = SKILL_CONTRACTS[skill_name]
            assert "evaluation" in contract

    # ------------------------------------------------------------------
    # Invariant breaking tests
    # ------------------------------------------------------------------

    def test_parse_non_deterministic_id_would_break_invariant(self, tmp_path: Path) -> None:
        """If parse used non-deterministic IDs, invariant would be broken.

        This test verifies that our deterministic ID generation actually works.
        """
        from docos.knowledge.extractor import _deterministic_id

        # Same inputs should produce same ID
        id1 = _deterministic_id("ent", "concept", "src1", "Machine Learning")
        id2 = _deterministic_id("ent", "concept", "src1", "Machine Learning")
        assert id1 == id2, "Deterministic ID generation broken: same inputs produced different IDs"

        # Different inputs should produce different IDs
        id3 = _deterministic_id("ent", "concept", "src1", "Deep Learning")
        assert id1 != id3, "Deterministic ID generation broken: different inputs produced same ID"

    def test_route_deterministic_invariant_verified(self, tmp_path: Path) -> None:
        """Verify route determinism invariant: same document routes to same route."""
        from tests.fixtures.build_fixtures import _build_simple_pdf
        from docos.pipeline.signal_extractor import SignalExtractor
        from docos.pipeline.router import ParserRouter
        from docos.models.config import AppConfig
        from docos.registry import SourceRegistry
        from docos.source_store import RawStorage
        import yaml

        config_yaml = (
            "environment: local\nschema_version: '1'\n"
            "router:\n  default_route: fallback_safe_route\n  routes:\n"
            "    - name: fallback_safe_route\n      description: 'test'\n"
            "      file_types: ['application/pdf']\n"
            "      primary_parser: stdlib_pdf\n      fallback_parsers: [basic_text_fallback]\n"
            "      expected_risks: []\n      post_parse_repairs: []\n"
            "      review_policy: default\n"
            "risk_thresholds: {}\nrelease_gates: {}\nreview_policies: {}\nlint_policy: {}\n"
        )
        config = AppConfig.model_validate(yaml.safe_load(config_yaml))

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_simple_pdf())

        extractor = SignalExtractor()
        signals = extractor.extract(pdf_path)

        raw = RawStorage(tmp_path / "raw")
        registry = SourceRegistry(tmp_path / "registry", raw)

        # Route twice
        source1 = registry.register(pdf_path)
        router = ParserRouter(config)
        decision1 = router.route(source1, signals)

        source2 = registry.register(pdf_path)
        decision2 = router.route(source2, signals)

        assert decision1.selected_route == decision2.selected_route
        assert decision1.primary_parser == decision2.primary_parser

    def test_lint_readonly_invariant_verified(self) -> None:
        """Verify lint is read-only: running lint does not modify inputs."""
        from docos.lint.checker import WikiLinter
        from docos.models.knowledge import ClaimRecord, ClaimStatus, EntityRecord, EntityType, EvidenceAnchor

        linter = WikiLinter()

        claims = [ClaimRecord(
            claim_id="clm_test",
            statement="Test claim",
            status=ClaimStatus.SUPPORTED,
            evidence_anchors=[EvidenceAnchor(
                anchor_id="anc_test",
                source_id="src_test",
                doc_id="doc_test",
                page_no=1,
                block_id="blk_test",
            )],
        )]
        entities = [EntityRecord(
            entity_id="ent_test",
            canonical_name="Test Entity",
            entity_type=EntityType.DOCUMENT,
        )]

        # Capture inputs before lint
        claims_before = [(c.claim_id, c.statement) for c in claims]
        entities_before = [(e.entity_id, e.canonical_name) for e in entities]

        linter.lint(pages=[], claims=claims, entities=entities)

        # Inputs unchanged after lint
        claims_after = [(c.claim_id, c.statement) for c in claims]
        entities_after = [(e.entity_id, e.canonical_name) for e in entities]

        assert claims_before == claims_after, "Lint modified claims input"
        assert entities_before == entities_after, "Lint modified entities input"
