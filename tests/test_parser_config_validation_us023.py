"""Tests for US-023: Fail fast on parser config validation during run and route."""

from __future__ import annotations

from pathlib import Path

import yaml

from docos.pipeline.runner import PipelineRunner


def _make_config_with_parsers(tmp_path: Path, primary: str, fallbacks: list[str] | None = None) -> Path:
    """Create a test router config with specific parser names."""
    config_data = {
        "router": {
            "routes": [
                {
                    "name": "test_route",
                    "file_types": ["application/pdf"],
                    "primary_parser": primary,
                    "fallback_parsers": fallbacks or [],
                }
            ],
            "default_route": "test_route",
        },
    }
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "router.yaml"
    config_path.write_text(yaml.dump(config_data))
    return config_path


class TestParserConfigValidation:
    """US-023: Parser config validation fails fast on unresolved parsers."""

    def test_validate_config_returns_empty_for_valid(self, tmp_path: Path) -> None:
        """validate_config returns empty list when all parsers are registered."""
        config_path = _make_config_with_parsers(tmp_path, "stdlib_pdf", ["basic_text_fallback"])
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        unresolved = runner.validate_config()
        assert unresolved == []

    def test_validate_config_detects_unresolved_primary(self, tmp_path: Path) -> None:
        """validate_config lists unresolved primary parser."""
        config_path = _make_config_with_parsers(tmp_path, "nonexistent_parser")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        unresolved = runner.validate_config()
        assert "nonexistent_parser" in unresolved

    def test_validate_config_detects_unresolved_fallback(self, tmp_path: Path) -> None:
        """validate_config lists unresolved fallback parser."""
        config_path = _make_config_with_parsers(tmp_path, "stdlib_pdf", ["missing_fallback"])
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        unresolved = runner.validate_config()
        assert "missing_fallback" in unresolved

    def test_validate_config_detects_multiple_unresolved(self, tmp_path: Path) -> None:
        """validate_config lists all unresolved parsers."""
        config_path = _make_config_with_parsers(tmp_path, "bad1", ["bad2", "bad3"])
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)
        unresolved = runner.validate_config()
        assert "bad1" in unresolved
        assert "bad2" in unresolved
        assert "bad3" in unresolved

    def test_run_fails_fast_on_unresolved_config(self, tmp_path: Path) -> None:
        """PipelineRunner.run raises ValueError for unresolved parser config."""
        config_path = _make_config_with_parsers(tmp_path, "nonexistent")
        runner = PipelineRunner(base_dir=tmp_path, config_path=config_path)

        # Create a dummy file to pass path validation
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")

        result = runner.run(file_path=test_file)
        assert result.status.value == "failed"
        assert "Unresolved parsers" in (result.error_detail or "")
