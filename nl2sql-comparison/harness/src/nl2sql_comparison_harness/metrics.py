from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Optional


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def summarize_jsonl(path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))

    if not rows:
        return {"count": 0}

    latencies = [float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]
    wall = [float(r["wall_ms"]) for r in rows if r.get("wall_ms") is not None]
    ex_vals = [bool(r.get("ex")) for r in rows if "ex" in r]
    sf1_vals = [float(r.get("soft_f1", 0.0)) for r in rows if "soft_f1" in r]

    ui_errors = sum(1 for r in rows if r.get("ui_error") or r.get("adapter_error"))
    eval_errors = sum(1 for r in rows if r.get("eval_error"))
    missing_gold = sum(1 for r in rows if r.get("error") == "missing_gold")

    resource_keys = (
        "ollama_cpu_pct_peak",
        "ollama_mem_mb_peak",
        "stack_cpu_pct_peak",
        "stack_mem_mb_peak",
        "gpu_util_pct_peak",
        "gpu_mem_mb_peak",
    )
    resource_means: dict[str, float] = {}
    for key in resource_keys:
        vals = []
        for r in rows:
            res = r.get("resources") or {}
            if isinstance(res, dict) and res.get(key) is not None:
                vals.append(float(res[key]))
        if vals:
            resource_means[f"mean_{key}"] = statistics.mean(vals)

    def _latency_stats(vals: list[float]) -> dict[str, float]:
        if not vals:
            return {}
        return {
            "mean": statistics.mean(vals),
            "median": statistics.median(vals),
            "p95": percentile(vals, 95),
        }

    scored_rows = sum(
        1
        for r in rows
        if r.get("pred_sql") and not r.get("ui_error") and not r.get("eval_error") and r.get("error") != "missing_gold"
    )
    denom = scored_rows or len(ex_vals) or 1
    return {
        "count": len(rows),
        "scored": scored_rows,
        "mean_ex": sum(int(v) for v in ex_vals) / denom if ex_vals else 0.0,
        "mean_soft_f1": sum(sf1_vals) / denom if sf1_vals else 0.0,
        "error_rate": {
            "ui_error": ui_errors,
            "eval_error": eval_errors,
            "missing_gold": missing_gold,
        },
        "latency_ms": _latency_stats(latencies),
        "wall_ms": _latency_stats(wall),
        "resources": resource_means,
        "framework": rows[0].get("framework") if rows else None,
        "suite": rows[0].get("suite") if rows else None,
    }


def format_summary_table(summaries: list[dict[str, Any]]) -> str:
    headers = ["framework", "n", "mean_ex", "mean_soft_f1", "mean_latency_ms", "p95_latency_ms", "ui_err"]
    lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for s in summaries:
        lat = s.get("latency_ms") or {}
        err = s.get("error_rate") or {}
        lines.append(
            " | ".join(
                [
                    str(s.get("framework", "")),
                    str(s.get("count", 0)),
                    f"{s.get('mean_ex', 0):.3f}",
                    f"{s.get('mean_soft_f1', 0):.3f}",
                    f"{lat.get('mean', 0):.0f}" if lat else "—",
                    f"{lat.get('p95', 0):.0f}" if lat else "—",
                    str(err.get("ui_error", 0)),
                ]
            )
        )
    return "\n".join(lines)
