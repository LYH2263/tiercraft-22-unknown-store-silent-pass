from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import stores

router = APIRouter(tags=["门店维"])


class StoreBody(BaseModel):
    store_code: str = Field(..., description="门店编码")
    store_name: str = Field(..., description="门店名称")
    enabled: bool = Field(default=True, description="启用态")


class StorePatch(BaseModel):
    store_code: str | None = Field(default=None, description="门店编码")
    store_name: str | None = Field(default=None, description="门店名称")
    enabled: bool | None = Field(default=None, description="启用态")


@router.get("/stores")
def list_stores(enabled: bool | None = Query(default=None)):
    flag = None if enabled is None else int(enabled)
    return stores.list_stores(flag)


@router.post("/stores")
def create_store(body: StoreBody):
    try:
        return stores.create_store(body.store_code, body.store_name, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/stores/{store_id}")
def update_store(store_id: int, body: StorePatch):
    try:
        return stores.update_store(
            store_id,
            store_name=body.store_name,
            enabled=body.enabled,
            store_code=body.store_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/stores/{store_id}")
def delete_store(store_id: int):
    try:
        stores.delete_store(store_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"已删除": store_id}


@router.get("/rejections")
def list_rejections(
    domain_id: int | None = Query(default=None),
    job_id: int | None = Query(default=None),
):
    return stores.list_rejections(domain_id, job_id)
