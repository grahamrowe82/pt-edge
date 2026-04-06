"""Ingest academic papers from Semantic Scholar API.

For each active project, searches S2 for papers mentioning the project name
or citing its GitHub repo URL, then stores results in the papers table with
citation count snapshots for time-series tracking.

No API key required (shared 1K req/s pool). Set SEMANTIC_SCHOLAR_API_KEY
for dedicated rate limits.
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "paperId,externalIds,title,authors,abstract,venue,citationCount,year,publicationDate,openAccessPdf"
SEMAPHORE_LIMIT = 2
DELAY_BETWEEN_REQUESTS = 1.0


async def _search_s2(
    client: httpx.AsyncClient,
    query: str,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """Run a single S2 search query, return list of paper dicts."""
    async with semaphore:
        try:
            resp = await client.get(
                S2_SEARCH_URL,
                params={"query": query, "fields": S2_FIELDS, "limit": 20},
            )
            if resp.status_code == 429:
                logger.warning("S2 rate limited, backing off")
                await asyncio.sleep(5.0)
                return []
            if resp.status_code != 200:
                logger.warning(f"S2 API {resp.status_code} for query '{query[:60]}'")
                return []
            data = resp.json()
            return data.get("data") or []
        except Exception as e:
            logger.error(f"S2 search error for '{query[:60]}': {e}")
            return []
        finally:
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)


def _extract_paper_row(hit: dict, project_id: int | None = None) -> dict | None:
    """Convert an S2 API hit into a row dict for insertion."""
    paper_id = hit.get("paperId")
    title = hit.get("title")
    if not paper_id or not title:
        return None

    ext_ids = hit.get("externalIds") or {}
    authors = hit.get("authors") or []
    oap = hit.get("openAccessPdf") or {}

    return {
        "semantic_scholar_id": paper_id,
        "arxiv_id": ext_ids.get("ArXiv"),
        "doi": ext_ids.get("DOI"),
        "title": title,
        "authors": [{"name": a.get("name"), "authorId": a.get("authorId")} for a in authors],
        "abstract": hit.get("abstract"),
        "venue": hit.get("venue"),
        "year": hit.get("year"),
        "publication_date": hit.get("publicationDate"),
        "citation_count": hit.get("citationCount") or 0,
        "open_access_url": oap.get("url"),
        "project_id": project_id,
    }


async def ingest_semantic_scholar() -> dict:
    """Ingest papers from Semantic Scholar for all active projects."""
    started_at = datetime.now(timezone.utc)

    session = SessionLocal()
    try:
        projects = (
            session.query(Project)
            .filter(Project.is_active.is_(True))
            .all()
        )
        project_list = [
            {
                "id": p.id,
                "name": p.name,
                "github_owner": p.github_owner,
                "github_repo": p.github_repo,
            }
            for p in projects
        ]
    finally:
        session.close()

    logger.info(f"Searching Semantic Scholar for {len(project_list)} projects")

    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = settings.SEMANTIC_SCHOLAR_API_KEY

    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    all_papers: dict[str, dict] = {}  # keyed by semantic_scholar_id

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for proj in project_list:
            # Search 1: project name + github
            hits = await _search_s2(client, f"{proj['name']} github", semaphore)
            for hit in hits:
                row = _extract_paper_row(hit, project_id=proj["id"])
                if row and row["semantic_scholar_id"] not in all_papers:
                    all_papers[row["semantic_scholar_id"]] = row

            # Search 2: repo URL (if available)
            if proj["github_owner"] and proj["github_repo"]:
                repo_query = f"github.com/{proj['github_owner']}/{proj['github_repo']}"
                hits2 = await _search_s2(client, repo_query, semaphore)
                for hit in hits2:
                    row = _extract_paper_row(hit, project_id=proj["id"])
                    if row and row["semantic_scholar_id"] not in all_papers:
                        all_papers[row["semantic_scholar_id"]] = row

    # Write to DB
    new_count = 0
    updated_count = 0
    snapshot_count = 0

    if all_papers:
        with engine.connect() as conn:
            for paper in all_papers.values():
                try:
                    result = conn.execute(
                        text("""
                            INSERT INTO papers
                                (semantic_scholar_id, arxiv_id, doi, title, authors, abstract,
                                 venue, year, publication_date, citation_count, open_access_url,
                                 project_id)
                            VALUES
                                (:semantic_scholar_id, :arxiv_id, :doi, :title, CAST(:authors AS jsonb),
                                 :abstract, :venue, :year, :publication_date, :citation_count,
                                 :open_access_url, :project_id)
                            ON CONFLICT (semantic_scholar_id) DO UPDATE SET
                                citation_count = EXCLUDED.citation_count,
                                updated_at = NOW()
                            RETURNING id, (xmax = 0) AS is_new
                        """),
                        {
                            **paper,
                            "authors": __import__("json").dumps(paper["authors"]),
                        },
                    )
                    row = result.fetchone()
                    if row:
                        paper_db_id = row[0]
                        is_new = row[1]
                        if is_new:
                            new_count += 1
                        else:
                            updated_count += 1

                        # Record citation snapshot
                        conn.execute(
                            text("""
                                INSERT INTO paper_snapshots (paper_id, citation_count)
                                VALUES (:paper_id, :citation_count)
                                ON CONFLICT (paper_id, snapshot_date) DO UPDATE SET
                                    citation_count = EXCLUDED.citation_count,
                                    captured_at = NOW()
                            """),
                            {"paper_id": paper_db_id, "citation_count": paper["citation_count"]},
                        )
                        snapshot_count += 1
                except Exception as e:
                    logger.error(f"Error inserting paper {paper['semantic_scholar_id']}: {e}")
            conn.commit()

    # SyncLog
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="semantic_scholar",
            status="success",
            records_written=new_count,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(
        f"Semantic Scholar ingest complete: {new_count} new, "
        f"{updated_count} updated, {snapshot_count} snapshots"
    )
    return {"new": new_count, "updated": updated_count, "snapshots": snapshot_count}


if __name__ == "__main__":
    import asyncio as _asyncio
    logging.basicConfig(level=logging.INFO)
    print(_asyncio.run(ingest_semantic_scholar()))
