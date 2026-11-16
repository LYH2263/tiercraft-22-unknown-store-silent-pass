from __future__ import annotations

import pytest

from app.db import connect
from app.seed import (
    NAME_SOURCE_AS_IS,
    NAME_SOURCE_BACKFILL,
    NAME_SOURCE_CONFLICT,
)
from app.services import pipeline, stores


# ---------- 1. 维命中才准入明细，未命中进拒收清单，不写占位行 ----------

def test_unknown_code_rejected_not_written(domain_id):
    job = pipeline.run_paste_to_detail(domain_id)
    detail = pipeline.layer_rows("detail")
    rejected = stores.list_rejections(job_id=job["id"])

    # 夹具 9 行：S03、S99 不在启用维内
    assert job["in_count"] == 9
    assert job["out_count"] == 7
    assert job["drop_count"] == 2
    assert job["in_count"] == job["out_count"] + job["drop_count"]

    detail_codes = {r["store_code"] for r in detail}
    assert "S03" not in detail_codes
    assert "S99" not in detail_codes

    rejected_codes = {r["store_code"] for r in rejected}
    assert {"S03", "S99"} <= rejected_codes
    s99 = next(r for r in rejected if r["store_code"] == "S99")
    # S99 贴源店名与 S01 完全相同，仍按编码拒收，证明没有店名模糊匹配放过
    assert s99["store_name_paste"] == "城东店"
    assert "未知门店编码" in s99["reason"]


def test_negative_amount_also_rejected_with_reason(domain_id):
    job = pipeline.run_paste_to_detail(domain_id)
    s03 = next(r for r in stores.list_rejections(job_id=job["id"]) if r["store_code"] == "S03")
    assert "未知门店编码" in s03["reason"]
    assert "金额为负" in s03["reason"]


def test_no_placeholder_detail_rows(domain_id):
    pipeline.run_paste_to_detail(domain_id)
    conn = connect()
    try:
        # 明细层每个编码都必须能在启用维集合中找到，且名称与维表一致
        bad = conn.execute(
            """
            SELECT d.id FROM layer_detail d
            LEFT JOIN dim_store s
              ON s.store_code = d.store_code AND s.enabled = 1
            WHERE s.id IS NULL OR s.store_name <> d.store_name
            """
        ).fetchall()
        assert bad == []
    finally:
        conn.close()


# ---------- 2. 店名回填 / 冲突覆盖 ----------

def test_empty_paste_name_backfilled_from_dim(domain_id):
    job = pipeline.run_paste_to_detail(domain_id)
    assert job["backfill_count"] == 1
    row = next(
        r for r in pipeline.layer_rows("detail")
        if r["store_code"] == "S02" and r["amount"] == 72.0
    )
    assert row["store_name"] == "城西店"  # 贴源为空，维表回填
    assert row["name_source"] == NAME_SOURCE_BACKFILL


def test_conflicting_paste_name_overwritten_by_dim(domain_id):
    job = pipeline.run_paste_to_detail(domain_id)
    assert job["conflict_count"] == 1
    row = next(
        r for r in pipeline.layer_rows("detail")
        if r["store_code"] == "S01" and r["amount"] == 66.0
    )
    assert row["store_name"] == "城东店"      # 贴源“城东旗舰店”被覆盖
    assert row["name_source"] == NAME_SOURCE_CONFLICT


def test_single_name_per_code_in_detail(domain_id):
    pipeline.run_paste_to_detail(domain_id)
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT store_code, COUNT(DISTINCT store_name) AS n FROM layer_detail GROUP BY store_code"
        ).fetchall()
        assert rows and all(r["n"] == 1 for r in rows)
    finally:
        conn.close()


def test_matching_name_marked_as_is(domain_id):
    pipeline.run_paste_to_detail(domain_id)
    rows = [r for r in pipeline.layer_rows("detail") if r["name_source"] == NAME_SOURCE_AS_IS]
    assert rows  # 名称一致的行保持原样来源


# ---------- 3. 停用/删除只影响之后的清洗，历史明细不被级联、读时不伪装 ----------

def test_disabling_dim_keeps_history_then_rejects_next_run(domain_id):
    pipeline.run_paste_to_detail(domain_id)
    conn = connect()
    try:
        s01 = conn.execute("SELECT id FROM dim_store WHERE store_code='S01'").fetchone()["id"]
        history_before = conn.execute(
            "SELECT store_name FROM layer_detail WHERE store_code='S01'"
        ).fetchall()
    finally:
        conn.close()
    assert history_before and all(r["store_name"] == "城东店" for r in history_before)

    stores.update_store(s01, enabled=False)

    # 维变更本身不得改写或删除任何历史明细
    conn = connect()
    try:
        kept = conn.execute(
            "SELECT store_name FROM layer_detail WHERE store_code='S01'"
        ).fetchall()
        assert [dict(r) for r in kept] == [dict(r) for r in history_before]
    finally:
        conn.close()

    # 再次清洗：S01 全部拒收
    job2 = pipeline.run_paste_to_detail(domain_id)
    rejected = {r["store_code"]: r["reason"] for r in stores.list_rejections(job_id=job2["id"])}
    assert "S01" in rejected and "停用" in rejected["S01"]
    assert all(r["store_code"] != "S01" for r in pipeline.layer_rows("detail"))

    # 重新启用后恢复准入
    stores.update_store(s01, enabled=True)
    job3 = pipeline.run_paste_to_detail(domain_id)
    assert job3["out_count"] == 7
    assert all(
        r["store_name"] == "城东店"
        for r in pipeline.layer_rows("detail") if r["store_code"] == "S01"
    )


def test_deleting_dim_does_not_touch_history_before_rerun(domain_id):
    pipeline.run_paste_to_detail(domain_id)
    conn = connect()
    try:
        s02 = conn.execute("SELECT id FROM dim_store WHERE store_code='S02'").fetchone()["id"]
        snap = conn.execute(
            "SELECT COUNT(*) AS c FROM layer_detail WHERE store_code='S02'"
        ).fetchone()["c"]
    finally:
        conn.close()

    stores.delete_store(s02)

    conn = connect()
    try:
        # 删除维表行没有级联删除明细（无外键从明细指向维表）
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM layer_detail WHERE store_code='S02'"
        ).fetchone()["c"] == snap
    finally:
        conn.close()

    job = pipeline.run_paste_to_detail(domain_id)
    rejected = {r["store_code"]: r["reason"] for r in stores.list_rejections(job_id=job["id"])}
    assert "S02" in rejected and "未知门店编码" in rejected["S02"]


def test_detail_read_does_not_join_dim(domain_id):
    # 改名后不重新清洗：明细读出来仍是入库快照，证明无读时 JOIN 伪装
    pipeline.run_paste_to_detail(domain_id)
    conn = connect()
    try:
        s01 = conn.execute("SELECT id FROM dim_store WHERE store_code='S01'").fetchone()["id"]
    finally:
        conn.close()
    stores.update_store(s01, store_name="城东店（新名）")
    rows = [r for r in pipeline.layer_rows("detail") if r["store_code"] == "S01"]
    assert rows and all(r["store_name"] == "城东店" for r in rows)


# ---------- 4. 报告同源派生 ----------

def test_job_counts_derived_from_tables(domain_id):
    job = pipeline.run_paste_to_detail(domain_id)
    conn = connect()
    try:
        paste_n = conn.execute(
            "SELECT COUNT(*) AS c FROM layer_paste WHERE domain_id=?", (domain_id,)
        ).fetchone()["c"]
        detail_n = conn.execute(
            "SELECT COUNT(*) AS c FROM layer_detail WHERE job_id=?", (job["id"],)
        ).fetchone()["c"]
        reject_n = conn.execute(
            "SELECT COUNT(*) AS c FROM clean_rejections WHERE job_id=?", (job["id"],)
        ).fetchone()["c"]
        backfill_n = conn.execute(
            "SELECT COUNT(*) AS c FROM layer_detail WHERE job_id=? AND name_source=?",
            (job["id"], NAME_SOURCE_BACKFILL),
        ).fetchone()["c"]
        conflict_n = conn.execute(
            "SELECT COUNT(*) AS c FROM layer_detail WHERE job_id=? AND name_source=?",
            (job["id"], NAME_SOURCE_CONFLICT),
        ).fetchone()["c"]
    finally:
        conn.close()

    assert job["in_count"] == paste_n
    assert job["out_count"] == detail_n
    assert job["drop_count"] == reject_n
    assert job["backfill_count"] == backfill_n
    assert job["conflict_count"] == conflict_n


def test_rejections_kept_per_job_across_reruns(domain_id):
    j1 = pipeline.run_paste_to_detail(domain_id)
    conn = connect()
    try:
        s01 = conn.execute("SELECT id FROM dim_store WHERE store_code='S01'").fetchone()["id"]
    finally:
        conn.close()
    stores.update_store(s01, enabled=False)
    j2 = pipeline.run_paste_to_detail(domain_id)

    first = stores.list_rejections(job_id=j1["id"])
    second = stores.list_rejections(job_id=j2["id"])
    assert len(first) == 2 and len(second) == 6
    # 历史任务的拒收清单不被后续重刷清除
    assert len(stores.list_rejections()) == 8


# ---------- 维表维护校验 ----------

def test_dim_crud_validation():
    with pytest.raises(ValueError):
        stores.create_store("  ", "名称")
    with pytest.raises(ValueError):
        stores.create_store("S10", "  ")
    created = stores.create_store("S10", "城南店", enabled=False)
    assert created["enabled"] == 0

    with pytest.raises(ValueError):
        stores.create_store("S10", "重复编码")

    updated = stores.update_store(created["id"], store_name="城南新店", enabled=True)
    assert updated["store_name"] == "城南新店" and updated["enabled"] == 1

    stores.delete_store(created["id"])
    assert stores.get_store(created["id"]) is None
    with pytest.raises(ValueError):
        stores.delete_store(created["id"])


def test_newly_added_dim_allows_previously_rejected_code(domain_id):
    job1 = pipeline.run_paste_to_detail(domain_id)
    assert "S03" in {r["store_code"] for r in stores.list_rejections(job_id=job1["id"])}

    stores.create_store("S03", "城中店", enabled=True)
    # S03 贴源金额为负：编码已命中维表，但金额规则仍然拒收
    job2 = pipeline.run_paste_to_detail(domain_id)
    s03 = next(r for r in stores.list_rejections(job_id=job2["id"]) if r["store_code"] == "S03")
    assert "未知" not in s03["reason"]
    assert "金额为负" in s03["reason"]
    assert job2["drop_count"] == 2  # S03（负金额）+ S99（未知）


# ---------- 下游汇总仍基于明细，对账闭环 ----------

def test_summary_and_reconcile_still_balanced(domain_id):
    pipeline.run_paste_to_detail(domain_id)
    pipeline.run_detail_to_summary(domain_id)
    report = pipeline.run_reconcile(domain_id)
    assert report["status"] == "一致"
    assert report["detail"]["明细行数"] == 7
    assert report["detail"]["键对齐"] is True
