from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", _REPO_ROOT / "data"))


def _fixtures_dir() -> Path:
    return Path(os.environ.get("FIXTURES_DIR", _REPO_ROOT / "fixtures"))


def _db_path() -> Path:
    return _data_dir() / "app.db"


# 兼容既有引用；新代码请优先用函数，以便环境变量在运行期生效
DATA_DIR = _data_dir()
FIXTURES_DIR = _fixtures_dir()
DB_PATH = _db_path()


def connect() -> sqlite3.Connection:
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "app.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]
