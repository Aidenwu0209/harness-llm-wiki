"""Tests for US-031: Add runtime entrypoints for domain skills."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.skills_mapping import (
    SKILL_ENTRYPOINTS,
    SKILLS_MAPPING_PATH,
    get_skill_entrypoint,
    list_skill_entrypoints,
)


class TestSkillEntrypoints:
    """Test that each domain skill maps to a real runtime entrypoint."""

    def test_all_skills_have_entrypoints(self) -> None:
        """Each domain skill maps to a runtime entrypoint."""
        expected_skills = [
            "docos-route",
            "docos-parse",
            "docos-extract",
            "docos-patch",
            "docos-lint",
            "docos-review",
        ]
        for skill_name in expected_skills:
            entry = get_skill_entrypoint(skill_name)
            assert entry is not None, f"Skill '{skill_name}' has no entrypoint"
            assert "cli_command" in entry
            assert "module" in entry
            assert "function" in entry

    def test_entrypoint_modules_exist(self) -> None:
        """Each entrypoint references an importable module."""
        import importlib

        for skill_name, entry in SKILL_ENTRYPOINTS.items():
            module_name = entry["module"]
            try:
                mod = importlib.import_module(module_name)
            except ImportError:
                pytest.fail(f"Skill '{skill_name}' module '{module_name}' not importable")
            assert hasattr(mod, entry["function"]), (
                f"Skill '{skill_name}' function '{entry['function']}' not found in {module_name}"
            )

    def test_entrypoint_cli_commands_are_click_commands(self) -> None:
        """Each CLI entrypoint is a registered Click command."""
        from docos.cli.main import cli

        cli_commands = {cmd.name for cmd in cli.commands.values() if cmd.name}
        # Also check subgroups (like review)
        for cmd in cli.commands.values():
            if hasattr(cmd, "commands"):
                for subcmd in cmd.commands.values():
                    cli_commands.add(subcmd.name)

        for skill_name, entry in SKILL_ENTRYPOINTS.items():
            func_name = entry["function"]
            # Map function names to CLI command names
            cmd_name = func_name.replace("_cmd", "").replace("_", "-")
            # Special cases
            name_map = {
                "route": "route",
                "parse": "parse",
                "extract": "extract",
                "compile_cmd": "compile",
                "lint": "lint",
                "review": "review",
            }
            expected_cmd = name_map.get(func_name, cmd_name)
            assert expected_cmd in cli_commands, (
                f"Skill '{skill_name}': CLI command '{expected_cmd}' not registered. "
                f"Available: {cli_commands}"
            )

    def test_skills_mapping_file_exists(self) -> None:
        """The skills-to-entrypoints mapping file exists in the repo."""
        assert SKILLS_MAPPING_PATH.exists(), (
            f"Skills mapping file not found at {SKILLS_MAPPING_PATH}"
        )

    def test_skills_mapping_file_valid_json(self) -> None:
        """The mapping file is valid JSON with expected structure."""
        data = json.loads(SKILLS_MAPPING_PATH.read_text())
        assert isinstance(data, dict)
        for skill_name, entry in data.items():
            assert "cli_command" in entry, f"{skill_name}: missing cli_command"
            assert "module" in entry, f"{skill_name}: missing module"
            assert "function" in entry, f"{skill_name}: missing function"

    def test_skills_mapping_file_matches_code(self) -> None:
        """The JSON mapping file matches the Python code mapping."""
        file_data = json.loads(SKILLS_MAPPING_PATH.read_text())
        for skill_name, entry in SKILL_ENTRYPOINTS.items():
            assert skill_name in file_data, f"Skill '{skill_name}' missing from JSON file"
            assert file_data[skill_name]["module"] == entry["module"]
            assert file_data[skill_name]["function"] == entry["function"]

    def test_list_skill_entrypoints_returns_all(self) -> None:
        """list_skill_entrypoints() returns all skills."""
        mapping = list_skill_entrypoints()
        assert len(mapping) >= 6
        assert "docos-route" in mapping
        assert "docos-parse" in mapping
        assert "docos-extract" in mapping
        assert "docos-patch" in mapping
        assert "docos-lint" in mapping
        assert "docos-review" in mapping

    def test_get_skill_entrypoint_unknown_returns_none(self) -> None:
        """get_skill_entrypoint returns None for unknown skills."""
        assert get_skill_entrypoint("nonexistent-skill") is None
