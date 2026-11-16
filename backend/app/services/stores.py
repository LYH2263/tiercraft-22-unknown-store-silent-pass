from __future__ import annotations

from app.db import connect, rows_to_dicts


def list_stores(enabled: int | None = None) -> list[dict]:
    conn = connect()
    try:
        sql = "SELECT * FROM dim_store"
        args: tuple = ()
        if enabled is not None:
            sql += " WHERE enabled=?"
            args = (1 if enabled else 0,)
        sql += " ORDER BY store_code"
        return rows_to_dicts(conn.execute(sql, args).fetchall())
    finally:
        conn.close()


def get_store(store_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM dim_store WHERE id=?", (store_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _validate(store_code: str, store_name: str) -> tuple[str, str]:
    code = (store_code or "").strip()
    name = (store_name or "").strip()
    if not code:
        raise ValueError("门店编码不能为空")
    if not name:
        raise ValueError("门店名称不能为空")
    return code, name


def create_store(store_code: str, store_name: str, enabled: bool = True) -> dict:
    code, name = _validate(store_code, store_name)
    conn = connect()
    try:
        exists = conn.execute(
            "SELECT id FROM dim_store WHERE store_code=?", (code,)
        ).fetchone()
        if exists:
            raise ValueError(f"门店编码 {code} 已存在")
        cur = conn.execute(
            "INSERT INTO dim_store(store_code, store_name, enabled) VALUES (?, ?, ?)",
            (code, name, 1 if enabled else 0),
        )
        conn.commit()
        return get_store(int(cur.lastrowid))  # type: ignore[return-value]
    finally:
        conn.close()


def update_store(
    store_id: int,
    store_name: str | None = None,
    enabled: bool | None = None,
    store_code: str | None = None,
) -> dict:
    """只改门店维本身；不级联触碰任何贴源/明细/汇总行。"""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM dim_store WHERE id=?", (store_id,)).fetchone()
        if not row:
            raise ValueError("门店维不存在")
        new_code = (store_code or "").strip() if store_code is not None else row["store_code"]
        new_name = (store_name or "").strip() if store_name is not None else row["store_name"]
        if not new_code:
            raise ValueError("门店编码不能为空")
        if not new_name:
            raise ValueError("门店名称不能为空")
        clash = conn.execute(
            "SELECT id FROM dim_store WHERE store_code=? AND id<>?", (new_code, store_id)
        ).fetchone()
        if clash:
            raise ValueError(f"门店编码 {new_code} 已被其他门店维占用")
        new_enabled = row["enabled"] if enabled is None else (1 if enabled else 0)
        conn.execute(
            """
            UPDATE dim_store
               SET store_code=?, store_name=?, enabled=?, updated_at=datetime('now')
             WHERE id=?
            """,
            (new_code, new_name, new_enabled, store_id),
        )
        # 只改维表本身：历史明细是清洗入库时的快照，不得级联改写或删除
        conn.commit()
        return get_store(store_id)  # type: ignore[return-value]
    finally:
        conn.close()


def delete_store(store_id: int) -> None:
    """删除只影响之后的贴源到明细清洗；历史明细行原样保留。"""
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM dim_store WHERE id=?", (store_id,)).fetchone()
        if not row:
            raise ValueError("门店维不存在")
        conn.execute("DELETE FROM dim_store WHERE id=?", (store_id,))
        conn.commit()
    finally:
        conn.close()


def list_rejections(domain_id: int | None = None, job_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        sql = "SELECT * FROM clean_rejections WHERE 1=1"
        args: list = []
        if domain_id is not None:
            sql += " AND domain_id=?"
            args.append(domain_id)
        if job_id is not None:
            sql += " AND job_id=?"
            args.append(job_id)
        sql += " ORDER BY id DESC"
        return rows_to_dicts(conn.execute(sql, tuple(args)).fetchall())
    finally:
        conn.close()
