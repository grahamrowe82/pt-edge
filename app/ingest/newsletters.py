"""Ingest AI newsletter entries via RSS/Atom feeds.

Fetches entries from curated feeds, extracts individual topics using Claude,
and stores one row per topic. Omnibus newsletters (Zvi, swyx) get exploded
into many rows; single-topic blogs (Simon Willison) get one row.

Deduplicates on (entry_url, topic_index).

Gracefully degrades: if ANTHROPIC_API_KEY is not set, entries are stored
as a single row without summaries, sentiment, or mention extraction.
"""
import json
import logging
import re
from calendar import timegm
from datetime import datetime, timedelta, timezone
from html import unescape

import feedparser
import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, Lab, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# ─── Feed configuration ──────────────────────────────────────────────
# Add new feeds by appending to this list. No code changes needed.
# Feeds with max_age_days will skip entries older than that threshold.

FEEDS = [
    {"slug": "simon-willison",  "url": "https://simonwillison.net/atom/everything/"},
    {"slug": "latent-space",    "url": "https://www.latent.space/feed"},
    {"slug": "zvi",             "url": "https://thezvi.substack.com/feed"},
    {"slug": "openai-news",     "url": "https://openai.com/blog/rss.xml",  "max_age_days": 90},
    {"slug": "google-ai",       "url": "https://blog.google/technology/ai/rss/"},
]
# Removed: bens-bites (malformed RSS), ai-news-swyx (feed stub, 1 placeholder entry)

# ─── HTML stripping ──────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


def _strip_html(html: str) -> str:
    """Strip HTML tags and collapse excessive whitespace."""
    text = unescape(html)
    text = _TAG_RE.sub("", text)
    text = _WS_RE.sub("\n\n", text)
    return text.strip()


# ─── RSS/Atom fetching ───────────────────────────────────────────────

def _fetch_entries(feed: dict) -> list[dict]:
    """Parse an RSS/Atom feed, return list of raw entry dicts."""
    try:
        d = feedparser.parse(feed["url"])
    except Exception as e:
        logger.error(f"Failed to parse feed {feed['slug']}: {e}")
        return []

    if d.bozo and not d.entries:
        logger.warning(f"Feed {feed['slug']} returned no entries (bozo: {d.bozo_exception})")
        return []

    # Recency filter — skip entries older than max_age_days
    max_age_days = feed.get("max_age_days")
    cutoff = None
    if max_age_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    entries = []
    for e in d.entries:
        content_html = ""
        if hasattr(e, "content") and e.content:
            content_html = e.content[0].get("value", "")
        elif hasattr(e, "summary"):
            content_html = e.summary or ""

        content_text = _strip_html(content_html)
        published = e.get("published_parsed") or e.get("updated_parsed")

        # Apply recency filter
        if cutoff and published:
            pub_dt = _parse_published(published)
            if pub_dt and pub_dt < cutoff:
                continue

        entries.append({
            "url": getattr(e, "link", None) or "",
            "title": getattr(e, "title", "") or "",
            "published": published,
            "content": content_text,
        })

    return entries


def _parse_published(time_struct) -> datetime | None:
    """Convert a feedparser time.struct_time to a timezone-aware datetime."""
    if time_struct is None:
        return None
    try:
        return datetime.fromtimestamp(timegm(time_struct), tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


# ─── LLM extraction ─────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
You are analyzing an AI/ML newsletter. Extract topics relevant to AI product \
adoption and industry dynamics.

For each topic return:
- "title": short title (max 10 words)
- "summary": 1-2 sentence summary
- "sentiment": "positive" | "neutral" | "negative" | "mixed"
- "mentions": AI projects/labs that are the SUBJECT of this topic

Mention normalization (CRITICAL — always use the canonical name on the left):
- "GPT" for ChatGPT, GPT-4, GPT-5, GPT-5.3, Codex, o1, o3, any OpenAI model
- "Claude" for Claude Opus, Claude Sonnet, Claude Haiku, Claude Code, any Anthropic model
- "Gemini" for Gemini Pro, Gemini Flash, Bard, any Google AI model
- "Llama" for Llama 2, Llama 3, Llama 4, any Meta AI model
- "Grok" for any xAI model
- For all other products, use the product family name without version numbers.

Mention types:
- type "project": an AI product, model family, or tool (Claude, GPT, Gemini, \
Cursor, Copilot, LangChain, Llama, Grok, Stable Diffusion, ElevenLabs, GLM, \
Seedance, etc).
- type "lab": a company/org whose primary work is AI (OpenAI, Anthropic, \
Google DeepMind, Mistral, Cohere, xAI, DeepSeek, Zhipu, METR, MIRI, \
Stability AI, etc). NOT general tech companies (Meta, Google, Amazon, \
Microsoft, Apple).

Mention relevance:
- The mention must be a subject of the topic, not passing context.
- In benchmark comparisons, all compared models are subjects.
- Every extracted topic should have at least one mention.

Topic filtering — ONLY extract topics where a specific AI product or lab is \
the subject:
- Product events: launches, updates, benchmarks, capabilities, incidents, pricing
- Business events: funding, revenue, M&A, key hires between AI labs, partnerships
- Adoption: a named customer deploying a named AI product
- Competitive dynamics: market shifts, switching between products

SKIP: government policy without a named AI product as subject, social \
commentary, philosophy, military doctrine, non-AI news.

Return: {{"topics": [...]}}
ONLY valid JSON.

Newsletter title: {title}

Content:
{content}"""

# ─── Mention normalization ───────────────────────────────────────────
# Thin safety net for the few cases the prompt consistently misses.
# The prompt handles most normalization; Claude sessions consuming
# this data can figure out aliases, so we only catch proven failures.

_MENTION_ALIASES = {
    "chatgpt": "GPT",
    "codex": "GPT",
    "bard": "Gemini",
}


def _normalize_mention_name(name: str) -> str:
    """Normalize a mention name using the alias map."""
    return _MENTION_ALIASES.get(name.lower(), name)


async def _extract_topics(entry: dict) -> list[dict]:
    """Call Claude to extract individual topics from a newsletter entry.

    Returns a list of topic dicts, each with title/summary/sentiment/mentions.
    For single-topic entries this is a list of one.
    """
    if not settings.ANTHROPIC_API_KEY:
        return []

    prompt = EXTRACTION_PROMPT.format(
        title=entry["title"],
        content=entry["content"],
    )

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 8192,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

        if resp.status_code != 200:
            logger.warning(f"Anthropic API {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        text_block = data.get("content", [{}])[0].get("text", "")

        # Parse JSON — strip markdown fencing if present
        text_clean = text_block.strip()
        if text_clean.startswith("```"):
            text_clean = re.sub(r"^```\w*\n?", "", text_clean)
            text_clean = re.sub(r"\n?```$", "", text_clean)

        result = json.loads(text_clean)

        if isinstance(result, dict) and "topics" in result:
            topics = result["topics"]
        elif isinstance(result, list):
            topics = result
        else:
            return []

        # Validate and normalize each topic
        validated = []
        for t in topics:
            if not isinstance(t, dict) or "summary" not in t:
                continue
            if "sentiment" not in t or t["sentiment"] not in (
                "positive", "neutral", "negative", "mixed"
            ):
                t["sentiment"] = "neutral"
            if "mentions" not in t:
                t["mentions"] = []
            if "title" not in t:
                t["title"] = t["summary"][:80]

            # Normalize mention names and deduplicate
            seen = set()
            normalized_mentions = []
            for m in t["mentions"]:
                m["name"] = _normalize_mention_name(m.get("name", ""))
                key = (m["name"].lower(), m.get("type", ""))
                if key not in seen:
                    seen.add(key)
                    normalized_mentions.append(m)
            t["mentions"] = normalized_mentions

            validated.append(t)

        return validated

    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM JSON for: {entry['title'][:80]}")
        return []
    except Exception as e:
        logger.error(f"LLM extraction error for {entry['title'][:80]}: {e}")
        return []


# ─── ID resolution ───────────────────────────────────────────────────

def _resolve_mention_ids(
    mentions: list[dict],
    project_name_to_id: dict[str, int],
    lab_slug_to_id: dict[str, int],
) -> list[dict]:
    """Resolve LLM-extracted mention names to database IDs."""
    from app.ingest.hn import LAB_ALIASES

    resolved = []
    for m in mentions:
        name = m.get("name", "")
        mention_type = m.get("type", "")
        entry = {"name": name, "type": mention_type}
        name_lower = name.lower()

        if mention_type == "project":
            pid = project_name_to_id.get(name_lower)
            if pid:
                entry["project_id"] = pid
        elif mention_type == "lab":
            lid = lab_slug_to_id.get(name_lower)
            if not lid:
                alias_slug = LAB_ALIASES.get(name_lower)
                if alias_slug:
                    lid = lab_slug_to_id.get(alias_slug)
            if lid:
                entry["lab_id"] = lid

        resolved.append(entry)
    return resolved


# ─── Main ingest ─────────────────────────────────────────────────────

async def ingest_newsletters() -> dict:
    """Fetch all configured RSS feeds, extract topics, store one row per topic."""
    started_at = datetime.now(timezone.utc)

    # Load project and lab lookups
    session = SessionLocal()
    try:
        projects = session.query(Project).filter(Project.is_active.is_(True)).all()
        project_name_to_id = {}
        for p in projects:
            if p.name:
                project_name_to_id[p.name.lower()] = p.id
            if p.slug:
                project_name_to_id[p.slug.lower()] = p.id

        labs = session.query(Lab).all()
        lab_slug_to_id = {lab.slug: lab.id for lab in labs}
    finally:
        session.close()

    total_new = 0
    total_fetched = 0
    error_count = 0
    llm_calls = 0

    for feed in FEEDS:
        logger.info(f"  Fetching {feed['slug']}...")
        entries = _fetch_entries(feed)
        total_fetched += len(entries)

        feed_new = 0
        with engine.connect() as conn:
            for entry in entries:
                if not entry["url"]:
                    continue

                # Check if any topics already ingested for this entry
                exists = conn.execute(
                    text("SELECT 1 FROM newsletter_mentions WHERE entry_url = :url LIMIT 1"),
                    {"url": entry["url"]},
                ).fetchone()
                if exists:
                    continue

                # LLM topic extraction
                topics = await _extract_topics(entry)
                if topics:
                    llm_calls += 1

                published_at = _parse_published(entry["published"])

                if not topics:
                    # No LLM — store as single row without extraction
                    try:
                        conn.execute(
                            text("""
                                INSERT INTO newsletter_mentions
                                    (feed_slug, entry_url, topic_index, title,
                                     published_at, raw_content)
                                VALUES
                                    (:feed_slug, :entry_url, 0, :title,
                                     :published_at, :raw_content)
                                ON CONFLICT (entry_url, topic_index) DO NOTHING
                            """),
                            {
                                "feed_slug": feed["slug"],
                                "entry_url": entry["url"],
                                "title": entry["title"],
                                "published_at": published_at,
                                "raw_content": entry["content"],
                            },
                        )
                        feed_new += 1
                    except Exception as e:
                        logger.error(f"Insert error for {entry['url'][:80]}: {e}")
                        error_count += 1
                else:
                    # Explode topics into individual rows
                    for idx, topic in enumerate(topics):
                        resolved_mentions = _resolve_mention_ids(
                            topic.get("mentions", []),
                            project_name_to_id,
                            lab_slug_to_id,
                        )
                        try:
                            conn.execute(
                                text("""
                                    INSERT INTO newsletter_mentions
                                        (feed_slug, entry_url, topic_index, title,
                                         published_at, summary, sentiment,
                                         mentions, raw_content)
                                    VALUES
                                        (:feed_slug, :entry_url, :topic_index, :title,
                                         :published_at, :summary, :sentiment,
                                         :mentions, :raw_content)
                                    ON CONFLICT (entry_url, topic_index) DO NOTHING
                                """),
                                {
                                    "feed_slug": feed["slug"],
                                    "entry_url": entry["url"],
                                    "topic_index": idx,
                                    "title": topic.get("title", entry["title"]),
                                    "published_at": published_at,
                                    "summary": topic.get("summary"),
                                    "sentiment": topic.get("sentiment"),
                                    "mentions": json.dumps(resolved_mentions),
                                    # Only store full content on topic 0
                                    "raw_content": entry["content"] if idx == 0 else None,
                                },
                            )
                            feed_new += 1
                        except Exception as e:
                            logger.error(f"Insert error for {entry['url'][:80]} topic {idx}: {e}")
                            error_count += 1

            conn.commit()

        total_new += feed_new
        if feed_new:
            logger.info(f"  {feed['slug']}: {feed_new} new topic rows")

    # Log sync
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="newsletters",
            status="success" if error_count == 0 else "partial",
            records_written=total_new,
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(
        f"Newsletter ingest complete: {total_new} new topic rows from "
        f"{total_fetched} fetched, {llm_calls} LLM calls, {error_count} errors"
    )
    return {
        "success": total_new,
        "fetched": total_fetched,
        "llm_calls": llm_calls,
        "errors": error_count,
    }
