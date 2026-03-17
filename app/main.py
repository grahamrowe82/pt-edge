from fastapi import FastAPI

from app.mcp.server import mount_mcp
from app.api.routes import router as api_router

app = FastAPI(title="pt-edge", version="0.1.0")

mount_mcp(app)
app.include_router(api_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}



# Debug endpoint removed — leaked API key prefix and internal details
