from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db import _fixtures_dir, connect


SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  biz_key TEXT NOT NULL,
  fixture_file TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS dim_store (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_code TEXT NOT NULL UNIQUE,
  store_name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS layer_paste (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  store_name TEXT NOT NULL,
  category TEXT NOT NULL,
  amount REAL NOT NULL,
  qty INTEGER NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS layer_detail (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  job_id INTEGER,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  store_name TEXT NOT NULL,
  category TEXT NOT NULL,
  amount REAL NOT NULL,
  qty INTEGER NOT NULL,
  clean_flag TEXT NOT NULL,
  name_source TEXT NOT NULL DEFAULT '原样',
  FOREIGN KEY(domain_id) REFERENCES domains(id),
  FOREIGN KEY(job_id) REFERENCES layer_jobs(id)
);

CREATE TABLE IF NOT EXISTS layer_summary (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  amount_sum REAL NOT NULL,
  qty_sum INTEGER NOT NULL,
  line_count INTEGER NOT NULL,
  UNIQUE(domain_id, biz_day, store_code),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS layer_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  step TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  in_count INTEGER NOT NULL DEFAULT 0,
  out_count INTEGER NOT NULL DEFAULT 0,
  drop_count INTEGER NOT NULL DEFAULT 0,
  backfill_count INTEGER NOT NULL DEFAULT 0,
  conflict_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS clean_rejections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL,
  domain_id INTEGER NOT NULL,
  paste_id INTEGER,
  biz_day TEXT NOT NULL DEFAULT '',
  store_code TEXT NOT NULL DEFAULT '',
  store_name_paste TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  amount REAL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(job_id) REFERENCES layer_jobs(id),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS reconcile_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  paste_count INTEGER NOT NULL,
  detail_count INTEGER NOT NULL,
  summary_line_sum INTEGER NOT NULL,
  key_mismatch INTEGER NOT NULL,
  amount_drift REAL NOT NULL,
  status TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);
"""

# 名称来源：原样 / 空名回填 / 异名覆盖
NAME_SOURCE_AS_IS = "原样"
NAME_SOURCE_BACKFILL = "空名回填"
NAME_SOURCE_CONFLICT = "异名覆盖"

REASON_UNKNOWN = "维表未命中：未知门店编码"
REASON_DISABLED = "维表未命中：门店维已停用"
REASON_NEGATIVE = "金额为负"

# 初始门店维：只登记 S01/S02；夹具中的 S03、S99 刻意不在维内，用于演示拒收
SEED_STORES = [
    ("S01", "城东店", 1),
    ("S02", "城西店", 1),
]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn: sqlite3.Connection) -> None:
    """对已存在的旧库做增量加列，不改动任何历史明细数据。"""
    existing = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "layer_detail" in existing:
        cols = _table_columns(conn, "layer_detail")
        if "job_id" not in cols:
            conn.execute("ALTER TABLE layer_detail ADD COLUMN job_id INTEGER")
        if "name_source" not in cols:
            conn.execute(
                f"ALTER TABLE layer_detail ADD COLUMN name_source TEXT NOT NULL "
                f"DEFAULT '{NAME_SOURCE_AS_IS}'"
            )
    if "layer_jobs" in existing:
        cols = _table_columns(conn, "layer_jobs")
        if "backfill_count" not in cols:
            conn.execute("ALTER TABLE layer_jobs ADD COLUMN backfill_count INTEGER NOT NULL DEFAULT 0")
        if "conflict_count" not in cols:
            conn.execute("ALTER TABLE layer_jobs ADD COLUMN conflict_count INTEGER NOT NULL DEFAULT 0")


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        row = conn.execute("SELECT COUNT(*) AS c FROM domains").fetchone()
        if int(row["c"]) == 0:
            _seed_domain(conn)
        row = conn.execute("SELECT COUNT(*) AS c FROM dim_store").fetchone()
        if int(row["c"]) == 0:
            _seed_stores(conn)
        conn.commit()
    finally:
        conn.close()


def _seed_stores(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO dim_store(store_code, store_name, enabled) VALUES (?, ?, ?)",
        SEED_STORES,
    )


def _seed_domain(conn: sqlite3.Connection) -> None:
    fixture = "门店日销售-贴源.jsonl"
    cur = conn.execute(
        """
        INSERT INTO domains(name, biz_key, fixture_file, description)
        VALUES (?, ?, ?, ?)
        """,
        (
            "门店日销售",
            "业务日+门店编码",
            fixture,
            "演示贴源装载、明细清洗与按门店日汇总",
        ),
    )
    domain_id = int(cur.lastrowid)
    path = _fixtures_dir() / fixture
    if not path.exists():
        # 仓库内相对路径兜底
        alt = Path(__file__).resolve().parents[2] / "fixtures" / fixture
        path = alt
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        conn.execute(
            """
            INSERT INTO layer_paste(
              domain_id, biz_day, store_code, store_name, category, amount, qty, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_id,
                obj.get("业务日") or "",
                obj.get("门店编码") or "",
                obj.get("门店名称") or "",
                obj.get("品类") or "",
                float(obj.get("金额") or 0),
                int(obj.get("件数") or 0),
                json.dumps(obj, ensure_ascii=False),
            ),
        )
