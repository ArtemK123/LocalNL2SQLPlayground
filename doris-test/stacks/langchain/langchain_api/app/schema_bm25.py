"""BM25 table retrieval for eval-time schema pruning (Study parity).

Rank tables by BM25(question + evidence, table+column document) and optionally
expand with direct FK neighbors. Pure-Python Okapi BM25 — no extra deps.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Mapping, Optional

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_SPLIT_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _morph_variants(token: str) -> list[str]:
    """Cheap singular/plural variants (no external stemmer)."""
    t = token.lower()
    out = [t]
    if len(t) > 3 and t.endswith("ies"):
        out.append(t[:-3] + "y")
    elif len(t) > 3 and t.endswith("ses"):
        out.append(t[:-2])
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        out.append(t[:-1])
    else:
        out.append(t + "s")
    return out


def tokenize(text: str) -> list[str]:
    """Lowercase alnum/underscore tokens; also split snake/camel identifiers."""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text or ""):
        pieces = raw.replace("-", "_").split("_")
        for p in pieces:
            if not p:
                continue
            camel_parts = _SPLIT_CAMEL.sub(" ", p).split()
            for c in camel_parts:
                for v in _morph_variants(c):
                    out.append(v)
            for v in _morph_variants(p):
                out.append(v)
    return out


def _table_document(meta: Mapping[str, Any], table_idx: int) -> str:
    table_names: list[str] = list(meta["table_names_original"])
    column_names: list[list[Any]] = list(meta["column_names_original"])
    name = table_names[table_idx]
    cols = [str(c[1]) for c in column_names if int(c[0]) == table_idx]
    # Repeat table name to bias toward table-name hits in the question.
    return f"{name} {name} " + " ".join(cols)


class Bm25Index:
    """Okapi BM25 over a fixed list of documents."""

    def __init__(
        self,
        documents: list[list[str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = float(k1)
        self.b = float(b)
        self.docs = documents
        self.N = len(documents)
        self.doc_len = [len(d) for d in documents]
        self.avgdl = (sum(self.doc_len) / self.N) if self.N else 0.0
        df: Counter[str] = Counter()
        for d in documents:
            df.update(set(d))
        self.df = df
        self.idf: dict[str, float] = {
            t: math.log(1.0 + (self.N - f + 0.5) / (f + 0.5)) for t, f in df.items()
        }

    def score(self, query_tokens: list[str], doc_idx: int) -> float:
        if self.N == 0 or not query_tokens:
            return 0.0
        tf = Counter(self.docs[doc_idx])
        dl = self.doc_len[doc_idx]
        score = 0.0
        for t in query_tokens:
            if t not in tf:
                continue
            idf = self.idf.get(t, 0.0)
            freq = tf[t]
            denom = freq + self.k1 * (1.0 - self.b + self.b * dl / max(self.avgdl, 1e-9))
            score += idf * (freq * (self.k1 + 1.0) / denom)
        return score

    def top_k(self, query_tokens: list[str], k: int) -> list[tuple[int, float]]:
        scored = [(i, self.score(query_tokens, i)) for i in range(self.N)]
        scored.sort(key=lambda x: x[1], reverse=True)
        if k <= 0:
            return scored
        return scored[:k]


def fk_neighbor_tables(meta: Mapping[str, Any], tables: set[str]) -> set[str]:
    """Tables directly connected by a foreign key to any table in `tables`."""
    table_names: list[str] = list(meta["table_names_original"])
    column_names: list[list[Any]] = list(meta["column_names_original"])
    lower = {t.lower() for t in tables}
    out: set[str] = set()
    for fk in meta.get("foreign_keys") or []:
        if len(fk) != 2:
            continue
        try:
            from_t = int(column_names[int(fk[0])][0])
            to_t = int(column_names[int(fk[1])][0])
        except (IndexError, TypeError, ValueError):
            continue
        if from_t < 0 or to_t < 0:
            continue
        name_from = table_names[from_t]
        name_to = table_names[to_t]
        if name_from.lower() in lower:
            out.add(name_to)
        if name_to.lower() in lower:
            out.add(name_from)
    return out - tables


def bm25_relevant_tables(
    meta: Mapping[str, Any],
    question: str,
    evidence: str = "",
    *,
    top_k: int = 8,
    include_fk_neighbors: bool = True,
    min_score: float = 0.0,
) -> set[str]:
    """Return original table names ranked relevant to question (+ evidence)."""
    table_names: list[str] = list(meta["table_names_original"])
    if not table_names:
        return set()
    docs = [tokenize(_table_document(meta, i)) for i in range(len(table_names))]
    index = Bm25Index(docs)
    query = tokenize(f"{question or ''} {evidence or ''}")
    ranked = index.top_k(query, k=max(1, int(top_k)))
    chosen: set[str] = set()
    for idx, score in ranked:
        if score <= min_score and chosen:
            break
        if score > min_score or not chosen:
            chosen.add(table_names[idx])
    if not chosen:
        return set(table_names)
    if len(chosen) > top_k > 0:
        chosen = {table_names[i] for i, _ in ranked[:top_k]}
    if include_fk_neighbors:
        chosen |= fk_neighbor_tables(meta, chosen)
    return chosen


def schema_text_from_table_meta(
    meta: Mapping[str, Any],
    include_tables: Optional[set[str]] = None,
) -> str:
    """Build CREATE TABLE schema text from a BIRD tables.json entry (Study format)."""
    table_names: list[str] = list(meta["table_names_original"])
    include_lower: Optional[set[str]] = (
        {t.lower() for t in include_tables} if include_tables is not None else None
    )

    def _included(t_idx: int) -> bool:
        return include_lower is None or table_names[t_idx].lower() in include_lower

    column_names: list[list[Any]] = list(meta["column_names_original"])
    column_types: list[str] = list(meta["column_types"])
    primary_keys: list[Any] = list(meta.get("primary_keys") or [])
    foreign_keys: list[list[int]] = list(meta.get("foreign_keys") or [])

    pk_cols: set[int] = set()
    for pk in primary_keys:
        if isinstance(pk, list):
            pk_cols.update(int(x) for x in pk)
        else:
            pk_cols.add(int(pk))

    cols_by_table: dict[int, list[tuple[str, str, bool]]] = {
        i: [] for i in range(len(table_names))
    }
    for col_idx, (table_idx, col_name) in enumerate(column_names):
        if table_idx < 0:
            continue
        ctype = column_types[col_idx] if col_idx < len(column_types) else "text"
        cols_by_table[int(table_idx)].append(
            (str(col_name), str(ctype), col_idx in pk_cols)
        )

    fk_lines: list[str] = []
    for fk in foreign_keys:
        if len(fk) != 2:
            continue
        from_idx, to_idx = int(fk[0]), int(fk[1])
        from_t, from_c = column_names[from_idx]
        to_t, to_c = column_names[to_idx]
        if from_t < 0 or to_t < 0:
            continue
        if not (_included(int(from_t)) and _included(int(to_t))):
            continue
        fk_lines.append(
            f"  FOREIGN KEY ({table_names[from_t]}.{from_c}) "
            f"REFERENCES {table_names[to_t]}.{to_c}"
        )

    blocks: list[str] = []
    for t_idx, t_name in enumerate(table_names):
        if not _included(t_idx):
            continue
        lines = [f"CREATE TABLE {t_name} ("]
        col_defs: list[str] = []
        for col_name, ctype, is_pk in cols_by_table[t_idx]:
            pk = " PRIMARY KEY" if is_pk else ""
            col_defs.append(f"  {col_name} {ctype.upper()}{pk}")
        lines.append(",\n".join(col_defs))
        lines.append(");")
        blocks.append("\n".join(lines))

    if fk_lines:
        blocks.append("/* Foreign keys */\n" + "\n".join(fk_lines))

    return "\n\n".join(blocks)


def bm25_pruned_schema_text(
    meta: Mapping[str, Any],
    question: str,
    evidence: str = "",
    *,
    top_k: int = 8,
    include_fk_neighbors: bool = True,
    min_score: float = 0.0,
    include_tables: Optional[set[str]] = None,
) -> tuple[str, set[str]]:
    """Return (schema_text, selected_table_names)."""
    tables = include_tables or bm25_relevant_tables(
        meta,
        question,
        evidence,
        top_k=top_k,
        include_fk_neighbors=include_fk_neighbors,
        min_score=min_score,
    )
    return schema_text_from_table_meta(meta, include_tables=tables), set(tables)
