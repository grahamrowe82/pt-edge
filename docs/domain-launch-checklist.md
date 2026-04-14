# Domain Launch Checklist

Everything needed when launching a new *-edge domain. Learned from launching CyberEdge (April 2026).

## DNS & Hosting

1. Add custom domain to Render web service: Settings → Custom Domains
2. Render gives you a CNAME target — add it in Namecheap DNS settings
3. SSL handled automatically by Render once DNS propagates (~5-30 min)

## Analytics (Umami)

1. Log into Umami admin at `a.phasetransitions.ai`
2. Create a new website for the domain
3. Copy the website ID
4. Add to the domain's `templates/base.html`:
   ```html
   <script defer src="https://a.phasetransitions.ai/pte.js" data-website-id="YOUR_WEBSITE_ID"></script>
   ```

## Access Logging (bot/crawler tracking)

Add to the domain's `main.py`:
```python
from app.core.middleware.access_log import AccessLogMiddleware
from your_domain.app.db import engine, SessionLocal

AccessLogMiddleware.ensure_table(engine)
app.add_middleware(AccessLogMiddleware, session_factory=SessionLocal)
```

- Table created automatically on first startup (no migration needed)
- Logs path, user-agent, client IP, status code, duration for all HTML requests
- Bot classification shared via `app/core/sql/bot_families.py`

### Downstream (once traffic exists)

Create a site-specific `mv_access_bot_demand` MV with path parsing for the domain's URL structure. The bot classification CASE statement is shared but the path parsing is site-specific because URL structures differ.

Then create `bot_activity_daily` snapshot table for ML training data. See OS AI migration 084 for the schema.

## Sitemaps

Google limits sitemaps to 50,000 URLs per file. Use a **sitemap index**:

```xml
<!-- sitemap.xml (the index) -->
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://your-domain/sitemap-chunk-1.xml</loc></sitemap>
  <sitemap><loc>https://your-domain/sitemap-chunk-2.xml</loc></sitemap>
</sitemapindex>
```

Split by natural boundaries — for CyberEdge: CVEs by published year, products, vendors, other entities. Each child sitemap should be under 40K URLs for safety margin.

Submit the index URL (not individual sitemaps) to Google Search Console.

## Search Engine Submission

### Google Search Console
1. Add property for the domain
2. Verify ownership via DNS TXT record (easiest with Namecheap)
3. Submit `https://your-domain/sitemap.xml` (the index)
4. Request indexing of the homepage

### Bing Webmaster Tools
1. Same process — add property, verify, submit sitemap
2. Takes 5 minutes, also feeds DuckDuckGo results

## Render Environment Variables

### Web service
- `DATABASE_URL` (from Render DB)
- `API_TOKEN` (auto-generated)
- Domain-specific keys (e.g., `NVD_API_KEY` for cyber)

### Worker service
- `DATABASE_URL` (from Render DB)
- `GEMINI_API_KEY` (for LLM enrichment pipelines)
- `OPENAI_API_KEY` (for embedding pipelines)
- Domain-specific keys

## Worker Pipeline

1. Create handler files in `app/queue/handlers/`
2. Register in `app/queue/handlers/__init__.py` (TASK_HANDLERS dict)
3. Add scheduling functions to `app/queue/scheduler.py`
4. Add to `schedule_all()`
5. Deploy — verify tasks appear in worker logs within 15 minutes

## Chunked Site Generation

For sites with >50K pages, use the chunked generation pattern (same as OS AI):

```bash
# start.sh — one invocation per chunk
python generate_site.py --chunk entity-type:subset
python generate_site.py --chunk entity-type:subset
...
python generate_site.py --chunk homepage  # last: index pages, sitemap, SEO
exec uvicorn ...
```

Each invocation is a separate Python process. Memory freed between chunks. No single step should exceed ~40K pages.

## Dead-Link Prevention

When building template lookup sets for internal links, only include entities that actually have pages. If an entity type uses a threshold (e.g., products need `score >= 10 OR cve_count >= 20`), the lookup query must apply the same threshold. Otherwise templates generate links to pages that don't exist → 404s that crawlers hit.

## Verification After Launch

- [ ] Site loads at custom domain with HTTPS
- [ ] Umami dashboard shows traffic for the new website
- [ ] `SELECT COUNT(*) FROM http_access_log` shows rows after a few minutes
- [ ] GSC shows sitemap as "Success" (may take hours)
- [ ] Worker logs show scheduled tasks running
- [ ] No 404s for internal links (check GSC coverage report after 24h)
