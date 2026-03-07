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
    from app.embeddings import is_enabled, embed_one, MODEL, DIMENSIONS
    from app.db import engine
    from sqlalchemy import text

    result = {
        "enabled": is_enabled(),
        "model": MODEL,
        "dimensions": DIMENSIONS,
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

    # Try a live embedding call
    if is_enabled():
        try:
            vec = await embed_one("test query")
            if vec:
                result["live_embed"] = f"ok ({len(vec)} dims)"
            else:
                result["live_embed"] = "returned None"
        except Exception as e:
            result["live_embed_error"] = str(e)
    else:
        result["live_embed"] = "skipped (not enabled)"

    # Check openai version
    try:
        import openai
        result["openai_version"] = openai.__version__
    except Exception:
        result["openai_version"] = "not installed"

    return result
