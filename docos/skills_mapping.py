"""Runtime entrypoints mapping for domain skills.

Maps each DocOS domain skill to its real CLI entrypoint so that skills
represent executable system capabilities.
"""

from __future__ import annotations

from pathlib import Path

# Mapping of skill name → CLI command
# Each skill maps to a real runtime entrypoint that can be invoked.
SKILL_ENTRYPOINTS: dict[str, dict[str, str]] = {
    "docos-route": {
        "cli_command": "docos route <source_id>",
        "description": "Route a document to the optimal parsing pipeline based on extracted signals",
        "module": "docos.cli.main",
        "function": "route",
    },
    "docos-parse": {
        "cli_command": "docos parse <source_id>",
        "description": "Parse a raw document into canonical DocIR using route-selected parser",
        "module": "docos.cli.main",
        "function": "parse",
    },
    "docos-extract": {
        "cli_command": "docos extract <source_id>",
        "description": "Extract entities, claims, and relations from DocIR",
        "module": "docos.cli.main",
        "function": "extract",
    },
    "docos-patch": {
        "cli_command": "docos compile <source_id>",
        "description": "Compile wiki pages and generate patches for changes",
        "module": "docos.cli.main",
        "function": "compile_cmd",
    },
    "docos-lint": {
        "cli_command": "docos lint [--run-id <run_id>]",
        "description": "Run lint checks on wiki state",
        "module": "docos.cli.main",
        "function": "lint",
    },
    "docos-review": {
        "cli_command": "docos review [list|approve|reject]",
        "description": "Manage review queue for high-risk items",
        "module": "docos.cli.main",
        "function": "review",
    },
}

# Path to the skills mapping file
SKILLS_MAPPING_PATH = Path(__file__).parent.parent / ".agents" / "skills" / "skills_entrypoints.json"


def get_skill_entrypoint(skill_name: str) -> dict[str, str] | None:
    """Get the runtime entrypoint for a skill."""
    return SKILL_ENTRYPOINTS.get(skill_name)


def list_skill_entrypoints() -> dict[str, dict[str, str]]:
    """List all skill-to-entrypoint mappings."""
    return dict(SKILL_ENTRYPOINTS)
