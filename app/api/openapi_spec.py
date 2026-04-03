"""Static OpenAPI 3.1 spec for agent discovery."""

OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "PT-Edge API",
        "version": "1.0.0",
        "description": (
            "AI project intelligence API. Quality scores, trends, and metadata "
            "for 220,000+ AI repos across GitHub, PyPI, npm, Docker Hub, "
            "HuggingFace, and Hacker News. Open by default: 100 requests/day without a key, 1,000 with a free key, 10,000 with email."
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
                    "No email: 1,000 requests/day. With email: 10,000/day."
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
        "/api/v1/quality": {
            "get": {
                "operationId": "getQualityScores",
                "summary": "Quality scores for AI projects across all 18 domains.",
                "description": (
                    "Returns quality-scored repos from any domain: mcp, agents, ml-frameworks, rag, "
                    "embeddings, llm-tools, nlp, transformers, and more. Filter by subcategory to get "
                    "all projects in a specific niche. No auth required (100/day), or use a key for higher limits."
                ),
                "parameters": [
                    {"name": "domain", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Domain slug: mcp, agents, ml-frameworks, rag, embeddings, etc."},
                    {"name": "subcategory", "in": "query", "schema": {"type": "string"}, "description": "Filter by category within the domain"},
                    {"name": "quality_tier", "in": "query", "schema": {"type": "string", "enum": ["verified", "established", "emerging", "experimental"]}},
                    {"name": "min_score", "in": "query", "schema": {"type": "integer", "minimum": 0, "maximum": 100}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": 500}},
                    {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
                ],
            }
        },
        "/api/v1/datasets/quality": {
            "get": {
                "operationId": "getDatasetQuality",
                "summary": "Public quality scores dataset — no auth required, 1-hour cache.",
                "description": "Same data as /quality but with higher default limit and HTTP caching. Ideal for bulk exports and embedding in pages.",
                "parameters": [
                    {"name": "domain", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "subcategory", "in": "query", "schema": {"type": "string"}},
                    {"name": "quality_tier", "in": "query", "schema": {"type": "string", "enum": ["verified", "established", "emerging", "experimental"]}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 500, "maximum": 2000}},
                    {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
                ],
            }
        },
        "/api/v1/mcp/scores": {
            "get": {
                "operationId": "getMcpScores",
                "summary": "MCP server quality scores (alias for /quality?domain=mcp).",
                "parameters": [
                    {"name": "quality_tier", "in": "query", "schema": {"type": "string", "enum": ["verified", "established", "emerging", "experimental"]}},
                    {"name": "subcategory", "in": "query", "schema": {"type": "string"}},
                    {"name": "min_score", "in": "query", "schema": {"type": "integer"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": 200}},
                ],
            }
        },
    },
    "security": [],
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": (
                    "Optional. All endpoints work without a key (100 requests/day). "
                    "A free key gives 1,000/day (POST /api/v1/keys). "
                    "Add your email for 10,000/day. All tiers are free."
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
        "for 220,000+ AI repos. Open by default: all endpoints work without "
        "authentication (100 requests/day). Optional API key for higher limits."
    ),
    "api": {
        "type": "openapi",
        "url": "https://pt-edge.onrender.com/api/v1/openapi.json",
    },
    "auth": {
        "type": "none",
        "instructions": (
            "No authentication required. All endpoints work anonymously at 100 requests/day. "
            "For higher limits: POST /api/v1/keys for 1,000/day (no email), "
            "or POST with {\"email\": \"...\"} for 10,000/day. All tiers free."
        ),
    },
}
