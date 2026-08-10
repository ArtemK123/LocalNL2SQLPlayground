from __future__ import annotations

import re

from app.schema_catalog import SelectionResult

_WHERE_LITERAL = re.compile(r"'([^']*)'", re.IGNORECASE)


def _schema_mentions(schema_reference: str, needle: str) -> bool:
    return needle.lower() in schema_reference.lower()


def _table_available(selection: SelectionResult, table_name: str) -> bool:
    needle = table_name.lower()
    return any(needle in fq.lower() for fq in selection.allowed_table_fq)


def lint_generated_sql(sql: str, question: str, selection: SelectionResult) -> list[str]:
    """Lightweight post-generation checks; messages are passed to the repair prompt."""
    issues: list[str] = []
    lowered = sql.lower()
    q_lower = question.lower()
    schema_ref = selection.schema_reference

    if re.search(r"\bposts\.ownerdisplayname\b", lowered) or "ownerdisplayname" in lowered:
        if _schema_mentions(schema_ref, "users") or _table_available(selection, "users"):
            issues.append(
                "Join public.users for owner/display names; do not use posts.ownerdisplayname."
            )

    if "charter" in q_lower and _table_available(selection, "schools"):
        if "frpm" in lowered and (
            "charter school number" in lowered
            or re.search(r'\bfrpm\b.*\bcharter\b', lowered)
        ):
            issues.append(
                "For charter numbers use schools.CharterNum joined on CDSCode, not frpm charter columns."
            )

    if "charter" in q_lower and "satscores" in lowered and "schools" not in lowered:
        if _table_available(selection, "schools"):
            issues.append("Join schools for CharterNum when the question asks for charter numbers.")

    if "season" in q_lower and re.search(r"\bseasons?\.", lowered):
        if "url" in q_lower and not re.search(r"\bseasons\.url\b", lowered):
            issues.append("Season-related URLs are in seasons.url, not other season columns.")

    return issues


def sql_string_literals(sql: str) -> list[str]:
    return [m.group(1) for m in _WHERE_LITERAL.finditer(sql)]


def string_literals_missing_from_question(sql: str, question: str) -> list[str]:
    """WHERE string literals that do not appear in the question (likely typos)."""
    q_lower = question.lower()
    missing: list[str] = []
    for lit in sql_string_literals(sql):
        if len(lit) < 2:
            continue
        if lit.lower() not in q_lower:
            missing.append(lit)
    return missing


def empty_result_repair_message(sql: str, question: str) -> str:
    parts = ["Query returned 0 rows. Revise filters, joins, and table choice."]
    missing = string_literals_missing_from_question(sql, question)
    if missing:
        quoted = ", ".join(repr(s) for s in missing[:5])
        parts.append(
            f"String literal(s) {quoted} not found in the question; copy exact spelling from the question."
        )
    return " ".join(parts)
