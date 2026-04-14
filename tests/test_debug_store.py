"""Tests for Debug Asset Store."""

import json
from pathlib import Path

import pytest

from docos.debug_store import DebugAssetStore
from docos.pipeline.parser import ParseResult


@pytest.fixture
def store(tmp_path: Path) -> DebugAssetStore:
    return DebugAssetStore(tmp_path / "debug")


@pytest.fixture
def parse_result() -> ParseResult:
    return ParseResult(
        parser_name="test_parser",
        parser_version="1.0.0",
        success=True,
        raw_output={"text": "Hello", "pages": 2},
        pages_parsed=2,
        blocks_extracted=5,
        warnings=["Low confidence on page 2"],
        elapsed_seconds=1.5,
    )


class TestDebugAssetStore:
    def test_persist_raw_output(self, store: DebugAssetStore) -> None:
        path = store.persist_raw_output("src_001", "run_001", "parser_a", {"text": "test"})
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["text"] == "test"

    def test_persist_parse_log(self, store: DebugAssetStore, parse_result: ParseResult) -> None:
        path = store.persist_parse_log("src_001", "run_001", "parser_a", parse_result)
        assert path.exists()
        log = json.loads(path.read_text(encoding="utf-8"))
        assert log["parser_name"] == "test_parser"
        assert log["success"] is True
        assert log["pages_parsed"] == 2

    def test_persist_rendered_pages(self, store: DebugAssetStore, tmp_path: Path) -> None:
        img1 = tmp_path / "page1.png"
        img1.write_bytes(b"fake image 1")
        img2 = tmp_path / "page2.png"
        img2.write_bytes(b"fake image 2")

        stored = store.persist_rendered_pages("src_001", "run_001", "parser_a", {1: img1, 2: img2})
        assert len(stored) == 2
        assert all(p.exists() for p in stored)

    def test_persist_overlay(self, store: DebugAssetStore) -> None:
        path = store.persist_overlay(
            "src_001", "run_001", "parser_a",
            "bbox_overlay",
            {"page_1": [[0, 0, 100, 50]]},
        )
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "page_1" in data

    def test_persist_run_result(self, store: DebugAssetStore, parse_result: ParseResult) -> None:
        assets = store.persist_run_result("src_001", "run_001", "parser_a", parse_result)
        assert "raw_output" in assets
        assert "parse_log" in assets
        assert assets["raw_output"].exists()
        assert assets["parse_log"].exists()

    def test_assets_manifest(self, store: DebugAssetStore, parse_result: ParseResult) -> None:
        store.persist_run_result("src_001", "run_001", "parser_a", parse_result)
        manifest = store.get_assets("src_001", "run_001", "parser_a")
        assert "raw_output" in manifest
        assert "parse_log" in manifest

    def test_assets_exist(self, store: DebugAssetStore, parse_result: ParseResult) -> None:
        assert not store.assets_exist("src_001", "run_001", "parser_a")
        store.persist_run_result("src_001", "run_001", "parser_a", parse_result)
        assert store.assets_exist("src_001", "run_001", "parser_a")

    def test_get_assets_nonexistent(self, store: DebugAssetStore) -> None:
        assert store.get_assets("nope", "nope", "nope") == {}

    def test_persist_multiple_runs(self, store: DebugAssetStore, parse_result: ParseResult) -> None:
        store.persist_run_result("src_001", "run_001", "parser_a", parse_result)
        store.persist_run_result("src_001", "run_002", "parser_b", parse_result)

        assert store.assets_exist("src_001", "run_001", "parser_a")
        assert store.assets_exist("src_001", "run_002", "parser_b")
