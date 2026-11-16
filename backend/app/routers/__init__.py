from fastapi import APIRouter

from app.routers import dashboard, domains, jobs, layers, reconcile, stores

api = APIRouter(prefix="/api")
api.include_router(dashboard.router)
api.include_router(domains.router)
api.include_router(layers.router)
api.include_router(jobs.router)
api.include_router(stores.router)
api.include_router(reconcile.router)
