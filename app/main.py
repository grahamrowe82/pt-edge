from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.settings import settings
from app.mcp.server import mcp

app = FastAPI(title="pt-edge", version="0.1.0")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        if request.url.path.startswith("/mcp"):
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {settings.API_TOKEN}":
                return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


app.add_middleware(BearerAuthMiddleware)
app.mount("/mcp", mcp.get_asgi_app())


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
