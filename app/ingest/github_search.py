"""Adaptive GitHub Search API engine.

Recursively sub-shards queries that exceed the 1,000-result limit.

Dimensions (applied in order when a shard overflows):
  1. Star ranges
  2. Language
  3. Created-date ranges
"""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.github.com/search/repositories"
PER_PAGE = 100
MAX_PAGES = 10  # 100 * 10 = 1,000 per query
OVERFLOW_THRESHOLD = 1_000

# ── Shard dimensions ──────────────────────────────────────────────────────

STAR_RANGES = [
    "stars:>=1000",
    "stars:100..999",
    "stars:50..99",
    "stars:20..49",
    "stars:10..19",
    "stars:5..9",
    "stars:1..4",
    "stars:0",
]

LANGUAGES = [
    "language:Python",
    "language:TypeScript",
    "language:JavaScript",
    "language:Go",
    "language:Rust",
    "language:Java",
    'language:"Jupyter Notebook"',
    # Catch-all: everything else
    "-language:Python -language:TypeScript -language:JavaScript "
    "-language:Go -language:Rust -language:Java "
    '-language:"Jupyter Notebook"',
]

CREATED_RANGES = [
    "created:>=2025-01-01",
    "created:2024-01-01..2024-12-31",
    "created:2023-01-01..2023-12-31",
    "created:2022-01-01..2022-12-31",
    "created:2021-01-01..2021-12-31",
    "created:<=2020-12-31",
]

DIMENSIONS = [STAR_RANGES, LANGUAGES, CREATED_RANGES]


# ── Probe ─────────────────────────────────────────────────────────────────

async def _probe_count(
    client: httpx.AsyncClient,
    query: str,
    semaphore: asyncio.Semaphore,
) -> int:
    """Check total_count for a query (1 API call, per_page=1)."""
    async with semaphore:
        try:
            resp = await client.get(
                SEARCH_URL,
                params={"q": query, "per_page": 1},
            )
        except httpx.HTTPError as exc:
            logger.warning(f"Probe failed for {query!r}: {exc}")
            return 0
    if resp.status_code == 403:
        logger.warning(f"Rate-limited during probe: {query!r}")
        await asyncio.sleep(60)
        return 0
    if resp.status_code != 200:
        logger.warning(f"Probe {resp.status_code} for {query!r}")
        return 0
    return resp.json().get("total_count", 0)


# ── Paginate one leaf shard ───────────────────────────────────────────────

async def _paginate(
    client: httpx.AsyncClient,
    query: str,
    semaphore: asyncio.Semaphore,
    seen: set[str],
) -> list[dict]:
    """Fetch up to 1,000 results for a query that fits within the limit."""
    repos: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        async with semaphore:
            try:
                resp = await client.get(
                    SEARCH_URL,
                    params={
                        "q": query,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": PER_PAGE,
                        "page": page,
                    },
                )
            except httpx.HTTPError as exc:
                logger.warning(f"Page error {query!r} p{page}: {exc}")
                break

        if resp.status_code == 403:
            logger.warning(f"Rate-limited {query!r} p{page}")
            await asyncio.sleep(60)
            break
        if resp.status_code == 422:
            logger.warning(f"422 on {query!r}: {resp.text[:200]}")
            break
        if resp.status_code != 200:
            logger.warning(f"GitHub {resp.status_code} {query!r} p{page}")
            break

        items = resp.json().get("items", [])
        if not items:
            break

        for item in items:
            full_name = (item.get("full_name") or "").lower()
            if full_name in seen:
                continue
            seen.add(full_name)

            owner, repo = item.get("full_name", "/").split("/", 1)
            lic = item.get("license") or {}
            repos.append({
                "github_owner": owner,
                "github_repo": repo,
                "full_name": item.get("full_name", ""),
                "name": item.get("name", repo),
                "description": (item.get("description") or "")[:2000] or None,
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "language": item.get("language"),
                "topics": item.get("topics") or [],
                "license": lic.get("spdx_id"),
                "last_pushed_at": item.get("pushed_at"),
                "archived": item.get("archived", False),
            })

        if len(items) < PER_PAGE:
            break
        await asyncio.sleep(0.5)

    return repos


# ── Recursive adaptive search ────────────────────────────────────────────

async def adaptive_search(
    client: httpx.AsyncClient,
    base_query: str,
    semaphore: asyncio.Semaphore,
    seen: set[str],
    depth: int = 0,
) -> list[dict]:
    """Search GitHub, recursively sub-sharding if results exceed 1,000.

    Args:
        client: authenticated httpx client
        base_query: the GitHub Search query string (e.g. "topic:llm stars:>=5")
        semaphore: rate-limit semaphore
        seen: global dedup set (lowercase full_name)
        depth: current dimension depth (0=stars, 1=language, 2=created)

    Returns list of repo dicts.
    """
    count = await _probe_count(client, base_query, semaphore)
    await asyncio.sleep(0.3)

    if count == 0:
        return []

    if count <= OVERFLOW_THRESHOLD:
        # Fits — paginate directly
        repos = await _paginate(client, base_query, semaphore, seen)
        logger.debug(f"Leaf shard [{depth}] {base_query!r}: {count} total, {len(repos)} new")
        return repos

    if depth >= len(DIMENSIONS):
        # All dimensions exhausted — accept top 1,000
        logger.warning(
            f"Shard overflow at max depth: {base_query!r} has {count} results, "
            f"capping at {OVERFLOW_THRESHOLD}"
        )
        return await _paginate(client, base_query, semaphore, seen)

    # Split by next dimension
    dimension = DIMENSIONS[depth]
    all_repos: list[dict] = []
    for qualifier in dimension:
        sub_query = f"{base_query} {qualifier}"
        repos = await adaptive_search(client, sub_query, semaphore, seen, depth + 1)
        all_repos.extend(repos)
        await asyncio.sleep(0.3)

    return all_repos
