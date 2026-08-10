from __future__ import annotations

import csv
import json
import re
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
    difficulty: Optional[str] = None


def _iter_json_records(path: Path) -> Iterator[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return
    if text.startswith("["):
        data = json.loads(text)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    yield row
        return
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def _pick_question(row: dict[str, Any]) -> Optional[str]:
    for k in ("question", "Question", "utterance", "text"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _pick_sql(row: dict[str, Any]) -> Optional[str]:
    for k in ("SQL", "query", "sql", "gold_sql", "ground_truth"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _pick_id(row: dict[str, Any], index: int) -> str:
    for k in ("question_id", "id", "qid"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return str(index)


def load_questions_file(path: Path) -> list[BenchmarkItem]:
    out: list[BenchmarkItem] = []
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                q = _pick_question(row)
                if not q:
                    continue
                out.append(
                    BenchmarkItem(
                        question_id=_pick_id(row, i),
                        question=q,
                        gold_sql="",
                        db_id=(row.get("db_id") or row.get("DB_ID") or None),
                        evidence=row.get("evidence"),
                        difficulty=row.get("difficulty"),
                    )
                )
        return out

    for i, row in enumerate(_iter_json_records(path)):
        if not isinstance(row, dict):
            continue
        q = _pick_question(row)
        if not q:
            continue
        sql = _pick_sql(row) or ""
        db_id = row.get("db_id") or row.get("DB_ID")
        out.append(
            BenchmarkItem(
                question_id=_pick_id(row, i),
                question=q,
                gold_sql=sql,
                db_id=str(db_id) if db_id is not None else None,
                evidence=row.get("evidence") if isinstance(row.get("evidence"), str) else None,
                difficulty=row.get("difficulty") if isinstance(row.get("difficulty"), str) else None,
            )
        )
    return out


def load_gold_jsonl(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in _iter_json_records(path):
        if not isinstance(row, dict):
            continue
        sql = _pick_sql(row)
        if not sql:
            continue
        rid = _pick_id(row, len(mapping))
        mapping[rid] = sql
    return mapping


def load_gold_sql_file(path: Path) -> dict[str, str]:
    """Tab-separated gold file: {SQL}\\t{db_id} per line (minidev postgresql gold)."""
    if path.suffix.lower() in {".json", ".jsonl"}:
        return load_gold_jsonl(path)

    mapping: dict[str, str] = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            sql, _db = line.split("\t", 1)
            mapping[str(i)] = sql.strip()
        else:
            mapping[str(i)] = line
    return mapping


def merge_gold(items: list[BenchmarkItem], gold_map: dict[str, str]) -> list[BenchmarkItem]:
    merged: list[BenchmarkItem] = []
    for it in items:
        g = gold_map.get(it.question_id) or it.gold_sql
        merged.append(
            BenchmarkItem(
                question_id=it.question_id,
                question=it.question,
                gold_sql=g,
                db_id=it.db_id,
                evidence=it.evidence,
                difficulty=it.difficulty,
            )
        )
    return merged


def strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    lines = []
    for line in sql.splitlines():
        if "--" in line:
            line = line[: line.index("--")]
        lines.append(line)
    return " ".join(lines).strip()


def harness_root() -> Path:
    return Path(__file__).resolve().parents[2]


def package_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_datasets_root() -> Path:
    root = package_root()
    for candidate in (
        root / "datasets",
        root.parent / "datasets",
        root.parent.parent / "datasets",
    ):
        if (candidate / "minidev").is_dir():
            return candidate
    return root.parent.parent / "datasets"


def minidev_paths(datasets_root: Path) -> tuple[Path, Path]:
    base = datasets_root / "minidev" / "MINIDEV"
    questions = base / "mini_dev_postgresql.json"
    gold = base / "mini_dev_postgresql_gold.sql"
    if not questions.is_file():
        raise FileNotFoundError(f"minidev questions not found: {questions}")
    if not gold.is_file():
        raise FileNotFoundError(f"minidev gold not found: {gold}")
    return questions, gold


def suite_paths(suite: str, suites_dir: Optional[Path] = None) -> tuple[Path, Path]:
    base = suites_dir or (harness_root() / "test_suites" / "minidev")
    questions = base / f"{suite}.json"
    gold = base / f"{suite}_gold.jsonl"
    if not questions.is_file():
        raise FileNotFoundError(f"Suite questions not found: {questions}")
    if not gold.is_file():
        raise FileNotFoundError(f"Suite gold not found: {gold}")
    return questions, gold


def load_minidev_indexed_gold(gold_path: Path) -> list[str]:
    lines = [ln.strip() for ln in gold_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out: list[str] = []
    for line in lines:
        if "\t" in line:
            sql, _ = line.split("\t", 1)
            out.append(sql.strip())
        else:
            out.append(line)
    return out


def build_gold_map_by_index(questions_path: Path, gold_lines: list[str]) -> dict[str, str]:
    items = load_questions_file(questions_path)
    mapping: dict[str, str] = {}
    for i, it in enumerate(items):
        if i < len(gold_lines):
            mapping[it.question_id] = gold_lines[i]
    return mapping


def _question_json_paths() -> list[Path]:
    root = harness_root()
    paths: list[Path] = []
    for sub in ("minidev", "formula_1"):
        base = root / "test_suites" / sub
        if base.is_dir():
            paths.extend(sorted(p for p in base.glob("*.json") if "manifest" not in p.name))
    try:
        q, _ = minidev_paths(default_datasets_root())
        paths.append(q)
    except FileNotFoundError:
        pass
    return paths


def lookup_benchmark_item(question_id: str) -> BenchmarkItem:
    """Resolve NL question + gold SQL by BIRD minidev question_id."""
    qid = str(question_id).strip()
    if not qid:
        raise ValueError("question_id is required")

    gold_sql = ""
    full_gold = harness_root() / "test_suites" / "minidev" / "full_gold.jsonl"
    if full_gold.is_file():
        gold_sql = load_gold_jsonl(full_gold).get(qid, "")

    for qpath in _question_json_paths():
        for it in load_questions_file(qpath):
            if it.question_id != qid:
                continue
            return BenchmarkItem(
                question_id=qid,
                question=it.question,
                gold_sql=gold_sql or it.gold_sql,
                db_id=it.db_id,
                evidence=it.evidence,
                difficulty=it.difficulty,
            )

    if gold_sql:
        return BenchmarkItem(question_id=qid, question="", gold_sql=gold_sql)

    raise KeyError(
        f"question_id {qid!r} not found under harness/test_suites "
        f"(searched minidev, formula_1, datasets/minidev)"
    )
