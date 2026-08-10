from __future__ import annotations

import re

from app.config import settings

FORBIDDEN_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
    "revoke",
    "copy",
    "call",
    "do",
    "vacuum",
    "analyze",
}


def sanitize_prompt(text: str) -> str:
    sanitized = text.replace("\x00", " ").replace("\r", " ").strip()
    sanitized = re.sub(r"\s+", " ", sanitized)
    if len(sanitized) > 2000:
        sanitized = sanitized[:2000]
    return sanitized


def validate_safe_question(text: str) -> None:
    """Reject obviously malicious natural-language prompts before SQL generation."""
    lowered = text.lower()
    if re.search(r"\bdrop\b", lowered):
        raise ValueError("Questions must not contain DDL instructions.")
    if "pg_catalog" in lowered:
        raise ValueError("Questions must not reference system catalogs.")


# Natural-language "select the column…" must not be treated as SQL.
# Do NOT treat bare "SELECT a FROM …" as NL — single-letter columns/aliases are valid SQL.
_NL_SELECT_PREFIX = re.compile(
    r"\bselect\s+(?:the|a|an)\s+(?:[\w]+\s+){0,4}"
    r"(?:column|columns|table|tables|row|rows|field|fields|value|values|name|names|list)\b",
    flags=re.IGNORECASE,
)

# Prose / reasoning markers that must not appear inside executable SQL.
# Backticks are NOT markers here — Arctic/SQLite often emits `ident`; we normalize them.
_NON_SQL_MARKERS = re.compile(
    r"(?:</?(?:plan|talk|think|thought|reasoning|analysis|action|execute)[^>]*>|\.\.\.)",
    flags=re.IGNORECASE,
)


def _looks_like_sql(candidate: str) -> bool:
    if not candidate or not candidate.strip():
        return False
    s = re.sub(r"\s+", " ", candidate.strip())
    if _NON_SQL_MARKERS.search(s):
        return False
    if _NL_SELECT_PREFIX.match(s):
        return False
    lowered = s.lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        return False
    if lowered.startswith("select ") and " from " not in lowered:
        if not re.match(r"select\s+[\d'\"(]", lowered):
            return False
    return True


def _strip_reasoning_wrappers(text: str) -> str:
    stripped = re.sub(
        r"</?(?:plan|talk|think|thought|reasoning|analysis|action|execute)[^>]*>",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", stripped).strip()


def _sqlite_backticks_to_pg(sql: str) -> str:
    """Convert SQLite-style `ident` backticks to PostgreSQL "ident" double quotes."""
    return re.sub(r"`([^`]+)`", r'"\1"', sql)


def _keyword_outside_strings(sql: str, keyword: str) -> bool:
    """True if keyword appears as a whole word outside single-quoted literals."""
    pattern = re.compile(rf"\b{re.escape(keyword)}\b", flags=re.IGNORECASE)
    in_quote = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_quote:
            in_quote = True
        elif ch == "'" and in_quote:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 1
            else:
                in_quote = False
        elif not in_quote:
            match = pattern.match(sql, i)
            if match:
                return True
        i += 1
    return False


def _last_read_query_fragment(text: str) -> str | None:
    """Prefer the last SELECT/WITH block (Arctic often appends the final SQL after reasoning)."""
    best: str | None = None
    for match in re.finditer(r"\b(?:select|with)\b", text, flags=re.IGNORECASE):
        tail = text[match.start() :].strip()
        lowered = tail.lower()
        if lowered.startswith("select ") and _NL_SELECT_PREFIX.match(tail):
            continue
        if lowered.startswith("select ") or lowered.startswith("with "):
            best = tail.split(";")[0].strip()
    return best


def extract_sql(markdown_or_sql: str) -> str:
    text = markdown_or_sql.strip()
    # vLLM stop=["```", "</answer>"] may leave a trailing incomplete fence/tag.
    text = re.sub(r"(?is)</answer>\s*$", "", text).strip()
    explicit_blocks: list[str] = []
    for pattern in (
        r"```sql\s*(.*?)```",
        r"<sql>\s*(.*?)\s*</sql>",
        # Ollama stop=["</sql>"] omits the closing tag from the completion.
        r"<sql>\s*((?:WITH|SELECT)\b.*)\s*\Z",
        # Prefill opened ```sql; stop on ``` leaves unclosed fence without trailing ```.
        r"```sql\s*((?:WITH|SELECT)\b(?:(?!```).)*)\s*\Z",
        r"```\s*((?:WITH|SELECT)\b.*?)```",
        r"<execute>\s*(.*?)\s*</execute>",
        r"<answer>\s*```sql\s*(.*?)(?:```|</answer>|\Z)",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            candidate = match.group(1).strip()
            if candidate:
                explicit_blocks.append(candidate)
    for candidate in reversed(explicit_blocks):
        # Drop accidental trailing fence markers from greedy unclosed matches.
        candidate = re.sub(r"```\s*$", "", candidate).strip()
        if _looks_like_sql(candidate):
            return candidate

    stripped = _strip_reasoning_wrappers(text)
    # Continuation after assistant prefill that already opened ```sql.
    if re.match(r"(?is)^(with|select)\b", stripped):
        cut = re.split(r"(?im)^```|</answer>", stripped, maxsplit=1)[0]
        if _looks_like_sql(cut):
            return cut.strip()
    fragment = _last_read_query_fragment(stripped) or _first_read_query_fragment(stripped)
    if fragment and _looks_like_sql(fragment):
        return fragment
    return stripped or text


def _split_outside_single_quotes(sql: str, sep: str = ";") -> list[str]:
    """Split on sep ignoring semicolons inside PostgreSQL single-quoted literals."""
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_quote:
            in_quote = True
            buf.append(ch)
        elif ch == "'" and in_quote:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                buf.append("''")
                i += 1
            else:
                in_quote = False
                buf.append(ch)
        elif ch == sep and not in_quote:
            segment = "".join(buf).strip()
            if segment:
                parts.append(segment)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _first_read_query_fragment(text: str) -> str | None:
    """Return substring starting at the first SQL-like SELECT or CTE WITH ... AS."""
    for match in re.finditer(
        r"\b(?:select|with)\b",
        text,
        flags=re.IGNORECASE,
    ):
        start = match.start()
        tail = text[start:].strip()
        lowered = tail.lower()
        if lowered.startswith("select ") and _NL_SELECT_PREFIX.match(tail):
            continue
        if lowered.startswith("select ") or lowered.startswith("with "):
            return tail
    return None


def _pick_read_query_statement(statements: list[str]) -> str | None:
    for stmt in statements:
        candidate = re.sub(r"\s+", " ", stmt.strip())
        if not candidate:
            continue
        fragment = _first_read_query_fragment(candidate) or candidate
        lowered = fragment.lower()
        if lowered.startswith("select ") and not _NL_SELECT_PREFIX.match(fragment):
            return fragment
        if lowered.startswith("with "):
            return fragment
    return None


def _strip_sql_line_comments(sql: str) -> str:
    """Remove `--` line comments outside single-quoted literals."""
    out: list[str] = []
    in_quote = False
    for line in sql.splitlines():
        buf: list[str] = []
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "'" and not in_quote:
                in_quote = True
                buf.append(ch)
            elif ch == "'" and in_quote:
                if i + 1 < len(line) and line[i + 1] == "'":
                    buf.append("''")
                    i += 1
                else:
                    in_quote = False
                    buf.append(ch)
            elif not in_quote and ch == "-" and i + 1 < len(line) and line[i + 1] == "-":
                break
            else:
                buf.append(ch)
            i += 1
        cleaned = "".join(buf).strip()
        if cleaned:
            out.append(cleaned)
    return " ".join(out)


def _normalize_llm_sql(sql: str, *, dialect: str = "postgresql") -> str:
    """Collapse whitespace, drop trailing semicolons, keep first read query if LLM emitted several."""
    normalized = _strip_sql_line_comments(re.sub(r"\s+", " ", sql.strip()))
    if not normalized:
        raise ValueError("Empty SQL was generated.")

    if dialect != "sqlite":
        normalized = _sqlite_backticks_to_pg(normalized)

    fragment = _first_read_query_fragment(normalized)
    if fragment:
        normalized = fragment

    while normalized.endswith(";"):
        normalized = normalized[:-1].strip()
        normalized = re.sub(r"\s+", " ", normalized)

    if ";" not in normalized:
        lowered = normalized.lower()
        if lowered.startswith("select ") and not _NL_SELECT_PREFIX.match(normalized):
            return normalized
        if lowered.startswith("with "):
            return normalized
        raise ValueError("Only read-only SELECT queries are allowed.")

    statements = _split_outside_single_quotes(normalized)
    picked = _pick_read_query_statement(statements)
    if picked:
        return picked if dialect == "sqlite" else _sqlite_backticks_to_pg(picked)
    raise ValueError("Only read-only SELECT queries are allowed.")


def validate_sql(
    sql: str,
    *,
    allowed_tables: tuple[str, ...] | list[str] | None = None,
    allowed_schemas: tuple[str, ...] | list[str] | None = None,
    dialect: str = "postgresql",
) -> str:
    dialect_n = (dialect or "postgresql").strip().lower()
    if dialect_n in {"postgres", "pg"}:
        dialect_n = "postgresql"
    normalized = _normalize_llm_sql(sql, dialect=dialect_n)

    if _NON_SQL_MARKERS.search(normalized):
        raise ValueError("Only read-only SELECT queries are allowed.")
    if not _looks_like_sql(normalized):
        raise ValueError("Only read-only SELECT queries are allowed.")

    lowered = normalized.lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise ValueError("Only SELECT queries are allowed.")

    for keyword in FORBIDDEN_KEYWORDS:
        if _keyword_outside_strings(normalized, keyword):
            raise ValueError(f"Blocked keyword detected: {keyword}.")

    # SQLite Gen EX path: bare table names; skip PG schema.table allowlist enforcement.
    if dialect_n == "sqlite":
        return normalized

    allowed = list(allowed_schemas) if allowed_schemas is not None else settings.allowed_schemas
    # Only treat `schema.table` after FROM/JOIN (not `, alias.col` comma-joins).
    referenced_schemas = set(
        schema
        for schema, _table in re.findall(
            r"(?:\bfrom|\bjoin)\s+(?:only\s+)?([a-z_][a-z0-9_]*)\s*\.\s*([a-z_][a-z0-9_]*)",
            lowered,
            flags=re.IGNORECASE,
        )
    )
    referenced_schemas = {s for s in referenced_schemas if len(s) >= 3}
    if referenced_schemas and allowed:
        bad = sorted(s for s in referenced_schemas if s not in allowed)
        if bad:
            raise ValueError(f"Query references disallowed schemas: {', '.join(bad)}.")

    if allowed_tables:
        allowed_fq = {t.lower() for t in allowed_tables}
        referenced_tables = {
            f"{schema}.{table}"
            for schema, table in re.findall(
                r"(?:\bfrom|\bjoin)\s+(?:only\s+)?([a-z_][a-z0-9_]*)\s*\.\s*([a-z_][a-z0-9_]*)",
                lowered,
                flags=re.IGNORECASE,
            )
        }
        if referenced_tables:
            bad_tables = sorted(t for t in referenced_tables if t not in allowed_fq)
            if bad_tables:
                raise ValueError(
                    "Query references tables outside selected schema subset: "
                    + ", ".join(bad_tables)
                    + "."
                )

    return normalized
