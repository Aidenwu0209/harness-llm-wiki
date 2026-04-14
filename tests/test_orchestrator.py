"""Tests for Pipeline Orchestrator (fallback execution)."""

from pathlib import Path

import pytest

from docos.models.docir import Block, BlockType, DocIR, Page
from docos.pipeline.orchestrator import PipelineOrchestrator
from docos.pipeline.parser import ParserBackend, ParserRegistry, ParseResult
from docos.pipeline.router import RouteDecision


# ---------------------------------------------------------------------------
# Test backends
# ---------------------------------------------------------------------------

class FailingParser(ParserBackend):
    @property
    def name(self) -> str:
        return "failing_parser"

    @property
    def version(self) -> str:
        return "1.0.0"

    def capabilities(self) -> set:
        return set()

    def parse(self, file_path: Path) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=False,
            error="Simulated parse failure",
        )

    def normalize(self, result: ParseResult) -> DocIR:
        raise RuntimeError("Should not be called on failure")

    def healthcheck(self):
        from docos.pipeline.parser import HealthStatus
        return HealthStatus(healthy=True, parser_name=self.name)


class WorkingParser(ParserBackend):
    @property
    def name(self) -> str:
        return "working_parser"

    @property
    def version(self) -> str:
        return "2.0.0"

    def capabilities(self) -> set:
        return set()

    def parse(self, file_path: Path) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            pages_parsed=1,
            blocks_extracted=1,
            raw_output={"text": "Hello"},
        )

    def normalize(self, result: ParseResult) -> DocIR:
        block = Block(
            block_id="b1", page_no=1, block_type=BlockType.PARAGRAPH,
            reading_order=0, bbox=(0, 0, 100, 50), text_plain="Hello",
            source_parser=self.name, source_node_id="n1",
        )
        page = Page(page_no=1, width=612, height=792, blocks=["b1"])
        return DocIR(
            doc_id="doc_test", source_id="src_test",
            parser=self.name, parser_version=self.version,
            page_count=1, pages=[page], blocks=[block],
        )

    def healthcheck(self):
        from docos.pipeline.parser import HealthStatus
        return HealthStatus(healthy=True, parser_name=self.name)


class ExceptionParser(ParserBackend):
    """Parser that throws during parse()."""

    @property
    def name(self) -> str:
        return "crash_parser"

    @property
    def version(self) -> str:
        return "0.0.1"

    def capabilities(self) -> set:
        return set()

    def parse(self, file_path: Path) -> ParseResult:
        raise RuntimeError("Unexpected crash!")

    def normalize(self, result: ParseResult) -> DocIR:
        raise RuntimeError("Should not be called")

    def healthcheck(self):
        from docos.pipeline.parser import HealthStatus
        return HealthStatus(healthy=True, parser_name=self.name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> ParserRegistry:
    reg = ParserRegistry()
    reg.register(FailingParser())
    reg.register(WorkingParser())
    reg.register(ExceptionParser())
    return reg


@pytest.fixture
def orchestrator(registry: ParserRegistry, tmp_path: Path) -> PipelineOrchestrator:
    return PipelineOrchestrator(registry, debug_dir=tmp_path / "debug")


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    f = tmp_path / "test.pdf"
    f.write_bytes(b"Test content")
    return f


def make_decision(primary: str, fallbacks: list[str] | None = None) -> RouteDecision:
    return RouteDecision(
        selected_route="test_route",
        primary_parser=primary,
        fallback_parsers=fallbacks or [],
        expected_risks=[],
        post_parse_repairs=[],
        review_policy="default",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPrimarySuccess:
    def test_primary_succeeds(self, orchestrator: PipelineOrchestrator, sample_file: Path) -> None:
        decision = make_decision("working_parser")
        result = orchestrator.execute("run_001", "src_001", sample_file, decision)

        assert result.success is True
        assert result.primary_succeeded is True
        assert result.fallback_used is False
        assert result.final_parser == "working_parser"
        assert result.docir is not None
        assert len(result.attempts) == 1

    def test_docir_populated(self, orchestrator: PipelineOrchestrator, sample_file: Path) -> None:
        decision = make_decision("working_parser")
        result = orchestrator.execute("run_001", "src_001", sample_file, decision)

        assert result.docir is not None
        assert result.docir.parser == "working_parser"
        assert len(result.docir.blocks) == 1


class TestFallbackExecution:
    def test_fallback_on_primary_failure(self, orchestrator: PipelineOrchestrator, sample_file: Path) -> None:
        decision = make_decision("failing_parser", ["working_parser"])
        result = orchestrator.execute("run_002", "src_002", sample_file, decision)

        assert result.success is True
        assert result.primary_succeeded is False
        assert result.fallback_used is True
        assert result.fallback_parser == "working_parser"
        assert result.final_parser == "working_parser"
        assert len(result.attempts) == 2

    def test_fallback_stricter_review(self, orchestrator: PipelineOrchestrator, sample_file: Path) -> None:
        decision = make_decision("failing_parser", ["working_parser"])
        result = orchestrator.execute("run_002", "src_002", sample_file, decision)

        assert result.review_policy_override == "strict"

    def test_primary_failure_reason_recorded(
        self, orchestrator: PipelineOrchestrator, sample_file: Path
    ) -> None:
        decision = make_decision("failing_parser", ["working_parser"])
        result = orchestrator.execute("run_002", "src_002", sample_file, decision)

        assert result.failure_reason == "Simulated parse failure"

    def test_exception_handled_as_failure(
        self, orchestrator: PipelineOrchestrator, sample_file: Path
    ) -> None:
        decision = make_decision("crash_parser", ["working_parser"])
        result = orchestrator.execute("run_003", "src_003", sample_file, decision)

        assert result.success is True
        assert result.fallback_used is True
        assert result.final_parser == "working_parser"


class TestAllFail:
    def test_all_parsers_fail(self, orchestrator: PipelineOrchestrator, sample_file: Path) -> None:
        decision = make_decision("failing_parser", ["failing_parser"])
        result = orchestrator.execute("run_004", "src_004", sample_file, decision)

        assert result.success is False
        assert result.docir is None
        assert result.primary_succeeded is False

    def test_parser_not_in_registry(self, orchestrator: PipelineOrchestrator, sample_file: Path) -> None:
        decision = make_decision("nonexistent_parser")
        result = orchestrator.execute("run_005", "src_005", sample_file, decision)

        assert result.success is False
        assert "not registered" in (result.failure_reason or "") or "not available" in (result.failure_reason or "")


class TestRunResultMetadata:
    def test_timing_recorded(self, orchestrator: PipelineOrchestrator, sample_file: Path) -> None:
        decision = make_decision("working_parser")
        result = orchestrator.execute("run_006", "src_006", sample_file, decision)

        assert result.started_at is not None
        assert result.finished_at is not None
        assert result.total_elapsed_seconds >= 0

    def test_no_override_when_primary_succeeds(
        self, orchestrator: PipelineOrchestrator, sample_file: Path
    ) -> None:
        decision = make_decision("working_parser")
        result = orchestrator.execute("run_007", "src_007", sample_file, decision)

        assert result.review_policy_override is None
