# Plan: Claude Connectors Directory Integration

## Context

PT-Edge is a production MCP server (35 tools, real users) now listed on awesome-mcp-servers, mcp.so, and Glama. The Claude Connectors directory is the highest-value listing — it puts PT-Edge directly in front of every Claude.ai user. Four gaps block submission: no OAuth 2.0, no tool annotations, no privacy policy, no usage examples.

## Requirements (from Anthropic submission guide)

- **OAuth 2.0** — Authorization code flow with PKCE (S256). MCP server must serve `.well-known/oauth-protected-resource` metadata
- **Tool annotations** — every tool must declare `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`
- **Privacy policy** — hosted URL on our domain
- **3+ working examples** — prompt + expected output pairs
- **GA status** — production, HTTPS, works across Claude.ai, Desktop, and Code
- **Submission** — Google Form, ~2 week review

## Phase 1: Tool Annotations (quick win)

Add `annotations` parameter to all 35 `@mcp.tool()` decorators. FastMCP 2.14.5 supports this natively via `ToolAnnotations`.

**Classification:**

| Category | Tools | Annotations |
|----------|-------|-------------|
| **Read-only** (23 tools) | `about`, `describe_schema`, `query`, `whats_new`, `project_pulse`, `lab_pulse`, `trending`, `hype_check`, `list_feedback`, `list_pitches`, `lifecycle_map`, `hype_landscape`, `sniff_projects`, `movers`, `compare`, `related`, `market_map`, `radar`, `explain`, `topic`, `scout`, `hn_pulse`, `deep_dive` | `readOnlyHint=True, openWorldHint=False` |
| **Community write** (6 tools) | `submit_feedback`, `upvote_feedback`, `amend_feedback`, `propose_article`, `upvote_pitch`, `amend_pitch` | `readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False` |
| **Editorial write** (3 tools) | `accept_candidate`, `set_tier`, `submit_lab_event` | `readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False` |

Also add annotations to legacy aliases (`submit_correction`, `upvote_correction`, `list_corrections`, `amend_correction`).

**File:** `app/mcp/server.py` — add `from mcp.types import ToolAnnotations` and update each decorator.

## Phase 2: Privacy Policy

Create a privacy policy page served by the FastAPI app at `https://mcp.phasetransitions.ai/privacy`.

**Content covers:**
- No user accounts, no PII collected
- Tool usage logged (tool name, params truncated to 200 chars, duration) for operational monitoring — no IP addresses stored in tool_usage
- User-submitted feedback (corrections, pitches) is stored and visible to other users
- All source data is from public APIs (GitHub, PyPI, npm, HuggingFace, Docker Hub, HN)
- No cookies, no tracking pixels, no third-party analytics
- Data retention: tool usage logs indefinite, user submissions indefinite
- Contact: link to GitHub issues

**Files:**
- `app/privacy.py` — new route returning HTML
- `app/main.py` — mount the route

## Phase 3: OAuth 2.0

Use **Auth0 free tier** as the authorization server. Implement resource metadata and JWT validation in PT-Edge.

### Why Auth0
- Free tier covers 25,000 MAU (more than enough)
- Handles login UI, token issuance, PKCE, refresh tokens
- We only need to validate JWTs server-side
- Battle-tested, reduces security risk vs rolling our own

### What PT-Edge needs to implement

**3.1 Resource metadata endpoint**
```
GET /.well-known/oauth-protected-resource
```
Returns JSON pointing Claude.ai to Auth0 for authorization.

**3.2 Updated auth middleware** — dual mode:
- If request has `?token=` or `Bearer` with our static token → existing flow (for Claude Desktop / Code)
- If request has `Bearer` JWT from Auth0 → validate via Auth0 JWKS endpoint
- If no auth → return 401 with `WWW-Authenticate` header pointing to resource metadata

**3.3 Auth0 configuration** (manual, outside code):
- Create Auth0 tenant + API resource
- Register Claude.ai callback URLs:
  - `https://claude.ai/api/mcp/auth_callback`
  - `https://claude.com/api/mcp/auth_callback`
- Enable PKCE, set token TTL

**3.4 New settings:**
- `AUTH0_DOMAIN` — Auth0 tenant domain
- `AUTH0_AUDIENCE` — API identifier
- `AUTH0_JWKS_URL` — derived from domain

**Files:**
- `app/mcp/server.py` — update `TokenAuthMiddleware`, add `.well-known` route
- `app/settings.py` — add Auth0 config
- `requirements.txt` — add `PyJWT` and `cryptography` for JWT validation

### Auth flow (from user's perspective)
1. User clicks "Connect PT-Edge" in Claude.ai
2. Redirected to Auth0 login (can use Google/GitHub social login)
3. Consents to "PT-Edge wants to provide AI project intelligence"
4. Redirected back to Claude.ai
5. Claude.ai stores token, uses it for all MCP calls
6. PT-Edge validates JWT on each request

## Phase 4: Working Examples

Prepare 3 examples for the submission form (README and submission):

1. **Discovery** — "What's trending in AI infrastructure this week?" → `trending` + `whats_new`
2. **Deep dive** — "Give me a full analysis of vLLM" → `project_pulse` + `hype_check`
3. **Comparison** — "Compare LangChain vs LlamaIndex vs Haystack" → `compare` + `related`

**File:** `README.md` — add Examples section

## Phase 5: Submit

Google Form submission:
- Server name, description, repo URL
- MCP endpoint URL
- OAuth configuration details
- Privacy policy URL
- 3 working examples
- Category: Developer Tools

## Files Changed

| File | Change |
|------|--------|
| `app/mcp/server.py` | Tool annotations on all 35 tools + OAuth middleware + `.well-known` endpoint |
| `app/settings.py` | Auth0 config vars |
| `app/privacy.py` | New — privacy policy HTML route |
| `app/main.py` | Mount privacy route |
| `requirements.txt` | Add `PyJWT`, `cryptography` |
| `README.md` | Add examples section |

## Verification

1. **Annotations** — MCP Inspector or tool listing shows annotations on all tools
2. **Privacy policy** — `curl https://mcp.phasetransitions.ai/privacy` returns HTML
3. **OAuth** — Test with Auth0 dev tenant: get token, call MCP endpoint with Bearer JWT
4. **Existing auth still works** — `curl https://mcp.phasetransitions.ai/mcp?token=...` still authenticates
5. **Claude.ai integration** — After Auth0 setup, test OAuth flow end-to-end

## Execution Order

Phases 1 + 2 can ship immediately (no external dependencies).
Phase 3 requires Auth0 tenant setup (manual step).
Phase 4 is copy — can be done anytime.
Phase 5 blocked until 1-4 are complete.
