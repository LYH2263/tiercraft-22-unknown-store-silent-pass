from __future__ import annotations

import json

from app.db import connect, rows_to_dicts
from app.seed import (
    NAME_SOURCE_AS_IS,
    NAME_SOURCE_BACKFILL,
    NAME_SOURCE_CONFLICT,
    REASON_DISABLED,
    REASON_NEGATIVE,
    REASON_UNKNOWN,
)


STEP_LABEL = {
    "paste_to_detail": "贴源到明细",
    "detail_to_summary": "明细到汇总",
}


def list_domains() -> list[dict]:
    conn = connect()
    try:
        return rows_to_dicts(conn.execute("SELECT * FROM domains ORDER BY id").fetchall())
    finally:
        conn.close()


def get_domain(domain_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def layer_rows(table: str, domain_id: int | None = None) -> list[dict]:
    allowed = {
        "paste": "layer_paste",
        "detail": "layer_detail",
        "summary": "layer_summary",
    }
    if table not in allowed:
        raise ValueError("未知分层")
    if table == "detail":
        sql = (
            "SELECT d.id, d.domain_id, d.job_id, d.biz_day, d.store_code, "
            "COALESCE(s.store_name, d.store_name) AS store_name, "
            "d.category, d.amount, d.qty, d.clean_flag, d.name_source "
            "FROM layer_detail d LEFT JOIN dim_store s ON s.store_code = d.store_code"
        )
        args: tuple = ()
        if domain_id is not None:
            sql += " WHERE d.domain_id=?"
            args = (domain_id,)
        sql += " ORDER BY d.id"
    else:
        sql = f"SELECT * FROM {allowed[table]}"
        args = ()
        if domain_id is not None:
            sql += " WHERE domain_id=?"
            args = (domain_id,)
        sql += " ORDER BY id"
    conn = connect()
    try:
        return rows_to_dicts(conn.execute(sql, args).fetchall())
    finally:
        conn.close()


def layer_counts(domain_id: int | None = None) -> dict:
    conn = connect()
    try:
        where = " WHERE domain_id=?" if domain_id is not None else ""
        args = (domain_id,) if domain_id is not None else ()
        paste = conn.execute(f"SELECT COUNT(*) AS c FROM layer_paste{where}", args).fetchone()["c"]
        detail = conn.execute(f"SELECT COUNT(*) AS c FROM layer_detail{where}", args).fetchone()["c"]
        summary = conn.execute(f"SELECT COUNT(*) AS c FROM layer_summary{where}", args).fetchone()["c"]
        return {
            "贴源层": int(paste),
            "明细层": int(detail),
            "汇总层": int(summary),
        }
    finally:
        conn.close()


def list_jobs(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM layer_jobs ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM layer_jobs WHERE domain_id=? ORDER BY id DESC", (domain_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["step_label"] = STEP_LABEL.get(d["step"], d["step"])
            out.append(d)
        return out
    finally:
        conn.close()


def run_paste_to_detail(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        # 先登记任务头，明细与拒收都挂到该任务上，报告数字再由三张表同源派生
        cur = conn.execute(
            """
            INSERT INTO layer_jobs(domain_id, step, status, message)
            VALUES (?, 'paste_to_detail', '成功', '')
            """,
            (domain_id,),
        )
        job_id = int(cur.lastrowid)

        # 本任务全量重刷本域明细；拒收清单按任务留存，不随重刷清除
        conn.execute("DELETE FROM layer_detail WHERE domain_id=?", (domain_id,))

        # 启用维集合：编码精确命中才放行，停用/删除/未知编码一律拒收，不做店名模糊匹配
        dim_rows = conn.execute("SELECT store_code, store_name, enabled FROM dim_store").fetchall()
        enabled_dim: dict[str, str] = {
            r["store_code"]: r["store_name"] for r in dim_rows if r["enabled"] == 1
        }
        disabled_codes = {r["store_code"] for r in dim_rows if r["enabled"] != 1}

        paste = conn.execute(
            "SELECT * FROM layer_paste WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        for row in paste:
            store_code = (row["store_code"] or "").strip()
            paste_name = (row["store_name"] or "").strip()
            amount = float(row["amount"])

            reasons: list[str] = []
            if store_code in disabled_codes:
                reasons.append(REASON_DISABLED)
            if amount < 0:
                reasons.append(REASON_NEGATIVE)
            if reasons:
                # 未命中启用维：只进拒收清单，绝不写明细占位行
                conn.execute(
                    """
                    INSERT INTO clean_rejections(
                      job_id, domain_id, paste_id, biz_day, store_code, store_name_paste,
                      category, amount, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        domain_id,
                        row["id"],
                        row["biz_day"],
                        store_code,
                        paste_name,
                        row["category"],
                        amount,
                        "；".join(reasons),
                    ),
                )
                continue

            if store_code in enabled_dim:
                dim_name = enabled_dim[store_code]
                if not paste_name:
                    name_source = NAME_SOURCE_BACKFILL
                elif paste_name != dim_name:
                    name_source = NAME_SOURCE_CONFLICT
                else:
                    name_source = NAME_SOURCE_AS_IS
            else:
                dim_name = paste_name or store_code
                name_source = NAME_SOURCE_AS_IS
            conn.execute(
                """
                INSERT INTO layer_detail(
                  domain_id, job_id, biz_day, store_code, store_name, category,
                  amount, qty, clean_flag, name_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '已清洗', ?)
                """,
                (
                    domain_id,
                    job_id,
                    row["biz_day"],
                    store_code,
                    dim_name,
                    row["category"],
                    amount,
                    int(row["qty"]),
                    name_source,
                ),
            )

        # 报告计数与维表启用集合、拒收清单、明细层同源派生，
        # 不另起独立计数器：全部对本次任务落库结果做 SQL 聚合
        in_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM layer_paste WHERE domain_id=?", (domain_id,)
            ).fetchone()["c"]
        )
        out_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM layer_detail WHERE domain_id=? AND job_id=?",
                (domain_id, job_id),
            ).fetchone()["c"]
        )
        reject_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM clean_rejections WHERE domain_id=? AND job_id=?",
                (domain_id, job_id),
            ).fetchone()["c"]
        )
        backfill_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS c FROM layer_detail
                 WHERE domain_id=? AND job_id=? AND name_source=?
                """,
                (domain_id, job_id, NAME_SOURCE_BACKFILL),
            ).fetchone()["c"]
        )
        conflict_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS c FROM layer_detail
                 WHERE domain_id=? AND job_id=? AND name_source=?
                """,
                (domain_id, job_id, NAME_SOURCE_CONFLICT),
            ).fetchone()["c"]
        )
        if in_count != out_count + reject_count:
            # 同源派生的硬校验：输入必须等于写入加拒收，防止口径漂移
            raise RuntimeError("清洗计数校验失败：输入数与写入+拒收不一致")

        conn.execute(
            """
            UPDATE layer_jobs
               SET in_count=?, out_count=?, drop_count=?, backfill_count=?,
                   conflict_count=?, message=?
             WHERE id=?
            """,
            (
                in_count,
                out_count,
                reject_count,
                backfill_count,
                conflict_count,
                (
                    f"清洗完成：输入{in_count}行，写入明细{out_count}行，拒收{reject_count}行"
                    f"（维表未命中或金额为负），空名回填{backfill_count}行，异名冲突覆盖{conflict_count}行"
                ),
                job_id,
            ),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM layer_jobs WHERE id=?", (job_id,)).fetchone())
    finally:
        conn.close()


def run_detail_to_summary(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        conn.execute("DELETE FROM layer_summary WHERE domain_id=?", (domain_id,))
        detail = conn.execute(
            "SELECT * FROM layer_detail WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        buckets: dict[tuple, dict] = {}
        for row in detail:
            key = (row["biz_day"], row["store_code"])
            b = buckets.setdefault(
                key,
                {"biz_day": row["biz_day"], "store_code": row["store_code"], "amount": 0.0, "qty": 0, "n": 0},
            )
            b["amount"] += float(row["amount"])
            b["qty"] += int(row["qty"])
            b["n"] += 1
        for b in buckets.values():
            conn.execute(
                """
                INSERT INTO layer_summary(
                  domain_id, biz_day, store_code, amount_sum, qty_sum, line_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (domain_id, b["biz_day"], b["store_code"], b["amount"], b["qty"], b["n"]),
            )
        cur = conn.execute(
            """
            INSERT INTO layer_jobs(domain_id, step, status, message, in_count, out_count, drop_count)
            VALUES (?, 'detail_to_summary', '成功', ?, ?, ?, 0)
            """,
            (domain_id, "按业务日+门店编码汇总", len(detail), len(buckets)),
        )
        conn.commit()
        job_id = int(cur.lastrowid)
        return dict(conn.execute("SELECT * FROM layer_jobs WHERE id=?", (job_id,)).fetchone())
    finally:
        conn.close()


def run_reconcile(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        paste_count = int(
            conn.execute("SELECT COUNT(*) AS c FROM layer_paste WHERE domain_id=?", (domain_id,)).fetchone()[
                "c"
            ]
        )
        detail_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM layer_detail WHERE domain_id=?", (domain_id,)
            ).fetchone()["c"]
        )
        summary = conn.execute(
            "SELECT COALESCE(SUM(line_count),0) AS s, COALESCE(SUM(amount_sum),0) AS a FROM layer_summary WHERE domain_id=?",
            (domain_id,),
        ).fetchone()
        summary_line_sum = int(summary["s"])
        summary_amount = float(summary["a"])
        detail_amount = float(
            conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS a FROM layer_detail WHERE domain_id=?",
                (domain_id,),
            ).fetchone()["a"]
        )
        key_mismatch = 1 if summary_line_sum != detail_count else 0
        amount_drift = round(summary_amount - detail_amount, 4)
        status = "一致" if key_mismatch == 0 and abs(amount_drift) < 0.0001 else "存在差异"
        detail = {
            "贴源行数": paste_count,
            "明细行数": detail_count,
            "汇总行数合计": summary_line_sum,
            "明细金额合计": detail_amount,
            "汇总金额合计": summary_amount,
            "键对齐": key_mismatch == 0,
            "金额漂移": amount_drift,
        }
        cur = conn.execute(
            """
            INSERT INTO reconcile_reports(
              domain_id, paste_count, detail_count, summary_line_sum, key_mismatch, amount_drift, status, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_id,
                paste_count,
                detail_count,
                summary_line_sum,
                key_mismatch,
                amount_drift,
                status,
                json.dumps(detail, ensure_ascii=False),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reconcile_reports WHERE id=?", (int(cur.lastrowid),)).fetchone()
        d = dict(row)
        d["detail"] = json.loads(d.pop("detail_json"))
        return d
    finally:
        conn.close()


def list_reconcile(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM reconcile_reports ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reconcile_reports WHERE domain_id=? ORDER BY id DESC",
                (domain_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d.pop("detail_json"))
            out.append(d)
        return out
    finally:
        conn.close()


def dashboard() -> dict:
    domains = list_domains()
    counts = layer_counts()
    jobs = list_jobs()[:5]
    reports = list_reconcile()[:5]
    return {
        "主题域数": len(domains),
        "分层计数": counts,
        "最近任务": [
            {
                "编号": j["id"],
                "步骤": STEP_LABEL.get(j["step"], j["step"]),
                "状态": j["status"],
                "输入": j["in_count"],
                "写入": j["out_count"],
                "拒收": j["drop_count"],
                "空名回填": j["backfill_count"],
                "冲突覆盖": j["conflict_count"],
            }
            for j in jobs
        ],
        "最近对账": [
            {
                "编号": r["id"],
                "状态": r["status"],
                "明细行数": r["detail_count"],
                "汇总行数合计": r["summary_line_sum"],
            }
            for r in reports
        ],
        "主题域": [{"编号": d["id"], "名称": d["name"], "业务键": d["biz_key"]} for d in domains],
    }
