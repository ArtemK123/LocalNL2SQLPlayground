from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from doris_test_harness.api_client import ask_via_api
from doris_test_harness.metrics import execution_match, soft_f1


@dataclass
class QuestionItem:
    question_id: str
    db_id: str
    question: str
    gold_sql: str
    evidence: str | None = None


def load_suite(path: Path, gold_path: Path) -> list[QuestionItem]:
    questions = json.loads(path.read_text(encoding="utf-8"))
    gold_by_id: dict[str, str] = {}
    for line in gold_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        gold_by_id[str(row["question_id"])] = row["SQL"]
    out: list[QuestionItem] = []
    for q in questions:
        qid = str(q["question_id"])
        ev = q.get("evidence")
        out.append(
            QuestionItem(
                question_id=qid,
                db_id=q.get("db_id", ""),
                question=q["question"],
                gold_sql=gold_by_id[qid],
                evidence=str(ev) if isinstance(ev, str) and ev.strip() else None,
            )
        )
    return out


def execute_sql(dsn: str, sql: str, max_rows: int = 200) -> tuple[list[str], list[dict[str, Any]], str | None]:
    try:
        engine = create_engine(dsn, pool_pre_ping=True)
        wrapped = f"SELECT * FROM ({sql}) AS q LIMIT :lim"
        with engine.connect() as conn:
            if "postgresql" in dsn:
                conn.execute(text("SET statement_timeout = 30000"))
            elif "mysql" in dsn:
                conn.execute(text("SET max_execution_time = 30000"))
            result = conn.execute(text(wrapped), {"lim": max_rows})
            rows = [dict(r._mapping) for r in result]
            cols = list(result.keys())
        return cols, rows, None
    except Exception as exc:  # noqa: BLE001
        return [], [], str(exc)


def run_benchmark(
    *,
    suite_path: Path,
    gold_path: Path,
    gold_dsn: str,
    pred_dsn: str,
    api_url: str,
    results_dir: Path,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    items = load_suite(suite_path, gold_path)
    results_dir.mkdir(parents=True, exist_ok=True)
    rows_out: list[dict[str, Any]] = []
    ex_hits = 0
    f1_sum = 0.0

    for item in items:
        api = ask_via_api(
            api_url=api_url,
            question=item.question,
            timeout_s=timeout_s,
            db_id=item.db_id or None,
            evidence=item.evidence,
        )
        record: dict[str, Any] = {
            "question_id": item.question_id,
            "db_id": item.db_id,
            "question": item.question,
            "pred_sql": api.pred_sql,
            "api_error": api.error,
            "latency_ms": api.latency_ms,
            "api_ok": bool(api.pred_sql) and api.error is None,
        }
        if not api.pred_sql:
            record["ex"] = None
            record["soft_f1"] = None
            rows_out.append(record)
            continue

        _, gold_rows, gold_err = execute_sql(gold_dsn, item.gold_sql)
        _, pred_rows, pred_err = execute_sql(pred_dsn, api.pred_sql)
        record["gold_error"] = gold_err
        record["pred_error"] = pred_err
        record["gold_ok"] = gold_err is None
        record["pred_ok"] = pred_err is None
        record["dual_ok"] = record["gold_ok"] and record["pred_ok"]
        if gold_err or pred_err:
            record["ex"] = None
            record["soft_f1"] = None
            if gold_err and pred_err:
                record["eval_error"] = f"gold:{gold_err} | pred:{pred_err}"
            elif gold_err:
                record["eval_error"] = f"gold:{gold_err}"
            else:
                record["eval_error"] = f"pred:{pred_err}"
        else:
            record["ex"] = execution_match(gold_rows, pred_rows)
            record["soft_f1"] = soft_f1(gold_rows, pred_rows)
            if record["ex"]:
                ex_hits += 1
            f1_sum += record["soft_f1"]
        rows_out.append(record)

    n = len(items)
    dual_ok = [r for r in rows_out if r.get("dual_ok")]
    summary = {
        "stack": "doris_cdc",
        "eval_mode": "dual_dsn",
        "suite": suite_path.name,
        "n": n,
        "n_dual_ok": len(dual_ok),
        "ex_among_dual_ok": (ex_hits / len(dual_ok)) if dual_ok else None,
        "ex": ex_hits / n if n else 0.0,
        "avg_soft_f1": f1_sum / len(dual_ok) if dual_ok else None,
        "api_url": api_url,
        "gold_dsn": gold_dsn.split("@")[-1] if "@" in gold_dsn else gold_dsn,
        "pred_dsn": pred_dsn.split("@")[-1] if "@" in pred_dsn else pred_dsn,
    }
    (results_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows_out) + "\n", encoding="utf-8"
    )
    (results_dir / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md = [
        f"# Run {results_dir.name}",
        "",
        f"- stack: doris_cdc",
        f"- eval_mode: dual_dsn",
        f"- n_dual_ok: {summary['n_dual_ok']}/{n}",
        f"- EX among dual_ok: {summary['ex_among_dual_ok']}",
        f"- avg soft_f1 among dual_ok: {summary['avg_soft_f1']}",
    ]
    (results_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary
