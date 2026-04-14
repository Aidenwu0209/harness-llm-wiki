"""Tests for run manifest model and run store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docos.models.run import (
    PIPELINE_STAGES,
    PipelineStage,
    RunManifest,
    RunStatus,
    StageStatus,
)
from docos.run_store import RunNotFoundError, RunStore


# ---------------------------------------------------------------------------
# RunManifest model tests
# ---------------------------------------------------------------------------


class TestRunManifest:
    def test_create_populates_all_stages(self) -> None:
        manifest = RunManifest.create(
            run_id="run_abc123",
            source_id="src_def456",
            source_file_path="/tmp/test.pdf",
            artifact_root="/tmp/artifacts/run_abc123",
        )
        assert manifest.run_id == "run_abc123"
        assert manifest.source_id == "src_def456"
        assert manifest.source_file_path == "/tmp/test.pdf"
        assert manifest.artifact_root == "/tmp/artifacts/run_abc123"
        assert manifest.status == RunStatus.CREATED
        assert len(manifest.stages) == len(PIPELINE_STAGES)
        assert all(s.status == StageStatus.PENDING for s in manifest.stages)

    def test_stage_names_match_pipeline(self) -> None:
        manifest = RunManifest.create(
            run_id="run_x",
            source_id="src_y",
            source_file_path="/tmp/f.pdf",
            artifact_root="/tmp/a",
        )
        stage_names = [s.name for s in manifest.stages]
        assert stage_names == PIPELINE_STAGES

    def test_mark_stage_updates_status(self) -> None:
        manifest = RunManifest.create(
            run_id="run_x",
            source_id="src_y",
            source_file_path="/tmp/f.pdf",
            artifact_root="/tmp/a",
        )
        manifest.mark_stage("ingest", StageStatus.COMPLETED)
        ingest_stage = next(s for s in manifest.stages if s.name == "ingest")
        assert ingest_stage.status == StageStatus.COMPLETED
        assert ingest_stage.completed_at is not None

    def test_mark_stage_running_sets_started_at(self) -> None:
        manifest = RunManifest.create(
            run_id="run_x",
            source_id="src_y",
            source_file_path="/tmp/f.pdf",
            artifact_root="/tmp/a",
        )
        manifest.mark_stage("route", StageStatus.RUNNING)
        route_stage = next(s for s in manifest.stages if s.name == "route")
        assert route_stage.status == StageStatus.RUNNING
        assert route_stage.started_at is not None

    def test_mark_stage_failed_sets_error(self) -> None:
        manifest = RunManifest.create(
            run_id="run_x",
            source_id="src_y",
            source_file_path="/tmp/f.pdf",
            artifact_root="/tmp/a",
        )
        manifest.mark_stage("parse", StageStatus.FAILED, error_detail="timeout")
        parse_stage = next(s for s in manifest.stages if s.name == "parse")
        assert parse_stage.status == StageStatus.FAILED
        assert parse_stage.error_detail == "timeout"
        assert parse_stage.completed_at is not None

    def test_mark_unknown_stage_raises(self) -> None:
        manifest = RunManifest.create(
            run_id="run_x",
            source_id="src_y",
            source_file_path="/tmp/f.pdf",
            artifact_root="/tmp/a",
        )
        with pytest.raises(ValueError, match="Unknown stage"):
            manifest.mark_stage("nonexistent", StageStatus.RUNNING)

    def test_serialization_round_trip(self) -> None:
        manifest = RunManifest.create(
            run_id="run_abc",
            source_id="src_def",
            source_file_path="/tmp/doc.pdf",
            artifact_root="/tmp/art",
        )
        manifest.mark_stage("ingest", StageStatus.COMPLETED)
        data = manifest.model_dump_json()
        restored = RunManifest.model_validate_json(data)
        assert restored.run_id == manifest.run_id
        assert restored.source_id == manifest.source_id
        assert len(restored.stages) == len(manifest.stages)
        for orig, rest in zip(manifest.stages, restored.stages):
            assert orig.name == rest.name
            assert orig.status == rest.status


# ---------------------------------------------------------------------------
# RunStore tests
# ---------------------------------------------------------------------------


class TestRunStore:
    def test_create_persists_manifest(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_abc123",
            source_hash="a" * 64,
            source_file_path="/tmp/test.pdf",
        )
        assert manifest.run_id.startswith("run_")
        assert manifest.source_id == "src_abc123"
        assert manifest.status == RunStatus.CREATED

        # Verify file on disk
        loaded = store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.run_id == manifest.run_id
        assert loaded.source_file_path == "/tmp/test.pdf"

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        assert store.get("run_nonexistent") is None

    def test_list_runs_returns_all(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        store.create(source_id="src_1", source_hash="a" * 64, source_file_path="/tmp/a.pdf")
        store.create(source_id="src_2", source_hash="b" * 64, source_file_path="/tmp/b.pdf")
        runs = store.list_runs()
        assert len(runs) == 2

    def test_update_persists_changes(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_x",
            source_hash="c" * 64,
            source_file_path="/tmp/x.pdf",
        )
        manifest.mark_stage("ingest", StageStatus.COMPLETED)
        manifest.status = RunStatus.RUNNING
        store.update(manifest)

        loaded = store.get(manifest.run_id)
        assert loaded is not None
        assert loaded.status == RunStatus.RUNNING
        ingest_stage = next(s for s in loaded.stages if s.name == "ingest")
        assert ingest_stage.status == StageStatus.COMPLETED

    def test_generate_run_id_is_deterministic(self) -> None:
        from datetime import datetime

        ts = datetime(2025, 1, 1, 12, 0, 0)
        id1 = RunStore.generate_run_id("abc123", ts)
        id2 = RunStore.generate_run_id("abc123", ts)
        assert id1 == id2

    def test_generate_run_id_differs_for_different_inputs(self) -> None:
        from datetime import datetime

        ts = datetime(2025, 1, 1, 12, 0, 0)
        id1 = RunStore.generate_run_id("abc123", ts)
        id2 = RunStore.generate_run_id("def456", ts)
        assert id1 != id2

    def test_manifest_contains_ordered_pipeline_stages(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_y",
            source_hash="d" * 64,
            source_file_path="/tmp/y.pdf",
        )
        stage_names = [s.name for s in manifest.stages]
        assert stage_names == PIPELINE_STAGES

    def test_manifest_artifact_root_default(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_z",
            source_hash="e" * 64,
            source_file_path="/tmp/z.pdf",
        )
        assert manifest.artifact_root == str(tmp_path / "artifacts" / manifest.run_id)

    def test_manifest_artifact_root_override(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        custom_root = "/custom/artifacts"
        manifest = store.create(
            source_id="src_w",
            source_hash="f" * 64,
            source_file_path="/tmp/w.pdf",
            artifact_root=custom_root,
        )
        assert manifest.artifact_root == custom_root

    def test_reload_after_new_process(self, tmp_path: Path) -> None:
        """Simulate process restart by constructing a fresh RunStore on the same dir."""
        store1 = RunStore(tmp_path)
        manifest = store1.create(
            source_id="src_restart",
            source_hash="a" * 64,
            source_file_path="/tmp/restart.pdf",
        )
        run_id = manifest.run_id

        # Simulate new process: create a new RunStore instance
        store2 = RunStore(tmp_path)
        loaded = store2.get(run_id)
        assert loaded is not None
        assert loaded.run_id == run_id
        assert loaded.source_id == "src_restart"
        assert loaded.source_file_path == "/tmp/restart.pdf"
        assert len(loaded.stages) == len(PIPELINE_STAGES)

    def test_get_or_raise_returns_manifest(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        manifest = store.create(
            source_id="src_ok",
            source_hash="b" * 64,
            source_file_path="/tmp/ok.pdf",
        )
        result = store.get_or_raise(manifest.run_id)
        assert result.run_id == manifest.run_id

    def test_get_or_raise_raises_structured_error(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path)
        with pytest.raises(RunNotFoundError) as exc_info:
            store.get_or_raise("run_missing_id")
        err = exc_info.value
        assert err.run_id == "run_missing_id"
        assert "run_missing_id" in str(err)
