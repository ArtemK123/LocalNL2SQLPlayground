from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional


@dataclass
class BenchmarkItem:
    question_id: str
    question: str
    gold_sql: str
    db_id: Optional[str] = None
    evidence: Optional[str] = None


def harness_root() -> Path:
    return Path(__file__).resolve().parents[2]


def suite_paths(suite: str) -> tuple[Path, Path]:
    base = harness_root() / "test_suites" / "minidev"
    return base / f"{suite}.json", base / f"{suite}_gold.jsonl"


def load_questions_file(path: Path) -> list[BenchmarkItem]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items: list[BenchmarkItem] = []
    for i, row in enumerate(data):
        evidence = row.get("evidence")
        items.append(
            BenchmarkItem(
                question_id=str(row.get("question_id", i)),
                question=str(row["question"]),
                gold_sql=str(row.get("SQL", row.get("gold_sql", ""))),
                db_id=(str(row["db_id"]) if row.get("db_id") is not None else None),
                evidence=str(evidence) if isinstance(evidence, str) and evidence.strip() else None,
            )
        )
    return items


def load_gold_jsonl(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        qid = str(row.get("question_id", row.get("id", "")))
        sql = row.get("SQL") or row.get("gold_sql") or row.get("sql")
        if qid and sql:
            out[qid] = str(sql).strip()
    return out


def merge_gold(items: list[BenchmarkItem], gold_map: dict[str, str]) -> list[BenchmarkItem]:
    merged: list[BenchmarkItem] = []
    for it in items:
        sql = gold_map.get(it.question_id, it.gold_sql)
        merged.append(
            BenchmarkItem(
                question_id=it.question_id,
                question=it.question,
                gold_sql=sql,
                db_id=it.db_id,
                evidence=it.evidence,
            )
        )
    return merged


def strip_sql_comments(sql: str) -> str:
    lines = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()
