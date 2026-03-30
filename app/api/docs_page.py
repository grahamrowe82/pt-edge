"""API documentation page served as inline HTML at /api/docs."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["docs"])


@router.get("/api/docs", response_class=HTMLResponse)
async def api_docs():
    return HTMLResponse(content=HTML_PAGE)


HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PT-Edge API Docs</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%232563eb'/><text x='16' y='22' font-family='system-ui' font-size='18' font-weight='bold' fill='white' text-anchor='middle'>PT</text></svg>">
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  body { font-family: 'Inter', sans-serif; }
  code, pre { font-family: 'JetBrains Mono', monospace; }
  pre { white-space: pre-wrap; word-break: break-word; }
</style>
<script defer src="https://a.phasetransitions.ai/pte.js" data-website-id="ccfc649f-a332-4b1b-8426-9144af570655"></script>
</head>
<body class="bg-white text-gray-900">

<!-- Site nav (shared with directory) -->
<nav class="border-b border-gray-200 bg-white sticky top-0 z-50">
  <div class="max-w-4xl mx-auto px-6 py-3 flex items-center justify-between">
    <a href="/" class="text-lg font-bold text-gray-900 hover:text-blue-600 transition-colors">
      PT-Edge <span class="font-normal text-gray-500">API</span>
    </a>
    <div class="flex items-center gap-6 text-sm font-medium text-gray-600">
      <a href="/" class="hover:text-gray-900">MCP Directory</a>
      <a href="/agents/" class="hover:text-gray-900">Agents</a>
      <a href="/rag/" class="hover:text-gray-900">RAG</a>
      <a href="/about/" class="hover:text-gray-900">About</a>
    </div>
  </div>
</nav>

<!-- Header -->
<header class="bg-white">
  <div class="max-w-4xl mx-auto px-6 py-8">
    <h1 class="text-3xl font-bold tracking-tight">PT-Edge API</h1>
    <p class="mt-2 text-lg text-gray-600">AI Project Intelligence API</p>
    <p class="mt-1 text-sm text-gray-500">Track 220,000+ AI repos across GitHub, PyPI, npm, Docker Hub, HuggingFace &amp; Hacker News.</p>
  </div>
</header>

<main class="max-w-4xl mx-auto px-6 py-10 space-y-16">

<!-- Quick Start -->
<section id="quick-start">
  <h2 class="text-2xl font-semibold mb-4">Quick Start</h2>
  <ol class="list-decimal list-inside space-y-3 text-gray-700">
    <li><strong>Get a key</strong> &mdash; Email <a href="mailto:graham@phasetransitions.ai" class="text-blue-600 underline">graham@phasetransitions.ai</a> for a trial API key.</li>
    <li><strong>Make a request:</strong></li>
  </ol>
  <pre class="mt-3 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY_HERE" \\
  https://pt-edge.onrender.com/api/v1/projects/langchain</pre>
  <p class="mt-3 text-gray-700">You'll get back:</p>
  <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": {
    "slug": "langchain",
    "name": "LangChain",
    "category": "agents",
    "description": "Building applications with LLMs through composability",
    "github": "langchain-ai/langchain",
    "github_metrics": {
      "stars": 102400,
      "forks": 16200,
      "commits_30d": 187,
      "contributors": 3200
    },
    "downloads": { "weekly": 4850000, "monthly": 19200000 },
    "tier": 1,
    "lifecycle_stage": "mature",
    "momentum": { "stars_7d_delta": 820, "dl_30d_delta": 0.12 }
  },
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00" }
}</pre>
</section>

<!-- Authentication -->
<section id="authentication">
  <h2 class="text-2xl font-semibold mb-4">Authentication</h2>
  <p class="text-gray-700">All requests require a Bearer token in the <code class="bg-gray-100 px-1.5 py-0.5 rounded text-sm">Authorization</code> header.</p>
  <pre class="mt-3 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm">Authorization: Bearer pte_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</pre>
  <p class="mt-3 text-gray-700">Keys use the <code class="bg-gray-100 px-1.5 py-0.5 rounded text-sm">pte_</code> prefix and are 36 characters total.</p>

  <h3 class="text-lg font-medium mt-6 mb-3">Rate Limits</h3>
  <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
    <thead class="bg-gray-50">
      <tr>
        <th class="text-left px-4 py-2 font-medium">Tier</th>
        <th class="text-left px-4 py-2 font-medium">Daily Limit</th>
        <th class="text-left px-4 py-2 font-medium">Resets</th>
      </tr>
    </thead>
    <tbody>
      <tr class="border-t border-gray-200">
        <td class="px-4 py-2">Free</td>
        <td class="px-4 py-2">100 requests/day</td>
        <td class="px-4 py-2">Midnight UTC</td>
      </tr>
      <tr class="border-t border-gray-200">
        <td class="px-4 py-2">Pro</td>
        <td class="px-4 py-2">10,000 requests/day</td>
        <td class="px-4 py-2">Midnight UTC</td>
      </tr>
    </tbody>
  </table>

  <h3 class="text-lg font-medium mt-6 mb-3">Error Responses</h3>
  <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto"><span class="text-gray-500">// 401 Unauthorized</span>
{ "detail": { "error": { "code": "unauthorized", "message": "Missing Authorization: Bearer &lt;key&gt; header" } } }

<span class="text-gray-500">// 429 Rate Limit Exceeded</span>
{ "detail": { "error": { "code": "rate_limit_exceeded", "message": "Daily limit of 100 requests exceeded. Resets at midnight UTC." } } }</pre>
</section>

<!-- Response Format -->
<section id="response-format">
  <h2 class="text-2xl font-semibold mb-4">Response Format</h2>
  <p class="text-gray-700">Every successful response returns a JSON envelope:</p>
  <pre class="mt-3 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": { ... },
  "meta": {
    "timestamp": "2026-03-17T10:30:00+00:00",
    "count": 20,
    "query": { "category": "agents", "limit": 20 }
  }
}</pre>
  <ul class="mt-3 text-sm text-gray-600 space-y-1">
    <li><code class="bg-gray-100 px-1.5 py-0.5 rounded">data</code> &mdash; the requested resource (object or array)</li>
    <li><code class="bg-gray-100 px-1.5 py-0.5 rounded">meta.timestamp</code> &mdash; UTC ISO 8601 response time</li>
    <li><code class="bg-gray-100 px-1.5 py-0.5 rounded">meta.count</code> &mdash; number of items (present for list endpoints)</li>
    <li><code class="bg-gray-100 px-1.5 py-0.5 rounded">meta.query</code> &mdash; echo of query parameters used</li>
  </ul>
</section>

<!-- Endpoints -->
<section id="endpoints">
  <h2 class="text-2xl font-semibold mb-6">Endpoints</h2>

  <!-- 1. GET /api/v1/projects/{slug} -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/projects/{slug}</code>
    </div>
    <p class="text-gray-600 mb-3">Full project detail including GitHub metrics, downloads, tier, lifecycle stage, momentum, hype ratio, and recent releases.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>slug</code></td><td class="px-4 py-2">path</td><td class="px-4 py-2">Project slug (e.g. <code>langchain</code>)</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  https://pt-edge.onrender.com/api/v1/projects/vllm</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": {
    "slug": "vllm",
    "name": "vLLM",
    "category": "inference",
    "description": "High-throughput and memory-efficient inference engine for LLMs",
    "url": "https://vllm.ai",
    "lab": "vLLM",
    "github": "vllm-project/vllm",
    "pypi_package": "vllm",
    "npm_package": null,
    "is_active": true,
    "github_metrics": {
      "stars": 48500,
      "forks": 7200,
      "open_issues": 3100,
      "watchers": 320,
      "commits_30d": 245,
      "contributors": 890,
      "last_commit_at": "2026-03-16T22:15:00",
      "license": "Apache-2.0",
      "snapshot_date": "2026-03-17"
    },
    "downloads": {
      "source": "pypi",
      "daily": 95000,
      "weekly": 620000,
      "monthly": 2500000,
      "snapshot_date": "2026-03-17"
    },
    "tier": 1,
    "lifecycle_stage": "growth",
    "momentum": {
      "stars_7d_delta": 650,
      "stars_30d_delta": 2400,
      "dl_7d_delta": 0.08,
      "dl_30d_delta": 0.15
    },
    "hype": {
      "stars": 48500,
      "monthly_downloads": 2500000,
      "hype_ratio": 0.019,
      "hype_bucket": "balanced"
    },
    "recent_releases": [
      { "version": "0.8.0", "title": "vLLM v0.8.0", "released_at": "2026-03-10T14:00:00" }
    ]
  },
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00" }
}</pre>
  </div>

  <!-- 2. GET /api/v1/projects/bulk -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/projects/bulk?slugs=</code>
    </div>
    <p class="text-gray-600 mb-3">Batch lookup for up to 20 projects in a single request. Returns the same detail as the single-project endpoint.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>slugs</code></td><td class="px-4 py-2">query, required</td><td class="px-4 py-2">Comma-separated slugs, max 20</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  "https://pt-edge.onrender.com/api/v1/projects/bulk?slugs=langchain,ollama"</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": [
    { "slug": "langchain", "name": "LangChain", "category": "agents", "stars": 102400, "..." : "..." },
    { "slug": "ollama", "name": "Ollama", "category": "inference", "stars": 130000, "..." : "..." }
  ],
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00", "count": 2, "query": { "slugs": ["langchain", "ollama"] } }
}</pre>
  </div>

  <!-- 3. GET /api/v1/projects -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/projects</code>
    </div>
    <p class="text-gray-600 mb-3">Search projects by name or category.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>q</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Search term (matches name/slug)</td></tr>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>category</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Filter by category</td></tr>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>limit</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Results per page (1-50, default 20)</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  "https://pt-edge.onrender.com/api/v1/projects?category=agents&limit=5"</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": [
    { "slug": "autogen", "name": "AutoGen", "category": "agents", "description": "Multi-agent conversation framework", "lab": "Microsoft" },
    { "slug": "crewai", "name": "CrewAI", "category": "agents", "description": "Framework for orchestrating AI agents", "lab": null }
  ],
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00", "count": 2, "query": { "q": null, "category": "agents", "limit": 5 } }
}</pre>
  </div>

  <!-- 4. GET /api/v1/trending -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/trending</code>
    </div>
    <p class="text-gray-600 mb-3">Star velocity leaderboard &mdash; projects gaining the most GitHub stars in the selected window.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>category</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Filter by category</td></tr>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>window</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2"><code>7d</code> or <code>30d</code> (default <code>7d</code>)</td></tr>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>limit</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Results per page (1-50, default 20)</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  "https://pt-edge.onrender.com/api/v1/trending?window=7d&limit=3"</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": [
    { "slug": "ollama", "name": "Ollama", "category": "inference", "stars": 130000, "stars_7d_delta": 2100, "hype_bucket": "balanced", "lifecycle_stage": "growth" },
    { "slug": "openwebui", "name": "Open WebUI", "category": "ux", "stars": 78000, "stars_7d_delta": 1850, "hype_bucket": "overhyped", "lifecycle_stage": "growth" }
  ],
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00", "count": 2, "query": { "category": null, "window": "7d", "limit": 3 } }
}</pre>
  </div>

  <!-- 5. GET /api/v1/whats-new -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/whats-new</code>
    </div>
    <p class="text-gray-600 mb-3">Combined digest: recent releases, trending projects, and top Hacker News posts about AI.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>days</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Lookback window in days (1-30, default 7)</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  "https://pt-edge.onrender.com/api/v1/whats-new?days=7"</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": {
    "releases": [
      { "project_name": "vLLM", "project_slug": "vllm", "version": "0.8.0", "title": "vLLM v0.8.0", "released_at": "2026-03-10T14:00:00" }
    ],
    "trending": [
      { "name": "Ollama", "category": "inference", "stars_now": 130000, "stars_7d_delta": 2100, "tier": 1 }
    ],
    "hn": [
      { "title": "Show HN: Local LLM inference just got 3x faster", "url": "https://news.ycombinator.com/item?id=12345", "points": 842, "num_comments": 312, "posted_at": "2026-03-15T08:00:00" }
    ]
  },
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00", "query": { "days": 7 } }
}</pre>
  </div>

  <!-- 6. GET /api/v1/labs/{slug} -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/labs/{slug}</code>
    </div>
    <p class="text-gray-600 mb-3">Lab detail with its projects and recent releases.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>slug</code></td><td class="px-4 py-2">path</td><td class="px-4 py-2">Lab slug (e.g. <code>meta</code>)</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  https://pt-edge.onrender.com/api/v1/labs/meta</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": {
    "slug": "meta",
    "name": "Meta AI",
    "url": "https://ai.meta.com",
    "github_org": "facebookresearch",
    "projects": [
      { "slug": "llama", "name": "LLaMA", "category": "models", "description": "Open foundation models" }
    ],
    "recent_releases": [
      { "project_name": "LLaMA", "version": "3.3", "title": "LLaMA 3.3", "released_at": "2026-02-20T12:00:00" }
    ]
  },
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00" }
}</pre>
  </div>

  <!-- 7. GET /api/v1/hn -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/hn</code>
    </div>
    <p class="text-gray-600 mb-3">AI-related Hacker News posts, sorted by points.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>q</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Search term (matches title)</td></tr>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>days</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Lookback window (1-90, default 30)</td></tr>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>limit</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Results per page (1-50, default 20)</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  "https://pt-edge.onrender.com/api/v1/hn?q=llm&days=7&limit=2"</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": [
    { "title": "LLM inference benchmarks: vLLM vs TGI vs Ollama", "url": "https://example.com/benchmarks", "points": 523, "num_comments": 187, "posted_at": "2026-03-14T16:00:00", "hn_id": 40123456 }
  ],
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00", "count": 1, "query": { "q": "llm", "days": 7, "limit": 2 } }
}</pre>
  </div>

  <!-- 8. GET /api/v1/briefings -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/briefings</code>
    </div>
    <p class="text-gray-600 mb-3">List narrative briefings, optionally filtered by domain.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>domain</code></td><td class="px-4 py-2">query, optional</td><td class="px-4 py-2">Filter by domain (e.g. <code>agents</code>, <code>inference</code>)</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  "https://pt-edge.onrender.com/api/v1/briefings?domain=agents"</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": [
    { "slug": "agent-frameworks-consolidation", "domain": "agents", "title": "Agent Frameworks Are Consolidating", "summary": "LangGraph and CrewAI are pulling away from the pack...", "verified_at": "2026-03-15T12:00:00" }
  ],
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00", "count": 1, "query": { "domain": "agents" } }
}</pre>
  </div>

  <!-- 9. GET /api/v1/briefings/{slug} -->
  <div class="mb-12">
    <div class="flex items-center gap-3 mb-2">
      <span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded">GET</span>
      <code class="text-sm font-medium">/api/v1/briefings/{slug}</code>
    </div>
    <p class="text-gray-600 mb-3">Full briefing detail with narrative, evidence, and verification timestamp.</p>
    <table class="w-full text-sm border border-gray-200 rounded-lg overflow-hidden mb-3">
      <thead class="bg-gray-50">
        <tr><th class="text-left px-4 py-2 font-medium">Param</th><th class="text-left px-4 py-2 font-medium">Type</th><th class="text-left px-4 py-2 font-medium">Description</th></tr>
      </thead>
      <tbody>
        <tr class="border-t border-gray-200"><td class="px-4 py-2"><code>slug</code></td><td class="px-4 py-2">path</td><td class="px-4 py-2">Briefing slug</td></tr>
      </tbody>
    </table>
    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">curl -H "Authorization: Bearer pte_YOUR_KEY" \\
  https://pt-edge.onrender.com/api/v1/briefings/agent-frameworks-consolidation</pre>
    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto">{
  "data": {
    "slug": "agent-frameworks-consolidation",
    "domain": "agents",
    "title": "Agent Frameworks Are Consolidating",
    "summary": "LangGraph and CrewAI are pulling away from the pack...",
    "detail": "Over the past 30 days, the agent framework category has shown clear consolidation...",
    "evidence": "LangGraph: +3,200 stars (7d), 4.2M monthly downloads. CrewAI: +1,800 stars (7d)...",
    "verified_at": "2026-03-15T12:00:00",
    "updated_at": "2026-03-15T12:00:00"
  },
  "meta": { "timestamp": "2026-03-17T10:30:00+00:00" }
}</pre>
  </div>

</section>
</main>

<!-- Footer -->
<footer class="border-t border-gray-200 mt-16">
  <div class="max-w-4xl mx-auto px-6 py-8 text-center text-sm text-gray-500">
    <p>Powered by <a href="https://phasetransitionsai.substack.com" class="text-blue-600 underline">Phase Transitions</a> &middot; 220,000+ AI tools tracked across 17 domains &middot; <a href="mailto:graham@phasetransitions.ai" class="text-blue-600 underline">graham@phasetransitions.ai</a></p>
    <p class="mt-1"><a href="/" class="text-blue-600 underline">Browse the directory</a> &middot; <a href="/methodology/" class="text-blue-600 underline">Methodology</a> &middot; <a href="/about/" class="text-blue-600 underline">About</a></p>
  </div>
</footer>

</body>
</html>
"""
