from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterable


def rows_to_multiset(rows: Iterable[dict[str, Any]]) -> Counter[tuple[Any, ...]]:
    out: Counter[tuple[Any, ...]] = Counter()
    for row in rows:
        key = tuple(json.dumps(row.get(c), sort_keys=True, default=str) for c in sorted(row.keys()))
        out[key] += 1
    return out


def execution_match(gold_rows: list[dict], pred_rows: list[dict]) -> bool:
    return rows_to_multiset(gold_rows) == rows_to_multiset(pred_rows)


def soft_f1(gold_rows: list[dict], pred_rows: list[dict]) -> float:
    g = rows_to_multiset(gold_rows)
    p = rows_to_multiset(pred_rows)
    if not g and not p:
        return 1.0
    if not g or not p:
        return 0.0
    overlap = sum(min(g[k], p[k]) for k in g.keys() & p.keys())
    precision = overlap / sum(p.values()) if p else 0.0
    recall = overlap / sum(g.values()) if g else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
