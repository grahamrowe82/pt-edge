import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.middleware.access_log import AccessLogMiddleware
from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.mcp.server import mount_mcp
from domains.cyber.app.api.routes import router as api_router, APIUsageMiddleware
from domains.cyber.app.api.keys import router as keys_router

app = FastAPI(title="cyber-edge", version="0.1.0")

# Access logging (shared middleware, cyber DB)
AccessLogMiddleware.ensure_table(engine)
app.add_middleware(AccessLogMiddleware, session_factory=SessionLocal)

mount_mcp(app)
app.include_router(api_router)
app.include_router(keys_router)
app.add_middleware(APIUsageMiddleware)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# Mount static directory site (generated at build time)
_site_dir = os.path.join(os.path.dirname(__file__), "..", "site")
if os.path.isdir(_site_dir):
    app.mount("/", StaticFiles(directory=_site_dir, html=True), name="directory")
