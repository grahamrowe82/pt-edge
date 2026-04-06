"""Shared helpers for HuggingFace Hub API ingestion.

Used by both hf_datasets.py and hf_models.py for tag parsing
and cursor-based pagination.
"""
import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)

# Regex to extract next-page URL from Link header
# Format: <https://huggingface.co/api/...?cursor=...>; rel="next"
_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def parse_hf_tags(tags: list[str] | None) -> dict:
    """Parse flat HuggingFace tag strings into structured categories.

    HF tags are flat strings with prefixes like:
        "task_categories:text-classification"
        "language:en"
        "license:mit"
        "size_categories:1K<n<10K"

    Returns dict with keys: task_categories, languages, licenses, sizes.
    Unprefixed tags are collected under "other".
    """
    result: dict[str, list[str]] = {
        "task_categories": [],
        "languages": [],
        "licenses": [],
        "sizes": [],
        "other": [],
    }
    if not tags:
        return result

    prefix_map = {
        "task_categories": "task_categories",
        "task_ids": "task_categories",
        "language": "languages",
        "license": "licenses",
        "size_categories": "sizes",
    }

    for tag in tags:
        if ":" in tag:
            prefix, _, value = tag.partition(":")
            key = prefix_map.get(prefix)
            if key:
                result[key].append(value)
            else:
                result["other"].append(tag)
        else:
            result["other"].append(tag)

    return result


def parse_next_url(link_header: str | None) -> str | None:
    """Extract the next-page URL from a Link header.

    Returns None if no next link is found.
    """
    if not link_header:
        return None
    match = _LINK_NEXT_RE.search(link_header)
    return match.group(1) if match else None


async def fetch_hf_pages(
    client: httpx.AsyncClient,
    base_url: str,
    params: dict,
    min_downloads: int,
    max_pages: int = 50,
) -> list[dict]:
    """Paginate through HuggingFace Hub API results.

    Follows cursor-based pagination via Link header. Stops when:
    - No more Link header (end of results)
    - Last item's downloads fall below min_downloads threshold
    - max_pages reached

    Items are expected to be sorted by downloads descending.

    Returns flat list of all raw API response items.
    """
    all_items: list[dict] = []
    url = base_url
    page = 0

    while url and page < max_pages:
        try:
            if page == 0:
                resp = await client.get(url, params=params)
            else:
                # Subsequent pages use the full URL from Link header (includes cursor)
                resp = await client.get(url)

            from app.ingest.budget import record_call
            await record_call("huggingface")
            resp.raise_for_status()
            items = resp.json()

            if not items:
                logger.info(f"Empty page at page {page}, stopping")
                break

            # Check download threshold on last item (results are sorted desc)
            last_downloads = items[-1].get("downloads", 0) or 0
            all_items.extend(items)
            page += 1

            logger.info(
                f"Page {page}: {len(items)} items "
                f"(total: {len(all_items)}, last downloads: {last_downloads:,})"
            )

            if last_downloads < min_downloads:
                logger.info(
                    f"Downloads dropped below {min_downloads:,}, stopping pagination"
                )
                break

            # Follow cursor pagination
            link_header = resp.headers.get("Link") or resp.headers.get("link")
            url = parse_next_url(link_header)

            if url:
                from app.ingest.budget import acquire_budget, record_call
                if not await acquire_budget("huggingface"):
                    logger.warning("HuggingFace budget exhausted, stopping pagination")
                    break

        except httpx.HTTPStatusError as e:
            logger.error(f"HF API error on page {page}: {e.response.status_code}")
            break
        except Exception as e:
            logger.error(f"HF API fetch error on page {page}: {e}")
            break

    logger.info(f"Fetched {len(all_items)} total items across {page} pages")
    return all_items
