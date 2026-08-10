from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from nl2sql_comparison_harness.db import (
    match_columns_case_insensitive,
    multiset_signatures,
    normalize_value,
    project_row,
)

ExMode = Literal["bird", "multiset"]


def _execution_metrics_core(
    gold_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    col_map: dict[str, str],
    gold_cols: list[str],
    *,
    ex_mode: ExMode = "multiset",
) -> tuple[bool, float]:
    gold_norm = [{k: normalize_value(v) for k, v in row.items()} for row in gold_rows]
    pred_proj = [project_row(pr, gold_cols, col_map) for pr in pred_rows]

    gold_tuples = multiset_signatures(gold_norm, gold_cols)
    pred_tuples = multiset_signatures(pred_proj, gold_cols)
    if ex_mode == "bird":
        ex = set(gold_tuples) == set(pred_tuples)
    else:
        ex = Counter(gold_tuples) == Counter(pred_tuples)

    g_counter = Counter(gold_tuples)
    p_counter = Counter(pred_tuples)
    keys = set(g_counter) | set(p_counter)
    tp = sum(min(g_counter[k], p_counter[k]) for k in keys)
    fp = sum(max(0, p_counter[k] - g_counter[k]) for k in keys)
    fn = sum(max(0, g_counter[k] - p_counter[k]) for k in keys)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    soft_f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    if ex:
        soft_f1 = 1.0
    return ex, float(soft_f1)


def execution_metrics(
    gold_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    *,
    ex_mode: ExMode = "multiset",
) -> tuple[bool, float, bool]:
    """Return (ex, soft_f1, alias_mismatch). alias_mismatch when single-column names differ but rows match."""
    if not gold_rows and not pred_rows:
        return True, 1.0, False
    if not gold_rows or not pred_rows:
        return False, 0.0, False

    gold_cols = list(gold_rows[0].keys())
    pred_cols = list(pred_rows[0].keys()) if pred_rows else []
    col_map = match_columns_case_insensitive(gold_cols, pred_cols)
    ex, soft_f1 = _execution_metrics_core(
        gold_rows, pred_rows, col_map, gold_cols, ex_mode=ex_mode
    )

    alias_mismatch = (
        ex
        and len(gold_cols) == 1
        and len(pred_cols) == 1
        and gold_cols[0].lower() != pred_cols[0].lower()
    )
    return ex, soft_f1, alias_mismatch


def summarize_mismatch(
    gold_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    *,
    max_examples: int = 8,
) -> dict[str, Any]:
    """Human-readable multiset diff for eval-sql reports."""
    if not gold_rows and not pred_rows:
        return {"note": "both empty"}

    gold_cols = list(gold_rows[0].keys()) if gold_rows else list(pred_rows[0].keys())
    pred_cols = list(pred_rows[0].keys()) if pred_rows else []
    col_map = match_columns_case_insensitive(gold_cols, pred_cols)

    gold_norm = [{k: normalize_value(v) for k, v in row.items()} for row in gold_rows]
    pred_proj = [project_row(pr, gold_cols, col_map) for pr in pred_rows]

    gold_tuples = multiset_signatures(gold_norm, gold_cols)
    pred_tuples = multiset_signatures(pred_proj, gold_cols)
    g_counter = Counter(gold_tuples)
    p_counter = Counter(pred_tuples)

    missing = []
    extra = []
    for t, c in g_counter.items():
        need = c - p_counter.get(t, 0)
        if need > 0:
            missing.extend([t] * need)
    for t, c in p_counter.items():
        need = c - g_counter.get(t, 0)
        if need > 0:
            extra.extend([t] * need)

    def _rows(tuples: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
        out = []
        for t in tuples[:max_examples]:
            out.append({gold_cols[i]: t[i] for i in range(len(gold_cols))})
        return out

    return {
        "gold_row_count": len(gold_rows),
        "pred_row_count": len(pred_rows),
        "gold_distinct_rows": len(g_counter),
        "pred_distinct_rows": len(p_counter),
        "missing_from_pred": _rows(missing),
        "extra_in_pred": _rows(extra),
        "missing_count": len(missing),
        "extra_count": len(extra),
    }
