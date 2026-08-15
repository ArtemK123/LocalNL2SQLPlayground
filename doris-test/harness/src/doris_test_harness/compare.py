from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from doris_test_harness.db import (
    match_columns_case_insensitive,
    multiset_signatures,
    normalize_value,
    project_row,
)

ExMode = Literal["bird", "strict"]


def _column_names(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    return list(rows[0].keys())


def _positional_tuples(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Cell tuples in result-column order (ignore aliases)."""
    return [tuple(normalize_value(v) for v in row.values()) for row in rows]


def _names_mismatch(gold_cols: list[str], pred_cols: list[str]) -> bool:
    if len(gold_cols) != len(pred_cols):
        return True
    return any(g.lower() != p.lower() for g, p in zip(gold_cols, pred_cols))


def _soft_f1(gold_tuples: list[tuple[Any, ...]], pred_tuples: list[tuple[Any, ...]], *, ex: bool) -> float:
    if ex:
        return 1.0
    g_counter = Counter(gold_tuples)
    p_counter = Counter(pred_tuples)
    keys = set(g_counter) | set(p_counter)
    tp = sum(min(g_counter[k], p_counter[k]) for k in keys)
    fp = sum(max(0, p_counter[k] - g_counter[k]) for k in keys)
    fn = sum(max(0, g_counter[k] - p_counter[k]) for k in keys)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    if (prec + rec) <= 0:
        return 0.0
    return float(2 * prec * rec / (prec + rec))


def execution_metrics(
    gold_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    *,
    ex_mode: ExMode = "bird",
) -> tuple[bool, float, bool]:
    """Return (ex, soft_f1, alias_mismatch).

    bird: match cells by column **position** (BIRD-style); ignore aliases; set equality.
          Do not None-fill missing names — unequal column counts are EX=false.
    strict: match columns by **name** (None-fill missing); Counter / multiset equality.
    """
    if not gold_rows and not pred_rows:
        return True, 1.0, False
    if not gold_rows or not pred_rows:
        return False, 0.0, False

    gold_cols = _column_names(gold_rows)
    pred_cols = _column_names(pred_rows)
    mode = (ex_mode or "bird").strip().lower()
    if mode not in {"bird", "strict"}:
        mode = "bird"

    if mode == "bird":
        gold_tuples = _positional_tuples(gold_rows)
        pred_tuples = _positional_tuples(pred_rows)
        if gold_tuples and pred_tuples and len(gold_tuples[0]) != len(pred_tuples[0]):
            ex = False
        else:
            ex = set(gold_tuples) == set(pred_tuples)
    else:
        col_map = match_columns_case_insensitive(gold_cols, pred_cols)
        gold_norm = [{k: normalize_value(v) for k, v in row.items()} for row in gold_rows]
        pred_proj = [project_row(pr, gold_cols, col_map) for pr in pred_rows]
        gold_tuples = multiset_signatures(gold_norm, gold_cols)
        pred_tuples = multiset_signatures(pred_proj, gold_cols)
        ex = Counter(gold_tuples) == Counter(pred_tuples)

    alias_mismatch = bool(ex and _names_mismatch(gold_cols, pred_cols))
    return ex, _soft_f1(gold_tuples, pred_tuples, ex=ex), alias_mismatch
