from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import pipeline, stores

client = TestClient(app)


def test_stores_crud_and_rejections_api(domain_id):
    # 列表 + 新增
    r = client.get("/api/stores")
    assert r.status_code == 200 and {s["store_code"] for s in r.json()} >= {"S01", "S02"}

    r = client.post("/api/stores", json={"store_code": "S08", "store_name": "城南店", "enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] == 1

    # 重复编码 400
    r = client.post("/api/stores", json={"store_code": "S08", "store_name": "重复"})
    assert r.status_code == 400

    # 空名称：服务层校验拒绝
    r = client.post("/api/stores", json={"store_code": "S09", "store_name": ""})
    assert r.status_code in (400, 422)

    sid = next(s["id"] for s in client.get("/api/stores").json() if s["store_code"] == "S08")
    r = client.put(f"/api/stores/{sid}", json={"store_name": "城南新店", "enabled": False})
    assert r.status_code == 200 and r.json()["store_name"] == "城南新店"
    assert client.get("/api/stores?enabled=true").json() and all(
        s["store_code"] != "S08" for s in client.get("/api/stores?enabled=true").json()
    )

    # 删除
    r = client.delete(f"/api/stores/{sid}")
    assert r.status_code == 200
    assert client.delete(f"/api/stores/{sid}").status_code == 404


def test_paste_to_detail_job_api_shape(domain_id):
    r = client.post("/api/jobs/paste-to-detail", json={"domain_id": domain_id})
    assert r.status_code == 200
    job = r.json()
    assert job["step_label"] == "贴源到明细"
    for key in ("in_count", "out_count", "drop_count", "backfill_count", "conflict_count"):
        assert key in job
    assert job["in_count"] == job["out_count"] + job["drop_count"]

    rj = client.get(f"/api/rejections?job_id={job['id']}")
    assert rj.status_code == 200 and len(rj.json()) == job["drop_count"]


def test_detail_api_returns_stored_snapshot_not_join(domain_id):
    client.post("/api/jobs/paste-to-detail", json={"domain_id": domain_id})
    sid = next(s["id"] for s in client.get("/api/stores").json() if s["store_code"] == "S01")
    client.put(f"/api/stores/{sid}", json={"store_name": "维表新名称"})
    detail = client.get("/api/layers/明细").json()
    s01 = [r for r in detail if r["store_code"] == "S01"]
    assert s01 and all(r["store_name"] == "城东店" for r in s01)


def test_dim_alignment_proof_readonly_api(domain_id):
    job = client.post("/api/jobs/paste-to-detail", json={"domain_id": domain_id}).json()
    r = client.get(f"/api/jobs/{job['id']}/dim-alignment-proof")
    assert r.status_code == 200
    proof = r.json()
    assert proof["job_id"] == job["id"]
    assert proof["hit_count"] == job["out_count"]
    assert proof["reject_count"] == job["drop_count"]
    assert set(proof["sample_keys"]) == {"命中", "空名回填", "冲突回填", "拒收"}
    # 只读接口：不接受写入方法
    assert client.post(
        f"/api/jobs/{job['id']}/dim-alignment-proof", json={}
    ).status_code == 405
    # 未跑清洗的任务没有证明
    assert client.get("/api/jobs/999999/dim-alignment-proof").status_code == 404


def test_jobs_list_carries_reject_reasons_and_proof(domain_id):
    job = client.post("/api/jobs/paste-to-detail", json={"domain_id": domain_id}).json()
    listed = next(j for j in client.get(f"/api/jobs?domain_id={domain_id}").json() if j["id"] == job["id"])
    reasons = {r["reason"] for r in listed["reject_reasons"]}
    assert any("未知门店编码" in r for r in reasons)
    assert listed["dim_alignment_proof"]["hit_count"] == job["out_count"]
