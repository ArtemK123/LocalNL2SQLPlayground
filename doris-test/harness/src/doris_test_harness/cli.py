from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from doris_test_harness.api_client import ask_via_api
from doris_test_harness.compare import execution_metrics
from doris_test_harness.dataset import (
    harness_root,
    load_gold_jsonl,
    load_questions_file,
    merge_gold,
    strip_sql_comments,
    suite_paths,
)
from doris_test_harness.db import rewrite_scalar_eq_subqueries_for_doris, run_query
from doris_test_harness.judge import (
    JUDGE_PROMPT_VERSION,
    judge_equivalence,
)

EVAL_MODES = {
    "dual_dsn",
    "doris",
    "mysql",
    "postgres",
    "sqlite",
    "dual_dsn_llm_judge",
    "judge_equiv",
}

JUDGE_MODES = {"dual_dsn_llm_judge", "judge_equiv"}


def _normalize_eval_mode(raw: str) -> str:
    mode = (raw or "dual_dsn").strip().lower()
    if mode in {"doris", "mysql"}:
        return "dual_dsn"
    if mode == "judge_equiv":
        return "dual_dsn_llm_judge"
    return mode


def _resolve_sqlite_db_path(databases_dir: str | Path, db_id: str) -> Path:
    base = Path(databases_dir)
    return base / db_id / f"{db_id}.sqlite"


def _run_query_sqlite(
    db_path: Path,
    sql: str,
    *,
    timeout_ms: int,
    max_rows: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    sql = sql.strip().rstrip(";")
    timeout_s = max(0.1, float(timeout_ms) / 1000.0)
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=min(5.0, timeout_s))
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(min(5.0, timeout_s) * 1000)}")
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description is None:
            return [], []
        cols = [d[0] for d in cur.description]
        raw = cur.fetchmany(int(max_rows) + 1) if max_rows > 0 else cur.fetchall()
        if max_rows > 0 and len(raw) > max_rows:
            raw = raw[:max_rows]
        return cols, [dict(zip(cols, tup)) for tup in raw]
    finally:
        conn.close()


def _normalize_ex_mode(raw: str | None) -> str:
    mode = (raw or "bird").strip().lower()
    if mode in {"multiset", "name"}:
        return "strict"
    if mode not in {"bird", "strict"}:
        return "bird"
    return mode


def _attach_result_shape(
    rec: dict[str, Any],
    *,
    gold_cols: list[str] | None,
    gold_rows: list[dict[str, Any]] | None,
    pred_cols: list[str] | None,
    pred_rows: list[dict[str, Any]] | None,
) -> None:
    if gold_cols is not None or gold_rows is not None:
        gcols = list(gold_cols) if gold_cols is not None else (
            list(gold_rows[0].keys()) if gold_rows else []
        )
        rec["gold_columns"] = gcols
        rec["n_cols_gold"] = len(gcols)
        rec["n_rows_gold"] = len(gold_rows or [])
    if pred_cols is not None or pred_rows is not None:
        pcols = list(pred_cols) if pred_cols is not None else (
            list(pred_rows[0].keys()) if pred_rows else []
        )
        rec["pred_columns"] = pcols
        rec["n_cols_pred"] = len(pcols)
        rec["n_rows_pred"] = len(pred_rows or [])


def _safe_run_query(
    *,
    eval_mode: str,
    which: str,
    sql: str,
    gold_dsn: str | None,
    pred_dsn: str | None,
    sqlite_databases_dir: str | None,
    db_id: str | None,
    sql_timeout_ms: int,
    max_rows: int,
) -> tuple[list[str] | None, list[dict[str, Any]] | None, str | None]:
    """Execute gold or pred SQL; return (cols, rows, error). Never raises."""
    try:
        if eval_mode == "sqlite":
            if not db_id:
                raise ValueError("db_id required for sqlite eval")
            if not sqlite_databases_dir:
                raise ValueError("--sqlite-databases-dir required for sqlite eval")
            db_path = _resolve_sqlite_db_path(sqlite_databases_dir, db_id)
            cols, rows = _run_query_sqlite(
                db_path, sql, timeout_ms=sql_timeout_ms, max_rows=max_rows
            )
            return cols, rows, None
        if eval_mode == "postgres":
            if not gold_dsn:
                raise ValueError("--gold-dsn (or --dsn) required for postgres eval")
            cols, rows = run_query(
                gold_dsn, sql, timeout_ms=sql_timeout_ms, max_rows=max_rows, schema=db_id
            )
            return cols, rows, None
        # dual_dsn (+ llm judge): gold on PG, pred on Doris/MySQL
        if which == "gold":
            if not gold_dsn:
                raise ValueError("--gold-dsn required")
            cols, rows = run_query(
                gold_dsn, sql, timeout_ms=sql_timeout_ms, max_rows=max_rows, schema=db_id
            )
        else:
            dsn = pred_dsn or gold_dsn
            if not dsn:
                raise ValueError("--pred-dsn required for dual_dsn")
            cols, rows = run_query(
                dsn, sql, timeout_ms=sql_timeout_ms, max_rows=max_rows, schema=db_id
            )
        return cols, rows, None
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)


def _apply_judge(
    rec: dict[str, Any],
    *,
    question: str,
    gold_sql: str,
    pred_sql: str,
    gold_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    evidence: str | None,
    judge_base_url: str | None,
    judge_model: str | None,
    judge_api_key: str,
    judge_max_rows: int,
    judge_timeout_s: float,
    judge_fn: Any = None,
) -> None:
    verdict, meta = judge_equivalence(
        question=question,
        gold_sql=gold_sql,
        pred_sql=pred_sql,
        gold_rows=gold_rows,
        pred_rows=pred_rows,
        evidence=evidence,
        judge_fn=judge_fn,
        judge_base_url=judge_base_url,
        judge_model=judge_model,
        judge_api_key=judge_api_key,
        max_rows=judge_max_rows,
        timeout_s=judge_timeout_s,
    )
    rec["llm_equivalent"] = verdict.equivalent
    rec["llm_confidence"] = verdict.confidence
    rec["llm_rationale"] = verdict.rationale
    rec["llm_mismatch_kind"] = verdict.mismatch_kind
    rec["llm_abstained"] = verdict.abstained
    rec.update(meta)


def _score_item(
    *,
    it: Any,
    api: Any,
    eval_mode: str,
    gold_dsn: str | None,
    pred_dsn: str | None,
    sqlite_databases_dir: str | None,
    sql_timeout_ms: int,
    max_rows: int,
    judge_base_url: str | None = None,
    judge_model: str | None = None,
    judge_api_key: str = "EMPTY",
    judge_max_rows: int = 50,
    judge_timeout_s: float = 60.0,
    judge_fn: Any = None,
    ex_mode: str = "bird",
    gold_rows_saved: list[dict[str, Any]] | None = None,
    pred_rows_saved: list[dict[str, Any]] | None = None,
    gold_cols_saved: list[str] | None = None,
    pred_cols_saved: list[str] | None = None,
) -> dict:
    use_judge = eval_mode == "dual_dsn_llm_judge"
    score_mode = "dual_dsn" if use_judge else eval_mode
    ex_mode_n = _normalize_ex_mode(ex_mode)

    rec: dict = {
        "question_id": it.question_id,
        "db_id": it.db_id,
        "question": it.question,
        "evidence": getattr(it, "evidence", None),
        "gold_sql": it.gold_sql,
        "pred_sql": api.pred_sql,
        "api_error": api.error,
        "latency_ms": api.latency_ms,
        "eval_mode": eval_mode,
        "ex_mode": ex_mode_n,
        "api_ok": bool(api.pred_sql) and api.error is None,
        "gold_ok": False,
        "pred_ok": False,
        "dual_ok": False,
    }
    if not api.pred_sql or not it.gold_sql:
        rec["ex"] = None
        rec["soft_f1"] = None
        rec["failure"] = api.error or ("missing_gold" if not it.gold_sql else "empty_pred_sql")
        return rec

    gold_sql = strip_sql_comments(it.gold_sql)
    pred_sql = strip_sql_comments(api.pred_sql)
    if score_mode not in {"postgres", "sqlite"}:
        rewritten = rewrite_scalar_eq_subqueries_for_doris(pred_sql)
        if rewritten != pred_sql:
            rec["pred_sql_doris"] = rewritten
            pred_sql = rewritten

    use_saved = gold_rows_saved is not None and pred_rows_saved is not None
    if use_saved:
        gold_cols, gold_rows, gold_err = gold_cols_saved, gold_rows_saved, None
        pred_cols, pred_rows, pred_err = pred_cols_saved, pred_rows_saved, None
    else:
        gold_cols, gold_rows, gold_err = _safe_run_query(
            eval_mode=score_mode,
            which="gold",
            sql=gold_sql,
            gold_dsn=gold_dsn,
            pred_dsn=pred_dsn,
            sqlite_databases_dir=sqlite_databases_dir,
            db_id=it.db_id,
            sql_timeout_ms=sql_timeout_ms,
            max_rows=max_rows,
        )
        pred_cols, pred_rows, pred_err = _safe_run_query(
            eval_mode=score_mode,
            which="pred",
            sql=pred_sql,
            gold_dsn=gold_dsn,
            pred_dsn=pred_dsn,
            sqlite_databases_dir=sqlite_databases_dir,
            db_id=it.db_id,
            sql_timeout_ms=sql_timeout_ms,
            max_rows=max_rows,
        )
    if gold_err:
        rec["gold_error"] = gold_err
    if pred_err:
        rec["pred_error"] = pred_err
    rec["gold_ok"] = gold_err is None
    rec["pred_ok"] = pred_err is None
    rec["dual_ok"] = rec["gold_ok"] and rec["pred_ok"]
    _attach_result_shape(
        rec,
        gold_cols=gold_cols,
        gold_rows=gold_rows,
        pred_cols=pred_cols,
        pred_rows=pred_rows,
    )

    if not rec["dual_ok"]:
        rec["ex"] = None
        rec["soft_f1"] = None
        parts = []
        if gold_err:
            parts.append(f"gold:{gold_err}")
        if pred_err:
            parts.append(f"pred:{pred_err}")
        # Keep opaque eval_error for backward compatibility, but prefer split fields.
        rec["eval_error"] = " | ".join(parts)
        rec["failure"] = "gold_error" if gold_err and not pred_err else (
            "pred_error" if pred_err and not gold_err else "dual_exec_error"
        )
        return rec

    assert gold_rows is not None and pred_rows is not None
    ex, sf1, alias_mismatch = execution_metrics(gold_rows, pred_rows, ex_mode=ex_mode_n)  # type: ignore[arg-type]
    rec["ex"] = ex
    rec["soft_f1"] = sf1
    if alias_mismatch:
        rec["alias_mismatch"] = True
    if not ex:
        rec["failure"] = "ex_mismatch_alias" if alias_mismatch else "ex_mismatch"

    if use_judge:
        try:
            _apply_judge(
                rec,
                question=it.question,
                gold_sql=gold_sql,
                pred_sql=pred_sql,
                gold_rows=gold_rows,
                pred_rows=pred_rows,
                evidence=getattr(it, "evidence", None),
                judge_base_url=judge_base_url,
                judge_model=judge_model,
                judge_api_key=judge_api_key,
                judge_max_rows=judge_max_rows,
                judge_timeout_s=judge_timeout_s,
                judge_fn=judge_fn,
            )
        except Exception as exc:  # noqa: BLE001
            rec["llm_equivalent"] = None
            rec["llm_error"] = str(exc)
            rec["judge_prompt_version"] = JUDGE_PROMPT_VERSION
            rec["failure"] = "judge_error"
    return rec


def _summarize(records: list[dict[str, Any]], *, eval_mode: str) -> dict[str, Any]:
    n = len(records)
    n_api_ok = sum(1 for r in records if r.get("api_ok"))
    n_gold_ok = sum(1 for r in records if r.get("gold_ok"))
    n_pred_ok = sum(1 for r in records if r.get("pred_ok"))
    dual_ok = [r for r in records if r.get("dual_ok")]
    n_dual_ok = len(dual_ok)
    # Classic EX only among items where both engines returned rows.
    ex_hits = sum(1 for r in dual_ok if r.get("ex") is True)
    soft_vals = [float(r["soft_f1"]) for r in dual_ok if r.get("soft_f1") is not None]
    lat = [float(r["latency_ms"]) for r in records if r.get("latency_ms") is not None]

    summary: dict[str, Any] = {
        "eval_mode": eval_mode,
        "n": n,
        "n_api_ok": n_api_ok,
        "n_gold_ok": n_gold_ok,
        "n_pred_ok": n_pred_ok,
        "n_dual_ok": n_dual_ok,
        "n_scored": n_dual_ok,
        "ex_among_dual_ok": (ex_hits / n_dual_ok) if n_dual_ok else None,
        "ex_count_among_dual_ok": ex_hits,
        # Denominator-all (legacy-looking) rates — do not treat as true zeros on failures.
        "ex_over_all": (ex_hits / n) if n else 0.0,
        "soft_f1_mean_among_dual_ok": (sum(soft_vals) / len(soft_vals)) if soft_vals else None,
        "latency_ms_mean": (sum(lat) / len(lat)) if lat else None,
        "n_api_fail": sum(1 for r in records if r.get("api_error")),
        "n_gold_fail": sum(1 for r in records if r.get("gold_error")),
        "n_pred_fail": sum(1 for r in records if r.get("pred_error")),
        "n_alias_mismatch": sum(1 for r in dual_ok if r.get("alias_mismatch")),
    }

    judged = [r for r in dual_ok if r.get("llm_equivalent") is not None]
    if judged or eval_mode == "dual_dsn_llm_judge":
        eq = sum(1 for r in judged if r.get("llm_equivalent") is True)
        abstain = sum(1 for r in records if r.get("llm_abstained"))
        summary["llm_judge"] = {
            "prompt_version": JUDGE_PROMPT_VERSION,
            "n_judged": len(judged),
            "n_equivalent": eq,
            "equiv_rate_among_judged": (eq / len(judged)) if judged else None,
            "equiv_rate_among_dual_ok": (eq / n_dual_ok) if n_dual_ok else None,
            "n_abstained": abstain,
            "n_judge_error": sum(1 for r in records if r.get("llm_error")),
        }
    return summary


def _add_judge_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--judge-base-url",
        default=os.environ.get("JUDGE_BASE_URL") or os.environ.get("VLLM_BASE_URL"),
        help="OpenAI-compatible base URL for LLM judge (env JUDGE_BASE_URL / VLLM_BASE_URL)",
    )
    p.add_argument(
        "--judge-model",
        default=os.environ.get("JUDGE_MODEL", "Snowflake/Arctic-Text2SQL-R1-7B"),
        help="Judge model id (fixed for a run; env JUDGE_MODEL)",
    )
    p.add_argument(
        "--judge-api-key",
        default=os.environ.get("JUDGE_API_KEY", "EMPTY"),
    )
    p.add_argument("--judge-max-rows", type=int, default=50)
    p.add_argument("--judge-timeout", type=float, default=60.0)


def _add_ex_mode_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--ex-mode",
        choices=["bird", "strict"],
        default="bird",
        help=(
            "bird = positional/BIRD-fair EX, ignore aliases (default for dual_dsn); "
            "strict = match columns by name (None-fill missing aliases)"
        ),
    )


def cmd_run_api(args: argparse.Namespace) -> int:
    q_path, g_path = suite_paths(args.suite)
    items = merge_gold(load_questions_file(q_path), load_gold_jsonl(g_path))
    if args.limit:
        items = items[: int(args.limit)]

    eval_mode = _normalize_eval_mode(args.eval_mode)
    ex_mode = _normalize_ex_mode(getattr(args, "ex_mode", None))
    if eval_mode not in {"dual_dsn", "postgres", "sqlite", "dual_dsn_llm_judge"}:
        print(f"Unsupported --eval-mode {eval_mode}", file=sys.stderr)
        return 2

    gold_dsn = args.gold_dsn or args.dsn
    pred_dsn = args.pred_dsn
    if eval_mode in {"dual_dsn", "dual_dsn_llm_judge"} and (not gold_dsn or not pred_dsn):
        print("dual_dsn / dual_dsn_llm_judge requires --gold-dsn and --pred-dsn", file=sys.stderr)
        return 2
    if eval_mode == "postgres" and not gold_dsn:
        print("postgres eval requires --gold-dsn or --dsn", file=sys.stderr)
        return 2
    if eval_mode == "sqlite" and not args.sqlite_databases_dir:
        print("sqlite eval requires --sqlite-databases-dir", file=sys.stderr)
        return 2
    if eval_mode == "dual_dsn_llm_judge" and not (args.judge_base_url and args.judge_model):
        print(
            "dual_dsn_llm_judge requires --judge-base-url and --judge-model "
            "(or JUDGE_BASE_URL / VLLM_BASE_URL env)",
            file=sys.stderr,
        )
        return 2

    out = (
        Path(args.out)
        if args.out
        else harness_root() / "runs" / f"langchain_{args.suite}_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")

    workers = max(1, int(args.workers or 1))
    results: list[Optional[dict]] = [None] * len(items)
    print_lock = __import__("threading").Lock()

    def _work(idx: int, it: Any) -> tuple[int, dict]:
        api = ask_via_api(
            api_url=args.api_url,
            question=it.question,
            timeout_s=args.timeout,
            db_id=getattr(it, "db_id", None),
            evidence=getattr(it, "evidence", None),
        )
        rec = _score_item(
            it=it,
            api=api,
            eval_mode=eval_mode,
            gold_dsn=gold_dsn,
            pred_dsn=pred_dsn,
            sqlite_databases_dir=args.sqlite_databases_dir,
            sql_timeout_ms=args.sql_timeout_ms,
            max_rows=args.max_rows,
            judge_base_url=args.judge_base_url,
            judge_model=args.judge_model,
            judge_api_key=args.judge_api_key,
            judge_max_rows=args.judge_max_rows,
            judge_timeout_s=args.judge_timeout,
            ex_mode=ex_mode,
        )
        return idx, rec

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_work, i, it) for i, it in enumerate(items)]
        done = 0
        for fut in as_completed(futures):
            idx, rec = fut.result()
            results[idx] = rec
            with print_lock:
                done += 1
                with out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(
                    f"[{done}/{len(items)}] {rec.get('question_id')}: "
                    f"ex={rec.get('ex')} llm_eq={rec.get('llm_equivalent')} "
                    f"api_err={rec.get('api_error')} gold_err={bool(rec.get('gold_error'))} "
                    f"pred_err={bool(rec.get('pred_error'))}"
                )

    ordered = [r for r in results if r is not None]
    with out.open("w", encoding="utf-8") as fh:
        for rec in ordered:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    summary = _summarize(ordered, eval_mode=eval_mode)
    summary.update(
        {
            "suite": args.suite,
            "workers": workers,
            "out": str(out),
            "ex_mode": ex_mode,
        }
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    """Re-execute gold/pred SQL from an existing jsonl and optionally LLM-judge."""
    eval_mode = _normalize_eval_mode(args.eval_mode)
    ex_mode = _normalize_ex_mode(getattr(args, "ex_mode", None))
    if eval_mode not in {"dual_dsn", "postgres", "sqlite", "dual_dsn_llm_judge"}:
        print(f"Unsupported --eval-mode {eval_mode}", file=sys.stderr)
        return 2

    in_path = Path(args.jsonl)
    if not in_path.is_file():
        print(f"jsonl not found: {in_path}", file=sys.stderr)
        return 2
    rows_in: list[dict[str, Any]] = []
    for line in in_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows_in.append(json.loads(line))

    def _has_saved_cells(row: dict[str, Any]) -> bool:
        return isinstance(row.get("gold_rows"), list) and isinstance(row.get("pred_rows"), list)

    scorable = [
        r
        for r in rows_in
        if r.get("pred_sql") and r.get("gold_sql")
    ]
    n_saved = sum(1 for r in scorable if _has_saved_cells(r))
    gold_dsn = args.gold_dsn or args.dsn
    pred_dsn = args.pred_dsn
    need_dsn = eval_mode in {"dual_dsn", "dual_dsn_llm_judge"}
    offline_cells = bool(scorable) and n_saved == len(scorable)
    if need_dsn and (not gold_dsn or not pred_dsn) and not offline_cells:
        print(
            "dual_dsn / dual_dsn_llm_judge rescore requires --gold-dsn and --pred-dsn "
            "(jsonl has no saved gold_rows/pred_rows; re-execute SQL). "
            "Older runs such as doris_20260814_170306 cannot recover EX offline.",
            file=sys.stderr,
        )
        return 2
    if eval_mode == "postgres" and not gold_dsn and not offline_cells:
        print("postgres rescore requires --gold-dsn or saved gold_rows/pred_rows", file=sys.stderr)
        return 2
    if eval_mode == "dual_dsn_llm_judge" and not (args.judge_base_url and args.judge_model):
        print("dual_dsn_llm_judge requires --judge-base-url and --judge-model", file=sys.stderr)
        return 2

    out_path = Path(args.out) if args.out else in_path.with_name(in_path.stem + "_rescored.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    class _Api:
        def __init__(self, pred_sql: str | None, error: str | None, latency_ms: Any):
            self.pred_sql = pred_sql
            self.error = error
            self.latency_ms = latency_ms

    class _Item:
        def __init__(self, row: dict[str, Any]):
            self.question_id = str(row.get("question_id"))
            self.db_id = row.get("db_id")
            self.question = str(row.get("question") or "")
            self.gold_sql = str(row.get("gold_sql") or "")
            self.evidence = row.get("evidence")

    suite_items: dict[str, Any] = {}
    if args.suite:
        q_path, g_path = suite_paths(args.suite)
        suite_items = {
            x.question_id: x
            for x in merge_gold(load_questions_file(q_path), load_gold_jsonl(g_path))
        }

    out_recs: list[dict[str, Any]] = []
    for row in rows_in:
        if args.skip_without_pred and not row.get("pred_sql"):
            # Preserve original failure record; do not invent scores.
            kept = dict(row)
            kept["rescored"] = False
            kept["rescore_skipped"] = "no_pred_sql"
            out_recs.append(kept)
            continue
        it = _Item(row)
        # Prefer evidence from suite merge if missing in old jsonl.
        if not it.evidence and it.question_id in suite_items:
            it.evidence = suite_items[it.question_id].evidence
        api = _Api(row.get("pred_sql"), row.get("api_error"), row.get("latency_ms"))
        saved = _has_saved_cells(row) and (offline_cells or not (gold_dsn and pred_dsn))
        rec = _score_item(
            it=it,
            api=api,
            eval_mode=eval_mode,
            gold_dsn=gold_dsn,
            pred_dsn=pred_dsn,
            sqlite_databases_dir=args.sqlite_databases_dir,
            sql_timeout_ms=args.sql_timeout_ms,
            max_rows=args.max_rows,
            judge_base_url=args.judge_base_url,
            judge_model=args.judge_model,
            judge_api_key=args.judge_api_key,
            judge_max_rows=args.judge_max_rows,
            judge_timeout_s=args.judge_timeout,
            ex_mode=ex_mode,
            gold_rows_saved=row.get("gold_rows") if saved else None,
            pred_rows_saved=row.get("pred_rows") if saved else None,
            gold_cols_saved=row.get("gold_columns") if saved else None,
            pred_cols_saved=row.get("pred_columns") if saved else None,
        )
        rec["rescored"] = True
        rec["rescore_source"] = str(in_path)
        rec["rescore_from_saved_rows"] = bool(saved)
        out_recs.append(rec)

    with out_path.open("w", encoding="utf-8") as fh:
        for rec in out_recs:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    summary = _summarize(out_recs, eval_mode=eval_mode)
    summary.update(
        {
            "in": str(in_path),
            "out": str(out_path),
            "cmd": "rescore",
            "ex_mode": ex_mode,
            "from_saved_rows": offline_cells,
        }
    )
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doris-test-harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_api = sub.add_parser(
        "run-api",
        help="LangChain API + flexible EX (dual_dsn | dual_dsn_llm_judge | postgres | sqlite)",
    )
    run_api.add_argument("--suite", required=True)
    run_api.add_argument("--api-url", default="http://127.0.0.1:8011/v1/chat")
    run_api.add_argument(
        "--eval-mode",
        default="dual_dsn",
        choices=sorted(EVAL_MODES),
        help=(
            "dual_dsn = gold PG + pred Doris (bird EX by default); "
            "dual_dsn_llm_judge|judge_equiv = bird EX + LLM logical equivalence; "
            "postgres|sqlite = single-engine EX"
        ),
    )
    run_api.add_argument("--gold-dsn", help="PostgreSQL DSN for gold SQL (dual_dsn / postgres)")
    run_api.add_argument("--pred-dsn", help="MySQL/Doris DSN for predicted SQL (dual_dsn)")
    run_api.add_argument("--dsn", help="Alias for --gold-dsn (postgres mode)")
    run_api.add_argument("--sqlite-databases-dir", help="MINIDEV/dev_databases for sqlite eval")
    run_api.add_argument("--out")
    run_api.add_argument("--limit", type=int)
    run_api.add_argument("--timeout", type=float, default=120.0)
    run_api.add_argument("--workers", type=int, default=1)
    run_api.add_argument("--sql-timeout-ms", type=int, default=60_000)
    run_api.add_argument("--max-rows", type=int, default=500)
    _add_ex_mode_arg(run_api)
    _add_judge_args(run_api)
    run_api.set_defaults(func=cmd_run_api)

    rescore = sub.add_parser(
        "rescore",
        help="Offline re-score existing jsonl (re-run SQL + optional LLM judge)",
    )
    rescore.add_argument("--jsonl", required=True, help="Input results jsonl with pred_sql")
    rescore.add_argument("--out", help="Output jsonl (default: <stem>_rescored.jsonl)")
    rescore.add_argument(
        "--eval-mode",
        default="dual_dsn",
        choices=sorted(EVAL_MODES),
    )
    rescore.add_argument("--gold-dsn")
    rescore.add_argument("--pred-dsn")
    rescore.add_argument("--dsn")
    rescore.add_argument("--sqlite-databases-dir")
    rescore.add_argument(
        "--suite",
        help="Optional suite name to backfill missing evidence from questions file",
    )
    rescore.add_argument("--sql-timeout-ms", type=int, default=60_000)
    rescore.add_argument("--max-rows", type=int, default=500)
    rescore.add_argument(
        "--skip-without-pred",
        action="store_true",
        help="Keep rows without pred_sql unchanged (default: score as empty_pred)",
    )
    _add_ex_mode_arg(rescore)
    _add_judge_args(rescore)
    rescore.set_defaults(func=cmd_rescore)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
