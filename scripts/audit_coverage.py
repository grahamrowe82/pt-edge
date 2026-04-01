"""Weekly coverage audit: discover awesome lists, extract repos, reconcile against ai_repos.

Usage:
    python scripts/audit_coverage.py                    # Full run (all lists)
    python scripts/audit_coverage.py --limit 3          # Test with 3 seed lists only
    python scripts/audit_coverage.py --skip-metadata    # Skip GitHub metadata for unmatched

Discovers AI-related awesome lists on GitHub, extracts every repo they reference,
reconciles against our ai_repos table, classifies gaps, and diagnoses why the
scanner missed them. Runs as Step 4 of the weekly structural cron (Sunday 3am UTC).

Principle: we never manually add missing repos. We diagnose why the scanner
didn't find them and fix the scanner.

Checking results after a run:

    -- Worst-covered lists first
    SELECT source_full_name, coverage_pct, matched, unmatched
    FROM coverage_snapshots ORDER BY scan_date DESC, coverage_pct ASC;

    -- Top genuine gaps (active repos we're missing)
    SELECT alr.repo_full_name, alr.github_stars, alr.github_description, als.full_name as source
    FROM awesome_list_repos alr
    JOIN awesome_list_sources als ON als.id = alr.source_id
    WHERE alr.status = 'unmatched' AND COALESCE(alr.github_stars, 0) >= 100
    ORDER BY alr.github_stars DESC LIMIT 20;
"""

import argparse
import base64
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine
from app.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GITHUB_TOKEN = settings.GITHUB_TOKEN
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
API_BASE = "https://api.github.com"

# Known seed lists (always included)
SEED_LISTS = [
    "sindresorhus/awesome",
    "josephmisiti/awesome-machine-learning",
    "keon/awesome-nlp",
    "jbhuang0604/awesome-computer-vision",
    "eugeneyan/open-llms",
    "igorbarinov/awesome-data-engineering",
    "visenger/awesome-mlops",
    "steven2358/awesome-generative-ai",
    "aimerou/awesome-ai-papers",
    "dair-ai/Prompt-Engineering-Guide",
    "hyp1231/awesome-llm-powered-agent",
    "e2b-dev/awesome-ai-agents",
    "Shubhamsaboo/awesome-llm-apps",
    "formulahendry/awesome-gpt",
]

# Topics to search for awesome list discovery
DISCOVERY_TOPICS = [
    "machine-learning", "deep-learning", "artificial-intelligence",
    "nlp", "natural-language-processing", "computer-vision",
    "llm", "large-language-models", "mcp", "rag",
    "voice", "speech", "embeddings", "vector-database",
    "transformers", "mlops", "data-engineering", "diffusion",
    "reinforcement-learning", "generative-ai",
]

# AI keywords for out-of-scope classification
AI_KEYWORDS = re.compile(
    r"(machine.?learn|deep.?learn|neural|ai|artificial.?intellig|nlp|"
    r"natural.?language|computer.?vision|llm|language.?model|transformer|"
    r"embedding|vector|rag|retrieval|diffusion|speech|voice|tts|asr|"
    r"gpt|bert|whisper|pytorch|tensorflow|keras|hugging.?face|openai|"
    r"agent|autonomous|rl|reinforcement|mlops|ml.?ops)",
    re.IGNORECASE,
)

GITHUB_REPO_RE = re.compile(
    r"github\.com/([\w.-]+)/([\w.-]+?)(?:/|\.git|#|\?|\)|\]| |$)"
)

SKIP_OWNERS = {"topics", "search", "explore", "settings", "notifications",
               "marketplace", "sponsors", "orgs", "apps"}
SKIP_REPOS = {"issues", "pulls", "wiki", "blob", "tree", "releases",
              "actions", "packages", "security"}


def _api_get(url, params=None):
    """GitHub API GET with rate limit handling."""
    for attempt in range(3):
        resp = httpx.get(url, headers=HEADERS, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            wait = max(reset - int(time.time()), 10)
            logger.warning(f"Rate limited, waiting {min(wait, 60)}s")
            time.sleep(min(wait, 60))
            continue
        if resp.status_code == 404:
            return None
        logger.warning(f"API {resp.status_code}: {url}")
        return None
    return None


def discover_awesome_lists(limit=0):
    """Find AI-related awesome lists on GitHub."""
    lists = {}

    # Seed lists
    for full_name in SEED_LISTS:
        if limit and len(lists) >= limit:
            break
        owner, repo = full_name.split("/", 1)
        data = _api_get(f"{API_BASE}/repos/{owner}/{repo}")
        if data and not data.get("archived"):
            lists[full_name.lower()] = {
                "full_name": full_name,
                "url": data["html_url"],
                "stars": data.get("stargazers_count", 0),
                "description": (data.get("description") or "")[:500],
            }
    logger.info(f"  {len(lists)} seed lists resolved")

    if limit and len(lists) >= limit:
        logger.info(f"  Limit {limit} reached, skipping topic discovery")
        return list(lists.values())[:limit]

    # Discover via topic search
    for topic in DISCOVERY_TOPICS:
        if limit and len(lists) >= limit:
            break
        query = f"awesome in:name topic:{topic} stars:>=100"
        data = _api_get(f"{API_BASE}/search/repositories",
                        {"q": query, "per_page": 30, "sort": "stars"})
        if not data or "items" not in data:
            continue
        for item in data["items"]:
            fn = item["full_name"].lower()
            if fn not in lists and not item.get("archived"):
                lists[fn] = {
                    "full_name": item["full_name"],
                    "url": item["html_url"],
                    "stars": item.get("stargazers_count", 0),
                    "description": (item.get("description") or "")[:500],
                }
        time.sleep(1)

    result = list(lists.values())
    if limit:
        result = result[:limit]
    logger.info(f"Discovered {len(result)} awesome lists")
    return result


def upsert_sources(sources):
    """Batch upsert awesome list sources."""
    if not sources:
        return
    with engine.connect() as conn:
        for s in sources:
            conn.execute(text("""
                INSERT INTO awesome_list_sources (full_name, url, stars, description)
                VALUES (:full_name, :url, :stars, :description)
                ON CONFLICT (full_name) DO UPDATE SET
                    stars = EXCLUDED.stars, description = EXCLUDED.description
            """), s)
        conn.commit()
    logger.info(f"Upserted {len(sources)} sources")


def extract_repos_from_readme(full_name):
    """Fetch README and extract GitHub repo URLs."""
    owner, repo = full_name.split("/", 1)
    data = _api_get(f"{API_BASE}/repos/{owner}/{repo}/readme")
    if not data or "content" not in data:
        return []
    try:
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return []

    seen = set()
    repos = []
    for match in GITHUB_REPO_RE.finditer(content):
        o = match.group(1).lower()
        r = match.group(2).lower().rstrip(".")
        if o in SKIP_OWNERS or r in SKIP_REPOS:
            continue
        fn = f"{o}/{r}"
        if fn not in seen:
            seen.add(fn)
            repos.append(fn)
    return repos


def extract_and_store(scan_date):
    """Extract repos from each awesome list and batch insert."""
    total = 0
    with engine.connect() as conn:
        sources = conn.execute(text(
            "SELECT id, full_name FROM awesome_list_sources ORDER BY stars DESC NULLS LAST"
        )).fetchall()

    for source in sources:
        sid = source._mapping["id"]
        fn = source._mapping["full_name"]
        repos = extract_repos_from_readme(fn)
        if not repos:
            logger.info(f"  {fn}: 0 repos")
            continue

        # Batch insert with multi-row VALUES
        with engine.connect() as conn:
            values_sql = ", ".join(
                f"({sid}, '{r.replace(chr(39), chr(39)*2)}', '{scan_date}')"
                for r in repos
            )
            conn.execute(text(f"""
                INSERT INTO awesome_list_repos (source_id, repo_full_name, scan_date)
                VALUES {values_sql}
                ON CONFLICT (source_id, repo_full_name, scan_date) DO NOTHING
            """))
            conn.execute(text("""
                UPDATE awesome_list_sources
                SET last_scanned_at = NOW(), repo_count = :count
                WHERE id = :id
            """), {"count": len(repos), "id": sid})
            conn.commit()

        total += len(repos)
        logger.info(f"  {fn}: {len(repos)} repos")

    logger.info(f"Total: {total} repo references extracted")
    return total


def reconcile(scan_date):
    """Match awesome_list_repos against ai_repos."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE awesome_list_repos alr
            SET matched_ai_repo_id = ar.id, status = 'matched'
            FROM ai_repos ar
            WHERE LOWER(alr.repo_full_name) = LOWER(ar.full_name)
              AND alr.scan_date = :scan_date
              AND alr.status = 'unmatched'
        """), {"scan_date": scan_date})
        matched = result.rowcount
        conn.commit()
    logger.info(f"Reconciled: {matched} matched")
    return matched


def classify_unmatched(scan_date, skip_metadata=False):
    """Fetch GitHub metadata for unmatched repos and classify."""
    with engine.connect() as conn:
        unmatched = conn.execute(text("""
            SELECT id, repo_full_name FROM awesome_list_repos
            WHERE scan_date = :scan_date AND status = 'unmatched'
        """), {"scan_date": scan_date}).fetchall()

    logger.info(f"{len(unmatched)} unmatched repos to classify")
    if skip_metadata or not unmatched:
        return

    batch_updates = []
    for i, row in enumerate(unmatched):
        rid = row._mapping["id"]
        fn = row._mapping["repo_full_name"]
        parts = fn.split("/", 1)
        if len(parts) != 2:
            batch_updates.append({"id": rid, "status": "out_of_scope",
                                  "stars": None, "pushed": None,
                                  "archived": None, "desc": None})
            continue

        data = _api_get(f"{API_BASE}/repos/{parts[0]}/{parts[1]}")

        if data is None:
            batch_updates.append({"id": rid, "status": "renamed",
                                  "stars": None, "pushed": None,
                                  "archived": None, "desc": None})
        else:
            stars = data.get("stargazers_count", 0)
            archived = data.get("archived", False)
            pushed = data.get("pushed_at")
            desc = (data.get("description") or "")[:500]
            topics = " ".join(data.get("topics", []))

            if archived:
                status = "archived"
            elif pushed:
                pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
                two_years_ago = datetime.now(timezone.utc).replace(
                    year=datetime.now().year - 2)
                if pushed_dt < two_years_ago:
                    status = "stale"
                elif not AI_KEYWORDS.search(f"{desc} {topics}"):
                    status = "out_of_scope"
                else:
                    status = "unmatched"
            else:
                status = "stale"

            batch_updates.append({"id": rid, "status": status, "stars": stars,
                                  "pushed": pushed, "archived": archived, "desc": desc})

        if len(batch_updates) >= 50:
            _flush_classifications(batch_updates)
            batch_updates = []
            logger.info(f"  Classified {i + 1}/{len(unmatched)}")

        time.sleep(0.3)

    if batch_updates:
        _flush_classifications(batch_updates)
    logger.info(f"Classification complete")


def _flush_classifications(updates):
    """Batch write classification results."""
    with engine.connect() as conn:
        for u in updates:
            conn.execute(text("""
                UPDATE awesome_list_repos
                SET status = :status, github_stars = :stars,
                    github_last_pushed = :pushed, github_archived = :archived,
                    github_description = :desc
                WHERE id = :id
            """), u)
        conn.commit()


def snapshot_coverage(scan_date):
    """Write summary metrics and print report."""
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO coverage_snapshots
                (scan_date, source_full_name, total_listed, matched, unmatched,
                 stale, archived, out_of_scope, coverage_pct)
            SELECT :scan_date, als.full_name,
                COUNT(*),
                COUNT(*) FILTER (WHERE alr.status = 'matched'),
                COUNT(*) FILTER (WHERE alr.status = 'unmatched'),
                COUNT(*) FILTER (WHERE alr.status = 'stale'),
                COUNT(*) FILTER (WHERE alr.status = 'archived'),
                COUNT(*) FILTER (WHERE alr.status IN ('out_of_scope', 'renamed')),
                ROUND(
                    COUNT(*) FILTER (WHERE alr.status = 'matched')::numeric * 100
                    / NULLIF(COUNT(*) FILTER (WHERE alr.status IN ('matched', 'unmatched')), 0),
                2)
            FROM awesome_list_repos alr
            JOIN awesome_list_sources als ON als.id = alr.source_id
            WHERE alr.scan_date = :scan_date
            GROUP BY als.full_name
            ON CONFLICT (source_full_name, scan_date) DO UPDATE SET
                total_listed = EXCLUDED.total_listed,
                matched = EXCLUDED.matched,
                unmatched = EXCLUDED.unmatched,
                stale = EXCLUDED.stale,
                archived = EXCLUDED.archived,
                out_of_scope = EXCLUDED.out_of_scope,
                coverage_pct = EXCLUDED.coverage_pct
        """), {"scan_date": scan_date})
        conn.commit()

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT source_full_name, total_listed, matched, unmatched,
                   stale, archived, out_of_scope, coverage_pct
            FROM coverage_snapshots WHERE scan_date = :scan_date
            ORDER BY total_listed DESC
        """), {"scan_date": scan_date}).fetchall()

    print("\n=== Coverage Audit Report ===\n")
    total_m, total_u = 0, 0
    for r in rows:
        m = r._mapping
        print(f"  {m['source_full_name']}: {m['coverage_pct'] or 0}% "
              f"({m['matched']} matched, {m['unmatched']} gaps, "
              f"{m['stale']} stale, {m['archived']} archived)")
        total_m += m["matched"]
        total_u += m["unmatched"]

    if total_m + total_u > 0:
        print(f"\n  Overall: {round(total_m * 100 / (total_m + total_u), 1)}% "
              f"({total_m} matched, {total_u} genuine gaps)")

    with engine.connect() as conn:
        gaps = conn.execute(text("""
            SELECT alr.repo_full_name, alr.github_stars, alr.github_description,
                   als.full_name as source
            FROM awesome_list_repos alr
            JOIN awesome_list_sources als ON als.id = alr.source_id
            WHERE alr.scan_date = :scan_date AND alr.status = 'unmatched'
              AND COALESCE(alr.github_stars, 0) >= 50
            ORDER BY alr.github_stars DESC NULLS LAST LIMIT 20
        """), {"scan_date": scan_date}).fetchall()

    if gaps:
        print(f"\n  Top gaps (active, >=50 stars):\n")
        for g in gaps:
            m = g._mapping
            stars = m["github_stars"] or "?"
            print(f"    {m['repo_full_name']} ({stars} stars) — from {m['source']}")


def main():
    parser = argparse.ArgumentParser(description="Weekly coverage audit")
    parser.add_argument("--skip-metadata", action="store_true",
                        help="Skip GitHub metadata fetch for unmatched repos")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit to N awesome lists (for testing; 0 = all)")
    args = parser.parse_args()

    scan_date = date.today()
    logger.info(f"Coverage audit for {scan_date}")

    logger.info("Phase 1: Discovering awesome lists...")
    sources = discover_awesome_lists(limit=args.limit)
    upsert_sources(sources)

    logger.info("Phase 2: Extracting repos...")
    extract_and_store(scan_date)

    logger.info("Phase 3: Reconciling against ai_repos...")
    reconcile(scan_date)

    logger.info("Phase 4: Classifying unmatched...")
    classify_unmatched(scan_date, skip_metadata=args.skip_metadata)

    logger.info("Phase 5: Coverage snapshot...")
    snapshot_coverage(scan_date)

    logger.info("Done")


if __name__ == "__main__":
    main()
