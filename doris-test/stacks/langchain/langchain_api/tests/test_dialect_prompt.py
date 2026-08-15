"""Arctic/MySQL prompt must demand dialect, not rely on per-question rewrites."""

from __future__ import annotations

import pytest

from app.dialect import MYSQL_DIALECT_INSTRUCTIONS


def test_mysql_dialect_instructions_forbid_sqlite():
    text = MYSQL_DIALECT_INSTRUCTIONS.lower()
    assert "date_format" in text
    assert "concat" in text
    assert "strftime" in text
    assert "datetime('now')" in text
    assert "||" in MYSQL_DIALECT_INSTRUCTIONS
    assert "`match`" in MYSQL_DIALECT_INSTRUCTIONS
    assert "`sets`" in MYSQL_DIALECT_INSTRUCTIONS
    assert "`order`" in MYSQL_DIALECT_INSTRUCTIONS


def test_arctic_sql_prompt_includes_mysql_dialect_rules():
    pytest.importorskip("langchain_core")
    pytest.importorskip("langchain_ollama")
    from app.agent import ARCTIC_SQL_PROMPT

    msgs = ARCTIC_SQL_PROMPT.format_prompt(
        schema_reference="CREATE TABLE myschema.users (id INT)",
        question_with_evidence="how many users?",
    ).to_messages()
    blob = "\n".join(str(m.content) for m in msgs)
    assert "DATE_FORMAT" in blob
    assert "CONCAT" in blob
    assert "strftime" in blob
    assert "Apache Doris (MySQL)" in blob


def test_arctic_repair_prompt_includes_mysql_dialect_rules():
    pytest.importorskip("langchain_core")
    pytest.importorskip("langchain_ollama")
    from app.agent import ARCTIC_REPAIR_PROMPT

    msgs = ARCTIC_REPAIR_PROMPT.format_prompt(
        engine="Apache Doris (MySQL)",
        schema_reference="CREATE TABLE myschema.users (id INT)",
        question="how many?",
        sql="SELECT 1",
        error_message="err",
        allowed_schemas="myschema",
    ).to_messages()
    blob = "\n".join(str(m.content) for m in msgs)
    assert "DATE_FORMAT" in blob
    assert "strftime" in blob


def test_non_arctic_sql_prompt_includes_mysql_dialect_rules():
    pytest.importorskip("langchain_core")
    pytest.importorskip("langchain_ollama")
    from app.agent import SQL_PROMPT

    msgs = SQL_PROMPT.format_prompt(
        allowed_schemas="myschema",
        schema_reference="CREATE TABLE myschema.users (id INT)",
        evidence_block="",
        question="how many?",
    ).to_messages()
    blob = "\n".join(str(m.content) for m in msgs)
    assert "DATE_FORMAT" in blob
    assert "CONCAT" in blob
