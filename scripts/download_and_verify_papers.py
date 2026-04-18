#!/usr/bin/env python3
"""Download a public paper set and run the existing quick-verify workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.quick_verify_papers import run_batch

DEFAULT_TIMEOUT_SECONDS = 60


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a paper set manifest, then run quick_verify_papers on the downloaded PDFs.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="YAML manifest describing the paper set to download.",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        required=True,
        help="Output directory for downloads, verify artifacts, and final summaries.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Download at most this many papers from the manifest, in manifest order.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "router.yaml",
        help="Router config passed through to quick_verify_papers.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-file download timeout in seconds.",
    )
    parser.add_argument(
        "--continue-on-error",
        dest="continue_on_error",
        action="store_true",
        default=True,
        help="Keep processing the remaining papers after a download or verify failure. This is the default.",
    )
    parser.add_argument(
        "--stop-on-error",
        dest="continue_on_error",
        action="store_false",
        help="Stop after the first download or verify failure.",
    )
    return parser.parse_args(argv)


def _slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-") or "paper-set"


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"Manifest must be a YAML mapping: {manifest_path}"
        raise ValueError(msg)

    papers = data.get("papers")
    if not isinstance(papers, list) or not papers:
        msg = f"Manifest must contain a non-empty 'papers' list: {manifest_path}"
        raise ValueError(msg)

    normalized_papers: list[dict[str, Any]] = []
    for index, raw_paper in enumerate(papers, start=1):
        if not isinstance(raw_paper, dict):
            msg = f"Manifest paper entry #{index} must be a mapping"
            raise ValueError(msg)

        title = raw_paper.get("title")
        pdf_url = raw_paper.get("pdf_url")
        filename = raw_paper.get("filename")

        if not title or not isinstance(title, str):
            msg = f"Manifest paper entry #{index} is missing a string 'title'"
            raise ValueError(msg)
        if not pdf_url or not isinstance(pdf_url, str):
            msg = f"Manifest paper entry #{index} is missing a string 'pdf_url'"
            raise ValueError(msg)
        if not filename or not isinstance(filename, str):
            msg = f"Manifest paper entry #{index} is missing a string 'filename'"
            raise ValueError(msg)
        if not filename.lower().endswith(".pdf"):
            msg = f"Manifest filename must end with .pdf: {filename}"
            raise ValueError(msg)

        paper = dict(raw_paper)
        paper.setdefault("id", f"paper_{index:02d}")
        normalized_papers.append(paper)

    return {
        "name": data.get("name", manifest_path.stem),
        "description": data.get("description", ""),
        "papers": normalized_papers,
    }


def _select_papers(manifest: dict[str, Any], max_files: int | None) -> list[dict[str, Any]]:
    papers = list(manifest["papers"])
    if max_files is not None:
        if max_files <= 0:
            msg = "--max-files must be greater than 0"
            raise ValueError(msg)
        return papers[:max_files]
    return papers


def _copy_local_file(source_path: Path, dest_path: Path) -> None:
    if not source_path.exists():
        msg = f"Local file URL does not exist: {source_path}"
        raise FileNotFoundError(msg)
    shutil.copy2(source_path, dest_path)


def _download_remote_file(url: str, dest_path: Path, timeout_seconds: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "docos-quick-verify/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        final_url = response.geturl()
        with dest_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    return final_url


def _materialize_pdf(source_url: str, dest_path: Path, timeout_seconds: int) -> str:
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme == "file":
        local_path = Path(urllib.request.url2pathname(parsed.path))
        _copy_local_file(local_path, dest_path)
        return source_url

    if parsed.scheme in ("http", "https"):
        return _download_remote_file(source_url, dest_path, timeout_seconds)

    if parsed.scheme == "" and Path(source_url).exists():
        _copy_local_file(Path(source_url), dest_path)
        return str(Path(source_url).resolve())

    msg = f"Unsupported URL scheme for pdf_url: {source_url}"
    raise ValueError(msg)


def _download_paper(
    paper: dict[str, Any],
    downloads_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    downloads_dir.mkdir(parents=True, exist_ok=True)

    dest_path = downloads_dir / paper["filename"]
    result: dict[str, Any] = {
        "id": paper["id"],
        "title": paper["title"],
        "filename": paper["filename"],
        "pdf_url": paper["pdf_url"],
        "status": "downloaded",
        "final_url": paper["pdf_url"],
        "file_path": str(dest_path),
        "size_bytes": 0,
        "sha256": None,
        "error_message": None,
    }

    if dest_path.exists() and dest_path.stat().st_size > 0:
        result["status"] = "reused"
        result["size_bytes"] = dest_path.stat().st_size
        result["sha256"] = _sha256(dest_path)
        return result

    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    if temp_path.exists():
        temp_path.unlink()

    try:
        final_url = _materialize_pdf(paper["pdf_url"], temp_path, timeout_seconds)
        if temp_path.stat().st_size == 0:
            msg = f"Downloaded empty file for {paper['title']}"
            raise ValueError(msg)
        temp_path.replace(dest_path)
        result["final_url"] = final_url
        result["size_bytes"] = dest_path.stat().st_size
        result["sha256"] = _sha256(dest_path)
        return result
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink()
        result["status"] = "failed"
        result["error_message"] = str(exc)
        return result


def _stage_verify_inputs(
    download_results: list[dict[str, Any]],
    verify_inputs_dir: Path,
) -> list[dict[str, Any]]:
    verify_inputs_dir.mkdir(parents=True, exist_ok=True)
    staged: list[dict[str, Any]] = []

    for item in download_results:
        if item["status"] not in ("downloaded", "reused"):
            continue

        source_path = Path(item["file_path"])
        staged_path = verify_inputs_dir / item["filename"]
        shutil.copy2(source_path, staged_path)

        staged_item = dict(item)
        staged_item["verify_input_path"] = str(staged_path)
        staged.append(staged_item)

    return staged


def _build_quick_verify_args(
    papers_dir: Path,
    outdir: Path,
    config_path: Path,
    continue_on_error: bool,
) -> argparse.Namespace:
    return argparse.Namespace(
        papers_dir=papers_dir,
        outdir=outdir,
        pattern="*",
        max_files=None,
        config=config_path,
        continue_on_error=continue_on_error,
    )


def _combine_paper_results(
    selected_papers: list[dict[str, Any]],
    download_results: list[dict[str, Any]],
    verify_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    download_by_filename = {item["filename"]: item for item in download_results}
    verify_by_filename = {
        item["file_name"]: item for item in (verify_payload.get("files", []) if verify_payload else [])
    }

    combined: list[dict[str, Any]] = []
    for index, paper in enumerate(selected_papers, start=1):
        download = download_by_filename.get(paper["filename"])
        verify = verify_by_filename.get(paper["filename"])
        combined.append(
            {
                "index": index,
                "id": paper["id"],
                "title": paper["title"],
                "filename": paper["filename"],
                "paper_meta": {
                    key: value
                    for key, value in paper.items()
                    if key not in {"id", "title", "filename", "pdf_url"}
                },
                "pdf_url": paper["pdf_url"],
                "download": download,
                "verify": verify,
            },
        )

    return combined


def _fmt_rate(rate: float | None) -> str:
    """Format a rate value for human-readable output."""
    if rate is None:
        return "N/A"
    return f"{rate:.0%}"


def _build_verdict(
    selected_papers: list[dict[str, Any]],
    download_results: list[dict[str, Any]],
    verify_payload: dict[str, Any] | None,
    *,
    verification_mode: str = "isolated_per_paper",
) -> dict[str, str]:
    """Build a quality-aware top-level verdict for download-and-verify.

    The verdict is independently composed from download outcomes AND
    quick-verify quality signals (gate pass rate, pending review count,
    usable-wiki-ready count).  It is never a direct passthrough of
    quick-verify's internal verdict.

    When *verification_mode* is ``"isolated_per_paper"`` (the default), verdict
    text is scoped to per-paper pipeline validation and explicitly notes that
    a unified shared vault was **not** validated.
    """
    selected_count = len(selected_papers)
    download_success_count = sum(1 for item in download_results if item["status"] in ("downloaded", "reused"))
    download_failed_count = sum(1 for item in download_results if item["status"] == "failed")

    is_isolated = verification_mode == "isolated_per_paper"

    # Isolated-mode disclaimer appended to every non-empty answer
    isolated_disclaimer = ""
    if is_isolated:
        isolated_disclaimer = " 本次运行为逐论文独立管线验证，未对统一共享 wiki 库进行校验。"

    if download_success_count == 0:
        if is_isolated:
            return {
                "status": "not_yet",
                "headline": "这次未形成有效验证样本",
                "answer": "选中的论文没有成功下载到可验证输入，因此还不能回答系统是否具备逐论文管线转 wiki 的能力。",
            }
        return {
            "status": "not_yet",
            "headline": "这次未形成有效验证样本",
            "answer": "选中的论文没有成功下载到可验证输入，因此还不能回答系统是否具备一键转 wiki 的能力。",
        }

    if verify_payload is None:
        return {
            "status": "partial_yes" if download_failed_count else "not_yet",
            "headline": "下载阶段部分完成，但验证阶段没有真正跑起来",
            "answer": "已经拿到部分 PDF，但这次没有形成 quick verify 结果，因此无法给出可靠结论。",
        }

    # Extract quality signals from quick-verify totals
    verify_totals = verify_payload["totals"]
    usable_wiki_ready = verify_totals.get("usable_wiki_ready_count", 0)
    quality_blocked = verify_totals.get("quality_blocked_count", 0)
    pending_review = verify_totals.get("pending_review_count", 0)
    gate_rate = verify_totals.get("gate_pass_rate")
    obsidian_safe_rate = verify_totals.get("vault_pass_rate")
    readable_rate = verify_totals.get("readable_page_rate")
    vault_total_pages = verify_totals.get("vault_validation_total_pages", 0)
    vault_failed_pages = verify_totals.get("vault_validation_failed_pages", 0)

    coverage_prefix = ""
    if download_failed_count > 0:
        coverage_prefix = f"已成功下载 {download_success_count}/{selected_count} 篇论文。"

    # Helper for page-level usability summary
    def _page_usability_note() -> str:
        if vault_total_pages == 0:
            return ""
        parts = [f"页面级可用性：共 {vault_total_pages} 个页面"]
        if obsidian_safe_rate is not None:
            parts.append(f"Obsidian 安全率 {_fmt_rate(obsidian_safe_rate)}")
        if readable_rate is not None:
            parts.append(f"可读率 {_fmt_rate(readable_rate)}")
        return " " + "，".join(parts) + "。"

    # All delivered — no quality blocks, all downloads succeeded
    if (
        usable_wiki_ready == download_success_count
        and quality_blocked == 0
        and download_failed_count == 0
    ):
        gate_note = f" gate 通过率 {_fmt_rate(gate_rate)}。" if gate_rate is not None else ""
        if is_isolated:
            headline = "当前系统已经基本具备逐论文管线转 wiki 的能力"
        else:
            headline = "当前系统已经基本具备一键批量转 wiki 的能力"
        return {
            "status": "basically_yes",
            "headline": headline,
            "answer": (
                f"下载全部成功，{usable_wiki_ready} 篇论文均通过质量门禁并导出了可用 wiki 页面。{gate_note}{_page_usability_note()}{isolated_disclaimer}"
            ).rstrip(),
        }

    # Some papers reached usable-wiki-ready
    if usable_wiki_ready > 0:
        if is_isolated:
            headline = "当前系统已经部分具备逐论文管线转 wiki 的能力"
        else:
            headline = "当前系统已经部分具备一键批量转 wiki 的能力"
        return {
            "status": "partial_yes",
            "headline": headline,
            "answer": (
                f"{coverage_prefix}"
                f"{usable_wiki_ready} 篇达到可用 wiki 标准，"
                f"{quality_blocked} 篇被质量阻断，"
                f"{pending_review} 篇待审核。"
                f"{_page_usability_note()}{isolated_disclaimer}"
            ).rstrip(),
        }

    # Quality blocks present but no usable wiki
    if quality_blocked > 0 or pending_review > 0:
        page_note = ""
        if vault_failed_pages > 0:
            page_note = f" 其中 {vault_failed_pages} 个页面未通过 Obsidian 安全校验。"
        return {
            "status": "quality_blocked",
            "headline": "下载成功但逐论文管线验证存在质量阻断",
            "answer": (
                f"{coverage_prefix}"
                f"{quality_blocked} 篇被质量门禁阻断，"
                f"{pending_review} 篇待审核。"
                f"{page_note}{_page_usability_note()}{isolated_disclaimer}"
            ).rstrip(),
        }

    if is_isolated:
        tail = "验证结果不足以说明系统具备稳定的逐论文管线转 wiki 能力。"
    else:
        tail = "验证结果不足以说明系统具备稳定的一键转 wiki 能力。"
    return {
        "status": "not_yet",
        "headline": "下载与验证均未形成稳定结论",
        "answer": (
            f"{coverage_prefix}"
            f"{tail}{isolated_disclaimer}"
        ).rstrip(),
    }


def _write_summary_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_summary_md(path: Path, payload: dict[str, Any]) -> None:
    totals = payload["totals"]
    verdict = payload["verdict"]
    verification = payload["verification"]

    lines = [
        "# Download And Verify Summary",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Manifest: `{payload['manifest_path']}`",
        f"- Manifest name: `{payload['manifest_name']}`",
        f"- Output dir: `{payload['outdir']}`",
        f"- Session dir: `{payload['session_dir']}`",
        f"- Verification mode: **{payload['verification_mode']}**",
        "",
        "## Recommended Paths",
        "",
        f"- Recommended vault path: `{payload.get('recommended_vault_path') or 'N/A'}`",
        f"- Recommended start page: `{payload.get('recommended_start_page') or 'N/A'}`",
        "",
        "## Sample Coverage",
        "",
        f"- Manifest total: **{totals['manifest_total']}**",
        f"- Selected for this run: **{totals['selected_paper_count']}**",
        f"- Downloaded successfully: **{totals['downloaded_paper_count']}**",
        f"- Verified: **{totals['verified_paper_count']}**",
        "",
        "## Run Outcomes",
        "",
        f"- Download failures: **{totals['download_failed_count']}**",
        f"- Successful quick-verify runs: **{totals['verify_success_count']} / {totals['verify_processed_count']}**",
        "",
        "## Quality Metrics",
        "",
        f"- Download success rate: **{_fmt_rate(totals['download_success_rate'])}**",
        f"- Verify success rate: **{_fmt_rate(totals['verify_success_rate'])}**",
        f"- Gate pass rate: **{_fmt_rate(totals['gate_pass_rate'])}**",
        f"- Pending review: **{totals['pending_review_count']}**",
        f"- Usable wiki ready: **{totals['usable_wiki_ready_count']}**",
        f"- Quality blocked: **{totals['quality_blocked_count']}**",
        "",
        "## Page-Level Usability",
        "",
        f"- Total pages validated: **{totals['vault_validation_total_pages']}**",
        f"- Pages passed validation: **{totals['vault_validation_passed_pages']}**",
        f"- Pages failed validation: **{totals['vault_validation_failed_pages']}**",
        f"- Obsidian-safe page rate: **{_fmt_rate(totals['obsidian_safe_page_rate'])}**",
        f"- Readable page rate: **{_fmt_rate(totals['readable_page_rate'])}**",
        "",
        "## Verdict",
        "",
        f"**{verdict['headline']}**",
        "",
        verdict["answer"],
        "",
    ]

    # US-024: Isolated-mode disclaimer in markdown
    if payload.get("verification_mode") == "isolated_per_paper":
        lines.extend(
            [
                "> **Verification mode: isolated per-paper** (did not validate a unified shared vault)",
                "",
            ],
        )

    if payload["manifest_description"]:
        lines.extend(
            [
                "## Manifest Description",
                "",
                payload["manifest_description"],
                "",
            ],
        )

    if verification["summary_md_path"]:
        lines.extend(
            [
                "## Quick Verify Output",
                "",
                f"- quick verify summary.json: `{verification['summary_json_path']}`",
                f"- quick verify summary.md: `{verification['summary_md_path']}`",
                "",
            ],
        )

    lines.extend(
        [
            "## Per Paper",
            "",
            "| # | File | Download | Verify | Failed Stage | Run ID |",
            "| --- | --- | --- | --- | --- | --- |",
        ],
    )

    for item in payload["files"]:
        download_status = item["download"]["status"] if item["download"] else "not-attempted"
        verify_status = item["verify"]["status"] if item["verify"] else "-"
        failed_stage = item["verify"]["failed_stage"] if item["verify"] else "-"
        run_id = item["verify"]["run_id"] if item["verify"] else "-"
        lines.append(
            f"| {item['index']} | {item['filename']} | {download_status} | {verify_status} | {failed_stage} | {run_id} |",
        )

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_download_and_verify(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.resolve()
    if not manifest_path.exists():
        msg = f"Manifest not found: {manifest_path}"
        raise ValueError(msg)

    config_path = args.config.resolve()
    if not config_path.exists():
        msg = f"Config file not found: {config_path}"
        raise ValueError(msg)

    if args.timeout_seconds <= 0:
        msg = "--timeout-seconds must be greater than 0"
        raise ValueError(msg)

    outdir = args.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(manifest_path)
    selected_papers = _select_papers(manifest, args.max_files)

    session_name = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_dir = outdir / "sessions" / session_name
    downloads_dir = outdir / "downloads"
    verify_inputs_dir = session_dir / "papers"
    verify_outdir = session_dir / "verify"
    session_dir.mkdir(parents=True, exist_ok=True)

    download_results: list[dict[str, Any]] = []
    for index, paper in enumerate(selected_papers, start=1):
        print(f"[download {index}/{len(selected_papers)}] {paper['title']}")
        result = _download_paper(
            paper=paper,
            downloads_dir=downloads_dir,
            timeout_seconds=args.timeout_seconds,
        )
        download_results.append(result)
        print(f"  -> {result['status']} ({paper['filename']})")
        if result["status"] == "failed" and not args.continue_on_error:
            break

    staged_inputs = _stage_verify_inputs(download_results, verify_inputs_dir)

    verify_payload: dict[str, Any] | None = None
    if staged_inputs:
        print("")
        print("Running quick_verify_papers on downloaded PDFs...")
        verify_args = _build_quick_verify_args(
            papers_dir=verify_inputs_dir,
            outdir=verify_outdir,
            config_path=config_path,
            continue_on_error=args.continue_on_error,
        )
        verify_payload = run_batch(verify_args, verification_mode="isolated_per_paper")

    combined_files = _combine_paper_results(
        selected_papers=selected_papers,
        download_results=download_results,
        verify_payload=verify_payload,
    )
    effective_mode = verify_payload.get("verification_mode", "isolated_per_paper") if verify_payload else "isolated_per_paper"

    verdict = _build_verdict(
        selected_papers=selected_papers,
        download_results=download_results,
        verify_payload=verify_payload,
        verification_mode=effective_mode,
    )

    verify_totals = verify_payload["totals"] if verify_payload else {}
    verify_processed = verify_totals.get("pdfs_processed", 0)
    verify_success = verify_totals.get("success_count", 0)

    # US-011: Independent quality summary
    download_success_rate = (
        round(sum(1 for item in download_results if item["status"] in ("downloaded", "reused")) / len(selected_papers), 4)
        if selected_papers
        else None
    )
    verify_success_rate = (
        round(verify_success / verify_processed, 4)
        if verify_processed > 0
        else None
    )

    # US-027: Propagate recommended vault path and start page from quick-verify
    recommended_vault_path = verify_payload.get("recommended_vault_path") if verify_payload else None
    recommended_start_page = verify_payload.get("recommended_start_page") if verify_payload else None

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest_path": str(manifest_path),
        "manifest_name": manifest["name"],
        "manifest_description": manifest["description"],
        "outdir": str(outdir),
        "session_dir": str(session_dir),
        "verification_mode": effective_mode,
        "recommended_vault_path": recommended_vault_path,
        "recommended_start_page": recommended_start_page,
        "downloads_dir": str(downloads_dir),
        "verify_inputs_dir": str(verify_inputs_dir),
        "options": {
            "max_files": args.max_files,
            "timeout_seconds": args.timeout_seconds,
            "continue_on_error": args.continue_on_error,
            "config_path": str(config_path),
        },
        "totals": {
            "manifest_papers": len(manifest["papers"]),
            "selected_papers": len(selected_papers),
            "download_success_count": sum(1 for item in download_results if item["status"] in ("downloaded", "reused")),
            "download_failed_count": sum(1 for item in download_results if item["status"] == "failed"),
            "verify_processed_count": verify_totals.get("pdfs_processed", 0),
            "verify_success_count": verify_totals.get("success_count", 0),
            "verify_failed_count": verify_totals.get("failed_count", 0),
            "verify_wiki_output_count": verify_totals.get("wiki_output_count", 0),
            # Explicit coverage counters (US-006)
            "manifest_total": len(manifest["papers"]),
            "selected_paper_count": len(selected_papers),
            "downloaded_paper_count": sum(1 for item in download_results if item["status"] in ("downloaded", "reused")),
            "verified_paper_count": verify_totals.get("pdfs_processed", 0),
            # US-011: Independent quality summary
            "download_success_rate": download_success_rate,
            "verify_success_rate": verify_success_rate,
            "gate_pass_rate": verify_totals.get("gate_pass_rate"),
            "pending_review_count": verify_totals.get("pending_review_count", 0),
            "usable_wiki_ready_count": verify_totals.get("usable_wiki_ready_count", 0),
            "quality_blocked_count": verify_totals.get("quality_blocked_count", 0),
            # US-022: Obsidian-safe and readable page rates
            "obsidian_safe_page_rate": verify_totals.get("vault_pass_rate"),
            "readable_page_rate": verify_totals.get("readable_page_rate"),
            "vault_validation_total_pages": verify_totals.get("vault_validation_total_pages", 0),
            "vault_validation_passed_pages": verify_totals.get("vault_validation_passed_pages", 0),
            "vault_validation_failed_pages": verify_totals.get("vault_validation_failed_pages", 0),
        },
        "verdict": verdict,
        "downloads": download_results,
        "verification": {
            "outdir": str(verify_outdir),
            "summary_json_path": verify_payload.get("summary_json_path") if verify_payload else None,
            "summary_md_path": verify_payload.get("summary_md_path") if verify_payload else None,
            "payload": verify_payload,
        },
        "files": combined_files,
    }

    session_summary_json = session_dir / "summary.json"
    session_summary_md = session_dir / "summary.md"
    root_summary_json = outdir / "summary.json"
    root_summary_md = outdir / "summary.md"

    _write_summary_json(session_summary_json, payload)
    _write_summary_json(root_summary_json, payload)
    _write_summary_md(session_summary_md, payload)
    _write_summary_md(root_summary_md, payload)

    payload["summary_json_path"] = str(root_summary_json)
    payload["summary_md_path"] = str(root_summary_md)
    payload["session_summary_json_path"] = str(session_summary_json)
    payload["session_summary_md_path"] = str(session_summary_md)

    _write_summary_json(session_summary_json, payload)
    _write_summary_json(root_summary_json, payload)

    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_download_and_verify(args)
    print("")
    print(payload["verdict"]["headline"])
    print(payload["verdict"]["answer"])
    print(f"summary.json: {payload['summary_json_path']}")
    print(f"summary.md: {payload['summary_md_path']}")
    if payload["verification"]["summary_json_path"]:
        print(f"quick verify summary.json: {payload['verification']['summary_json_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
