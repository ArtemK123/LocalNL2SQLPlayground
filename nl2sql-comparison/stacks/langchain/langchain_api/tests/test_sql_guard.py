from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.sql_guard import extract_sql, validate_sql  # noqa: E402


class TestSqlGuardSemicolons(unittest.TestCase):
    def test_trailing_semicolon(self) -> None:
        self.assertEqual(validate_sql("SELECT 1;"), "SELECT 1")

    def test_double_trailing_semicolon(self) -> None:
        self.assertEqual(validate_sql("SELECT lat, lng FROM t;;"), "SELECT lat, lng FROM t")

    def test_multi_statement_keeps_first(self) -> None:
        self.assertEqual(validate_sql("SELECT 1; SELECT 2"), "SELECT 1")

    def test_semicolon_inside_string_literal(self) -> None:
        sql = "SELECT x FROM t WHERE n = 'a;b'"
        out = validate_sql(sql)
        self.assertIn("a;b", out)
        self.assertNotIn(";", out.replace("a;b", ""))

    def test_preamble_before_select(self) -> None:
        sql = "Here is the query: SELECT lat, lng FROM circuits"
        self.assertEqual(validate_sql(sql), "SELECT lat, lng FROM circuits")

    def test_leading_garbage_before_select_after_semicolon(self) -> None:
        sql = "Note: use joins; SELECT lat, lng FROM circuits c"
        self.assertEqual(validate_sql(sql), "SELECT lat, lng FROM circuits c")

    def test_arctic_xml_sql_tag(self) -> None:
        raw = (
            "with columns like lat. <talk>explain</talk> "
            "<sql>SELECT lat, lng FROM circuits WHERE country = 'Australia';</sql>"
        )
        self.assertEqual(
            validate_sql(extract_sql(raw)),
            "SELECT lat, lng FROM circuits WHERE country = 'Australia'",
        )

    def test_arctic_unclosed_sql_tag_after_stop(self) -> None:
        # ChatOllama stop=["</sql>"] omits the closing tag from the model output.
        raw = "<sql>SELECT lat, lng FROM circuits WHERE country = 'Australia'"
        self.assertEqual(
            validate_sql(extract_sql(raw)),
            "SELECT lat, lng FROM circuits WHERE country = 'Australia'",
        )

    def test_prose_select_the_is_not_sql(self) -> None:
        raw = "select the race names from the formula_1 table where country = Germany"
        with self.assertRaises(ValueError):
            validate_sql(extract_sql(raw))

    def test_select_single_letter_column_is_sql(self) -> None:
        self.assertEqual(validate_sql("SELECT a FROM x"), "SELECT a FROM x")

    def test_sqlite_backticks_normalized_to_pg(self) -> None:
        raw = "SELECT MAX(f.`Free Meal Count` / f.`Enrollment`) FROM frpm AS f"
        out = validate_sql(extract_sql(raw))
        self.assertIn('"Free Meal Count"', out)
        self.assertNotIn("`", out)

    def test_forbidden_do_inside_string_literal_allowed(self) -> None:
        sql = "SELECT status FROM loan WHERE status = 'do'"
        self.assertEqual(validate_sql(sql), sql)

    def test_create_then_select_keeps_select(self) -> None:
        raw = "CREATE TABLE x(a int); SELECT a FROM x"
        self.assertEqual(validate_sql(extract_sql(raw)), "SELECT a FROM x")

    def test_arctic_markdown_sql_fence(self) -> None:
        raw = (
            "Let me solve this step by step.\n"
            "1. Join schools and satscores.\n"
            "```sql\n"
            "SELECT CharterNum FROM schools WHERE CharterNum IS NOT NULL\n"
            "```"
        )
        self.assertEqual(
            validate_sql(extract_sql(raw)),
            "SELECT CharterNum FROM schools WHERE CharterNum IS NOT NULL",
        )

    def test_arctic_vllm_prefill_continuation_bare_select(self) -> None:
        # Assistant prefill already opened ```sql; stop=["```"] yields SQL only.
        raw = "SELECT lat, lng FROM circuits WHERE country = 'Australia'"
        self.assertEqual(
            validate_sql(extract_sql(raw)),
            "SELECT lat, lng FROM circuits WHERE country = 'Australia'",
        )

    def test_arctic_vllm_stop_unclosed_sql_fence(self) -> None:
        raw = "```sql\nSELECT CharterNum FROM schools WHERE CharterNum IS NOT NULL\n"
        self.assertEqual(
            validate_sql(extract_sql(raw)),
            "SELECT CharterNum FROM schools WHERE CharterNum IS NOT NULL",
        )

    def test_plan_wrapper_with_sql_block(self) -> None:
        raw = (
            "<plan>Pick circuits join races.</plan>"
            "```sql\nSELECT T2.name FROM formula_1.circuits AS T1 "
            "INNER JOIN formula_1.races AS T2 ON T2.circuitId = T1.circuitId "
            "WHERE T1.country = 'Germany'\n```"
        )
        out = validate_sql(extract_sql(raw), allowed_schemas=["formula_1"])
        self.assertIn("FROM formula_1.circuits", out)

    def test_execute_tag_with_prose_is_not_sql(self) -> None:
        raw = (
            "<plan>Pick card rule column.</plan>"
            "<execute>select the column that holds the rule from card_games where name = 'Benalish Knight'</execute>"
        )
        with self.assertRaises(ValueError):
            validate_sql(extract_sql(raw))

    def test_arctic_prefers_last_sql_block(self) -> None:
        raw = (
            "<plan>draft</plan><sql>SELECT 1</sql>"
            "<sql>SELECT T2.format FROM card_games.cards AS T1 "
            "INNER JOIN card_games.legalities AS T2 ON T1.uuid = T2.uuid "
            "WHERE T1.name = 'Benalish Knight'</sql>"
        )
        out = validate_sql(extract_sql(raw), allowed_schemas=["card_games"])
        self.assertIn("legalities", out)

    def test_table_alias_not_treated_as_schema(self) -> None:
        sql = (
            "SELECT T2.Consumption FROM customers AS T1 "
            "INNER JOIN yearmonth AS T2 ON T1.CustomerID = T2.CustomerID "
            "WHERE T2.Date BETWEEN '201301' AND '201312'"
        )
        out = validate_sql(sql, allowed_schemas=["public"])
        self.assertIn("yearmonth", out)

    def test_inline_sql_comment_stripped(self) -> None:
        sql = "SELECT amount FROM loan WHERE amount < 100000 -- cheap loans only"
        out = validate_sql(sql)
        self.assertNotIn("--", out)
        self.assertIn("amount < 100000", out)

    def test_comma_join_alias_not_treated_as_schema(self) -> None:
        sql = (
            "SELECT y.Consumption FROM customers c, yearmonth y "
            "WHERE c.CustomerID = y.CustomerID"
        )
        out = validate_sql(sql, allowed_schemas=["public"])
        self.assertIn("yearmonth", out)


if __name__ == "__main__":
    unittest.main()
