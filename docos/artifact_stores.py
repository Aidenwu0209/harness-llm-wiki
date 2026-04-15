"""Artifact Stores — persist patch, report, and wiki state artifacts.

Each store follows the same pattern: save a typed artifact under a key
(run_id or patch_id) and allow retrieval after process restart.

Storage layout::

    patch_store/<patch_id>.json
    report_store/<run_id>.json
    wiki_store/<page_path_hash>.json
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from docos.harness.runner import HarnessReport
from docos.models.patch import Patch


class _JsonArtifactStore:
    """Generic JSON-backed artifact store."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)

    def _artifact_path(self, key: str) -> Path:
        return self._base / f"{key}.json"

    def _save_json(self, key: str, data: dict[str, Any]) -> Path:
        path = self._artifact_path(key)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return path

    def _load_json(self, key: str) -> dict[str, Any] | None:
        path = self._artifact_path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    def exists(self, key: str) -> bool:
        return self._artifact_path(key).exists()


# ---------------------------------------------------------------------------
# Patch Store
# ---------------------------------------------------------------------------


class PatchStore(_JsonArtifactStore):
    """Persist and retrieve Patch artifacts."""

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)

    def save(self, patch: Patch) -> Path:
        """Persist a patch artifact. Key is patch_id."""
        data = json.loads(patch.model_dump_json())
        return self._save_json(patch.patch_id, data)

    def get(self, patch_id: str) -> Patch | None:
        """Load a patch by patch_id."""
        data = self._load_json(patch_id)
        if data is None:
            return None
        return Patch.model_validate(data)

    def save_patch_set(self, patch_set: Any) -> Path:
        """Persist a PatchSet artifact. Key is run_id."""
        from docos.models.patch_set import PatchSet
        data = json.loads(patch_set.model_dump_json())
        key = f"patchset-{patch_set.run_id}"
        return self._save_json(key, data)

    def get_patch_set(self, run_id: str) -> Any:
        """Load a PatchSet by run_id with all linked patches intact."""
        from docos.models.patch_set import PatchSet
        key = f"patchset-{run_id}"
        data = self._load_json(key)
        if data is None:
            return None
        return PatchSet.model_validate(data)


# ---------------------------------------------------------------------------
# Report Store
# ---------------------------------------------------------------------------


class ReportStore(_JsonArtifactStore):
    """Persist and retrieve HarnessReport artifacts."""

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)

    def save(self, report: HarnessReport) -> Path:
        """Persist a harness report. Key is run_id."""
        data = _report_to_dict(report)
        return self._save_json(report.run_id, data)

    def get(self, run_id: str) -> HarnessReport | None:
        """Load a report by run_id."""
        data = self._load_json(run_id)
        if data is None:
            return None
        return _dict_to_report(data)


# ---------------------------------------------------------------------------
# Wiki State Store
# ---------------------------------------------------------------------------

class WikiPageState:
    """Compiled wiki page state for persistence."""

    def __init__(
        self,
        page_path: str,
        run_id: str,
        frontmatter: dict[str, Any],
        body: str,
        compiled_at: datetime | None = None,
    ) -> None:
        self.page_path = page_path
        self.run_id = run_id
        self.frontmatter = frontmatter
        self.body = body
        self.compiled_at = compiled_at or datetime.now()


class WikiStore(_JsonArtifactStore):
    """Persist and retrieve wiki page state artifacts."""

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)

    def list_page_paths(self) -> list[str]:
        """List all stored wiki page paths."""
        paths: list[str] = []
        for json_file in self._base.glob("*.json"):
            data = self._load_json(json_file.stem)
            if data is not None and "page_path" in data:
                paths.append(data["page_path"])
        return paths

    def save(self, state: WikiPageState) -> Path:
        """Persist wiki page state. Key is page_path (sanitized)."""
        key = _sanitize_key(state.page_path)
        data = {
            "page_path": state.page_path,
            "run_id": state.run_id,
            "frontmatter": state.frontmatter,
            "body": state.body,
            "compiled_at": state.compiled_at.isoformat() if state.compiled_at else None,
        }
        return self._save_json(key, data)

    def get(self, page_path: str) -> WikiPageState | None:
        """Load wiki page state by page path."""
        key = _sanitize_key(page_path)
        data = self._load_json(key)
        if data is None:
            return None
        return WikiPageState(
            page_path=data["page_path"],
            run_id=data["run_id"],
            frontmatter=data["frontmatter"],
            body=data["body"],
            compiled_at=datetime.fromisoformat(data["compiled_at"]) if data.get("compiled_at") else None,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_key(page_path: str) -> str:
    """Convert a page path to a safe filename key."""
    return page_path.replace("/", "_").replace(" ", "-").strip("_-")


def _report_to_dict(report: HarnessReport) -> dict[str, Any]:
    """Convert HarnessReport to a JSON-serializable dict."""
    return {
        "run_id": report.run_id,
        "source_id": report.source_id,
        "generated_at": report.generated_at.isoformat(),
        "parse_quality": _section_to_dict(report.parse_quality),
        "knowledge_quality": _section_to_dict(report.knowledge_quality),
        "maintenance_quality": _section_to_dict(report.maintenance_quality),
        "overall_passed": report.overall_passed,
        "release_decision": report.release_decision,
        "release_reasoning": report.release_reasoning,
        "gate_blockers": report.gate_blockers,
    }


def _section_to_dict(section: Any) -> dict[str, Any]:
    return {
        "name": section.name,
        "metrics": section.metrics,
        "passed": section.passed,
        "notes": section.notes,
    }


def _dict_to_report(data: dict[str, Any]) -> HarnessReport:
    """Reconstruct HarnessReport from a dict."""
    report = HarnessReport(
        run_id=data["run_id"],
        source_id=data["source_id"],
        generated_at=datetime.fromisoformat(data["generated_at"]),
    )
    report.parse_quality = _dict_to_section(data["parse_quality"])
    report.knowledge_quality = _dict_to_section(data["knowledge_quality"])
    report.maintenance_quality = _dict_to_section(data["maintenance_quality"])
    report.overall_passed = data["overall_passed"]
    report.release_decision = data["release_decision"]
    report.release_reasoning = data.get("release_reasoning", [])
    report.gate_blockers = data.get("gate_blockers", [])
    return report


def _dict_to_section(data: dict[str, Any]) -> Any:
    from docos.harness.runner import HarnessSection

    section = HarnessSection(name=data["name"])
    section.metrics = data.get("metrics", {})
    section.passed = data["passed"]
    section.notes = data.get("notes", [])
    return section
