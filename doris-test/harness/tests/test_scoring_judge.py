"""Unit tests for harness scoring + LLM judge (no live AWS)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from doris_test_harness.cli import _score_item, _summarize
from doris_test_harness.compare import execution_metrics
from doris_test_harness.db import normalize_value
from doris_test_harness.judge import (
    JUDGE_PROMPT_VERSION,
    canonicalize_table,
    inputs_hash,
    judge_equivalence,
)


def test_normalize_value_decimals_and_timestamps():
    from decimal import Decimal

    assert normalize_value(Decimal("2.0")) == 2
    assert normalize_value("2024-01-02 03:04:05.123") == "2024-01-02 03:04:05"
    assert normalize_value("null") is None


def test_execution_metrics_normalized_multiset():
    gold = [{"a": "1", "b": None}]
    pred = [{"A": 1.0, "b": None}]
    ex, sf1, alias = execution_metrics(gold, pred, ex_mode="bird")
    assert ex is True
    assert sf1 == 1.0
    assert alias is False


def test_canonicalize_and_hash_stable():
    rows = [{"b": 2, "a": 1}, {"a": 0, "b": 9}]
    t1 = canonicalize_table(rows)
    t2 = canonicalize_table(list(reversed(rows)))
    assert t1["rows"] == t2["rows"]
    h1 = inputs_hash(
        question="q",
        gold_sql="SELECT 1",
        pred_sql="SELECT 1",
        gold_table=t1,
        pred_table=t2,
    )
    h2 = inputs_hash(
        question="q",
        gold_sql="SELECT 1",
        pred_sql="SELECT 1",
        gold_table=t2,
        pred_table=t1,
    )
    assert h1 == h2
    assert len(h1) == 64


def test_judge_mock_equivalent():
    def fake_judge(_messages):
        return json.dumps(
            {
                "equivalent": True,
                "confidence": 0.91,
                "rationale": "same values",
                "mismatch_kind": None,
            }
        )

    verdict, meta = judge_equivalence(
        question="how many?",
        gold_sql="SELECT 1",
        pred_sql="SELECT 1",
        gold_rows=[{"c": 1}],
        pred_rows=[{"c": 1}],
        judge_fn=fake_judge,
        judge_model="mock-model",
    )
    assert verdict.equivalent is True
    assert meta["judge_prompt_version"] == JUDGE_PROMPT_VERSION
    assert meta["judge_model"] == "mock-model"
    assert meta["judge_inputs_hash"]


def test_judge_abstain_asymmetric_empty():
    verdict, meta = judge_equivalence(
        question="q",
        gold_sql="SELECT 1",
        pred_sql="SELECT 1",
        gold_rows=[{"c": 1}],
        pred_rows=[],
        judge_fn=lambda m: "{}",  # should not be called meaningfully
        judge_model="mock",
    )
    assert verdict.abstained is True
    assert meta["judge_abstain"] == "asymmetric_empty"


def test_score_item_splits_gold_pred_errors(monkeypatch):
    calls = {"n": 0}

    def fake_run(dsn, sql, timeout_ms=0, max_rows=0, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("connection timeout expired")
        return ["c"], [{"c": 1}]

    monkeypatch.setattr("doris_test_harness.cli.run_query", fake_run)

    it = SimpleNamespace(
        question_id="1",
        db_id="financial",
        question="q",
        gold_sql="SELECT 1",
        evidence="ev",
    )
    api = SimpleNamespace(pred_sql="SELECT 1", error=None, latency_ms=10)
    rec = _score_item(
        it=it,
        api=api,
        eval_mode="dual_dsn",
        gold_dsn="postgresql://x",
        pred_dsn="mysql://y",
        sqlite_databases_dir=None,
        sql_timeout_ms=1000,
        max_rows=10,
    )
    assert rec["gold_ok"] is False
    assert rec["pred_ok"] is True
    assert rec["gold_error"]
    assert rec["ex"] is None
    assert rec["soft_f1"] is None
    assert "gold:" in rec["eval_error"]


def test_summarize_separates_failure_zeros():
    records = [
        {
            "api_ok": True,
            "gold_ok": False,
            "pred_ok": True,
            "dual_ok": False,
            "gold_error": "timeout",
            "ex": None,
            "soft_f1": None,
            "latency_ms": 100,
        },
        {
            "api_ok": True,
            "gold_ok": True,
            "pred_ok": True,
            "dual_ok": True,
            "ex": True,
            "soft_f1": 1.0,
            "latency_ms": 200,
            "llm_equivalent": True,
        },
    ]
    s = _summarize(records, eval_mode="dual_dsn_llm_judge")
    assert s["n"] == 2
    assert s["n_dual_ok"] == 1
    assert s["ex_among_dual_ok"] == 1.0
    assert s["ex_over_all"] == 0.5
    assert s["n_gold_fail"] == 1
    assert s["llm_judge"]["n_equivalent"] == 1
