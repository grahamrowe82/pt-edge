"""Adaptive GitHub Search API engine.

Recursively sub-shards queries that exceed the 1,000-result limit.

Dimensions (applied in order when a shard overflows):
  1. Star ranges
  2. Language
  3. Created-date ranges
"""
import asyncio
import logging

from app.github_client import GitHubRateLimitError, get_github_client

logger = logging.getLogger(__name__)

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


# ── Budget guard ─────────────────────────────────────────────────────────

class BudgetExhausted(Exception):
    """Raised when the API call budget is exceeded."""
    pass


class CallCounter:
    """Tracks API calls and raises BudgetExhausted when budget exceeded."""

    def __init__(self, budget: int = 3000):
        self.count = 0
        self.budget = budget

    def increment(self):
        self.count += 1
        if self.count > self.budget:
            raise BudgetExhausted(
                f"API call budget exhausted: {self.count}/{self.budget}"
            )


# ── Probe ─────────────────────────────────────────────────────────────────

async def _probe_count(
    query: str,
    semaphore: asyncio.Semaphore,
    counter: CallCounter | None = None,
) -> int:
    """Check total_count for a query (1 API call, per_page=1)."""
    gh = get_github_client()
    for attempt in range(3):  # initial + 2 retries
        async with semaphore:
            if counter:
                counter.increment()
            try:
                resp = await gh.get(
                    "/search/repositories",
                    caller="ingest.github_search",
                    params={"q": query, "per_page": 1},
                )
            except GitHubRateLimitError:
                return 0
            except Exception as exc:
                logger.warning(f"Probe failed for {query!r}: {exc}")
                return 0

        if resp.status_code == 403:
            if attempt < 2:
                retry_after = int(resp.headers.get("Retry-After", "60"))
                logger.warning(f"Rate-limited during probe (attempt {attempt+1}): {query!r}, retrying in {retry_after}s")
                await asyncio.sleep(retry_after)
                continue
            else:
                logger.warning(f"Rate-limited during probe, all retries exhausted: {query!r}")
                return 0

        if resp.status_code != 200:
            logger.warning(f"Probe {resp.status_code} for {query!r}")
            return 0
        return resp.json().get("total_count", 0)

    return 0


# ── Paginate one leaf shard ───────────────────────────────────────────────

async def _paginate(
    query: str,
    semaphore: asyncio.Semaphore,
    seen: set[str],
    counter: CallCounter | None = None,
) -> list[dict]:
    """Fetch up to 1,000 results for a query that fits within the limit."""
    gh = get_github_client()
    repos: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        async with semaphore:
            if counter:
                counter.increment()
            try:
                resp = await gh.get(
                    "/search/repositories",
                    caller="ingest.github_search",
                    params={
                        "q": query,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": PER_PAGE,
                        "page": page,
                    },
                )
            except (GitHubRateLimitError, Exception) as exc:
                logger.warning(f"Page error {query!r} p{page}: {exc}")
                break

        if resp.status_code == 403:
            # Retry up to 2 times on rate limit
            retried = False
            for attempt in range(2):
                retry_after = int(resp.headers.get("Retry-After", "60"))
                logger.warning(f"Rate-limited {query!r} p{page} (attempt {attempt+1}), retrying in {retry_after}s")
                await asyncio.sleep(retry_after)
                async with semaphore:
                    if counter:
                        counter.increment()
                    try:
                        resp = await gh.get(
                            "/search/repositories",
                            caller="ingest.github_search",
                            params={
                                "q": query,
                                "sort": "stars",
                                "order": "desc",
                                "per_page": PER_PAGE,
                                "page": page,
                            },
                        )
                    except Exception as exc:
                        logger.warning(f"Page retry error {query!r} p{page}: {exc}")
                        break
                if resp.status_code != 403:
                    retried = True
                    break
            if not retried and resp.status_code == 403:
                logger.warning(f"Rate-limited {query!r} p{page}, all retries exhausted")
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
                "created_at": item.get("created_at"),
                "archived": item.get("archived", False),
            })

        if len(items) < PER_PAGE:
            break
        await asyncio.sleep(0.5)

    return repos


# ── Recursive adaptive search ────────────────────────────────────────────

async def adaptive_search(
    base_query: str,
    semaphore: asyncio.Semaphore,
    seen: set[str],
    depth: int = 0,
    pushed_after: str | None = None,
    counter: CallCounter | None = None,
) -> list[dict]:
    """Search GitHub, recursively sub-sharding if results exceed 1,000.

    Args:
        base_query: the GitHub Search query string (e.g. "topic:llm stars:>=5")
        semaphore: rate-limit semaphore
        seen: global dedup set (lowercase full_name)
        depth: current dimension depth (0=stars, 1=language, 2=created)
        pushed_after: if set, append pushed:>=YYYY-MM-DD filter at depth 0
        counter: optional API call budget counter

    Returns list of repo dicts.
    """
    # Apply pushed_after filter at depth 0 (before any sub-sharding)
    if depth == 0 and pushed_after:
        base_query = f"{base_query} pushed:>={pushed_after}"

    count = await _probe_count(base_query, semaphore, counter)
    # Only sleep after probes that returned results (zero-result probes are cheap)
    if count > 0:
        await asyncio.sleep(0.3)

    if count == 0:
        return []

    if count <= OVERFLOW_THRESHOLD:
        # Fits — paginate directly
        repos = await _paginate(base_query, semaphore, seen, counter)
        logger.debug(f"Leaf shard [{depth}] {base_query!r}: {count} total, {len(repos)} new")
        return repos

    if depth >= len(DIMENSIONS):
        # All dimensions exhausted — accept top 1,000
        logger.warning(
            f"Shard overflow at max depth: {base_query!r} has {count} results, "
            f"capping at {OVERFLOW_THRESHOLD}"
        )
        return await _paginate(base_query, semaphore, seen, counter)

    # Split by next dimension
    dimension = DIMENSIONS[depth]
    all_repos: list[dict] = []
    for qualifier in dimension:
        sub_query = f"{base_query} {qualifier}"
        repos = await adaptive_search(
            sub_query, semaphore, seen, depth + 1,
            counter=counter,
        )
        all_repos.extend(repos)
        await asyncio.sleep(0.3)

    return all_repos
