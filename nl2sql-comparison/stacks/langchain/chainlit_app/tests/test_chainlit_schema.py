from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from db_schema import init_history_db


def _read_schema(db_path: Path) -> tuple[set[str], set[str]]:
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        step_cols = {r[1] for r in conn.execute('PRAGMA table_info("steps")').fetchall()}
        return tables, step_cols
    finally:
        conn.close()


class ChainlitSchemaInitTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_bootstrap_creates_threads_and_steps(self) -> None:
        db_path = Path(self._tmpdir) / "history.db"
        init_history_db(db_path)
        tables, step_cols = _read_schema(db_path)
        self.assertIn("threads", tables)
        self.assertIn("steps", tables)
        self.assertIn("autoCollapse", step_cols)

    def test_alter_adds_autocollapse_on_legacy_steps(self) -> None:
        db_path = Path(self._tmpdir) / "history.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE steps (
                    "id" TEXT PRIMARY KEY,
                    "name" TEXT NOT NULL,
                    "type" TEXT NOT NULL,
                    "threadId" TEXT NOT NULL,
                    "streaming" INTEGER NOT NULL,
                    "input" TEXT,
                    "output" TEXT,
                    "createdAt" TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        init_history_db(db_path)
        _, step_cols = _read_schema(db_path)
        self.assertIn("autoCollapse", step_cols)


if __name__ == "__main__":
    unittest.main()
