"""Enrich task: generate a problem brief from a cached README via Gemini.

Pure enrich — no GitHub API calls, no README fetching. Reads the README
from raw_cache, calls Gemini, writes the parsed result to ai_repos.

The prompt and output format match the existing ai_repo_summaries pipeline
exactly, so output quality is identical.
"""
import logging

from sqlalchemy import text

from app.db import engine
from app.ingest.llm import call_llm

logger = logging.getLogger(__name__)

MIN_README_LENGTH = 100

PROBLEM_BRIEF_PROMPT = """\
You are writing a short problem brief for an open-source project. Your audience is NOT a developer — \
it's the person who has the problem this project solves. That might be a scientist, a marketer, \
a trader, an HR manager, a teacher, an operations engineer — whoever benefits from this existing.

From the README below, produce a JSON object with these fields:

1. "summary": 2-3 sentences covering:
   - What real-world task or workflow this helps with, in plain language
   - What goes in and what comes out (in terms the practitioner understands, not API terms)
   - Who would use this — the actual end-user persona, not "Python developers"

2. "use_this_if": One sentence starting with "Use this if..." describing the ideal use case

3. "not_ideal_if": One sentence starting with "Not ideal if..." describing when to look elsewhere

4. "domain_tags": 3-5 tags in the vocabulary of the end user, NOT the developer. \
   Use job/field/workflow terms like "spectroscopy", "competitor-analysis", "portfolio-backtesting", \
   "resume-screening" — not technology terms like "contrastive-learning", "multi-agent", "transformer".

Rules:
- Write for the person who has the problem, in their language
- Be specific and concrete — name the domain, the data type, the workflow
- If this is genuinely a developer tool (library, SDK, infrastructure), then the developer IS the end user — write in their language
- Don't mention GitHub stars, scores, or popularity
- Don't start with "This project..." — start with the substance
- Maximum 80 words for the summary

Project: {full_name}
GitHub description: {description}

README (truncated):
{readme_text}"""


async def handle_enrich_summary(task: dict) -> dict:
    """Read cached README, call Gemini, save problem brief to ai_repos.

    Returns:
        {"status": "generated", "summary_length": N} on success
        {"status": "no_readme"} if no cached README found
        {"status": "repo_not_found"} if repo doesn't exist

    Raises:
        RuntimeError on LLM failure — triggers requeue
    """
    full_name = task["subject_id"]

    # Read inputs from database — never from external APIs
    with engine.connect() as conn:
        cache_row = conn.execute(text(
            "SELECT payload FROM raw_cache "
            "WHERE source = 'github_readme' AND subject_id = :s"
        ), {"s": full_name}).fetchone()

        repo_row = conn.execute(text(
            "SELECT id, description FROM ai_repos WHERE full_name = :fn"
        ), {"fn": full_name}).fetchone()

    if not repo_row:
        return {"status": "repo_not_found"}

    if not cache_row or not cache_row[0]:
        return {"status": "no_readme"}

    readme_text = cache_row[0]
    if len(readme_text) < MIN_README_LENGTH:
        return {"status": "readme_too_short"}

    repo_id = repo_row[0]
    description = repo_row[1] or "No description provided"

    prompt = PROBLEM_BRIEF_PROMPT.format(
        full_name=full_name,
        description=description,
        readme_text=readme_text,
    )

    result = await call_llm(prompt, max_tokens=400)

    if not result or not isinstance(result, dict) or not result.get("summary"):
        raise RuntimeError(f"LLM returned no usable result for {full_name}")

    summary = result["summary"]
    use_this_if = result.get("use_this_if", "")
    not_ideal_if = result.get("not_ideal_if", "")
    domain_tags = result.get("domain_tags", [])

    if isinstance(domain_tags, list):
        domain_tags = [str(t) for t in domain_tags[:10]]
    else:
        domain_tags = []

    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos
            SET ai_summary = :summary,
                use_this_if = :use_this_if,
                not_ideal_if = :not_ideal_if,
                problem_domains = :domain_tags,
                ai_summary_at = now()
            WHERE id = :id
        """), {
            "summary": summary,
            "use_this_if": use_this_if,
            "not_ideal_if": not_ideal_if,
            "domain_tags": domain_tags,
            "id": repo_id,
        })
        conn.commit()

    return {"status": "generated", "summary_length": len(summary)}
