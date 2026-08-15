from __future__ import annotations

from app.schema_catalog import TableEntry, filter_catalog_by_db_id, format_schema_subset


def _entry(schema: str, table: str, *cols: str) -> TableEntry:
    return TableEntry(schema, table, tuple((c, "varchar") for c in cols) or (("id", "int"),))


def test_filter_catalog_by_db_id_as_schema():
    entries = [
        _entry("financial", "loan", "amount"),
        _entry("formula_1", "drivers", "name"),
    ]
    out = filter_catalog_by_db_id(entries, "financial", db_id_as_schema=True)
    assert [e.fq for e in out] == ["financial.loan"]


def test_filter_catalog_disabled():
    entries = [_entry("financial", "loan", "amount")]
    out = filter_catalog_by_db_id(entries, "financial", db_id_as_schema=False)
    assert len(out) == 1


def test_filter_catalog_case_insensitive():
    entries = [_entry("Toxicology", "bond", "bond_type")]
    out = filter_catalog_by_db_id(entries, "toxicology", db_id_as_schema=True)
    assert [e.fq for e in out] == ["Toxicology.bond"]


def test_format_schema_subset_create_table_fqn():
    text = format_schema_subset(
        [_entry("california_schools", "schools", "charternum")],
        db_id="california_schools",
    )
    assert "CREATE TABLE california_schools.schools" in text
    assert "charternum" in text
    assert "not a table" in text.lower()
    assert "california_schools.schools:" not in text.split("CREATE", 1)[0]
