"""Tests for US-007: route command wired to real sources and signals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docos.models.config import AppConfig
from docos.models.source import SourceRecord
from docos.pipeline.router import ParserRouter
from docos.pipeline.signal_extractor import SignalExtractor, signals_to_dict
from docos.registry import SourceRegistry
from docos.source_store import RawStorage


def _write_minimal_pdf(path: Path) -> Path:
    """Write a minimal valid PDF."""
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n0\n%%EOF"
    )
    path.write_bytes(pdf_content)
    return path


def _make_config() -> AppConfig:
    """Load the router config."""
    config_path = Path("configs/router.yaml")
    with open(config_path) as f:
        return AppConfig.model_validate(yaml.safe_load(f))


class TestRouteRealSource:
    def test_route_uses_stored_source_record(self, tmp_path: Path) -> None:
        """Route command loads the real source record from registry."""
        raw = RawStorage(tmp_path / "raw")
        registry = SourceRegistry(tmp_path / "registry", raw)

        pdf_path = _write_minimal_pdf(tmp_path / "test.pdf")
        source = registry.register(source_file=pdf_path)
        assert source is not None

        # Now route using the stored source
        loaded = registry.get(source.source_id)
        assert loaded is not None

        config = _make_config()
        extractor = SignalExtractor()
        signals = extractor.extract(Path(loaded.raw_storage_path or loaded.file_name))
        router = ParserRouter(config, log_dir=tmp_path / "route_logs")
        decision = router.route(loaded, signals)

        assert decision.selected_route != ""
        assert decision.primary_parser != ""

    def test_route_output_includes_signals(self, tmp_path: Path) -> None:
        """Route output includes extracted signal values."""
        raw = RawStorage(tmp_path / "raw")
        registry = SourceRegistry(tmp_path / "registry", raw)

        pdf_path = _write_minimal_pdf(tmp_path / "test.pdf")
        source = registry.register(source_file=pdf_path)

        config = _make_config()
        extractor = SignalExtractor()
        signals = extractor.extract(Path(source.raw_storage_path or source.file_name))

        sig_dict = signals_to_dict(signals)
        assert "file_type" in sig_dict
        assert sig_dict["file_type"] == "application/pdf"
        assert "page_count" in sig_dict

    def test_route_log_written_to_disk(self, tmp_path: Path) -> None:
        """A route log entry is written to disk for each route decision."""
        raw = RawStorage(tmp_path / "raw")
        registry = SourceRegistry(tmp_path / "registry", raw)

        pdf_path = _write_minimal_pdf(tmp_path / "test.pdf")
        source = registry.register(source_file=pdf_path)

        config = _make_config()
        extractor = SignalExtractor()
        signals = extractor.extract(Path(source.raw_storage_path or source.file_name))

        log_dir = tmp_path / "route_logs"
        router = ParserRouter(config, log_dir=log_dir)
        router.route(source, signals)

        # Verify log file was written
        log_path = log_dir / f"route_{source.source_id}.json"
        assert log_path.exists()
        log_data = json.loads(log_path.read_text())
        assert log_data["source_id"] == source.source_id
        assert "selected_route" in log_data
        assert "primary_parser" in log_data

    def test_route_missing_source_returns_error(self, tmp_path: Path) -> None:
        """Routing a non-existent source returns a structured error."""
        raw = RawStorage(tmp_path / "raw")
        registry = SourceRegistry(tmp_path / "registry", raw)
        result = registry.get("src_nonexistent")
        assert result is None

    def test_route_output_includes_all_fields(self, tmp_path: Path) -> None:
        """Route output includes selected route, primary parser, fallback parsers, and signals."""
        raw = RawStorage(tmp_path / "raw")
        registry = SourceRegistry(tmp_path / "registry", raw)

        pdf_path = _write_minimal_pdf(tmp_path / "test.pdf")
        source = registry.register(source_file=pdf_path)

        config = _make_config()
        extractor = SignalExtractor()
        signals = extractor.extract(Path(source.raw_storage_path or source.file_name))
        router = ParserRouter(config, log_dir=tmp_path / "logs")
        decision = router.route(source, signals)

        output = {
            "selected_route": decision.selected_route,
            "primary_parser": decision.primary_parser,
            "fallback_parsers": decision.fallback_parsers,
            "review_policy": decision.review_policy,
            "signals": signals_to_dict(signals),
        }
        # All fields present and non-empty
        assert output["selected_route"]
        assert output["primary_parser"]
        assert isinstance(output["fallback_parsers"], list)
        assert output["review_policy"]
        assert isinstance(output["signals"], dict)
