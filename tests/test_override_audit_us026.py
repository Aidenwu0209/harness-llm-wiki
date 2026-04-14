"""US-026: Record manual override audit fields.

Verifies that:
- Manual overrides record reviewer identity, override reason, overridden checks, and timestamp
- Override audit data is persisted and visible from report or review inspection output
- Override reason is required (not optional)
- Test manual override creates auditable record
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from docos.lint.checker import (
    LintFinding,
    LintSeverity,
    OverrideAuditRecord,
    ReleaseGate,
)
from docos.models.run import RunManifest
from docos.run_store import RunStore


class TestManualOverrideAudit:
    """Test that manual gate overrides leave audit records."""

    def test_override_records_all_audit_fields(self) -> None:
        """Manual override records reviewer, reason, overridden checks, and timestamp."""
        gate = ReleaseGate()
        record = gate.override(
            reviewer="alice@example.com",
            reason="False positive: ID exists but lint misread the field",
            overridden_checks=["P0 lint: MISSING_ID"],
            original_decision="blocked",
        )
        assert record.reviewer == "alice@example.com"
        assert record.reason == "False positive: ID exists but lint misread the field"
        assert record.overridden_checks == ["P0 lint: MISSING_ID"]
        assert record.timestamp is not None
        assert isinstance(record.timestamp, datetime)
        assert record.original_gate_decision == "blocked"
        assert record.overridden_gate_decision == "override_approved"

    def test_override_reason_is_required(self) -> None:
        """Override reason must not be empty."""
        gate = ReleaseGate()
        try:
            gate.override(
                reviewer="bob@example.com",
                reason="",
                overridden_checks=["P0 lint"],
            )
            msg = "Should have raised ValueError"
            raise AssertionError(msg)
        except ValueError as e:
            assert "required" in str(e).lower()

    def test_override_reason_whitespace_only_is_rejected(self) -> None:
        """Override reason of only whitespace is rejected."""
        gate = ReleaseGate()
        try:
            gate.override(
                reviewer="bob@example.com",
                reason="   ",
                overridden_checks=["P0 lint"],
            )
            msg = "Should have raised ValueError"
            raise AssertionError(msg)
        except ValueError as e:
            assert "required" in str(e).lower()

    def test_override_audit_record_is_dataclass(self) -> None:
        """OverrideAuditRecord is a proper dataclass with all fields."""
        record = OverrideAuditRecord(
            reviewer="carol@example.com",
            reason="Approved after manual review",
            overridden_checks=["P0 lint", "harness"],
            timestamp=datetime(2026, 4, 15, 12, 0, 0),
            original_gate_decision="blocked",
        )
        assert record.reviewer == "carol@example.com"
        assert record.reason == "Approved after manual review"
        assert len(record.overridden_checks) == 2
        assert record.timestamp.year == 2026


class TestOverridePersistedToManifest:
    """Test that override audit fields are persisted to RunManifest."""

    def test_override_saved_to_manifest(self) -> None:
        """Override audit fields are saved in RunManifest and reloadable."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_store = RunStore(base)

            manifest = RunManifest.create(
                run_id="run_override_test",
                source_id="src_001",
                source_file_path="/tmp/test.pdf",
                artifact_root=str(base / "artifacts" / "run_override_test"),
            )

            # Simulate gate block
            manifest.gate_decision = "blocked"
            manifest.gate_blockers = ["P0 lint exists (1 findings)"]
            manifest.review_status = "pending"

            # Apply override
            gate = ReleaseGate()
            record = gate.override(
                reviewer="alice@example.com",
                reason="Approved: false positive on MISSING_ID",
                overridden_checks=["P0 lint: MISSING_ID"],
            )

            manifest.override_reviewer = record.reviewer
            manifest.override_reason = record.reason
            manifest.override_timestamp = record.timestamp
            manifest.overridden_checks = record.overridden_checks
            manifest.gate_decision = "override_approved"
            manifest.review_status = "approved"

            run_store.update(manifest)

            # Reload and verify
            loaded = run_store.get("run_override_test")
            assert loaded is not None
            assert loaded.override_reviewer == "alice@example.com"
            assert loaded.override_reason == "Approved: false positive on MISSING_ID"
            assert loaded.override_timestamp is not None
            assert "P0 lint: MISSING_ID" in loaded.overridden_checks
            assert loaded.gate_decision == "override_approved"
            assert loaded.review_status == "approved"

    def test_override_persists_via_json(self) -> None:
        """Override fields survive JSON serialization round-trip."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_store = RunStore(base)

            manifest = RunManifest.create(
                run_id="run_override_json",
                source_id="src_001",
                source_file_path="/tmp/test.pdf",
                artifact_root=str(base / "artifacts" / "run_override_json"),
            )

            manifest.override_reviewer = "bob@example.com"
            manifest.override_reason = "Emergency release: P0 is a known doc issue"
            manifest.override_timestamp = datetime(2026, 4, 15, 14, 30, 0)
            manifest.overridden_checks = ["P0 lint", "harness"]
            manifest.gate_decision = "override_approved"

            run_store.update(manifest)

            # Read raw JSON
            manifest_path = base / "manifests" / "run_override_json.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert data["override_reviewer"] == "bob@example.com"
            assert data["override_reason"] == "Emergency release: P0 is a known doc issue"
            assert data["override_timestamp"] == "2026-04-15T14:30:00"
            assert data["overridden_checks"] == ["P0 lint", "harness"]

    def test_no_override_fields_are_none_by_default(self) -> None:
        """Override fields are None/empty by default in a new manifest."""
        manifest = RunManifest.create(
            run_id="run_no_override",
            source_id="src_001",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts",
        )
        assert manifest.override_reviewer is None
        assert manifest.override_reason is None
        assert manifest.override_timestamp is None
        assert manifest.overridden_checks == []


class TestOverrideAuditRecordPersistence:
    """Test override records can be stored as separate artifacts."""

    def test_override_record_saved_as_json(self) -> None:
        """Override audit record can be saved as a standalone JSON artifact."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            override_dir = base / "overrides"
            override_dir.mkdir()

            gate = ReleaseGate()
            record = gate.override(
                reviewer="dave@example.com",
                reason="Approved after thorough manual review of the P0 lint finding",
                overridden_checks=["P0 lint: DUPLICATE_ID"],
            )

            # Save as JSON
            override_path = override_dir / "run_override_record.json"
            override_data = {
                "reviewer": record.reviewer,
                "reason": record.reason,
                "overridden_checks": record.overridden_checks,
                "timestamp": record.timestamp.isoformat(),
                "original_gate_decision": record.original_gate_decision,
                "overridden_gate_decision": record.overridden_gate_decision,
            }
            override_path.write_text(
                json.dumps(override_data, indent=2),
                encoding="utf-8",
            )

            # Reload and verify
            loaded_data = json.loads(override_path.read_text(encoding="utf-8"))
            assert loaded_data["reviewer"] == "dave@example.com"
            assert loaded_data["reason"] == "Approved after thorough manual review of the P0 lint finding"
            assert loaded_data["overridden_checks"] == ["P0 lint: DUPLICATE_ID"]
            assert loaded_data["original_gate_decision"] == "blocked"
