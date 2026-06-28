from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"

# DB path can be overridden via PHAROS_DB env var so the same code can run
# on a developer laptop (./drugbank_full.db) and inside a Docker container
# that mounts the database at, say, /data/drugbank_full.db.
DB_PATH = Path(os.environ.get("PHAROS_DB", str(ROOT / "drugbank_full.db")))


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
