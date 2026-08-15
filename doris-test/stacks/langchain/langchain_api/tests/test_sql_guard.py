from __future__ import annotations

import re

import pytest

from app.sql_guard import extract_sql, validate_sql

TOX_TABLES = ("toxicology.atom", "toxicology.bond", "toxicology.molecule")
SCHOOL_TABLES = ("california_schools.schools", "california_schools.satscores")
FIN_TABLES = ("financial.loan", "financial.account")


def test_reject_db_id_used_as_table():
    with pytest.raises(ValueError, match="used as a table"):
        validate_sql(
            "SELECT cds.charternum FROM california_schools cds",
            allowed_tables=SCHOOL_TABLES,
            allowed_schemas=["california_schools"],
        )


def test_reject_wrong_bird_schema():
    with pytest.raises(ValueError, match="disallowed schemas"):
        validate_sql(
            "SELECT bond_type FROM card_games.foreign_data WHERE label = '+'",
            allowed_tables=TOX_TABLES,
            allowed_schemas=["toxicology"],
        )


def test_reject_unqualified_table_not_in_catalog():
    with pytest.raises(ValueError, match="not in the filtered catalog"):
        validate_sql(
            "SELECT type FROM cards WHERE name = 'Benalish Knight'",
            allowed_tables=TOX_TABLES,
            allowed_schemas=["toxicology"],
        )


def test_qualify_bare_catalog_table():
    out = validate_sql(
        "SELECT amount FROM loan WHERE amount < 100000",
        allowed_tables=FIN_TABLES,
        allowed_schemas=["financial"],
    )
    assert "financial.loan" in out.lower()


def test_strip_trailing_unmatched_paren():
    out = validate_sql(
        "SELECT year FROM formula_1.races WHERE raceid = 901)",
        allowed_tables=("formula_1.races", "formula_1.seasons"),
        allowed_schemas=["formula_1"],
    )
    assert out.endswith("901")
    assert not out.endswith(")")


def test_keep_balanced_parens():
    out = validate_sql(
        "SELECT CAST(SUM(amount) AS REAL) FROM financial.loan",
        allowed_tables=FIN_TABLES,
        allowed_schemas=["financial"],
    )
    assert "cast(sum(amount) as real)" in out.lower()


def test_extract_unclosed_sql_fence():
    raw = "SELECT year FROM formula_1.races"
    assert extract_sql("```sql\n" + raw).upper().startswith("SELECT")


def test_backticks_are_valid_mysql_sql():
    out = validate_sql(
        "SELECT `amount` FROM `financial`.`loan`",
        allowed_tables=FIN_TABLES,
        allowed_schemas=["financial"],
    )
    assert "loan" in out.lower()


# Synthetic catalog: dialect-compiler tests must not encode BIRD qids or named columns.
SYN_TABLES = (
    "myschema.users",
    "myschema.posts",
    "myschema.tags",
    "myschema.items",
    "myschema.match",
    "myschema.sets",
    "myschema.person",
    "myschema.lab",
)
SYN_SCHEMAS = ["myschema"]


def test_rewrite_scalar_eq_subquery_to_in():
    out = validate_sql(
        "SELECT url FROM myschema.users WHERE year = (SELECT year FROM myschema.posts WHERE postid = 1)",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    lowered = re.sub(r"\s+", " ", out).lower()
    assert "year in (select" in lowered
    assert "year = (select" not in lowered
    assert "myschema.posts" in lowered
    assert "postid = 1" in lowered


def test_rewrite_scalar_eq_keeps_inner_predicates():
    out = validate_sql(
        "SELECT url FROM users WHERE year = (SELECT year FROM posts WHERE postid = 1 AND tagid = 2)",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    lowered = re.sub(r"\s+", " ", out).lower()
    assert " in (select" in lowered
    assert "tagid = 2" in lowered


def test_no_scalar_rewrite_on_postgresql_dialect():
    out = validate_sql(
        "SELECT url FROM myschema.users WHERE year = (SELECT year FROM myschema.posts WHERE postid = 1)",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="postgresql",
    )
    lowered = re.sub(r"\s+", " ", out).lower()
    assert "year = (select" in lowered
    assert "year in (select" not in lowered


def test_no_rewrite_when_already_in_subquery():
    out = validate_sql(
        "SELECT url FROM myschema.users WHERE year IN (SELECT year FROM myschema.posts WHERE postid = 1)",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    lowered = re.sub(r"\s+", " ", out).lower()
    assert lowered.count(" in (select") == 1
    assert "= (select" not in lowered


def test_rewrite_strftime_year_to_date_format():
    out = validate_sql(
        "SELECT DisplayName FROM myschema.users WHERE strftime('%Y', CreationDate) = '2011'",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    lowered = out.lower()
    assert "strftime" not in lowered
    assert "date_format(creationdate, '%y')" in lowered
    assert "myschema.users" in lowered


def test_rewrite_strftime_now_and_year_month():
    out = validate_sql(
        "SELECT COUNT(*) FROM myschema.person "
        "WHERE strftime('%Y', 'now') - strftime('%Y', Birthday) > 50 "
        "AND strftime('%Y%m', First_Date) = '199002'",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    lowered = out.lower()
    assert "strftime" not in lowered
    assert "date_format(now(), '%y')" in lowered
    assert "%y%m" in lowered


def test_pg_dialect_keeps_strftime():
    out = validate_sql(
        "SELECT DisplayName FROM myschema.users WHERE strftime('%Y', CreationDate) = '2011'",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="postgresql",
    )
    assert "strftime" in out.lower()


def test_rewrite_pipe_concat_like_chain():
    out = validate_sql(
        "SELECT t.TagName FROM myschema.posts p "
        "JOIN myschema.tags t ON p.Tags LIKE '%' || t.TagName || '%'",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    assert "||" not in out
    assert "concat('%', t.tagname, '%')" in out.lower()


def test_rewrite_pipe_concat_coalesce_names():
    out = validate_sql(
        "SELECT COALESCE(s.FirstName, '') || ' ' || COALESCE(s.LastName, '') AS Admin1 "
        "FROM myschema.users s",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    lowered = out.lower()
    assert "||" not in out
    assert "concat(" in lowered
    assert "coalesce(s.firstname, '')" in lowered


def test_rewrite_double_quotes_and_cdc_parens():
    """Any identifier with parens is CDC-sanitized; not a named column list."""
    out = validate_sql(
        'SELECT t."Col (X)" FROM myschema.items t WHERE t."Amt (Y)" > 0',
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    assert "`Col _X`" in out
    assert "`Amt _Y`" in out


def test_quote_reserved_match_table():
    out = validate_sql(
        "SELECT M.season FROM myschema.match M WHERE M.league_id = 1",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    assert "`match`" in out
    assert "myschema." in out.lower()


def test_quote_reserved_sets_table():
    out = validate_sql(
        "SELECT s.code FROM myschema.sets s WHERE s.block = 'Ice Age'",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    assert "`sets`" in out


def test_lowercase_unquoted_idents_generic():
    out = validate_sql(
        "SELECT Foo.Bar FROM myschema.person JOIN myschema.lab ON Foo.Bar = Baz.Qux",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    assert "Foo.Bar" not in out
    assert "foo.bar" in out
    assert "baz.qux" in out


def test_rewrite_datetime_now_and_iif():
    out = validate_sql(
        "SELECT IIF(datetime('now') > date, 1, 0) FROM myschema.users",
        allowed_tables=SYN_TABLES,
        allowed_schemas=SYN_SCHEMAS,
        dialect="mysql",
    )
    lowered = out.lower()
    assert "datetime(" not in lowered
    assert "now()" in lowered
    assert "iif(" not in lowered
    assert "if(" in lowered
