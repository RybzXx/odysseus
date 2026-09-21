"""routes/mahdawi/mahdawi_routes.py

The Platforms dashboard API: gather Fedshi products, price and caption them,
stage for approval, and package for manual posting to Instagram and TikTok.

Reads and writes the MahdawiPost table (app.db) — one store, no Supabase.
Nothing here posts to a platform: a human approves, then packaging builds a
folder to post by hand. Fetch runs Playwright off the event loop via
asyncio.to_thread, and its progress is polled at /runs/{id}.
"""
import asyncio
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.database import SessionLocal
from core.middleware import require_admin
from src.auth_helpers import require_user
from services import mahdawi as svc

logger = logging.getLogger(__name__)


class FetchRequest(BaseModel):
    skus: Optional[List[str]] = None
    collection: Optional[str] = None      # "new" | "bestseller" | "collection-id=<n>"


class SkuRequest(BaseModel):
    sku: str


def setup_mahdawi_routes() -> APIRouter:
    router = APIRouter(prefix="/api/mahdawi", tags=["Mahdawi Platforms"])

    def _owner(request: Request) -> str:
        require_admin(request)
        return require_user(request) or "unknown"

    @router.get("/platforms/status")
    async def platforms_status(request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            return svc.platform_status(db, owner)
        finally:
            db.close()

    @router.get("/products")
    async def products(request: Request, status: Optional[str] = None):
        owner = _owner(request)
        db = SessionLocal()
        try:
            return {"products": svc.list_products(db, status=status, owner=owner)}
        finally:
            db.close()

    @router.post("/fetch")
    async def fetch(request: Request, body: FetchRequest):
        owner = _owner(request)
        if not body.skus and not body.collection:
            raise HTTPException(422, "provide skus or a collection")
        run_id = str(uuid.uuid4())
        svc._RUNS[run_id] = {"id": run_id, "state": "queued", "done": 0,
                             "total": 0, "staged": 0, "skipped": 0,
                             "flagged": [], "error": None}
        # Playwright is a blocking sync API — run the whole fetch off the loop.
        asyncio.get_event_loop().run_in_executor(
            None, svc.run_fetch, run_id, body.skus or [], owner, body.collection)
        return {"run_id": run_id}

    @router.get("/runs/{run_id}")
    async def run_status(request: Request, run_id: str):
        _owner(request)
        state = svc.run_state(run_id)
        if state is None:
            raise HTTPException(404, "no such run")
        return state

    @router.post("/approve")
    async def approve(request: Request, body: SkuRequest):
        owner = _owner(request)
        db = SessionLocal()
        try:
            return svc.approve(db, body.sku, owner)
        except svc.NotFound:
            raise HTTPException(404, "no staged product %s" % body.sku)
        except svc.BadState as e:
            raise HTTPException(409, str(e))
        finally:
            db.close()

    @router.post("/package")
    async def package(request: Request, body: SkuRequest):
        owner = _owner(request)
        db = SessionLocal()
        try:
            path = svc.build_package(db, body.sku, owner)
            return {"sku": body.sku, "package_dir": path}
        except svc.NotFound:
            raise HTTPException(404, "no product %s" % body.sku)
        except svc.BadState as e:
            raise HTTPException(409, str(e))
        finally:
            db.close()

    @router.post("/posted")
    async def posted(request: Request, body: SkuRequest):
        owner = _owner(request)
        db = SessionLocal()
        try:
            return svc.mark_posted(db, body.sku, owner)
        except svc.NotFound:
            raise HTTPException(404, "no product %s" % body.sku)
        finally:
            db.close()

    return router
