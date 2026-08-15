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
    if "pg_catalog" in lowered or "information_schema" in lowered:
        raise ValueError("Questions must not reference system catalogs.")


# Natural-language "select the column…" must not be treated as SQL.
# Do NOT treat bare "SELECT a FROM …" as NL — single-letter columns/aliases are valid SQL.
_NL_SELECT_PREFIX = re.compile(
    r"\bselect\s+(?:the|a|an)\s+(?:[\w]+\s+){0,4}"
    r"(?:column|columns|table|tables|row|rows|field|fields|value|values|name|names|list)\b",
    flags=re.IGNORECASE,
)

# Prose / reasoning markers that must not appear inside executable SQL.
# Backticks are valid MySQL/Doris identifiers — do not treat them as non-SQL.
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
        r"<sql>\s*((?:WITH|SELECT)\b.*)\s*\Z",
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
        candidate = re.sub(r"```\s*$", "", candidate).strip()
        if _looks_like_sql(candidate):
            return candidate

    stripped = _strip_reasoning_wrappers(text)
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


def _paren_balance_outside_strings(sql: str) -> int:
    """Positive = extra '('; negative = extra ')'."""
    depth = 0
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
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        i += 1
    return depth


def _strip_trailing_unmatched_parens(sql: str) -> str:
    """Drop extra closing parens Arctic sometimes appends after the WHERE clause."""
    out = sql.rstrip()
    while out.endswith(")") and _paren_balance_outside_strings(out) < 0:
        out = out[:-1].rstrip()
    return out


def _unquote_ident(ident: str) -> str:
    ident = ident.strip()
    if len(ident) >= 2 and ident[0] == ident[-1] and ident[0] in {"`", '"', "'"}:
        return ident[1:-1]
    return ident


_FROM_JOIN_TABLE_RE = re.compile(
    r"(?:\bfrom|\bjoin)\s+(?:only\s+)?(?!\()"
    r"(?:(?P<schema>`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*)?"
    r"(?P<table>`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)",
    flags=re.IGNORECASE,
)


def _from_join_table_matches(sql: str) -> list[re.Match[str]]:
    return list(_FROM_JOIN_TABLE_RE.finditer(sql))


def _qualify_and_enforce_tables(
    sql: str,
    *,
    allowed_tables: tuple[str, ...] | list[str] | None,
    allowed_schemas: tuple[str, ...] | list[str] | None,
) -> str:
    """Reject db_id-as-table / wrong BIRD schema; qualify unique bare catalog tables."""
    schema_set = {s.strip().lower() for s in (allowed_schemas or []) if s and str(s).strip()}
    allowed_fq = {t.lower() for t in allowed_tables} if allowed_tables else set()
    table_to_fqs: dict[str, list[str]] = {}
    for fq in allowed_fq:
        if "." not in fq:
            continue
        _schema, table = fq.split(".", 1)
        table_to_fqs.setdefault(table, []).append(fq)

    replacements: list[tuple[int, int, str]] = []
    for match in _from_join_table_matches(sql):
        schema_raw = match.group("schema")
        table_raw = match.group("table")
        table = _unquote_ident(table_raw).lower()
        if schema_raw:
            schema = _unquote_ident(schema_raw).lower()
            fq = f"{schema}.{table}"
            if schema_set and schema not in schema_set:
                raise ValueError(f"Query references disallowed schemas: {schema}.")
            if allowed_fq and fq not in allowed_fq:
                raise ValueError(
                    "Query references tables outside selected schema subset: " + fq + "."
                )
            continue
        # Unqualified FROM/JOIN identifier.
        if schema_set and table in schema_set and table not in table_to_fqs:
            raise ValueError(
                f"Database/schema name '{table}' used as a table; qualify as schema.table "
                "using only tables listed in the schema reference."
            )
        if table in table_to_fqs:
            fqs = table_to_fqs[table]
            if len(fqs) == 1:
                replacements.append((match.start("table"), match.end("table"), fqs[0]))
            continue
        if allowed_fq:
            raise ValueError(
                f"Query references table '{table}' which is not in the filtered catalog."
            )

    if not replacements:
        return sql
    out = sql
    for start, end, fq in reversed(replacements):
        out = out[:start] + fq + out[end:]
    return out


def _normalize_llm_sql(sql: str, *, dialect: str = "mysql") -> str:
    """Collapse whitespace, drop trailing semicolons, keep first read query if LLM emitted several."""
    _ = dialect
    normalized = _strip_sql_line_comments(re.sub(r"\s+", " ", sql.strip()))
    if not normalized:
        raise ValueError("Empty SQL was generated.")

    fragment = _first_read_query_fragment(normalized)
    if fragment:
        normalized = fragment

    while normalized.endswith(";"):
        normalized = normalized[:-1].strip()
        normalized = re.sub(r"\s+", " ", normalized)

    normalized = _strip_trailing_unmatched_parens(normalized)

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
        return _strip_trailing_unmatched_parens(picked)
    raise ValueError("Only read-only SELECT queries are allowed.")


def _matching_close_paren(sql: str, open_idx: int) -> int | None:
    depth = 0
    in_quote = False
    i = open_idx
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_quote:
            in_quote = True
        elif ch == "'" and in_quote:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_quote = False
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def _lhs_ident_start(sql: str, eq_pos: int) -> int | None:
    """Start index of the identifier (possibly schema.table.col) left of ``=``."""
    i = eq_pos - 1
    while i >= 0 and sql[i].isspace():
        i -= 1
    if i < 0:
        return None
    end = i
    while i >= 0:
        if sql[i] in {"`", '"'}:
            quote = sql[i]
            i -= 1
            while i >= 0 and sql[i] != quote:
                i -= 1
            if i >= 0:
                i -= 1
        elif sql[i].isalnum() or sql[i] == "_":
            while i >= 0 and (sql[i].isalnum() or sql[i] == "_"):
                i -= 1
        else:
            break
        j = i
        while j >= 0 and sql[j].isspace():
            j -= 1
        if j >= 0 and sql[j] == ".":
            j -= 1
            while j >= 0 and sql[j].isspace():
                j -= 1
            i = j
            continue
        break
    start = i + 1
    while start <= end and sql[start].isspace():
        start += 1
    if start > end:
        return None
    return start


def _rewrite_scalar_eq_subqueries(sql: str) -> str:
    """Rewrite ``col = (SELECT ...)`` to ``col IN (SELECT ...)``.

    Doris rejects some uncorrelated scalar subqueries (``SCALARSUBQUERY`` /
    ``Expected EQ 1``). ``IN`` is equivalent for a single-column subquery and
    applies to any SQL, not a named table or question.
    """
    replacements: list[tuple[int, int]] = []  # (eq_pos, open_paren)
    i = 0
    in_quote = False
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_quote:
            in_quote = True
            i += 1
            continue
        if ch == "'" and in_quote:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_quote = False
            i += 1
            continue
        if in_quote:
            i += 1
            continue
        if (
            ch == "="
            and (i == 0 or sql[i - 1] not in "<>=!")
            and (i + 1 >= len(sql) or sql[i + 1] != "=")
        ):
            j = i + 1
            while j < len(sql) and sql[j].isspace():
                j += 1
            if j < len(sql) and sql[j] == "(":
                k = j + 1
                while k < len(sql) and sql[k].isspace():
                    k += 1
                if sql[k : k + 6].upper() == "SELECT" and _lhs_ident_start(sql, i) is not None:
                    end = _matching_close_paren(sql, j)
                    if end is not None:
                        replacements.append((i, j))
                        i = end + 1
                        continue
        i += 1

    if not replacements:
        return sql
    out = sql
    for eq_pos, open_pos in reversed(replacements):
        out = out[:eq_pos].rstrip() + " IN " + out[open_pos:]
    return out


# MySQL/Doris reserved words that fail as unquoted FROM/JOIN tables (any schema).
_MYSQL_RESERVED_TABLES = frozenset({"match", "sets", "order", "event"})

# Illegal in Doris column names; same sanitizer as scripts/codegen/generate_cdc.py.
_DORIS_IDENT_ILLEGAL = re.compile(r"[^\w\s/.\-+/?@#$%^&*\"\s,:]")


def _split_args_top_level(inner: str) -> list[str]:
    """Split function-argument list on commas outside strings/parens."""
    args: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote = False
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "'" and not in_quote:
            in_quote = True
            buf.append(ch)
        elif ch == "'" and in_quote:
            if i + 1 < len(inner) and inner[i + 1] == "'":
                buf.append("''")
                i += 1
            else:
                in_quote = False
                buf.append(ch)
        elif in_quote:
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def _find_fn_calls(sql: str, name: str) -> list[tuple[int, int, int]]:
    """Return (name_start, open_paren, close_paren) for ``name(...)`` outside strings."""
    n = len(name)
    found: list[tuple[int, int, int]] = []
    i = 0
    in_quote = False
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_quote:
            in_quote = True
        elif ch == "'" and in_quote:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_quote = False
        elif not in_quote and sql[i : i + n].lower() == name.lower():
            prev = sql[i - 1] if i else ""
            if prev.isalnum() or prev == "_":
                i += 1
                continue
            j = i + n
            while j < len(sql) and sql[j].isspace():
                j += 1
            if j < len(sql) and sql[j] == "(":
                end = _matching_close_paren(sql, j)
                if end is not None:
                    found.append((i, j, end))
                    i = end + 1
                    continue
        i += 1
    return found


def _sqlite_strftime_fmt_to_mysql(fmt: str) -> str:
    """Map SQLite strftime tokens that differ from MySQL DATE_FORMAT."""
    out: list[str] = []
    i = 0
    while i < len(fmt):
        if fmt[i] == "%" and i + 1 < len(fmt):
            spec = fmt[i : i + 2]
            out.append({"%M": "%i", "%S": "%s"}.get(spec, spec))
            i += 2
            continue
        out.append(fmt[i])
        i += 1
    return "".join(out)


def _rewrite_strftime_family(sql: str) -> str:
    """SQLite ``strftime(fmt, expr)`` → MySQL/Doris ``DATE_FORMAT(expr, fmt)``."""
    calls = _find_fn_calls(sql, "strftime")
    if not calls:
        return sql
    out = sql
    for start, open_paren, close_paren in reversed(calls):
        args = _split_args_top_level(out[open_paren + 1 : close_paren])
        if len(args) < 2:
            continue
        fmt_raw = args[0].strip()
        expr = args[1].strip()
        if len(fmt_raw) >= 2 and fmt_raw[0] == fmt_raw[-1] == "'":
            fmt = _sqlite_strftime_fmt_to_mysql(fmt_raw[1:-1])
        else:
            continue
        expr_norm = expr.lower().replace(" ", "")
        if expr_norm in {"'now'", "now()"}:
            expr = "NOW()"
        out = out[:start] + f"DATE_FORMAT({expr}, '{fmt}')" + out[close_paren + 1 :]
    return out


def _rewrite_sqlite_now_fns(sql: str) -> str:
    """``datetime('now')`` / ``date('now')`` / ``time('now')`` → NOW/CURDATE/CURTIME."""
    mapping = {
        "datetime": "NOW()",
        "date": "CURDATE()",
        "time": "CURTIME()",
    }
    out = sql
    for name, repl in mapping.items():
        for start, open_paren, close_paren in reversed(_find_fn_calls(out, name)):
            inner = out[open_paren + 1 : close_paren].strip()
            if inner.lower().replace(" ", "") != "'now'":
                continue
            out = out[:start] + repl + out[close_paren + 1 :]
    return out


def _rewrite_iif(sql: str) -> str:
    """SQLite ``IIF(a, b, c)`` → MySQL ``IF(a, b, c)``."""
    out = sql
    for start, open_paren, close_paren in reversed(_find_fn_calls(out, "iif")):
        out = out[:start] + "IF" + out[open_paren : close_paren + 1]
    return out


def _span_operand_right(sql: str, i: int) -> int:
    """Exclusive end index of an expression starting at ``i`` (leading space skipped)."""
    while i < len(sql) and sql[i].isspace():
        i += 1
    if i >= len(sql):
        return i
    if sql[i] == "'":
        i += 1
        while i < len(sql):
            if sql[i] == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            if sql[i] == "'":
                return i + 1
            i += 1
        return i
    if sql[i] == "`":
        i += 1
        while i < len(sql) and sql[i] != "`":
            i += 1
        return min(i + 1, len(sql))
    if sql[i] == "(":
        end = _matching_close_paren(sql, i)
        return (end + 1) if end is not None else i
    if sql[i].isdigit() or (sql[i] == "." and i + 1 < len(sql) and sql[i + 1].isdigit()):
        while i < len(sql) and (sql[i].isdigit() or sql[i] == "."):
            i += 1
        return i
    if sql[i].isalpha() or sql[i] == "_":
        while i < len(sql):
            if sql[i].isalnum() or sql[i] == "_":
                i += 1
                continue
            j = i
            while j < len(sql) and sql[j].isspace():
                j += 1
            if j < len(sql) and sql[j] == ".":
                i = j + 1
                while i < len(sql) and sql[i].isspace():
                    i += 1
                if i < len(sql) and sql[i] == "`":
                    i += 1
                    while i < len(sql) and sql[i] != "`":
                        i += 1
                    i = min(i + 1, len(sql))
                continue
            if j < len(sql) and sql[j] == "(":
                end = _matching_close_paren(sql, j)
                return (end + 1) if end is not None else i
            break
        return i
    return i


def _span_operand_left(sql: str, pos: int) -> int:
    """Inclusive start index of the expression ending just before ``pos``."""
    i = pos
    while i > 0 and sql[i - 1].isspace():
        i -= 1
    if i <= 0:
        return 0
    i -= 1
    if sql[i] == "'":
        i -= 1
        while i >= 0:
            if sql[i] == "'" and i > 0 and sql[i - 1] == "'":
                i -= 2
                continue
            if sql[i] == "'":
                return i
            i -= 1
        return 0
    if sql[i] == "`":
        i -= 1
        while i >= 0 and sql[i] != "`":
            i -= 1
        return max(i, 0)
    if sql[i] == ")":
        depth = 0
        in_quote = False
        k = i
        while k >= 0:
            ch = sql[k]
            if ch == "'" and not in_quote:
                in_quote = True
            elif ch == "'" and in_quote:
                if k > 0 and sql[k - 1] == "'":
                    k -= 1
                else:
                    in_quote = False
            elif not in_quote:
                if ch == ")":
                    depth += 1
                elif ch == "(":
                    depth -= 1
                    if depth == 0:
                        k -= 1
                        while k >= 0 and sql[k].isspace():
                            k -= 1
                        if k >= 0 and (sql[k].isalnum() or sql[k] == "_"):
                            while k >= 0 and (sql[k].isalnum() or sql[k] == "_"):
                                k -= 1
                            return k + 1
                        return k + 1
            k -= 1
        return 0
    if sql[i].isdigit() or sql[i] == ".":
        while i >= 0 and (sql[i].isdigit() or sql[i] == "."):
            i -= 1
        return i + 1
    if sql[i].isalnum() or sql[i] == "_":
        while i >= 0:
            if sql[i].isalnum() or sql[i] == "_":
                i -= 1
                continue
            if sql[i] == "`":
                i -= 1
                while i >= 0 and sql[i] != "`":
                    i -= 1
                i -= 1
                continue
            j = i
            while j >= 0 and sql[j].isspace():
                j -= 1
            if j >= 0 and sql[j] == ".":
                i = j - 1
                while i >= 0 and sql[i].isspace():
                    i -= 1
                continue
            break
        return i + 1
    return i + 1


def _pipe_positions(sql: str) -> list[int]:
    """Start index of each ``||`` outside single-quoted strings."""
    pos: list[int] = []
    i = 0
    in_quote = False
    while i < len(sql) - 1:
        ch = sql[i]
        if ch == "'" and not in_quote:
            in_quote = True
        elif ch == "'" and in_quote:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_quote = False
        elif not in_quote and sql[i : i + 2] == "||":
            pos.append(i)
            i += 2
            continue
        i += 1
    return pos


def _rewrite_pipe_concat(sql: str) -> str:
    """SQLite ``a || b`` concatenation → MySQL ``CONCAT(a, b)``."""
    pipes = _pipe_positions(sql)
    if not pipes:
        return sql
    chains: list[list[int]] = []
    current = [pipes[0]]
    for p in pipes[1:]:
        left = _span_operand_left(sql, p)
        prev_right = _span_operand_right(sql, current[-1] + 2)
        if left <= prev_right:
            current.append(p)
        else:
            chains.append(current)
            current = [p]
    chains.append(current)

    out = sql
    for chain in reversed(chains):
        start = _span_operand_left(out, chain[0])
        end = _span_operand_right(out, chain[-1] + 2)
        pieces: list[str] = []
        cursor = start
        for p in chain:
            pieces.append(out[cursor:p].strip())
            cursor = p + 2
        pieces.append(out[cursor:end].strip())
        if any(not p for p in pieces):
            continue
        out = out[:start] + "CONCAT(" + ", ".join(pieces) + ")" + out[end:]
    return out


def _rewrite_double_quotes_to_backticks(sql: str) -> str:
    """SQLite/PG ``\"ident\"`` → MySQL/Doris backticks (Doris treats \" as a string)."""
    out: list[str] = []
    i = 0
    in_single = False
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_single:
            in_single = True
            out.append(ch)
        elif ch == "'" and in_single:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_single = False
            out.append(ch)
        elif not in_single and ch == '"':
            j = i + 1
            while j < len(sql) and sql[j] != '"':
                j += 1
            inner = sql[i + 1 : j] if j <= len(sql) else sql[i + 1 :]
            out.append("`" + inner.replace("`", "") + "`")
            i = j + 1 if j < len(sql) else len(sql)
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _doris_sanitize_ident(name: str) -> str:
    """Mirror CDC ``doris_column_name``: parentheses and other illegal chars → ``_``."""
    cleaned = _DORIS_IDENT_ILLEGAL.sub("_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_ ")
    return cleaned or name


def _rewrite_cdc_backtick_idents(sql: str) -> str:
    """Sanitize backticked identifiers that CDC could not keep (parens, etc.)."""

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not _DORIS_IDENT_ILLEGAL.search(inner):
            return match.group(0)
        return f"`{_doris_sanitize_ident(inner)}`"

    return re.sub(r"`([^`]+)`", repl, sql)


def _lowercase_unquoted_idents(sql: str) -> str:
    """Fold unquoted identifiers to lowercase (Doris views are lowercase; unquoted is case-sensitive)."""
    out: list[str] = []
    i = 0
    in_single = False
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_single:
            in_single = True
            out.append(ch)
        elif ch == "'" and in_single:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_single = False
            out.append(ch)
        elif not in_single and ch == "`":
            j = i + 1
            while j < len(sql) and sql[j] != "`":
                j += 1
            out.append(sql[i : min(j + 1, len(sql))])
            i = j + 1 if j < len(sql) else len(sql)
            continue
        elif not in_single and (ch.isalpha() or ch == "_"):
            j = i + 1
            while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            out.append(sql[i:j].lower())
            i = j
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _quote_reserved_from_join_tables(sql: str) -> str:
    """Backtick reserved MySQL/Doris table names after FROM/JOIN (``match``, ``sets``, …)."""
    replacements: list[tuple[int, int, str]] = []
    for match in _from_join_table_matches(sql):
        table_raw = match.group("table")
        table = _unquote_ident(table_raw)
        if table.lower() not in _MYSQL_RESERVED_TABLES:
            continue
        quoted = f"`{table.lower()}`"
        if table_raw == quoted:
            continue
        replacements.append((match.start("table"), match.end("table"), quoted))
    if not replacements:
        return sql
    out = sql
    for start, end, quoted in reversed(replacements):
        out = out[:start] + quoted + out[end:]
    return out


def _rewrite_sqlite_to_mysql(sql: str) -> str:
    """Universal SQLite → MySQL/Doris dialect compiler (no schema- or question-specific patches)."""
    out = _rewrite_double_quotes_to_backticks(sql)
    out = _rewrite_strftime_family(out)
    out = _rewrite_sqlite_now_fns(out)
    out = _rewrite_iif(out)
    out = _rewrite_pipe_concat(out)
    out = _rewrite_cdc_backtick_idents(out)
    out = _lowercase_unquoted_idents(out)
    return out


def validate_sql(
    sql: str,
    *,
    allowed_tables: tuple[str, ...] | list[str] | None = None,
    allowed_schemas: tuple[str, ...] | list[str] | None = None,
    dialect: str = "mysql",
) -> str:
    dialect_n = (dialect or "mysql").strip().lower()
    if dialect_n in {"postgres", "pg"}:
        dialect_n = "postgresql"
    if dialect_n == "doris":
        dialect_n = "mysql"
    normalized = _normalize_llm_sql(sql, dialect=dialect_n)

    if _NON_SQL_MARKERS.search(normalized):
        raise ValueError("Only read-only SELECT queries are allowed.")
    if not _looks_like_sql(normalized):
        raise ValueError("Only read-only SELECT queries are allowed.")

    lowered = normalized.lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise ValueError("Only SELECT queries are allowed.")

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            raise ValueError(f"Blocked keyword detected: {keyword}.")

    allowed = list(allowed_schemas) if allowed_schemas is not None else settings.allowed_schemas
    if dialect_n == "mysql":
        normalized = _rewrite_sqlite_to_mysql(normalized)
    qualified = _qualify_and_enforce_tables(
        normalized,
        allowed_tables=allowed_tables,
        allowed_schemas=allowed,
    )
    if dialect_n == "mysql":
        qualified = _quote_reserved_from_join_tables(qualified)
        qualified = _rewrite_scalar_eq_subqueries(qualified)
    return qualified
