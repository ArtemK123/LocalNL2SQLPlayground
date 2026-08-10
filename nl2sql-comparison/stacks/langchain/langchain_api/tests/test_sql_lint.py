from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.schema_catalog import SelectionResult, TableEntry  # noqa: E402
from app.sql_lint import (  # noqa: E402
    empty_result_repair_message,
    lint_generated_sql,
    string_literals_missing_from_question,
)


def _selection(schema_ref: str, *, allowed: tuple[str, ...] = ()) -> SelectionResult:
    entries = tuple(
        TableEntry("public", t.split(".")[-1], (("id", "integer"),))
        for t in allowed
    )
    return SelectionResult(
        selected_entries=entries,
        schema_reference=schema_ref,
        selected_table_fq=allowed,
        allowed_table_fq=allowed or ("public.users", "public.schools", "public.frpm"),
        used_fallback_full_schema=False,
    )


class TestSqlLint(unittest.TestCase):
    def test_ownerdisplayname_flag(self) -> None:
        sql = "SELECT ownerdisplayname FROM posts"
        sel = _selection("public.users: id\npublic.posts: ownerdisplayname", allowed=("public.users",))
        issues = lint_generated_sql(sql, "Who owns the post?", sel)
        self.assertTrue(any("users" in i for i in issues))

    def test_charter_frpm_flag(self) -> None:
        sql = (
            'SELECT f."Charter School Number" FROM frpm f '
            "JOIN satscores s ON f.cdscode = s.cds"
        )
        sel = _selection(
            "public.schools: CharterNum\npublic.frpm: cdscode",
            allowed=("public.schools", "public.frpm", "public.satscores"),
        )
        issues = lint_generated_sql(sql, "Rank schools by charter numbers", sel)
        self.assertTrue(any("CharterNum" in i for i in issues))

    def test_string_literal_missing(self) -> None:
        missing = string_literals_missing_from_question(
            "SELECT * FROM t WHERE name = 'Wrong Spelling'",
            "Find card named Lightning Bolt",
        )
        self.assertEqual(missing, ["Wrong Spelling"])

    def test_empty_result_message_includes_literals(self) -> None:
        msg = empty_result_repair_message(
            "SELECT * FROM cards WHERE name = 'Typo'",
            "Benalish Knight",
        )
        self.assertIn("0 rows", msg)
        self.assertIn("Typo", msg)


if __name__ == "__main__":
    unittest.main()
