from __future__ import annotations

import re
from typing import Optional

_CTE_WITH = re.compile(r"\bwith\s+[a-z_][a-z0-9_]*\s+as\s*\(", re.IGNORECASE)
_SELECT = re.compile(r"\bselect\b", re.IGNORECASE)
_NOISE_LINE = re.compile(r"^(sql|json|markdown|result preview)\s*$", re.IGNORECASE)


def _trim_sql_fragment(fragment: str) -> str:
    lines = []
    for line in fragment.splitlines():
        if _NOISE_LINE.match(line.strip()):
            continue
        lines.append(line)
    s = "\n".join(lines).strip().strip("`").rstrip(";")
    for sep in ("\n未", "\n就绪", "\nStep ID:", "\n1 个输出", "\nResult preview:", "\nModel:"):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    if ";" in s:
        s = s.split(";", 1)[0].strip()
    return s


def _looks_like_sql(sql: str) -> bool:
    """Reject NL fragments that happen to contain SQL keywords."""
    if not sql or len(sql) < 8:
        return False
    if re.search(r"\)\s*\.|\)\s*\n\s*sql\b", sql, re.IGNORECASE):
        return False
    low = sql.lower()
    if _CTE_WITH.search(low):
        return True
    if not _SELECT.search(low):
        return False
    if re.search(r"\bfrom\b", low):
        return True
    if re.search(r"\bselect\s+(?:\*|\d+|count\s*\()", low):
        return True
    return False


def _sql_rank(sql: str) -> int:
    low = sql.lower()
    score = len(sql)
    if re.search(r"\bfrom\b", low):
        score += 200
    if re.search(r"\bjoin\b", low):
        score += 100
    if re.search(r"\bwhere\b", low):
        score += 50
    if re.search(r"\)\s*\.", sql):
        score -= 500
    return score


def _best_sql(candidates: list[str]) -> Optional[str]:
    best: Optional[str] = None
    best_rank = -1
    for raw in candidates:
        candidate = _trim_sql_fragment(raw)
        if not _looks_like_sql(candidate):
            continue
        rank = _sql_rank(candidate)
        if rank > best_rank:
            best_rank = rank
            best = candidate
    return best


def normalize_sql_candidate(text: str) -> Optional[str]:
    if not text:
        return None
    s = text.strip().replace("\\n", "\n").replace('\\"', '"')
    candidates: list[str] = []

    fenced = re.findall(r"```sql\s*(.*?)```", s, re.IGNORECASE | re.DOTALL)
    candidates.extend(fenced)
    if "```" in s:
        generic = re.findall(r"```\s*(.*?)```", s, re.DOTALL)
        candidates.extend(generic)
    for m in re.finditer(r"\bselect\b", s, re.IGNORECASE):
        tail = s[m.start() :]
        stop = len(tail)
        for marker in ("\n```", "\nResult preview:", "\nModel:", "\nReasoning trace:"):
            pos = tail.find(marker)
            if pos > 0:
                stop = min(stop, pos)
        candidates.append(tail[:stop])
    m = _CTE_WITH.search(s)
    if m:
        candidates.append(s[m.start() :])

    return _best_sql(candidates)


def extract_sql_from_page_text(text: str) -> Optional[str]:
    return normalize_sql_candidate(text)
