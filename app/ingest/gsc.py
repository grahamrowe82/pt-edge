"""Fetch Google Search Console data and store in Postgres."""

import json
import logging
from datetime import date, datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy import text

from app.db import engine
from app.settings import settings

logger = logging.getLogger(__name__)

ROW_LIMIT = 25_000  # GSC API max per request


def _get_credentials() -> Credentials:
    """Build OAuth2 credentials from settings or local token file."""
    if settings.GSC_REFRESH_TOKEN:
        return Credentials(
            token=None,
            refresh_token=settings.GSC_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GSC_CLIENT_ID,
            client_secret=settings.GSC_CLIENT_SECRET,
        )
    # Fall back to local token file (dev)
    try:
        with open("secrets/gsc_token.json") as f:
            data = json.load(f)
        return Credentials(
            token=data.get("token"),
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
        )
    except FileNotFoundError:
        return None


def _fetch_day(service, property_uri: str, day: date) -> list[dict]:
    """Fetch all rows for a single day, paginating if needed."""
    all_rows = []
    start_row = 0

    while True:
        response = (
            service.searchanalytics()
            .query(
                siteUrl=property_uri,
                body={
                    "startDate": day.isoformat(),
                    "endDate": day.isoformat(),
                    "dimensions": ["query", "page"],
                    "rowLimit": ROW_LIMIT,
                    "startRow": start_row,
                },
            )
            .execute()
        )

        rows = response.get("rows", [])
        if not rows:
            break

        for row in rows:
            all_rows.append(
                {
                    "search_date": day.isoformat(),
                    "query": row["keys"][0],
                    "page": row["keys"][1],
                    "clicks": row["clicks"],
                    "impressions": row["impressions"],
                    "ctr": round(row["ctr"], 6),
                    "position": round(row["position"], 2),
                }
            )

        if len(rows) < ROW_LIMIT:
            break
        start_row += ROW_LIMIT

    return all_rows


async def ingest_gsc(days_back: int = 3) -> dict:
    """Pull recent GSC data and upsert into gsc_search_data.

    Args:
        days_back: how many days to backfill (GSC has ~2 day lag,
                   so 3 days catches yesterday's final data plus
                   any late-arriving rows).
    """
    creds = _get_credentials()
    if creds is None:
        logger.info("GSC skipped (no credentials configured)")
        return "skipped (no GSC credentials)"
    service = build("searchconsole", "v1", credentials=creds)
    property_uri = settings.GSC_PROPERTY

    today = date.today()
    total_rows = 0
    days_fetched = 0

    for i in range(days_back, 0, -1):
        day = today - timedelta(days=i)
        rows = _fetch_day(service, property_uri, day)

        if not rows:
            logger.info(f"  {day}: no data (too recent or empty)")
            continue

        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO gsc_search_data (search_date, query, page, clicks, impressions, ctr, position)
                    VALUES (:search_date, :query, :page, :clicks, :impressions, :ctr, :position)
                    ON CONFLICT (search_date, query, page) DO UPDATE SET
                        clicks = EXCLUDED.clicks,
                        impressions = EXCLUDED.impressions,
                        ctr = EXCLUDED.ctr,
                        position = EXCLUDED.position
                """),
                rows,
            )
            conn.commit()

        logger.info(f"  {day}: {len(rows)} rows")
        total_rows += len(rows)
        days_fetched += 1

    logger.info(f"GSC ingest done: {total_rows} rows across {days_fetched} days")
    return {"rows": total_rows, "days": days_fetched}
