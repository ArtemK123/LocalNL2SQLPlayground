from __future__ import annotations

import unittest

from nl2sql_comparison_harness.compare import execution_metrics
from nl2sql_comparison_harness.db import match_columns_case_insensitive


class TestSingleColumnAlias(unittest.TestCase):
    def test_match_columns_positional_single_column(self) -> None:
        m = match_columns_case_insensitive(["?column?"], ["percentage"])
        self.assertEqual(m["?column?"], "percentage")

    def test_execution_metrics_alias_mismatch(self) -> None:
        gold = [{"?column?": 46.885245901639344}]
        pred = [{"percentage": 46.885245901639344}]
        ex, sf1, alias_mismatch = execution_metrics(gold, pred)
        self.assertTrue(ex)
        self.assertEqual(sf1, 1.0)
        self.assertTrue(alias_mismatch)

    def test_same_column_name_no_alias_flag(self) -> None:
        gold = [{"pct": 1}]
        pred = [{"pct": 1}]
        ex, _, alias_mismatch = execution_metrics(gold, pred)
        self.assertTrue(ex)
        self.assertFalse(alias_mismatch)


if __name__ == "__main__":
    unittest.main()
