"""Static OpenAPI 3.1 spec for agent discovery."""

OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "PT-Edge API",
        "version": "1.0.0",
        "description": (
            "AI project intelligence API. Quality scores, trends, and metadata "
            "for 220,000+ AI repos across GitHub, PyPI, npm, Docker Hub, "
            "HuggingFace, and Hacker News. Free tier: 100 requests/day."
        ),
    },
    "servers": [{"url": "https://pt-edge.onrender.com"}],
    "paths": {
        "/api/v1/keys": {
            "post": {
                "operationId": "createApiKey",
                "summary": "Create a free API key instantly. No email required.",
                "description": (
                    "Returns a bearer token for authenticating API requests. "
                    "All fields are optional — agents can POST with an empty body. "
                    "Free tier: 100 requests/day."
                ),
                "requestBody": {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "email": {"type": "string", "format": "email", "description": "Optional contact email"},
                                    "company": {"type": "string", "description": "Optional company or project name"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "API key created",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "data": {
                                            "type": "object",
                                            "properties": {
                                                "key": {"type": "string", "description": "Bearer token (shown once)"},
                                                "prefix": {"type": "string"},
                                                "tier": {"type": "string", "enum": ["free"]},
                                                "daily_limit": {"type": "integer", "example": 100},
                                            },
                                        }
                                    },
                                }
                            }
                        },
                    }
                },
                "security": [],
            }
        },
        "/api/v1/projects/{slug}": {
            "get": {
                "operationId": "getProject",
                "summary": "Full project detail including GitHub metrics, downloads, tier, and momentum.",
                "parameters": [{"name": "slug", "in": "path", "required": True, "schema": {"type": "string"}}],
                "security": [{"bearerAuth": []}],
            }
        },
        "/api/v1/projects": {
            "get": {
                "operationId": "searchProjects",
                "summary": "Search projects by name, category, stack layer, or domain.",
                "parameters": [
                    {"name": "q", "in": "query", "schema": {"type": "string"}},
                    {"name": "category", "in": "query", "schema": {"type": "string"}},
                    {"name": "stack_layer", "in": "query", "schema": {"type": "string", "enum": ["model", "inference", "orchestration", "data", "eval", "interface", "infra"]}},
                    {"name": "domain", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20, "maximum": 50}},
                ],
                "security": [{"bearerAuth": []}],
            }
        },
        "/api/v1/trending": {
            "get": {
                "operationId": "getTrending",
                "summary": "Star velocity leaderboard — projects gaining the most GitHub stars.",
                "parameters": [
                    {"name": "category", "in": "query", "schema": {"type": "string"}},
                    {"name": "window", "in": "query", "schema": {"type": "string", "enum": ["7d", "30d"], "default": "7d"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20, "maximum": 50}},
                ],
                "security": [{"bearerAuth": []}],
            }
        },
        "/api/v1/whats-new": {
            "get": {
                "operationId": "getWhatsNew",
                "summary": "Combined digest: recent releases, trending projects, and top HN posts.",
                "parameters": [
                    {"name": "days", "in": "query", "schema": {"type": "integer", "default": 7, "maximum": 30}},
                ],
                "security": [{"bearerAuth": []}],
            }
        },
        "/api/v1/briefings": {
            "get": {
                "operationId": "listBriefings",
                "summary": "Narrative briefings on AI topics, optionally filtered by domain.",
                "parameters": [
                    {"name": "domain", "in": "query", "schema": {"type": "string"}},
                ],
                "security": [{"bearerAuth": []}],
            }
        },
        "/api/v1/mcp/scores": {
            "get": {
                "operationId": "getMcpScores",
                "summary": "MCP server quality scores with filtering.",
                "parameters": [
                    {"name": "quality_tier", "in": "query", "schema": {"type": "string", "enum": ["verified", "established", "emerging", "experimental"]}},
                    {"name": "subcategory", "in": "query", "schema": {"type": "string"}},
                    {"name": "min_score", "in": "query", "schema": {"type": "integer"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": 200}},
                ],
                "security": [{"bearerAuth": []}],
            }
        },
    },
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": (
                    "Get a free key by POSTing to /api/v1/keys (no fields required). "
                    "Use the returned key as: Authorization: Bearer pte_..."
                ),
            }
        }
    },
}

AI_PLUGIN = {
    "schema_version": "v1",
    "name": "PT-Edge",
    "description": (
        "AI project intelligence — quality scores, trends, and metadata "
        "for 220,000+ AI repos. Agents can create their own API key instantly "
        "with no email required."
    ),
    "api": {
        "type": "openapi",
        "url": "https://pt-edge.onrender.com/api/v1/openapi.json",
    },
    "auth": {
        "type": "bearer",
        "instructions": (
            "POST https://pt-edge.onrender.com/api/v1/keys with an empty body "
            "or optional JSON {\"email\": \"...\", \"company\": \"...\"}. "
            "Returns a bearer token immediately. No email required. "
            "Free tier: 100 requests/day."
        ),
    },
}
