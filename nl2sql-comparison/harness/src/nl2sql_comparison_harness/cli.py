from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from nl2sql_comparison_harness.api_client import API_FRAMEWORKS, ask_via_api, default_api_url
from nl2sql_comparison_harness.compare import execution_metrics, summarize_mismatch
from nl2sql_comparison_harness.dataset import (
    BenchmarkItem,
    harness_root,
    load_gold_jsonl,
    load_questions_file,
    lookup_benchmark_item,
    merge_gold,
    strip_sql_comments,
    suite_paths,
)
from nl2sql_comparison_harness.db import resolve_sqlite_db_path, run_query, run_query_sqlite, strip_exec_wrapper
from nl2sql_comparison_harness.metrics import format_summary_table, summarize_jsonl
from nl2sql_comparison_harness.resources import LocalDockerResourceProvider, NullResourceProvider
from nl2sql_comparison_harness.ui import UIAskerSession
from nl2sql_comparison_harness.ui.drivers import UI_FRAMEWORKS, normalize_framework


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def _default_out(framework: str, suite: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return harness_root() / "runs" / f"{framework}_{suite}_{ts}.jsonl"


def cmd_run(args: argparse.Namespace) -> int:
    framework = normalize_framework(args.framework)
    q_path, g_path = suite_paths(args.suite)
    items = load_questions_file(q_path)
    gold_map = load_gold_jsonl(g_path)
    items = merge_gold(items, gold_map)
    if getattr(args, "limit", None):
        items = items[: int(args.limit)]

    out_path = Path(args.out) if args.out else _default_out(framework, args.suite)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trace_dir = (
        Path(args.trace_dir)
        if args.trace_dir
        else (harness_root() / "runs" / "traces" / f"{framework}_{args.suite}")
    )
    effective_trace = trace_dir if args.trace else None

    if args.resources == "local_docker":
        stack_containers = [c.strip() for c in (args.stack_containers or "").split(",") if c.strip()]
        resource_provider = LocalDockerResourceProvider(stack_containers=stack_containers)
    else:
        resource_provider = NullResourceProvider()

    results: List[dict] = []
    scored = 0
    sum_ex = 0
    sum_sf1 = 0.0
    run_started = time.perf_counter()
    total_items = len(items)

    with UIAskerSession(
        framework=framework,
        ui_url=args.ui_url,
        trace_dir=effective_trace,
        headless=not args.headed,
    ) as session:
        for idx, it in enumerate(items, start=1):
            q_started = time.perf_counter()
            ctx = {"question_id": it.question_id, "db_id": it.db_id}
            resource_provider.start(ctx)

            if not it.gold_sql.strip():
                row = {
                    "framework": framework,
                    "suite": args.suite,
                    "question_id": it.question_id,
                    "db_id": it.db_id,
                    "question": it.question,
                    "error": "missing_gold",
                    "ex": False,
                    "soft_f1": 0.0,
                    "latency_ms": None,
                    "resources": resource_provider.stop(),
                }
                results.append(row)
                _print_progress(idx, total_items, it.question_id, q_started, run_started)
                continue

            ui_result = session.ask(it.question, timeout_s=args.timeout)
            wall_ms = int((time.perf_counter() - q_started) * 1000)
            resources = resource_provider.stop()

            rec: dict = {
                "framework": framework,
                "suite": args.suite,
                "question_id": it.question_id,
                "db_id": it.db_id,
                "question": it.question,
                "gold_sql": it.gold_sql,
                "pred_sql": ui_result.pred_sql,
                "latency_ms": ui_result.latency_ms,
                "wall_ms": wall_ms,
                "ui_error": ui_result.error,
                "resources": resources,
            }
            if ui_result.raw:
                rec["ui_raw"] = ui_result.raw

            if ui_result.error or not ui_result.pred_sql:
                rec["ex"] = False
                rec["soft_f1"] = 0.0
                results.append(rec)
                _print_progress(idx, total_items, it.question_id, q_started, run_started)
                continue

            eval_started = time.perf_counter()
            gold_sql = strip_sql_comments(it.gold_sql)
            pred_sql = strip_sql_comments(ui_result.pred_sql)
            try:
                _, gold_rows = run_query(
                    args.dsn, gold_sql, timeout_ms=args.sql_timeout_ms, max_rows=args.max_rows
                )
            except Exception as exc:  # noqa: BLE001
                rec["ex"] = False
                rec["soft_f1"] = 0.0
                rec["eval_error"] = f"gold_sql: {exc}"
                rec["eval_ms"] = int((time.perf_counter() - eval_started) * 1000)
                results.append(rec)
                _print_progress(idx, total_items, it.question_id, q_started, run_started)
                continue
            try:
                _, pred_rows = run_query(
                    args.dsn, pred_sql, timeout_ms=args.sql_timeout_ms, max_rows=args.max_rows
                )
            except Exception as exc:  # noqa: BLE001
                rec["ex"] = False
                rec["soft_f1"] = 0.0
                rec["eval_error"] = f"pred_sql: {exc}"
                rec["eval_ms"] = int((time.perf_counter() - eval_started) * 1000)
                results.append(rec)
                _print_progress(idx, total_items, it.question_id, q_started, run_started)
                continue

            ex, sf1, alias_mismatch = execution_metrics(gold_rows, pred_rows)
            rec["ex"] = ex
            rec["soft_f1"] = sf1
            if alias_mismatch:
                rec["alias_mismatch"] = True
            rec["eval_ms"] = int((time.perf_counter() - eval_started) * 1000)
            scored += 1
            sum_ex += int(ex)
            sum_sf1 += sf1
            results.append(rec)
            _print_progress(idx, total_items, it.question_id, q_started, run_started)

    with out_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = scored or 1
    summary = {
        "framework": framework,
        "suite": args.suite,
        "count": len(results),
        "scored": scored,
        "mean_ex": sum_ex / n,
        "mean_soft_f1": sum_sf1 / n,
        "out": str(out_path),
    }
    print(json.dumps(summary, indent=2))
    return 0


def _process_one_api_item(
    *,
    it: BenchmarkItem,
    framework: str,
    suite: str,
    api_url: str,
    timeout_s: float,
    dsn: str,
    sql_timeout_ms: int,
    max_rows: int,
    eval_engine: str = "postgres",
    sqlite_databases_dir: str | None = None,
    ex_mode: str = "multiset",
) -> dict:
    """Ask one question via HTTP API and score locally. Thread-safe (no shared mutable state)."""
    q_started = time.perf_counter()

    if not it.gold_sql.strip():
        return {
            "framework": framework,
            "suite": suite,
            "mode": "api",
            "question_id": it.question_id,
            "db_id": it.db_id,
            "question": it.question,
            "error": "missing_gold",
            "failure": "missing_gold",
            "ex": False,
            "soft_f1": 0.0,
            "latency_ms": None,
        }

    api_result = ask_via_api(
        api_url=api_url,
        question=it.question,
        timeout_s=timeout_s,
        db_id=it.db_id,
        evidence=it.evidence,
    )
    wall_ms = int((time.perf_counter() - q_started) * 1000)

    # API returns 200 after generation (+ optional server-side exec).
    executable = api_result.error is None and bool((api_result.pred_sql or "").strip())

    rec: dict = {
        "framework": framework,
        "suite": suite,
        "mode": "api",
        "question_id": it.question_id,
        "db_id": it.db_id,
        "question": it.question,
        "evidence": it.evidence,
        "gold_sql": it.gold_sql,
        "pred_sql": api_result.pred_sql,
        "latency_ms": api_result.latency_ms,
        "wall_ms": wall_ms,
        "api_error": api_result.error,
        "executable": executable,
        "llm_calls": 1,
        "eval_engine": eval_engine,
        "ex_mode": ex_mode,
    }
    if api_result.raw:
        rec["api_raw"] = api_result.raw

    if not api_result.pred_sql:
        rec["ex"] = False
        rec["soft_f1"] = 0.0
        rec["failure"] = api_result.error or "empty_pred_sql"
        return rec

    eval_started = time.perf_counter()
    gold_sql = strip_exec_wrapper(strip_sql_comments(it.gold_sql))
    pred_sql = strip_exec_wrapper(strip_sql_comments(api_result.pred_sql))
    try:
        if eval_engine == "sqlite":
            if not it.db_id:
                raise ValueError("db_id required for sqlite eval")
            if not sqlite_databases_dir:
                raise ValueError("--sqlite-databases-dir required for sqlite eval")
            db_path = resolve_sqlite_db_path(sqlite_databases_dir, it.db_id)
            _, gold_rows = run_query_sqlite(
                db_path, gold_sql, timeout_ms=sql_timeout_ms, max_rows=max_rows
            )
            _, pred_rows = run_query_sqlite(
                db_path, pred_sql, timeout_ms=sql_timeout_ms, max_rows=max_rows
            )
        else:
            _, gold_rows = run_query(dsn, gold_sql, timeout_ms=sql_timeout_ms, max_rows=max_rows)
            _, pred_rows = run_query(dsn, pred_sql, timeout_ms=sql_timeout_ms, max_rows=max_rows)
    except Exception as exc:  # noqa: BLE001
        rec["ex"] = False
        rec["soft_f1"] = 0.0
        rec["eval_error"] = str(exc)
        rec["failure"] = rec["eval_error"]
        rec["eval_ms"] = int((time.perf_counter() - eval_started) * 1000)
        return rec

    ex, sf1, alias_mismatch = execution_metrics(
        gold_rows, pred_rows, ex_mode="bird" if ex_mode == "bird" else "multiset"
    )
    rec["ex"] = ex
    rec["soft_f1"] = sf1
    if alias_mismatch:
        rec["alias_mismatch"] = True
    if not ex:
        # Keep EX-mismatch analyzable without dumping full result sets.
        rec["failure"] = "ex_mismatch"
        if alias_mismatch:
            rec["failure"] = "ex_mismatch_alias"
    rec["eval_ms"] = int((time.perf_counter() - eval_started) * 1000)
    return rec


def _run_api_items(
    *,
    items: List[BenchmarkItem],
    framework: str,
    suite: str,
    api_url: str,
    timeout_s: float,
    dsn: str,
    sql_timeout_ms: int,
    max_rows: int,
    workers: int = 1,
    out_path: Path | None = None,
    eval_engine: str = "postgres",
    sqlite_databases_dir: str | None = None,
    ex_mode: str = "multiset",
) -> List[dict]:
    """Run API asks for all items with up to ``workers`` concurrent HTTP POSTs.

    Results are returned in the original item order. Progress lines are serialized
    with a lock. ``workers=1`` is sequential (single pool worker).
    When ``out_path`` is set, each finished record is appended immediately (AFK progress /
    crash safety); the file is rewritten in item order at the end.
    """
    workers = max(1, int(workers))
    total_items = len(items)
    run_started = time.perf_counter()
    print_lock = threading.Lock()
    done_count = 0

    def _work(index: int, it: BenchmarkItem) -> tuple[int, dict, float]:
        q_started = time.perf_counter()
        rec = _process_one_api_item(
            it=it,
            framework=framework,
            suite=suite,
            api_url=api_url,
            timeout_s=timeout_s,
            dsn=dsn,
            sql_timeout_ms=sql_timeout_ms,
            max_rows=max_rows,
            eval_engine=eval_engine,
            sqlite_databases_dir=sqlite_databases_dir,
            ex_mode=ex_mode,
        )
        return index, rec, q_started

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("", encoding="utf-8")

    results: List[Optional[dict]] = [None] * total_items
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_work, i, it) for i, it in enumerate(items)]
        for fut in as_completed(futures):
            index, rec, q_started = fut.result()
            results[index] = rec
            with print_lock:
                done_count += 1
                if out_path is not None:
                    with out_path.open("a", encoding="utf-8") as af:
                        af.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        af.flush()
                _print_progress(
                    done_count, total_items, items[index].question_id, q_started, run_started
                )

    ordered = [r for r in results if r is not None]
    if out_path is not None:
        with out_path.open("w", encoding="utf-8") as f:
            for r in ordered:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return ordered


def cmd_run_api(args: argparse.Namespace) -> int:
    framework = normalize_framework(args.framework)
    if framework not in API_FRAMEWORKS:
        print(f"run-api supports: {sorted(API_FRAMEWORKS)}", file=sys.stderr)
        return 2

    q_path, g_path = suite_paths(args.suite)
    items = load_questions_file(q_path)
    gold_map = load_gold_jsonl(g_path)
    items = merge_gold(items, gold_map)
    if getattr(args, "limit", None):
        items = items[: int(args.limit)]

    api_url = (args.api_url or default_api_url(framework)).rstrip("/")
    if not api_url.endswith("/v1/chat"):
        api_url = f"{api_url}/v1/chat"

    out_path = Path(args.out) if args.out else _default_out(f"{framework}_api", args.suite)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    workers = max(1, int(getattr(args, "workers", 1) or 1))
    eval_engine = (getattr(args, "eval_engine", None) or "postgres").strip().lower()
    sqlite_dir = getattr(args, "sqlite_databases_dir", None)
    ex_mode = (getattr(args, "ex_mode", None) or "multiset").strip().lower()
    if eval_engine == "sqlite" and not sqlite_dir:
        print("run-api --eval-engine sqlite requires --sqlite-databases-dir", file=sys.stderr)
        return 2
    if eval_engine == "sqlite" and not getattr(args, "dsn", None):
        # DSN unused for sqlite; keep argparse happy when callers pass a placeholder.
        args.dsn = args.dsn or "postgresql://unused"
    results = _run_api_items(
        items=items,
        framework=framework,
        suite=args.suite,
        api_url=api_url,
        timeout_s=args.timeout,
        dsn=args.dsn,
        sql_timeout_ms=args.sql_timeout_ms,
        max_rows=args.max_rows,
        workers=workers,
        out_path=out_path,
        eval_engine=eval_engine,
        sqlite_databases_dir=sqlite_dir,
        ex_mode=ex_mode,
    )

    scored = 0
    sum_ex = 0
    sum_sf1 = 0.0
    executable_count = 0
    for rec in results:
        if rec.get("executable"):
            executable_count += 1
        if rec.get("pred_sql") and "eval_error" not in rec and rec.get("error") != "missing_gold":
            scored += 1
            sum_ex += int(rec.get("ex") or False)
            sum_sf1 += float(rec.get("soft_f1") or 0.0)

    # Ordered rewrite already done inside _run_api_items when out_path is set.
    n = scored or 1
    total_n = len(results) or 1
    summary = {
        "framework": framework,
        "mode": "api",
        "suite": args.suite,
        "api_url": api_url,
        "workers": workers,
        "eval_engine": eval_engine,
        "ex_mode": ex_mode,
        "count": len(results),
        "executable": executable_count,
        "executable_rate": executable_count / total_n,
        "scored": scored,
        "mean_ex": sum_ex / n,
        "mean_soft_f1": sum_sf1 / n,
        "out": str(out_path),
    }
    print(json.dumps(summary, indent=2))
    return 0


def _print_progress(idx: int, total: int, qid: str, q_started: float, run_started: float) -> None:
    q_elapsed = time.perf_counter() - q_started
    elapsed = time.perf_counter() - run_started
    avg = elapsed / idx
    eta_remaining = avg * (total - idx)
    eta_finish = datetime.now().astimezone().fromtimestamp(datetime.now().timestamp() + eta_remaining)
    print(
        f"[{idx}/{total}] id={qid} latency={q_elapsed*1000:.0f}ms "
        f"elapsed={_fmt_duration(elapsed)} eta_left={_fmt_duration(eta_remaining)} "
        f"eta_finish_local={eta_finish.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        flush=True,
    )


def cmd_summarize(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.jsonl]
    summaries = []
    for path in paths:
        if not path.is_file():
            print(f"Missing: {path}", file=sys.stderr)
            return 2
        s = summarize_jsonl(path)
        s["path"] = str(path)
        summaries.append(s)
    print(json.dumps(summaries, indent=2))
    if args.table:
        print()
        print(format_summary_table(summaries))
    return 0


def cmd_smoke_ui(args: argparse.Namespace) -> int:
    """Verify Playwright can reach framework UI (ensure_ready + optional one short ask)."""
    framework = normalize_framework(args.framework)
    ui_url = args.ui_url
    with UIAskerSession(
        framework=framework,
        ui_url=ui_url,
        headless=not args.headed,
    ) as session:
        print(json.dumps({"framework": framework, "ensure_ready": "ok", "ui_url": session.ui_url}))
        if not args.ask:
            return 0
        sample = (args.question or "how many tables in db").strip()
        result = session.ask(sample, timeout_s=args.timeout)
        payload = {
            "framework": framework,
            "ask_ok": result.error is None,
            "pred_sql": result.pred_sql,
            "latency_ms": result.latency_ms,
            "error": result.error,
        }
        print(json.dumps(payload, indent=2))
        return 0 if result.error is None else 1


def cmd_eval_sql(args: argparse.Namespace) -> int:
    """Execute predicted SQL vs gold for one question_id (EX / soft_f1)."""
    pred_sql = (args.pred_sql or "").strip()
    if not pred_sql and args.pred_file:
        pred_sql = Path(args.pred_file).read_text(encoding="utf-8").strip()
    if not pred_sql:
        print("Provide --pred-sql or --pred-file", file=sys.stderr)
        return 2

    try:
        item = lookup_benchmark_item(args.question_id)
    except (KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not item.gold_sql.strip():
        print(f"No gold SQL for question_id={item.question_id}", file=sys.stderr)
        return 2

    gold_sql = strip_sql_comments(item.gold_sql)
    pred_sql = strip_sql_comments(pred_sql)
    report: dict = {
        "question_id": item.question_id,
        "db_id": item.db_id,
        "question": item.question,
        "gold_sql": gold_sql,
        "pred_sql": pred_sql,
    }
    if item.evidence:
        report["evidence"] = item.evidence

    try:
        _, gold_rows = run_query(
            args.dsn, gold_sql, timeout_ms=args.sql_timeout_ms, max_rows=args.max_rows
        )
    except Exception as exc:  # noqa: BLE001
        report["eval_error"] = f"gold_sql: {exc}"
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    try:
        _, pred_rows = run_query(
            args.dsn, pred_sql, timeout_ms=args.sql_timeout_ms, max_rows=args.max_rows
        )
    except Exception as exc:  # noqa: BLE001
        report["eval_error"] = f"pred_sql: {exc}"
        report["gold_preview"] = gold_rows[: args.preview_rows]
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 1

    ex, sf1, alias_mismatch = execution_metrics(gold_rows, pred_rows)
    report["ex"] = ex
    report["soft_f1"] = sf1
    if alias_mismatch:
        report["alias_mismatch"] = True
    report["gold_row_count"] = len(gold_rows)
    report["pred_row_count"] = len(pred_rows)
    if args.preview_rows:
        report["gold_preview"] = gold_rows[: args.preview_rows]
        report["pred_preview"] = pred_rows[: args.preview_rows]
    if not ex:
        report["mismatch"] = summarize_mismatch(
            gold_rows, pred_rows, max_examples=args.preview_rows
        )

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if ex else 1


def cmd_build_suites(args: argparse.Namespace) -> int:
    script = harness_root() / "scripts" / "build_minidev_suites.py"
    import subprocess

    cmd = [sys.executable, str(script)]
    if args.all_suites:
        cmd.append("--all")
    elif args.suite:
        cmd.extend(["--suite", args.suite])
    else:
        cmd.append("--all")
    proc = subprocess.run(cmd, check=False)
    return int(proc.returncode)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="NL2SQL comparison harness (UI-only benchmark runs)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run UI benchmark for one framework (stack must be up)")
    r.add_argument("--framework", required=True, choices=sorted(UI_FRAMEWORKS))
    r.add_argument("--suite", default="smoke_3", help="Suite name under test_suites/minidev/")
    r.add_argument("--limit", type=int, help="Run only the first N questions (smoke/debug)")
    r.add_argument("--dsn", required=True, help='PostgreSQL DSN e.g. postgresql://olap:olap@127.0.0.1:55432/bird')
    r.add_argument("--out", help="Output JSONL path")
    r.add_argument("--ui-url", help="Override framework UI URL")
    r.add_argument("--timeout", type=float, default=300.0, help="Per-question UI timeout (seconds)")
    r.add_argument("--sql-timeout-ms", type=int, default=60_000)
    r.add_argument("--max-rows", type=int, default=500)
    r.add_argument("--trace-dir", help="Playwright trace directory")
    r.add_argument("--trace", action="store_true", help="Save Playwright traces on failures")
    r.add_argument("--headed", action="store_true", help="Run browser headed (debug)")
    r.add_argument(
        "--resources",
        choices=["none", "local_docker"],
        default="local_docker",
        help="Resource sampling provider",
    )
    r.add_argument(
        "--stack-containers",
        help="Comma-separated docker container names for stack CPU/mem sampling",
    )
    r.add_argument("--debug-http", action="store_true", help="Probe HTTP health before run (not scored)")
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("run-api", help="Run API benchmark (langchain/dbgpt /v1/chat; same EX scoring)")
    a.add_argument("--framework", required=True, choices=sorted(API_FRAMEWORKS))
    a.add_argument("--suite", default="smoke_3", help="Suite name under test_suites/minidev/")
    a.add_argument("--limit", type=int, help="Run only the first N questions")
    a.add_argument(
        "--dsn",
        default="postgresql://olap:olap@127.0.0.1:55433/bird",
        help="PostgreSQL DSN for gold/pred execution (ignored when --eval-engine sqlite)",
    )
    a.add_argument("--out", help="Output JSONL path")
    a.add_argument("--api-url", help="Base or full chat URL (default per framework, port 8011/8012)")
    a.add_argument("--timeout", type=float, default=900.0, help="Per-question API timeout (seconds)")
    a.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent API request workers (default 1 = sequential)",
    )
    a.add_argument("--sql-timeout-ms", type=int, default=60_000)
    a.add_argument("--max-rows", type=int, default=500)
    a.add_argument(
        "--eval-engine",
        choices=["postgres", "sqlite"],
        default="postgres",
        help="Where to execute gold/pred for EX (sqlite = Study Gen EX path)",
    )
    a.add_argument(
        "--sqlite-databases-dir",
        help="Path to MINIDEV/dev_databases (required for --eval-engine sqlite)",
    )
    a.add_argument(
        "--ex-mode",
        choices=["bird", "multiset"],
        default="multiset",
        help="bird = set equality (Study/BIRD leaderboard); multiset = Counter equality",
    )
    a.set_defaults(func=cmd_run_api)

    s = sub.add_parser("summarize", help="Summarize one or more JSONL run files")
    s.add_argument("jsonl", nargs="+", help="Paths to run JSONL files")
    s.add_argument("--table", action="store_true", help="Print markdown table")
    s.set_defaults(func=cmd_summarize)

    u = sub.add_parser("smoke-ui", help="Smoke-test UI reachability (ensure_ready; optional one ask)")
    u.add_argument("--framework", required=True, choices=sorted(UI_FRAMEWORKS))
    u.add_argument("--ui-url", help="Override framework UI URL")
    u.add_argument("--timeout", type=float, default=120.0, help="Per-question timeout when --ask is set")
    u.add_argument("--ask", action="store_true", help="Submit one sample question after ensure_ready")
    u.add_argument(
        "--question",
        default="how many tables in db",
        help="NL question when --ask is set (operator smoke gate)",
    )
    u.add_argument("--headed", action="store_true")
    u.set_defaults(func=cmd_smoke_ui)

    b = sub.add_parser("build-suites", help="Regenerate minidev suite files from datasets/")
    b.add_argument("--suite", help="Single suite name")
    b.add_argument("--all-suites", action="store_true")
    b.set_defaults(func=cmd_build_suites)

    e = sub.add_parser(
        "eval-sql",
        help="Compare predicted SQL vs gold for one question_id (EX / soft_f1)",
    )
    e.add_argument("--question-id", required=True, help="BIRD minidev question_id (e.g. 847)")
    e.add_argument("--pred-sql", help="Generated SQL to score")
    e.add_argument("--pred-file", help="File containing generated SQL")
    e.add_argument(
        "--dsn",
        default="postgresql://olap:olap@127.0.0.1:55432/bird",
        help="PostgreSQL DSN (local 1-db :55432; AWS tunnel :55433)",
    )
    e.add_argument("--sql-timeout-ms", type=int, default=60_000)
    e.add_argument("--max-rows", type=int, default=500)
    e.add_argument("--preview-rows", type=int, default=12, help="Rows shown in JSON preview")
    e.set_defaults(func=cmd_eval_sql)

    args = p.parse_args(argv)

    if getattr(args, "debug_http", False) and args.cmd == "run":
        from nl2sql_comparison_harness.debug.http_probes import FRAMEWORK_DEBUG_URLS, probe_url

        url = FRAMEWORK_DEBUG_URLS.get(normalize_framework(args.framework))
        if url:
            ok, err = probe_url(url)
            print(f"HTTP probe {url}: {'OK' if ok else err}")

    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
