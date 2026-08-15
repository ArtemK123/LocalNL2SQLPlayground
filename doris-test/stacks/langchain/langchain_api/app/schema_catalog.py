from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.schema_bm25 import bm25_pruned_schema_text, schema_text_from_table_meta

log = logging.getLogger(__name__)


class BirdTablesCatalog:
    """Load BIRD minidev/dev_tables.json once and serve Study-format schemas."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._by_db: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(f"BIRD tables.json not found: {self.path}")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"Expected list in {self.path}")
        self._by_db = {str(t["db_id"]): t for t in raw if isinstance(t, dict) and "db_id" in t}
        log.info("Loaded BIRD tables metadata for %d db_id(s) from %s", len(self._by_db), self.path)

    def meta(self, db_id: str) -> Mapping[str, Any]:
        key = db_id.strip()
        if key not in self._by_db:
            raise KeyError(f"Unknown db_id for BIRD tables: {db_id!r}")
        return self._by_db[key]

    def schema_for(
        self,
        db_id: str,
        question: str,
        evidence: str = "",
        *,
        enabled: bool,
        top_k: int,
        include_fk: bool,
    ) -> tuple[str, tuple[str, ...], bool]:
        """Return (schema_text, selected_table_names, used_full)."""
        meta = self.meta(db_id)
        all_tables = [str(t) for t in meta["table_names_original"]]
        if not enabled or len(all_tables) <= max(1, top_k):
            text_out = schema_text_from_table_meta(meta)
            return text_out, tuple(all_tables), True
        text_out, chosen = bm25_pruned_schema_text(
            meta,
            question,
            evidence,
            top_k=top_k,
            include_fk_neighbors=include_fk,
        )
        ordered = [t for t in all_tables if t in chosen]
        used_full = len(ordered) >= len(all_tables)
        return text_out, tuple(ordered), used_full


@dataclass(frozen=True)
class TableEntry:
    schema_name: str
    table_name: str
    columns: tuple[tuple[str, str], ...]  # (column_name, data_type)

    @property
    def key(self) -> tuple[str, str]:
        return (self.schema_name, self.table_name)

    @property
    def fq(self) -> str:
        return f"{self.schema_name}.{self.table_name}"

    def format_reference_line(self) -> str:
        if not self.columns:
            return self.fq
        col_parts = [f"{c} ({t})" for c, t in self.columns]
        return f"{self.fq}: {', '.join(col_parts)}"

    def format_create_table(self) -> str:
        """OmniSQL-style CREATE TABLE using schema.table (Doris needs the qualifier)."""

        def _ident(name: str) -> str:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                return name
            return f"`{name.replace('`', '')}`"

        lines = [f"CREATE TABLE {self.fq} ("]
        col_defs: list[str] = []
        for col_name, data_type in self.columns:
            ctype = (data_type or "text").upper()
            col_defs.append(f"  {_ident(col_name)} {ctype}")
        if col_defs:
            lines.append(",\n".join(col_defs))
        lines.append(");")
        return "\n".join(lines)

    def bm25_document(self) -> str:
        names = [c for c, _ in self.columns]
        return f"{self.fq} {' '.join(names)}"


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _normalize_token(token: str) -> str:
    t = token.lower().strip("_")
    # Very small singularization heuristic to improve overlap recall.
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _normalized_tokens(text: str) -> set[str]:
    return {_normalize_token(t) for t in _tokenize(text) if t}


def _system_schema_excludes() -> str:
    if settings.is_mysql:
        return "('information_schema', 'mysql', 'sys', 'bird_minidev_olap')"
    return "('pg_catalog', 'information_schema')"


def discover_user_schemas(engine: Engine) -> list[str]:
    sql = f"""
    SELECT DISTINCT table_schema
    FROM information_schema.tables
    WHERE table_type IN ('BASE TABLE', 'VIEW')
      AND table_schema NOT IN {_system_schema_excludes()}
    ORDER BY table_schema
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    return [r[0] for r in rows]


def resolve_allowed_schemas(engine: Engine, configured: Sequence[str]) -> list[str]:
    """Use configured schemas when set; else discover all user schemas from the DB."""
    schemas = [s.strip() for s in configured if s and str(s).strip()]
    if not schemas:
        discovered = discover_user_schemas(engine)
        if discovered:
            log.info("DB_ALLOWED_SCHEMAS unset; using all %d user schemas", len(discovered))
            return discovered
        return ["public"]
    entries = load_table_catalog(engine, schemas)
    if entries:
        return schemas
    public_entries = load_table_catalog(engine, ["public"])
    if public_entries and "public" not in {s.lower() for s in schemas}:
        log.warning(
            "No tables in configured schemas %s; falling back to public (%d tables)",
            schemas,
            len(public_entries),
        )
        return ["public"]
    return schemas


def load_table_catalog(engine: Engine, allowed_schemas: Sequence[str]) -> list[TableEntry]:
    schema_list = list(allowed_schemas)
    if settings.is_mysql:
        placeholders = ", ".join(f":s{i}" for i in range(len(schema_list)))
        tables_sql = f"""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ({placeholders})
          AND table_type IN ('BASE TABLE', 'VIEW')
        ORDER BY table_schema, table_name
        """
        columns_sql = f"""
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema IN ({placeholders})
        ORDER BY table_schema, table_name, ordinal_position
        """
        params = {f"s{i}": s for i, s in enumerate(schema_list)}
    else:
        tables_sql = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = ANY(:schemas)
          AND table_type IN ('BASE TABLE', 'VIEW')
        ORDER BY table_schema, table_name
        """
        columns_sql = """
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = ANY(:schemas)
        ORDER BY table_schema, table_name, ordinal_position
        """
        params = {"schemas": schema_list}
    with engine.connect() as conn:
        table_rows = conn.execute(text(tables_sql), params).fetchall()
        col_rows = conn.execute(text(columns_sql), params).fetchall()

    cols_by_table: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for schema, table, column_name, data_type in col_rows:
        cols_by_table[(schema, table)].append((column_name, data_type))

    out: list[TableEntry] = []
    for schema, table in table_rows:
        key = (schema, table)
        cols = tuple(cols_by_table.get(key, ()))
        out.append(TableEntry(schema_name=schema, table_name=table, columns=cols))
    return out


def filter_catalog_by_db_id(entries: list[TableEntry], db_id: str | None, *, db_id_as_schema: bool) -> list[TableEntry]:
    if not db_id or not db_id.strip() or not db_id_as_schema:
        return list(entries)
    d = db_id.strip().lower()
    matched = [e for e in entries if e.schema_name.lower() == d]
    if matched:
        return matched
    # Underscore/hyphen drift between BIRD db_id and Doris database names.
    d_norm = d.replace("-", "_")
    return [e for e in entries if e.schema_name.lower().replace("-", "_") == d_norm]


def format_schema_subset(entries: Sequence[TableEntry], *, db_id: str | None = None) -> str:
    """Study-like CREATE TABLE blocks; FQNs so Arctic copies schema.table for Doris."""
    if not entries:
        return "(no visible tables/views)"
    header = ""
    if db_id and db_id.strip():
        schema = db_id.strip()
        header = (
            f"Database schema `{schema}` only. Every table must be written as {schema}.table. "
            f"`{schema}` is a schema name, not a table. Do not use other BIRD databases.\n\n"
        )
    return header + "\n\n".join(e.format_create_table() for e in entries)


def compact_catalog_for_selector(entries: Sequence[TableEntry], *, max_line_len: int = 500) -> list[str]:
    """One line per table: fq + column names (types omitted) for the selector LLM."""
    lines: list[str] = []
    for e in entries:
        names = ", ".join(c for c, _ in e.columns) if e.columns else ""
        s = f"{e.fq}: {names}" if names else e.fq
        if len(s) > max_line_len:
            s = s[: max_line_len - 3] + "..."
        lines.append(s)
    return lines


def bm25_shortlist(entries: list[TableEntry], question: str, top_m: int) -> list[TableEntry]:
    """Return top_m tables by BM25 over fq+column names; if top_m <= 0 or few entries, return all."""
    if top_m <= 0 or len(entries) <= top_m:
        return list(entries)
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        return list(entries)

    corpus = [_tokenize(e.bm25_document()) for e in entries]
    if not any(corpus):
        return list(entries)
    q = _tokenize(question)
    if not q:
        return list(entries[:top_m])
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(q)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    pick = ranked[:top_m]
    return [entries[i] for i in pick]


@dataclass(frozen=True)
class SelectionResult:
    selected_entries: tuple[TableEntry, ...]
    schema_reference: str
    selected_table_fq: tuple[str, ...]
    allowed_table_fq: tuple[str, ...]
    used_fallback_full_schema: bool
    db_id: str | None = None


class SchemaSelector:
    def __init__(
        self,
        *,
        engine: Engine,
        allowed_schemas: Sequence[str],
        enabled: bool,
        shortlist_top_m: int,
        final_top_k: int,
        mode: str,
        refresh_seconds: int,
        schema_source: str = "catalog",
        bird_tables: BirdTablesCatalog | None = None,
        include_fk_neighbors: bool = True,
        llm_selector: Callable[[str, list[str]], list[str]] | None = None,
    ) -> None:
        self.engine = engine
        self.allowed_schemas = tuple(allowed_schemas)
        self.enabled = enabled
        self.shortlist_top_m = max(1, shortlist_top_m)
        self.final_top_k = max(1, final_top_k)
        self.mode = mode.lower().strip()
        self.refresh_seconds = max(0, refresh_seconds)
        self.schema_source = (schema_source or "catalog").strip().lower()
        self.bird_tables = bird_tables
        self.include_fk_neighbors = include_fk_neighbors
        self.llm_selector = llm_selector
        self._catalog: list[TableEntry] = []
        self._loaded_at = 0.0

    def _maybe_refresh_catalog(self) -> list[TableEntry]:
        now = monotonic()
        if not self._catalog or (self.refresh_seconds > 0 and (now - self._loaded_at) >= self.refresh_seconds):
            self._catalog = load_table_catalog(self.engine, self.allowed_schemas)
            self._loaded_at = now
        return self._catalog

    def _heuristic_rank(self, entries: list[TableEntry], question: str) -> list[TableEntry]:
        q_tokens = _normalized_tokens(question)
        if not q_tokens:
            return entries

        def score(entry: TableEntry) -> tuple[int, int, int]:
            table_tokens = _normalized_tokens(entry.table_name)
            schema_tokens = _normalized_tokens(entry.schema_name)
            col_tokens: set[str] = set()
            for col_name, _dtype in entry.columns:
                col_tokens.update(_normalized_tokens(col_name))
            table_overlap = len(q_tokens & table_tokens)
            col_overlap = len(q_tokens & col_tokens)
            schema_overlap = len(q_tokens & schema_tokens)
            return (table_overlap * 5 + col_overlap * 2 + schema_overlap, table_overlap, col_overlap)

        return sorted(entries, key=score, reverse=True)

    def _apply_llm_selection(self, question: str, ranked: list[TableEntry]) -> list[TableEntry]:
        if not self.llm_selector or self.mode not in {"llm", "hybrid"}:
            return ranked[: self.final_top_k]
        compact_lines = compact_catalog_for_selector(ranked, max_line_len=220)[: self.shortlist_top_m]
        picked = {v.strip().lower() for v in self.llm_selector(question, compact_lines) if v.strip()}
        if not picked:
            return ranked[: self.final_top_k]
        chosen = [e for e in ranked if e.fq.lower() in picked]
        if not chosen:
            return ranked[: self.final_top_k]
        return chosen[: self.final_top_k]

    def reference_for(
        self,
        question: str,
        *,
        db_id: str | None = None,
        evidence: str | None = None,
    ) -> SelectionResult:
        if self.schema_source == "bird_tables":
            return self._reference_from_bird_tables(question, db_id, evidence)
        all_entries = self._maybe_refresh_catalog()
        scoped = filter_catalog_by_db_id(
            all_entries,
            db_id,
            db_id_as_schema=settings.db_id_as_schema,
        )
        if db_id and settings.db_id_as_schema and not scoped and all_entries:
            # Mixing all BIRD databases teaches Arctic to emit the wrong db_id.
            log.warning(
                "db_id=%r matched no schemas (DB_ID_AS_SCHEMA=true); "
                "keeping empty catalog instead of all %d tables",
                db_id,
                len(all_entries),
            )
        if not scoped:
            return SelectionResult(
                selected_entries=tuple(),
                schema_reference=format_schema_subset(scoped, db_id=db_id),
                selected_table_fq=tuple(),
                allowed_table_fq=tuple(),
                used_fallback_full_schema=True,
                db_id=db_id,
            )
        # After a db_id schema filter, list every table in that schema. BM25 top-K
        # on a single BIRD database drops join partners (legalities, seasons, users).
        if (db_id and settings.db_id_as_schema) or not self.enabled or len(scoped) <= self.final_top_k:
            selected = scoped
        else:
            query = f"{question or ''} {evidence or ''}".strip()
            shortlist = bm25_shortlist(scoped, query, self.shortlist_top_m)
            ranked = shortlist if self.mode == "llm" else self._heuristic_rank(shortlist, query)
            selected = self._apply_llm_selection(question, ranked)
            if not selected:
                selected = ranked[: self.final_top_k] if ranked else shortlist[: self.final_top_k]
            if not selected:
                selected = scoped
        schema_reference = format_schema_subset(selected, db_id=db_id)
        used_fallback = not self.enabled or not selected or len(selected) >= len(scoped)
        return SelectionResult(
            selected_entries=tuple(selected),
            schema_reference=schema_reference,
            selected_table_fq=tuple(e.fq for e in selected),
            allowed_table_fq=tuple(e.fq for e in scoped),
            used_fallback_full_schema=used_fallback,
            db_id=db_id,
        )

    def _reference_from_bird_tables(
        self,
        question: str,
        db_id: str | None,
        evidence: str | None,
    ) -> SelectionResult:
        if not self.bird_tables:
            raise RuntimeError("schema_source=bird_tables but BirdTablesCatalog is not configured")
        if not db_id or not str(db_id).strip():
            raise ValueError("db_id is required when SCHEMA_SOURCE=bird_tables")
        key = str(db_id).strip()
        schema_text, tables, used_full = self.bird_tables.schema_for(
            key,
            question,
            evidence or "",
            enabled=self.enabled,
            top_k=self.final_top_k,
            include_fk=self.include_fk_neighbors,
        )
        # OmniSQL prompt uses bare CREATE TABLE names (Study parity). Qualify
        # as db_id.table so sql_guard can rewrite FROM/JOIN for Doris.
        selected_fq = tuple(f"{key}.{t}" for t in tables)
        return SelectionResult(
            selected_entries=tuple(),
            schema_reference=schema_text,
            selected_table_fq=selected_fq,
            allowed_table_fq=selected_fq,
            used_fallback_full_schema=used_full,
            db_id=key,
        )
