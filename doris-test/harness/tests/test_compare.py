"""Bird vs strict EX (no live AWS). q118-like 1x1 alias mismatch."""

from __future__ import annotations

from types import SimpleNamespace

from doris_test_harness.cli import _score_item
from doris_test_harness.compare import execution_metrics
from doris_test_harness.db import dedupe_column_names


def test_bird_ex_q118_alias_mismatch():
    gold = [{"?column?": 46.885245901639344}]
    pred = [{"percentage": 46.885245901639344}]
    ex, sf1, alias = execution_metrics(gold, pred, ex_mode="bird")
    assert ex is True
    assert sf1 == 1.0
    assert alias is True


def test_strict_ex_q118_alias_mismatch_false():
    gold = [{"?column?": 46.885245901639344}]
    pred = [{"percentage": 46.885245901639344}]
    ex, sf1, alias = execution_metrics(gold, pred, ex_mode="strict")
    assert ex is False
    assert sf1 == 0.0
    assert alias is False


def test_bird_ex_does_not_none_fill_missing_names():
    gold = [{"a": 1, "b": 2}]
    pred = [{"a": 1}]
    ex, _, _ = execution_metrics(gold, pred, ex_mode="bird")
    assert ex is False


def test_bird_ex_positional_two_cols_different_aliases():
    gold = [{"?column?": 10, "?column?__2": 20}]
    pred = [{"sme_lam": 10, "lam_kam": 20}]
    ex, sf1, alias = execution_metrics(gold, pred, ex_mode="bird")
    assert ex is True
    assert sf1 == 1.0
    assert alias is True


def test_rewrite_scalar_eq_subquery_to_in():
    from doris_test_harness.db import rewrite_scalar_eq_subqueries_for_doris

    sql = (
        "SELECT url FROM myschema.users WHERE year = "
        "(SELECT year FROM myschema.posts WHERE postid = 1)"
    )
    out = rewrite_scalar_eq_subqueries_for_doris(sql)
    assert "year IN (SELECT" in out
    assert "year = (SELECT" not in out


def test_dedupe_column_names():
    assert dedupe_column_names(["?column?", "?column?"]) == ["?column?", "?column?__2"]


def test_score_item_persists_shape_and_alias(monkeypatch):
    def fake_run(dsn, sql, timeout_ms=0, max_rows=0, **_kwargs):
        if "gold" in dsn or "postgresql" in dsn:
            return ["?column?"], [{"?column?": 1}]
        return ["percentage"], [{"percentage": 1}]

    monkeypatch.setattr("doris_test_harness.cli.run_query", fake_run)
    it = SimpleNamespace(
        question_id="118",
        db_id="financial",
        question="q",
        gold_sql="SELECT 1",
        evidence=None,
    )
    api = SimpleNamespace(pred_sql="SELECT 1 AS percentage", error=None, latency_ms=1)
    rec = _score_item(
        it=it,
        api=api,
        eval_mode="dual_dsn",
        gold_dsn="postgresql://x",
        pred_dsn="mysql://y",
        sqlite_databases_dir=None,
        sql_timeout_ms=1000,
        max_rows=10,
        ex_mode="bird",
    )
    assert rec["ex"] is True
    assert rec["alias_mismatch"] is True
    assert rec["n_rows_gold"] == 1
    assert rec["n_rows_pred"] == 1
    assert rec["n_cols_gold"] == 1
    assert rec["n_cols_pred"] == 1
    assert rec["gold_columns"] == ["?column?"]
    assert rec["pred_columns"] == ["percentage"]
    assert rec["ex_mode"] == "bird"


def test_score_item_from_saved_rows_offline():
    it = SimpleNamespace(
        question_id="118",
        db_id="financial",
        question="q",
        gold_sql="SELECT 1",
        evidence=None,
    )
    api = SimpleNamespace(pred_sql="SELECT 1 AS percentage", error=None, latency_ms=1)
    rec = _score_item(
        it=it,
        api=api,
        eval_mode="dual_dsn",
        gold_dsn=None,
        pred_dsn=None,
        sqlite_databases_dir=None,
        sql_timeout_ms=1000,
        max_rows=10,
        ex_mode="bird",
        gold_rows_saved=[{"?column?": 1}],
        pred_rows_saved=[{"percentage": 1}],
        gold_cols_saved=["?column?"],
        pred_cols_saved=["percentage"],
    )
    assert rec["ex"] is True
    assert rec["alias_mismatch"] is True


def test_rescore_170306_without_dsn_exits(tmp_path):
    from pathlib import Path

    from doris_test_harness.cli import main

    src = Path(
        r"C:\Users\Artem\.cursor\worktrees\code\v2z0\aws\doris-test"
        r"\results\doris_20260814_170306\jsonl\langchain_minidev_diverse_10.jsonl"
    )
    if not src.is_file():
        return
    out = tmp_path / "out.jsonl"
    rc = main(
        [
            "rescore",
            "--jsonl",
            str(src),
            "--eval-mode",
            "dual_dsn",
            "--ex-mode",
            "bird",
            "--out",
            str(out),
            "--skip-without-pred",
        ]
    )
    assert rc == 2
