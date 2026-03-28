import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.mcp.server import mount_mcp
from app.api.routes import router as api_router, APIUsageMiddleware
from app.api.docs_page import router as docs_router

app = FastAPI(title="pt-edge", version="0.1.0")

mount_mcp(app)
app.include_router(api_router)
app.include_router(docs_router)
app.add_middleware(APIUsageMiddleware)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# Mount static MCP directory site (generated at build time)
_site_dir = os.path.join(os.path.dirname(__file__), "..", "site")
if os.path.isdir(_site_dir):
    app.mount("/", StaticFiles(directory=_site_dir, html=True), name="directory")



# Debug endpoint removed — leaked API key prefix and internal details
