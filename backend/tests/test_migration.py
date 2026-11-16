from __future__ import annotations

import sqlite3
from pathlib import Path


def test_legacy_db_migrates_without_touching_history(monkeypatch, tmp_path):
    """旧版本库（无门店维/拒收表、明细与任务缺新列）启动后应平滑迁移，历史行原样保留。"""
    from app import db as db_mod
    from app import seed as seed_mod

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv(
        "FIXTURES_DIR", str(Path(__file__).resolve().parents[2] / "fixtures")
    )

    # 手工建一份旧结构库
    legacy = sqlite3.connect(data_dir / "app.db")
    legacy.executescript(
        """
        CREATE TABLE domains (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
          biz_key TEXT NOT NULL, fixture_file TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE layer_paste (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL,
          biz_day TEXT NOT NULL, store_code TEXT NOT NULL, store_name TEXT NOT NULL,
          category TEXT NOT NULL, amount REAL NOT NULL, qty INTEGER NOT NULL, raw_json TEXT NOT NULL
        );
        CREATE TABLE layer_detail (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL,
          biz_day TEXT NOT NULL, store_code TEXT NOT NULL, store_name TEXT NOT NULL,
          category TEXT NOT NULL, amount REAL NOT NULL, qty INTEGER NOT NULL, clean_flag TEXT NOT NULL
        );
        CREATE TABLE layer_summary (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL,
          biz_day TEXT NOT NULL, store_code TEXT NOT NULL, amount_sum REAL NOT NULL,
          qty_sum INTEGER NOT NULL, line_count INTEGER NOT NULL
        );
        CREATE TABLE layer_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL, step TEXT NOT NULL,
          status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', in_count INTEGER NOT NULL DEFAULT 0,
          out_count INTEGER NOT NULL DEFAULT 0, drop_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE reconcile_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL,
          paste_count INTEGER NOT NULL, detail_count INTEGER NOT NULL,
          summary_line_sum INTEGER NOT NULL, key_mismatch INTEGER NOT NULL,
          amount_drift REAL NOT NULL, status TEXT NOT NULL, detail_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO domains(name, biz_key, fixture_file, description)
          VALUES ('旧主题域', '业务日+门店编码', 'x.jsonl', '迁移前已存在');
        INSERT INTO layer_detail(domain_id, biz_day, store_code, store_name, category, amount, qty, clean_flag)
          VALUES (1, '2026-10-01', 'S01', '旧库历史店名', '饮料', 12.5, 1, '已清洗');
        INSERT INTO layer_jobs(domain_id, step, status, message, in_count, out_count, drop_count)
          VALUES (1, 'paste_to_detail', '成功', '旧任务', 1, 1, 0);
        """
    )
    legacy.commit()
    legacy.close()

    # 路径在 connect() 内按环境变量动态解析，无需重载模块即可指向临时库
    seed_mod.init_db()

    conn = db_mod.connect()
    try:
        # 新表存在
        names = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"dim_store", "clean_rejections"} <= names

        # 新列存在且默认值合理
        detail_cols = {r["name"] for r in conn.execute("PRAGMA table_info(layer_detail)").fetchall()}
        job_cols = {r["name"] for r in conn.execute("PRAGMA table_info(layer_jobs)").fetchall()}
        assert {"job_id", "name_source"} <= detail_cols
        assert {"backfill_count", "conflict_count"} <= job_cols

        # 历史明细未被迁移动作改写
        hist = conn.execute("SELECT store_name, name_source FROM layer_detail").fetchall()
        assert len(hist) == 1
        assert hist[0]["store_name"] == "旧库历史店名"
        assert hist[0]["name_source"] == "原样"

        # 旧任务行新计数列默认 0
        old_job = conn.execute("SELECT * FROM layer_jobs WHERE id=1").fetchone()
        assert old_job["backfill_count"] == 0 and old_job["conflict_count"] == 0

        # 初始门店维已播种
        codes = {r["store_code"] for r in conn.execute("SELECT store_code FROM dim_store").fetchall()}
        assert codes == {"S01", "S02"}
    finally:
        conn.close()
