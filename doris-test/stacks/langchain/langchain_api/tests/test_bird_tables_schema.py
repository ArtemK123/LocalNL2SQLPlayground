from __future__ import annotations

from pathlib import Path

from app.schema_catalog import BirdTablesCatalog, SchemaSelector
from app.sql_guard import validate_sql

_DATA = Path(__file__).resolve().parents[1] / "data" / "dev_tables.json"


def test_bird_tables_omnisql_bare_create_table():
    cat = BirdTablesCatalog(_DATA)
    text, tables, used_full = cat.schema_for(
        "california_schools",
        "Rank schools by writing score",
        "charter number is not null",
        enabled=True,
        top_k=8,
        include_fk=True,
    )
    assert used_full
    assert "CREATE TABLE schools (" in text
    assert "CREATE TABLE california_schools.schools" not in text
    assert "satscores" in tables
    assert "financial" not in text.lower()


def test_bird_tables_selector_qualifies_for_doris_guard():
    cat = BirdTablesCatalog(_DATA)
    selector = SchemaSelector(
        engine=None,  # type: ignore[arg-type]
        allowed_schemas=["california_schools"],
        enabled=True,
        shortlist_top_m=25,
        final_top_k=8,
        mode="bm25",
        refresh_seconds=3600,
        schema_source="bird_tables",
        bird_tables=cat,
        include_fk_neighbors=True,
    )
    sel = selector.reference_for(
        "Rank schools by writing score",
        db_id="california_schools",
        evidence="charter number is not null",
    )
    assert "CREATE TABLE schools (" in sel.schema_reference
    assert "california_schools.schools" in sel.allowed_table_fq
    qualified = validate_sql(
        "SELECT CharterNum FROM schools WHERE CharterNum IS NOT NULL",
        allowed_tables=sel.allowed_table_fq,
        allowed_schemas=["california_schools"],
        dialect="mysql",
    )
    assert "california_schools.schools" in qualified.lower()


def test_bird_tables_rejects_schema_as_table():
    cat = BirdTablesCatalog(_DATA)
    selector = SchemaSelector(
        engine=None,  # type: ignore[arg-type]
        allowed_schemas=["california_schools"],
        enabled=True,
        shortlist_top_m=25,
        final_top_k=8,
        mode="bm25",
        refresh_seconds=3600,
        schema_source="bird_tables",
        bird_tables=cat,
    )
    sel = selector.reference_for("q", db_id="california_schools")
    try:
        validate_sql(
            "SELECT 1 FROM california_schools",
            allowed_tables=sel.allowed_table_fq,
            allowed_schemas=["california_schools"],
            dialect="mysql",
        )
    except ValueError as exc:
        assert "schema.table" in str(exc).lower() or "used as a table" in str(exc).lower()
    else:
        raise AssertionError("expected schema-as-table rejection")
