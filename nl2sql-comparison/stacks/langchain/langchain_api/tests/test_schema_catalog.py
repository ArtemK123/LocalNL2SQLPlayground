from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.schema_catalog import SchemaSelector, TableEntry, bm25_shortlist  # noqa: E402


def _entry(table: str, schema: str = "public") -> TableEntry:
    return TableEntry(schema_name=schema, table_name=table, columns=(("id", "integer"),))


def _selector(*, bird_db_profile: str = "public", final_top_k: int = 8) -> SchemaSelector:
    return SchemaSelector(
        engine=MagicMock(),
        allowed_schemas=["public"],
        enabled=True,
        shortlist_top_m=25,
        final_top_k=final_top_k,
        mode="heuristic",
        refresh_seconds=3600,
        bird_db_profile=bird_db_profile,
    )


class TestUseAllScopedTables(unittest.TestCase):
    def test_public_db_id_includes_all_when_scoped_fits_k(self) -> None:
        sel = _selector(bird_db_profile="public", final_top_k=8)
        self.assertTrue(sel._use_all_scoped_tables("california_schools", 3))
        self.assertTrue(sel._use_all_scoped_tables("toxicology", 8))

    def test_public_db_id_does_not_bypass_when_scoped_exceeds_k(self) -> None:
        sel = _selector(bird_db_profile="public", final_top_k=8)
        # formula_1 has 13 tables on AWS public profile — BM25/heuristic must run.
        self.assertFalse(sel._use_all_scoped_tables("formula_1", 13))
        self.assertFalse(sel._use_all_scoped_tables("superhero", 9))

    def test_multi_schema_same_threshold(self) -> None:
        sel = _selector(bird_db_profile="multi_schema", final_top_k=8)
        self.assertTrue(sel._use_all_scoped_tables("formula_1", 8))
        self.assertFalse(sel._use_all_scoped_tables("formula_1", 9))

    def test_no_db_id_uses_same_threshold(self) -> None:
        sel = _selector(final_top_k=8)
        self.assertTrue(sel._use_all_scoped_tables(None, 5))
        self.assertFalse(sel._use_all_scoped_tables("", 10))


class TestReferenceForBm25Path(unittest.TestCase):
    def test_large_public_scope_selects_top_k(self) -> None:
        from time import monotonic

        sel = _selector(bird_db_profile="public", final_top_k=8)
        tables = [
            "circuits",
            "constructors",
            "drivers",
            "races",
            "results",
            "seasons",
            "status",
            "laptimes",
            "pitstops",
            "qualifying",
            "driverstandings",
            "constructorstandings",
            "constructorresults",
        ]
        catalog = [_entry(t) for t in tables]
        sel._catalog = catalog
        sel._loaded_at = monotonic()
        result = sel.reference_for("How many races did drivers win in seasons?", db_id="formula_1")
        self.assertEqual(len(result.selected_entries), 8)
        self.assertLess(len(result.selected_entries), len(catalog))
        self.assertFalse(result.used_fallback_full_schema)

    def test_bm25_shortlist_caps(self) -> None:
        entries = [_entry(f"t{i}") for i in range(20)]
        short = bm25_shortlist(entries, "drivers races seasons", top_m=8)
        self.assertEqual(len(short), 8)


if __name__ == "__main__":
    unittest.main()
