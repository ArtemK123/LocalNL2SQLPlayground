"""Regenerate 20_routine_loads.sql from 10_ods_tables.sql (no Postgres required)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "codegen"))
from generate_cdc import emit_routine_loads  # noqa: E402

ODS = ROOT / "stack" / "doris" / "10_ods_tables.sql"
OUT = ROOT / "stack" / "doris" / "20_routine_loads.sql"

SCHEMAS = [
    "california_schools",
    "card_games",
    "codebase_community",
    "debit_card_specializing",
    "european_football_2",
    "financial",
    "formula_1",
    "student_club",
    "superhero",
    "thrombosis_prediction",
    "toxicology",
]


def doris_to_pg(ctype: str) -> str:
    t = ctype.upper()
    if t == "DATE":
        return "date"
    if t == "DATETIME":
        return "timestamp without time zone"
    if t.startswith("DECIMAL"):
        return "numeric"
    if t.startswith("VARCHAR") or t == "STRING":
        return "text"
    return {
        "INT": "integer",
        "BIGINT": "bigint",
        "FLOAT": "real",
        "DOUBLE": "double precision",
        "BOOLEAN": "boolean",
    }.get(t.split("(")[0], "text")


def parse_ods(text: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    tables: list[tuple[str, str, list[tuple[str, str]]]] = []
    pattern = re.compile(
        r"CREATE TABLE IF NOT EXISTS `([^`]+)`\s*\((.*?)\)\s*DUPLICATE",
        re.S,
    )
    for m in pattern.finditer(text):
        name, body = m.group(1), m.group(2)
        if not name.startswith("ods_"):
            continue
        rest = name[4:]
        schema = None
        tbl = None
        for s in sorted(SCHEMAS, key=len, reverse=True):
            if rest.startswith(s + "_"):
                schema = s
                tbl = rest[len(s) + 1 :]
                break
        if not schema:
            print("SKIP", name)
            continue
        cols: list[tuple[str, str]] = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.startswith("`__"):
                continue
            cm = re.match(r"`([^`]+)`\s+(\w+(?:\([^)]*\))?)", line)
            if not cm:
                continue
            cols.append((cm.group(1), doris_to_pg(cm.group(2))))
        tables.append((schema, tbl, cols))
    return tables


def main() -> None:
    tables = parse_ods(ODS.read_text(encoding="utf-8"))
    sql = emit_routine_loads(tables)
    OUT.write_text(sql, encoding="utf-8")
    print(f"tables={len(tables)} bytes={len(sql)} -> {OUT}")
    for key in (
        "ods_formula_1_races_load",
        "ods_thrombosis_prediction_examination_load",
        "ods_thrombosis_prediction_patient_load",
    ):
        i = sql.find(key)
        print("---", key, "---")
        print(sql[i : i + 600])
        print()


if __name__ == "__main__":
    main()
