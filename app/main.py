from fastapi import FastAPI

from app.mcp.server import mount_mcp

app = FastAPI(title="pt-edge", version="0.1.0")

mount_mcp(app)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/debug/embeddings")
async def debug_embeddings():
    """Diagnostic endpoint — test embedding pipeline end-to-end."""
    from app.embeddings import is_enabled, MODEL, DIMENSIONS
    from app.settings import settings
    from app.db import engine
    from sqlalchemy import text

    key = settings.OPENAI_API_KEY or ""
    result = {
        "enabled": is_enabled(),
        "model": MODEL,
        "dimensions": DIMENSIONS,
        "key_prefix": key[:8] + "..." if len(key) > 8 else "(empty)",
        "key_length": len(key),
    }

    # Check stored embeddings
    try:
        with engine.connect() as conn:
            count = conn.execute(text(
                "SELECT COUNT(*) FROM projects WHERE embedding IS NOT NULL"
            )).scalar()
            result["stored_embeddings"] = count
    except Exception as e:
        result["stored_embeddings_error"] = str(e)

    # Try a live embedding call — raw, to capture actual errors
    if is_enabled():
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.embeddings.create(
                input=["test query"], model=MODEL, dimensions=DIMENSIONS,
            )
            vec = resp.data[0].embedding
            result["live_embed"] = f"ok ({len(vec)} dims)"
        except Exception as e:
            result["live_embed_error"] = f"{type(e).__name__}: {e}"
    else:
        result["live_embed"] = "skipped (not enabled)"

    # Check openai version
    try:
        import openai
        result["openai_version"] = openai.__version__
    except Exception:
        result["openai_version"] = "not installed"

    return result
