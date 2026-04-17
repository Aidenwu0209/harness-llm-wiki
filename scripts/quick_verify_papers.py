#!/usr/bin/env python3
"""Smoke-test a folder of PDFs through the existing DocOS pipeline."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docos.artifact_stores import ReportStore, WikiStore
from docos.pipeline.runner import PipelineRunner
from docos.run_store import RunStore


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quickly verify whether a folder of PDFs can run through the DocOS pipeline.",
    )
    parser.add_argument("papers_dir", type=Path, help="Local folder containing PDFs")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help="Output directory for the batch verification run. Defaults to ./quick_verify_output/<timestamp>.",
    )
    parser.add_argument(
        "--pattern",
        default="*",
        help="Filename pattern applied after PDF filtering, for example '*transformer*' or '01_*.pdf'.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Process at most this many PDFs after sorting by filename.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "router.yaml",
        help="Path to router config. Defaults to the repo's configs/router.yaml.",
    )
    parser.add_argument(
        "--continue-on-error",
        dest="continue_on_error",
        action="store_true",
        default=True,
        help="Keep processing the remaining PDFs after a failure. This is the default.",
    )
    parser.add_argument(
        "--stop-on-error",
        dest="continue_on_error",
        action="store_false",
        help="Stop after the first failed PDF.",
    )
    return parser.parse_args(argv)


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip())
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-._") or "paper"


def _discover_pdfs(papers_dir: Path, pattern: str, max_files: int | None) -> tuple[list[Path], int]:
    pdfs = sorted(
        [path for path in papers_dir.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"],
        key=lambda path: path.name.lower(),
    )
    discovered_count = len(pdfs)

    pattern_lower = pattern.lower()
    filtered = [path for path in pdfs if fnmatch.fnmatch(path.name.lower(), pattern_lower)]
    if max_files is not None:
        filtered = filtered[:max_files]
    return filtered, discovered_count


def _default_outdir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "quick_verify_output" / timestamp


def _report_json_path(workspace: Path, run_id: str | None) -> str | None:
    if not run_id:
        return None
    path = workspace / "reports" / f"{run_id}.json"
    return str(path) if path.exists() else None


def _patch_json_path(workspace: Path, run_id: str | None) -> str | None:
    if not run_id:
        return None
    path = workspace / "patches" / f"patchset-{run_id}.json"
    return str(path) if path.exists() else None


def _knowledge_dir_path(workspace: Path, run_id: str | None) -> str | None:
    if not run_id:
        return None
    path = workspace / "knowledge" / run_id
    return str(path) if path.exists() else None


def _load_manifest(workspace: Path, run_id: str | None) -> Any:
    run_store = RunStore(workspace)
    if run_id:
        manifest = run_store.get(run_id)
        if manifest is not None:
            return manifest
    manifests = run_store.list_runs()
    if len(manifests) == 1:
        return manifests[0]
    return None


def _render_markdown(frontmatter: dict[str, Any], body: str) -> str:
    yaml_block = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"


def _export_wiki_pages(workspace: Path, wiki_root: Path) -> list[str]:
    wiki_store = WikiStore(workspace / "wiki_state")
    exported: list[str] = []

    for page_path in sorted(wiki_store.list_page_paths()):
        state = wiki_store.get(page_path)
        if state is None:
            continue

        compiled_path = Path(page_path)
        try:
            relative_path = compiled_path.relative_to(workspace / "wiki")
        except ValueError:
            relative_path = Path(compiled_path.name)

        dest_path = wiki_root / relative_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(
            _render_markdown(state.frontmatter, state.body),
            encoding="utf-8",
        )
        exported.append(str(dest_path))

    return exported


def _classify_verdict(item: dict[str, Any]) -> str:
    """Classify a per-paper result into a verdict tier.

    Tiers:
    - ``usable_wiki_ready``  – completed, gate passed, wiki pages exported
    - ``quality_blocked``    – completed but gate blocked or review pending
    - ``pipeline_runnable``  – pipeline ran but did not meet usable-wiki criteria
    """
    run_status = item.get("run_status", "")
    if run_status != "completed":
        return "pipeline_runnable"

    gate_passed: bool | None = item.get("gate", {}).get("passed")
    review_status: str | None = item.get("review_status")
    wiki_pages_exported: int = item.get("counts", {}).get("wiki_pages_exported", 0)

    if gate_passed is False or review_status == "pending":
        return "quality_blocked"

    if gate_passed is True and wiki_pages_exported > 0:
        return "usable_wiki_ready"

    return "pipeline_runnable"


def _is_knowledge_sparse(item: dict[str, Any]) -> bool:
    """Return True when extracted knowledge is entirely empty."""
    counts = item.get("counts", {})
    return (
        counts.get("entities", 0) == 0
        and counts.get("claims", 0) == 0
        and counts.get("relations", 0) == 0
    )


def _is_wiki_sparse(item: dict[str, Any]) -> bool:
    """Return True when wiki export contains only source pages (no entity or concept pages)."""
    wiki_pages: list[str] = item.get("artifacts", {}).get("wiki_pages", [])
    if not wiki_pages:
        return False
    for page_path in wiki_pages:
        parts = Path(page_path).parts
        if "entities" in parts or "concepts" in parts:
            return False
    return True


def _summarize_stage_statuses(manifest: Any) -> tuple[dict[str, str], dict[str, str]]:
    if manifest is None:
        return {}, {}

    statuses = {stage.name: stage.status.value for stage in manifest.stages}
    errors = {
        stage.name: stage.error_detail
        for stage in manifest.stages
        if stage.error_detail
    }
    return statuses, errors


def _build_file_result(
    *,
    index: int,
    pdf_path: Path,
    workspace: Path,
    result: Any,
    manifest: Any,
    wiki_root: Path,
    wiki_pages: list[str],
) -> dict[str, Any]:
    report = ReportStore(workspace / "reports").get(result.run_id) if result.run_id else None
    stage_statuses, stage_errors = _summarize_stage_statuses(manifest)

    run_status = result.status.value
    status = "success" if run_status == "completed" else "failed"

    counts = {
        "ir_pages": result.docir.page_count if result.docir else None,
        "ir_blocks": len(result.docir.blocks) if result.docir else None,
        "entities": len(result.entities),
        "claims": len(result.claims),
        "relations": len(result.relations),
        "patches": len(result.patches),
        "lint_findings": result.lint_findings_count,
        "compiled_pages": manifest.compiled_page_count if manifest is not None else None,
        "wiki_pages_exported": len(wiki_pages),
    }

    artifacts = {
        "workspace_dir": str(workspace),
        "route_artifact": manifest.route_artifact_path if manifest is not None else None,
        "ir_artifact": manifest.ir_artifact_path if manifest is not None else None,
        "knowledge_artifact": _knowledge_dir_path(workspace, result.run_id or None),
        "patch_artifact": _patch_json_path(workspace, result.run_id or None),
        "lint_artifact": manifest.lint_artifact_path if manifest is not None else None,
        "report_artifact": _report_json_path(workspace, result.run_id or None),
        "wiki_pages_dir": str(wiki_root) if wiki_pages else None,
        "wiki_pages": wiki_pages,
    }

    return {
        "index": index,
        "file_name": pdf_path.name,
        "file_path": str(pdf_path),
        "status": status,
        "run_status": run_status,
        "failed_stage": result.failed_stage,
        "error_message": result.error_detail,
        "run_id": result.run_id or None,
        "source_id": result.source_id or None,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
        "selected_route": result.route_decision.selected_route if result.route_decision else getattr(manifest, "selected_route", None),
        "primary_parser": result.route_decision.primary_parser if result.route_decision else None,
        "parser_chain": manifest.parser_chain if manifest is not None else [],
        "fallback_used": manifest.fallback_used if manifest is not None else False,
        "stage_statuses": stage_statuses,
        "stage_errors": stage_errors,
        "counts": counts,
        "harness": {
            "overall_passed": report.overall_passed if report is not None else result.harness_passed,
            "release_decision": report.release_decision if report is not None else None,
            "gate_blockers": report.gate_blockers if report is not None else [],
        },
        "gate": {
            "passed": result.gate_passed,
            "decision": manifest.gate_decision if manifest is not None else None,
            "reasons": result.gate_reasons,
        },
        "review_status": manifest.review_status if manifest is not None else result.review_status,
        "artifacts": artifacts,
    }


def _build_script_failure(
    *,
    index: int,
    pdf_path: Path,
    workspace: Path,
    error_message: str,
) -> dict[str, Any]:
    return {
        "index": index,
        "file_name": pdf_path.name,
        "file_path": str(pdf_path),
        "status": "failed",
        "run_status": "failed",
        "failed_stage": "script",
        "error_message": error_message,
        "run_id": None,
        "source_id": None,
        "elapsed_seconds": 0.0,
        "selected_route": None,
        "primary_parser": None,
        "parser_chain": [],
        "fallback_used": False,
        "stage_statuses": {},
        "stage_errors": {"script": error_message},
        "counts": {
            "ir_pages": None,
            "ir_blocks": None,
            "entities": 0,
            "claims": 0,
            "relations": 0,
            "patches": 0,
            "lint_findings": 0,
            "compiled_pages": None,
            "wiki_pages_exported": 0,
        },
        "harness": {
            "overall_passed": None,
            "release_decision": None,
            "gate_blockers": [],
        },
        "gate": {
            "passed": None,
            "decision": None,
            "reasons": [],
        },
        "review_status": None,
        "artifacts": {
            "workspace_dir": str(workspace),
            "route_artifact": None,
            "ir_artifact": None,
            "knowledge_artifact": None,
            "patch_artifact": None,
            "lint_artifact": None,
            "report_artifact": None,
            "wiki_pages_dir": None,
            "wiki_pages": [],
        },
    }


def _build_verdict(
    results: list[dict[str, Any]],
    *,
    manifest_total: int = 0,
    verified_paper_count: int = 0,
) -> dict[str, str]:
    """Build top-level headline and answer from verdict-tier totals.

    The verdict is derived from the per-paper classification produced by
    ``_classify_verdict`` rather than raw ``success_count`` / ``wiki_output_count``.
    """
    total = len(results)
    verdict_counts = Counter(item.get("verdict", "pipeline_runnable") for item in results)
    usable = verdict_counts.get("usable_wiki_ready", 0)
    blocked = verdict_counts.get("quality_blocked", 0)
    runnable = verdict_counts.get("pipeline_runnable", 0)

    # Coverage limitation note
    coverage_note = ""
    if manifest_total > 0 and verified_paper_count < manifest_total:
        coverage_note = (
            f"（本次验证覆盖 {verified_paper_count}/{manifest_total} 篇论文，"
            "结论仅限于该样本范围）"
        )

    if total == 0:
        return {
            "status": "no_input",
            "headline": "没有发现可验证的 PDF 文件",
            "answer": "这次没有实际跑任何论文，因此还不能回答系统是否具备一键转 wiki 能力。",
        }

    if usable == total and blocked == 0:
        headline = "当前系统已经基本具备一键批量转 wiki 的能力"
        answer = (
            f"这次验证中，所有 {total} 篇论文均通过质量门禁并导出了可用 wiki 页面。"
            f"{coverage_note}"
        )
        return {
            "status": "basically_yes",
            "headline": headline,
            "answer": answer.rstrip(),
        }

    if usable > 0 and (blocked > 0 or runnable > 0):
        headline = "当前系统已经部分具备一键批量转 wiki 的能力"
        answer = (
            f"这次验证中，{usable}/{total} 篇论文达到可用 wiki 标准，"
            f"{blocked} 篇被质量门禁或审核阻断，"
            f"{runnable} 篇未达到可用标准。"
            f"{coverage_note}"
        )
        return {
            "status": "partial_yes",
            "headline": headline,
            "answer": answer.rstrip(),
        }

    if blocked > 0 and usable == 0:
        return {
            "status": "quality_blocked",
            "headline": "当前系统在本次验证中存在质量阻断，尚不具备可用 wiki 交付能力",
            "answer": (
                f"这次验证中，{blocked} 篇论文被质量门禁或审核流程阻断，"
                f"没有论文达到可用 wiki 标准。"
                f"{coverage_note}"
            ).rstrip(),
        }

    return {
        "status": "not_yet",
        "headline": "当前系统还不具备稳定的一键批量转 wiki 能力",
        "answer": (
            f"这次验证中，没有论文达到可用 wiki 标准。"
            f"{coverage_note}"
        ).rstrip(),
    }


def _failure_stage_histogram(results: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter()
    for item in results:
        if item["status"] == "failed":
            counter[item.get("failed_stage") or "unknown"] += 1
    return dict(sorted(counter.items()))


def _write_summary_json(outdir: Path, payload: dict[str, Any]) -> Path:
    summary_path = outdir / "summary.json"
    summary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary_path


def _write_summary_md(outdir: Path, payload: dict[str, Any]) -> Path:
    totals = payload["totals"]
    verdict = payload["verdict"]
    lines = [
        "# Quick Verify Summary",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Papers dir: `{payload['papers_dir']}`",
        f"- Config: `{payload['config_path']}`",
        f"- Output dir: `{payload['outdir']}`",
        "",
        "## Sample Coverage",
        "",
        f"- Manifest total: **{totals['manifest_total']}**",
        f"- Selected for this run: **{totals['selected_paper_count']}**",
        f"- Available for verification: **{totals['downloaded_paper_count']}**",
        f"- Verified: **{totals['verified_paper_count']}**",
        "",
        "## Run Outcomes",
        "",
        f"- Successful full-chain runs: **{totals['success_count']} / {totals['pdfs_processed']}**",
        f"- Failed runs: **{totals['failed_count']}**",
        f"- Runs with exported wiki pages: **{totals['wiki_output_count']}**",
        "",
        "## Verdict Tiers",
        "",
        f"- Pipeline runnable: **{totals['pipeline_runnable_count']}**",
        f"- Quality blocked: **{totals['quality_blocked_count']}**",
        f"- Usable wiki ready: **{totals['usable_wiki_ready_count']}**",
        f"- Pending review: **{totals['pending_review_count']}**",
        f"- Knowledge sparse: **{totals['knowledge_sparse_count']}**",
        f"- Wiki sparse: **{totals['wiki_sparse_count']}**",
        "",
        "## Verdict",
        "",
        f"**{verdict['headline']}**",
        "",
        verdict["answer"],
        "",
    ]

    if payload["failure_stage_histogram"]:
        lines.extend(
            [
                "## Failure Breakdown",
                "",
            ],
        )
        for stage, count in payload["failure_stage_histogram"].items():
            lines.append(f"- `{stage}`: {count}")
        lines.append("")

    lines.extend(
        [
            "## Per Paper",
            "",
            "| # | File | Verdict | Gate | Review Status | Status | Failed Stage | Route | Wiki Pages | Run ID |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ],
    )

    for item in payload["files"]:
        route = item["selected_route"] or "-"
        failed_stage = item["failed_stage"] or "-"
        run_id = item["run_id"] or "-"
        wiki_pages = item["counts"]["wiki_pages_exported"]
        verdict_tier = item.get("verdict", "-")
        gate = item.get("gate", {})
        gate_decision = gate.get("decision") if isinstance(gate, dict) else None
        gate_display = gate_decision if gate_decision is not None else ("passed" if gate.get("passed") is True else ("blocked" if gate.get("passed") is False else "-"))
        review_status = item.get("review_status") or "-"
        lines.append(
            f"| {item['index']} | {item['file_name']} | {verdict_tier} | {gate_display} | {review_status} | {item['status']} | {failed_stage} | {route} | {wiki_pages} | {run_id} |",
        )

    lines.append("")

    summary_md_path = outdir / "summary.md"
    summary_md_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_md_path


def run_batch(args: argparse.Namespace) -> dict[str, Any]:
    papers_dir = args.papers_dir.resolve()
    if not papers_dir.exists() or not papers_dir.is_dir():
        msg = f"papers_dir must be an existing directory: {papers_dir}"
        raise ValueError(msg)

    if args.max_files is not None and args.max_files <= 0:
        msg = "--max-files must be greater than 0"
        raise ValueError(msg)

    config_path = args.config.resolve()
    if not config_path.exists():
        msg = f"Config file not found: {config_path}"
        raise ValueError(msg)

    outdir = (args.outdir or _default_outdir()).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    selected_pdfs, discovered_count = _discover_pdfs(
        papers_dir=papers_dir,
        pattern=args.pattern,
        max_files=args.max_files,
    )
    matched_count = len(selected_pdfs)

    results: list[dict[str, Any]] = []

    for index, pdf_path in enumerate(selected_pdfs, start=1):
        paper_label = f"{index:03d}_{_slug(pdf_path.stem)}"
        run_root = outdir / "runs" / paper_label
        workspace = run_root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        print(f"[{index}/{len(selected_pdfs)}] {pdf_path.name}")
        try:
            runner = PipelineRunner(base_dir=workspace, config_path=config_path)
            pipeline_result = runner.run(
                file_path=pdf_path,
                origin="quick_verify",
                tags=["quick-verify"],
            )
            manifest = _load_manifest(workspace, pipeline_result.run_id or None)

            wiki_root = outdir / "wiki_pages" / paper_label
            wiki_pages = _export_wiki_pages(workspace, wiki_root)

            file_result = _build_file_result(
                index=index,
                pdf_path=pdf_path,
                workspace=workspace,
                result=pipeline_result,
                manifest=manifest,
                wiki_root=wiki_root,
                wiki_pages=wiki_pages,
            )
            print(
                f"  -> {file_result['status']}"
                f" (run_id={file_result['run_id'] or '-'}, failed_stage={file_result['failed_stage'] or '-'})",
            )
        except Exception as exc:
            file_result = _build_script_failure(
                index=index,
                pdf_path=pdf_path,
                workspace=workspace,
                error_message=str(exc),
            )
            print(f"  -> failed (script: {exc})")

        file_result["verdict"] = _classify_verdict(file_result)
        file_result["knowledge_sparse"] = _is_knowledge_sparse(file_result)
        file_result["wiki_sparse"] = _is_wiki_sparse(file_result)

        (run_root / "result.json").write_text(
            json.dumps(file_result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        results.append(file_result)

        if file_result["status"] == "failed" and not args.continue_on_error:
            break

    success_count = sum(1 for item in results if item["status"] == "success")
    failed_count = sum(1 for item in results if item["status"] == "failed")
    wiki_output_count = sum(1 for item in results if item["counts"]["wiki_pages_exported"] > 0)
    pending_review_count = sum(1 for item in results if item.get("review_status") == "pending")
    knowledge_sparse_count = sum(1 for item in results if item.get("knowledge_sparse"))
    wiki_sparse_count = sum(1 for item in results if item.get("wiki_sparse"))

    verdict_counts = Counter(item["verdict"] for item in results)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_root": str(REPO_ROOT),
        "papers_dir": str(papers_dir),
        "config_path": str(config_path),
        "outdir": str(outdir),
        "options": {
            "pattern": args.pattern,
            "max_files": args.max_files,
            "continue_on_error": args.continue_on_error,
        },
        "totals": {
            "pdfs_discovered": discovered_count,
            "pdfs_selected": matched_count,
            "pdfs_processed": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "wiki_output_count": wiki_output_count,
            "pending_review_count": pending_review_count,
            "knowledge_sparse_count": knowledge_sparse_count,
            "wiki_sparse_count": wiki_sparse_count,
            "pipeline_runnable_count": verdict_counts.get("pipeline_runnable", 0),
            "quality_blocked_count": verdict_counts.get("quality_blocked", 0),
            "usable_wiki_ready_count": verdict_counts.get("usable_wiki_ready", 0),
            # Explicit coverage counters (US-006)
            "manifest_total": discovered_count,
            "selected_paper_count": matched_count,
            "downloaded_paper_count": matched_count,
            "verified_paper_count": len(results),
        },
        "failure_stage_histogram": _failure_stage_histogram(results),
        "verdict": _build_verdict(
            results,
            manifest_total=discovered_count,
            verified_paper_count=len(results),
        ),
        "files": results,
    }

    payload["summary_json_path"] = str(_write_summary_json(outdir, payload))
    payload["summary_md_path"] = str(_write_summary_md(outdir, payload))

    # Refresh summary.json after adding the generated file paths.
    _write_summary_json(outdir, payload)

    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_batch(args)
    print("")
    print(payload["verdict"]["headline"])
    print(payload["verdict"]["answer"])
    print(f"summary.json: {payload['summary_json_path']}")
    print(f"summary.md: {payload['summary_md_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
