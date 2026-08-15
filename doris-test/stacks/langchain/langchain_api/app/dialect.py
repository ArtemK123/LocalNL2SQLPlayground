"""Shared MySQL/Doris dialect demand for OmniSQL / Arctic prompts (not per-question)."""

MYSQL_DIALECT_INSTRUCTIONS = (
    "- Emit Apache Doris / MySQL SQL only (schema.table). Do not emit SQLite or PostgreSQL.\n"
    "- Dates: use DATE_FORMAT(expr, '%Y'), YEAR(expr), MONTH(expr), NOW(), CURDATE(). "
    "Never use SQLite strftime, julianday, datetime('now'), date('now'), or time('now').\n"
    "- Strings: use CONCAT(a, b) or CONCAT(a, b, c). Never use SQLite || concatenation.\n"
    "- Identifiers: backtick reserved table names (`match`, `sets`, `order`, `event`). "
    "Backtick names with spaces or punctuation. Never PostgreSQL/SQLite double quotes around identifiers.\n"
    "- Conditionals: IF(a, b, c) not SQLite IIF. No PostgreSQL ILIKE, ::cast, or EXTRACT(EPOCH ...).\n"
    "- Prefer JOIN or IN over scalar subqueries; do not write col = (SELECT ...) "
    "(Doris requires those subqueries to return exactly one row)."
)
