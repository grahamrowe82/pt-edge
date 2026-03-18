"""Reddit social signal ingest (STUB).

This module is a placeholder for Reddit post ingestion. It requires
Reddit API credentials to function.

Setup steps:
1. Create a Reddit app at https://www.reddit.com/prefs/apps
2. Choose "script" type
3. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env
4. Target subreddits: r/MachineLearning, r/LocalLLaMA, r/artificial, r/ChatGPT

Once credentials are configured, implement the full ingest following
the pattern in hn.py (httpx async, Semaphore, SyncLog).
"""

import logging

from app.settings import settings

logger = logging.getLogger(__name__)


async def ingest_reddit() -> dict:
    """Ingest Reddit posts mentioning tracked projects.

    Returns early if REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not set.
    """
    if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
        logger.info("Reddit ingest skipped: no credentials configured")
        return {"skipped": True, "reason": "no credentials"}

    # TODO: Implement full Reddit ingest when credentials are available
    # Pattern: OAuth2 token exchange, search subreddits for project names,
    # upsert into reddit_posts, record SyncLog entry.
    return {"skipped": True, "reason": "not yet implemented"}
