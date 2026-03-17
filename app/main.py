from fastapi import FastAPI

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



# Debug endpoint removed — leaked API key prefix and internal details
