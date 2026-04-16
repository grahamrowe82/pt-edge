"""Tests for canonical host redirect middleware."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.middleware.canonical_host import CanonicalHostMiddleware

CANONICAL = "mcp.phasetransitions.ai"


def _make_app(canonical_host: str = CANONICAL) -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/servers/{owner}/{repo}/")
    async def server_detail(owner: str, repo: str):
        return {"owner": owner, "repo": repo}

    app.add_middleware(CanonicalHostMiddleware, canonical_host=canonical_host)
    return app


class TestCanonicalHostRedirect:

    def test_canonical_host_passes_through(self):
        client = TestClient(_make_app())
        resp = client.get("/healthz", headers={"host": CANONICAL}, follow_redirects=False)
        assert resp.status_code == 200

    def test_root_domain_redirects(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/servers/foo/bar/",
            headers={"host": "phasetransitions.ai"},
            follow_redirects=False,
        )
        assert resp.status_code == 301
        assert resp.headers["location"] == f"https://{CANONICAL}/servers/foo/bar/"

    def test_www_redirects(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/servers/foo/bar/",
            headers={"host": "www.phasetransitions.ai"},
            follow_redirects=False,
        )
        assert resp.status_code == 301
        assert resp.headers["location"].startswith(f"https://{CANONICAL}/")

    def test_onrender_redirects(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/servers/foo/bar/",
            headers={"host": "pt-edge.onrender.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 301

    def test_healthz_never_redirects(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/healthz",
            headers={"host": "phasetransitions.ai"},
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_preserves_query_string(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/servers/foo/bar/?sort=stars&limit=10",
            headers={"host": "phasetransitions.ai"},
            follow_redirects=False,
        )
        assert resp.status_code == 301
        assert resp.headers["location"] == f"https://{CANONICAL}/servers/foo/bar/?sort=stars&limit=10"

    def test_x_forwarded_host_takes_precedence(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/servers/foo/bar/",
            headers={
                "host": "phasetransitions.ai",
                "x-forwarded-host": CANONICAL,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_disabled_when_empty(self):
        client = TestClient(_make_app(canonical_host=""))
        resp = client.get(
            "/servers/foo/bar/",
            headers={"host": "phasetransitions.ai"},
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_case_insensitive_host_match(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/servers/foo/bar/",
            headers={"host": "MCP.PhaseTransitions.AI"},
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_redirect_uses_canonical_casing(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/servers/foo/bar/",
            headers={"host": "PHASETRANSITIONS.AI"},
            follow_redirects=False,
        )
        assert resp.status_code == 301
        # Target uses the canonical casing from env, not the incoming host
        assert CANONICAL in resp.headers["location"]

    def test_missing_host_passes_through(self):
        """Missing/empty host should not 500 — let the app handle it."""
        app = FastAPI()

        @app.get("/")
        async def root():
            return {"ok": True}

        app.add_middleware(CanonicalHostMiddleware, canonical_host=CANONICAL)
        client = TestClient(app)
        # TestClient always sends a Host header, but we can set it empty
        resp = client.get("/", headers={"host": ""}, follow_redirects=False)
        # Should pass through (not redirect, not 500)
        assert resp.status_code != 500

    def test_host_with_port_stripped(self):
        client = TestClient(_make_app())
        resp = client.get(
            "/servers/foo/bar/",
            headers={"host": f"{CANONICAL}:443"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
