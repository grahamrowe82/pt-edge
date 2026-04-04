import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fastapi.responses import HTMLResponse, JSONResponse

from app.mcp.server import mount_mcp
from app.api.routes import router as api_router, APIUsageMiddleware
from app.middleware.access_log import AccessLogMiddleware
from app.api.docs_page import router as docs_router
from app.api.keys import router as keys_router
from app.api.signup_page import SIGNUP_HTML
from app.api.openapi_spec import OPENAPI_SPEC, AI_PLUGIN

from starlette.middleware.base import BaseHTTPMiddleware


class APIDiscoveryHeadersMiddleware(BaseHTTPMiddleware):
    """Attach API discovery headers to all HTML responses."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Link"] = (
                '<https://pt-edge.onrender.com/api/v1/openapi.json>; rel="service-desc", '
                '<https://pt-edge.onrender.com/api/v1/keys>; rel="service-key"'
            )
            response.headers["X-API-Docs"] = "https://pt-edge.onrender.com/api/docs"
            response.headers["X-API-Key-Endpoint"] = "https://pt-edge.onrender.com/api/v1/keys"
        return response


app = FastAPI(title="pt-edge", version="0.1.0")

app.add_middleware(APIDiscoveryHeadersMiddleware)
mount_mcp(app)
app.include_router(api_router)
app.include_router(docs_router)
app.include_router(keys_router)
app.add_middleware(APIUsageMiddleware)
app.add_middleware(AccessLogMiddleware)


@app.get("/api/signup", response_class=HTMLResponse)
async def api_signup():
    return HTMLResponse(content=SIGNUP_HTML)


@app.get("/api/v1/openapi.json")
async def openapi_spec():
    return JSONResponse(content=OPENAPI_SPEC, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/.well-known/ai-plugin.json")
async def ai_plugin():
    return JSONResponse(content=AI_PLUGIN, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# Mount static MCP directory site (generated at build time)
_site_dir = os.path.join(os.path.dirname(__file__), "..", "site")
if os.path.isdir(_site_dir):
    app.mount("/", StaticFiles(directory=_site_dir, html=True), name="directory")



# Debug endpoint removed — leaked API key prefix and internal details
