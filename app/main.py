from fastapi import FastAPI

from app.mcp.server import mount_mcp

app = FastAPI(title="pt-edge", version="0.1.0")

mount_mcp(app)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}



# Debug endpoint removed — leaked API key prefix and internal details
