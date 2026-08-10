#!/usr/bin/env python3
"""Build fixed-question_id minidev suites for nl2sql-comparison harness."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

# Fixed question_id lists (committed manifests).
# smoke_3: local 1-db profile — formula_1 only (public schema seed).
SUITE_IDS: dict[str, list[int] | None] = {
    "smoke_3": [847, 850, 854],
    "small_10": None,
    "medium_25": None,
    "big_100": None,
    "full": None,
}


def _harness_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _datasets_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    root = _harness_root()
    for candidate in (
        root.parent.parent.parent / "datasets",
        root.parent.parent / "datasets",
    ):
        if (candidate / "minidev").is_dir():
            return candidate.resolve()
    raise FileNotFoundError("datasets/ not found; pass --datasets-root")


def _formula_1_sources() -> tuple[Path, Path]:
    root = _harness_root() / "test_suites" / "formula_1"
    questions_path = root / "mini_dev_formula_1_postgresql.json"
    gold_path = root / "mini_dev_formula_1_postgresql_gold.sql"
    if not questions_path.is_file() or not gold_path.is_file():
        raise FileNotFoundError(
            f"formula_1 suite sources missing under {root} "
            "(copy from battleground_local/harness/test_suites/formula_1/)"
        )
    return questions_path, gold_path


def _load_minidev(
    datasets_root: Path,
    *,
    db_profile: str = "full",
) -> tuple[list[dict], list[str], dict[str, str]]:
    if db_profile == "1-db":
        questions_path, gold_path = _formula_1_sources()
        source_files = {
            "questions": "harness/test_suites/formula_1/mini_dev_formula_1_postgresql.json",
            "gold": "harness/test_suites/formula_1/mini_dev_formula_1_postgresql_gold.sql",
            "db_profile": "1-db",
        }
    else:
        base = datasets_root / "minidev" / "MINIDEV"
        questions_path = base / "mini_dev_postgresql.json"
        gold_path = base / "mini_dev_postgresql_gold.sql"
        source_files = {
            "questions": "datasets/minidev/MINIDEV/mini_dev_postgresql.json",
            "gold": "datasets/minidev/MINIDEV/mini_dev_postgresql_gold.sql",
            "db_profile": "full",
        }
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    gold_lines = [ln.strip() for ln in gold_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    gold_sql: list[str] = []
    for line in gold_lines:
        if "\t" in line:
            sql, _ = line.split("\t", 1)
            gold_sql.append(sql.strip())
        else:
            gold_sql.append(line)
    if len(questions) != len(gold_sql):
        raise RuntimeError(f"questions ({len(questions)}) != gold lines ({len(gold_sql)})")
    return questions, gold_sql, source_files


def _pick_stratified(questions: list[dict], n: int) -> list[int]:
    """Deterministic spread across difficulty buckets."""
    by_diff: dict[str, list[int]] = {}
    for row in questions:
        qid = int(row["question_id"])
        diff = str(row.get("difficulty") or "unknown")
        by_diff.setdefault(diff, []).append(qid)
    for diff in by_diff:
        by_diff[diff].sort()

    picked: list[int] = []
    diffs = sorted(by_diff.keys())
    idx = 0
    while len(picked) < n:
        progressed = False
        for diff in diffs:
            pool = by_diff[diff]
            if idx < len(pool):
                qid = pool[idx]
                if qid not in picked:
                    picked.append(qid)
                    progressed = True
            if len(picked) >= n:
                break
        if not progressed:
            break
        idx += 1
    return picked[:n]


def _build_big_100(questions: list[dict]) -> list[int]:
    """Deterministic stratified sample: spread across difficulties and db_id."""
    by_diff: dict[str, list[int]] = {}
    for row in questions:
        qid = int(row["question_id"])
        diff = str(row.get("difficulty") or "unknown")
        by_diff.setdefault(diff, []).append(qid)
    for diff in by_diff:
        by_diff[diff].sort()

    picked: list[int] = []
    diffs = sorted(by_diff.keys())
    idx = 0
    while len(picked) < 100:
        for diff in diffs:
            pool = by_diff[diff]
            if idx < len(pool):
                qid = pool[idx]
                if qid not in picked:
                    picked.append(qid)
            if len(picked) >= 100:
                break
        idx += 1
        if idx > max(len(v) for v in by_diff.values()):
            break
    return picked[:100]


def _question_row(row: dict) -> dict:
    return {
        "question_id": row["question_id"],
        "db_id": row["db_id"],
        "question": row["question"],
        "evidence": row.get("evidence"),
        "difficulty": row.get("difficulty"),
    }


def build_suite(
    name: str,
    question_ids: list[int],
    questions: list[dict],
    gold_sql: list[str],
    out_dir: Path,
    source_files: dict[str, str],
) -> None:
    by_id = {int(r["question_id"]): (i, r) for i, r in enumerate(questions)}
    selected_q: list[dict] = []
    selected_gold: list[dict] = []
    missing = []
    for qid in question_ids:
        if qid not in by_id:
            missing.append(qid)
            continue
        idx, row = by_id[qid]
        selected_q.append(_question_row(row))
        selected_gold.append({"question_id": qid, "SQL": gold_sql[idx]})
    if missing:
        raise RuntimeError(f"Suite {name}: missing question_ids: {missing}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(
        json.dumps(selected_q, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (out_dir / f"{name}_gold.jsonl").open("w", encoding="utf-8") as f:
        for row in selected_gold:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "name": name,
        "question_ids": question_ids,
        "source_files": source_files,
        "db_profile": source_files.get("db_profile", "full"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_dir = out_dir / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{name}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {name}: {len(selected_q)} questions")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets-root", help="Path to repo datasets/")
    parser.add_argument("--suite", help="Single suite name")
    parser.add_argument("--all", action="store_true", help="Build all suites")
    parser.add_argument(
        "--db-profile",
        choices=["1-db", "full"],
        default="full",
        help="1-db uses formula_1-only sources (for smoke_3); full uses datasets/minidev/MINIDEV",
    )
    args = parser.parse_args()

    datasets_root = _datasets_root(args.datasets_root)
    out_dir = _harness_root() / "test_suites" / "minidev"

    names = sorted(SUITE_IDS.keys())
    if args.suite:
        names = [args.suite]
    elif not args.all:
        names = ["smoke_3"]

    for name in names:
        profile = "1-db" if name == "smoke_3" else args.db_profile
        questions, gold_sql, source_files = _load_minidev(datasets_root, db_profile=profile)
        if SUITE_IDS.get(name) is not None:
            ids = SUITE_IDS[name]
        elif name == "small_10":
            ids = _pick_stratified(questions, 10)
        elif name == "medium_25":
            ids = _pick_stratified(questions, 25)
        elif name == "big_100":
            ids = _build_big_100(questions)
        elif name == "full":
            ids = [int(r["question_id"]) for r in questions]
        else:
            raise SystemExit(f"Unknown suite: {name}")
        build_suite(name, ids, questions, gold_sql, out_dir, source_files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
