from __future__ import annotations

import os
import sqlite3
from pathlib import Path

HISTORY_DB_PATH = Path(os.environ.get("CHAINLIT_HISTORY_DB_PATH", "/app/.chainlit/history.db"))

_CHAINLIT_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    "id" TEXT PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" TEXT NOT NULL,
    "createdAt" TEXT
);
CREATE TABLE IF NOT EXISTS threads (
    "id" TEXT PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" TEXT,
    "userIdentifier" TEXT,
    "tags" TEXT,
    "metadata" TEXT,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS steps (
    "id" TEXT PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "parentId" TEXT,
    "streaming" INTEGER NOT NULL,
    "waitForAnswer" INTEGER,
    "isError" INTEGER,
    "metadata" TEXT,
    "tags" TEXT,
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "command" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" TEXT,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INTEGER,
    "defaultOpen" INTEGER,
    "modes" TEXT,
    "autoCollapse" INTEGER,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS elements (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INTEGER,
    "language" TEXT,
    "forId" TEXT,
    "mime" TEXT,
    "props" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS feedbacks (
    "id" TEXT PRIMARY KEY,
    "forId" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "value" INTEGER NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
"""

_STEPS_ALTER_COLUMNS = (
    ("command", "TEXT"),
    ("defaultOpen", "INTEGER"),
    ("modes", "TEXT"),
    ("autoCollapse", "INTEGER"),
    ("showInput", "TEXT"),
)


def _alter_steps_missing_columns(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='steps'"
    ).fetchone()
    if not row:
        return
    existing = {r[1] for r in conn.execute('PRAGMA table_info("steps")').fetchall()}
    for col_name, col_type in _STEPS_ALTER_COLUMNS:
        if col_name not in existing:
            conn.execute(f'ALTER TABLE steps ADD COLUMN "{col_name}" {col_type}')


def init_history_db(db_path: Path | None = None) -> Path:
    """Ensure Chainlit SQLAlchemy tables exist (SQLite). Never drops existing data."""
    path = db_path or HISTORY_DB_PATH
    if os.environ.get("CHAINLIT_RESET_HISTORY_DB", "").lower() in {"1", "true", "yes"}:
        if path.exists():
            path.unlink()

    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(_CHAINLIT_SQLITE_SCHEMA)
        _alter_steps_missing_columns(conn)
        conn.commit()
    return path
