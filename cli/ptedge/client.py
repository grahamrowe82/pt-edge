"""HTTP client for the PT-Edge REST API."""

import json
import os
import sys
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "https://mcp.phasetransitions.ai/api/v1"
CONFIG_DIR = Path.home() / ".ptedge"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load_config() -> dict:
    """Load config from ~/.ptedge/config.json if it exists."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_config(config: dict) -> None:
    """Save config to ~/.ptedge/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_api_key() -> str | None:
    """Get API key from env var, config file, or None for anonymous."""
    key = os.environ.get("PTEDGE_API_KEY")
    if key:
        return key
    config = _load_config()
    return config.get("api_key")


def get_base_url() -> str:
    """Get base URL from env var, config, or default."""
    url = os.environ.get("PTEDGE_BASE_URL")
    if url:
        return url.rstrip("/")
    config = _load_config()
    return config.get("base_url", DEFAULT_BASE_URL).rstrip("/")


class PTEdgeClient:
    """Thin HTTP client wrapping the PT-Edge REST API."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = base_url or get_base_url()
        self.api_key = api_key or get_api_key()
        self._headers = {}
        if self.api_key:
            self._headers["Authorization"] = f"Bearer {self.api_key}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{self.base_url}{path}", params=params, headers=self._headers)
            return self._handle(resp)

    def _post(self, path: str, json_body: dict) -> dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{self.base_url}{path}", json=json_body, headers=self._headers)
            return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> dict:
        if resp.status_code == 429:
            msg = self._extract_error(resp, "Rate limit exceeded")
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        if resp.status_code == 401:
            print("Error: Unauthorized. Run 'ptedge login' or set PTEDGE_API_KEY.", file=sys.stderr)
            sys.exit(1)
        if resp.status_code >= 400:
            msg = self._extract_error(resp, resp.text[:200])
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        return resp.json()

    @staticmethod
    def _extract_error(resp: httpx.Response, fallback: str) -> str:
        try:
            data = resp.json()
            detail = data.get("detail", {})
            if isinstance(detail, dict):
                err = detail.get("error", {})
                if isinstance(err, dict):
                    return err.get("message", fallback)
                return str(err) if err else fallback
            return str(detail) if detail else fallback
        except Exception:
            return fallback

    def status(self) -> dict:
        return self._get("/status")

    def list_tables(self) -> dict:
        return self._get("/tables")

    def describe_table(self, name: str) -> dict:
        return self._get(f"/tables/{name}")

    def search_tables(self, keyword: str) -> dict:
        return self._get("/tables/search", params={"q": keyword})

    def query(self, sql: str) -> dict:
        return self._post("/query", {"sql": sql})

    def workflows(self) -> dict:
        return self._get("/workflows")

    def search(self, q: str, domain: str = "", limit: int = 5) -> dict:
        params = {"q": q, "limit": limit}
        if domain:
            params["domain"] = domain
        return self._get("/search", params=params)

    def feedback(self, topic: str, text: str, category: str = "observation") -> dict:
        return self._post("/feedback", {"topic": topic, "text": text, "category": category})
