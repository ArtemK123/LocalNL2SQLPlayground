from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from nl2sql_comparison_harness.api_client import ApiAskResult
from nl2sql_comparison_harness.cli import _run_api_items
from nl2sql_comparison_harness.dataset import BenchmarkItem


def _items(n: int) -> list[BenchmarkItem]:
    return [
        BenchmarkItem(
            question_id=str(i),
            question=f"q{i}",
            gold_sql=f"SELECT {i}",
            db_id="db",
            evidence=None,
        )
        for i in range(n)
    ]


class TestRunApiWorkers(unittest.TestCase):
    def test_ordered_output_despite_out_of_order_completion(self) -> None:
        items = _items(4)
        # Later indices finish first so completion order != submit order.
        delays = {0: 0.12, 1: 0.09, 2: 0.05, 3: 0.01}

        def fake_ask(*, api_url, question, timeout_s, db_id=None, evidence=None):
            qid = int(question[1:])
            time.sleep(delays[qid])
            return ApiAskResult(pred_sql=f"SELECT {qid}", latency_ms=1, error=None)

        def fake_run_query(dsn, sql, timeout_ms=0, max_rows=0):
            n = int(str(sql).split()[-1])
            return (["n"], [{"n": n}])

        with (
            patch("nl2sql_comparison_harness.cli.ask_via_api", side_effect=fake_ask),
            patch("nl2sql_comparison_harness.cli.run_query", side_effect=fake_run_query),
        ):
            results = _run_api_items(
                items=items,
                framework="langchain",
                suite="smoke",
                api_url="http://example/v1/chat",
                timeout_s=30.0,
                dsn="postgresql://unused",
                sql_timeout_ms=1000,
                max_rows=10,
                workers=4,
            )

        self.assertEqual([r["question_id"] for r in results], ["0", "1", "2", "3"])
        self.assertEqual([r["pred_sql"] for r in results], ["SELECT 0", "SELECT 1", "SELECT 2", "SELECT 3"])
        self.assertTrue(all(r["ex"] for r in results))
        self.assertTrue(all(r["executable"] for r in results))

    def test_concurrency_capped_at_workers(self) -> None:
        items = _items(6)
        workers = 2
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_ask(*, api_url, question, timeout_s, db_id=None, evidence=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            qid = question[1:]
            return ApiAskResult(pred_sql=f"SELECT {qid}", latency_ms=50, error=None)

        def fake_run_query(dsn, sql, timeout_ms=0, max_rows=0):
            return (["n"], [{"n": 1}])

        with (
            patch("nl2sql_comparison_harness.cli.ask_via_api", side_effect=fake_ask),
            patch("nl2sql_comparison_harness.cli.run_query", side_effect=fake_run_query),
        ):
            results = _run_api_items(
                items=items,
                framework="langchain",
                suite="smoke",
                api_url="http://example/v1/chat",
                timeout_s=30.0,
                dsn="postgresql://unused",
                sql_timeout_ms=1000,
                max_rows=10,
                workers=workers,
            )

        self.assertEqual(len(results), 6)
        self.assertLessEqual(max_active, workers)
        self.assertGreaterEqual(max_active, 1)

    def test_workers_one_is_sequential(self) -> None:
        items = _items(3)
        active = 0
        max_active = 0
        lock = threading.Lock()
        call_order: list[str] = []

        def fake_ask(*, api_url, question, timeout_s, db_id=None, evidence=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                call_order.append(question)
            time.sleep(0.02)
            with lock:
                active -= 1
            return ApiAskResult(pred_sql="SELECT 1", latency_ms=20, error=None)

        def fake_run_query(dsn, sql, timeout_ms=0, max_rows=0):
            return (["n"], [{"n": 1}])

        with (
            patch("nl2sql_comparison_harness.cli.ask_via_api", side_effect=fake_ask),
            patch("nl2sql_comparison_harness.cli.run_query", side_effect=fake_run_query),
        ):
            results = _run_api_items(
                items=items,
                framework="langchain",
                suite="smoke",
                api_url="http://example/v1/chat",
                timeout_s=30.0,
                dsn="postgresql://unused",
                sql_timeout_ms=1000,
                max_rows=10,
                workers=1,
            )

        self.assertEqual(max_active, 1)
        self.assertEqual(call_order, ["q0", "q1", "q2"])
        self.assertEqual([r["question_id"] for r in results], ["0", "1", "2"])


if __name__ == "__main__":
    unittest.main()
