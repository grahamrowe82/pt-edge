# Docker Hub Pull Counts — Implementation Plan

## Context

Many PT-Edge tracked projects are primarily distributed as Docker images rather than
packages (Ollama, vLLM, TGI, LocalAI, Jan, Open WebUI, AnythingLLM, LibreChat, etc.).
These currently show `no_downloads` in the hype ratio because their adoption signal
lives on Docker Hub, not PyPI/npm. Adding Docker Hub pull counts fills this gap and
gives the hype ratio real data for container-distributed projects.

References feedback item #42.

## Docker Hub API

**Endpoint:** `GET https://hub.docker.com/v2/repositories/{namespace}/{repository}`

**Response (relevant fields):**
```json
{
  "pull_count": 1234567890,
  "star_count": 456,
  "last_updated": "2025-01-15T12:00:00Z"
}
```

- No authentication required for public repos
- `pull_count` is cumulative (all-time), not periodic — we'll store it as
  `downloads_monthly` and compute deltas via snapshots over time, same as other sources
- Rate limit: undocumented but generous for read-only public repo queries; we add
  0.5s delays between requests (same pattern as HuggingFace ingest)

**Note:** `pull_count` is all-time, not last-30-days. For the first snapshot there's no
delta baseline. After two days of collection, `downloads_daily` can be computed as the
difference between today's and yesterday's `pull_count`. After 30 days, monthly delta
becomes meaningful. This matches how we bootstrap any new data source — the materialized
views handle the absence of historical baselines gracefully.

## Project-to-Docker-Image Mapping

Add a `docker_image` column to the `projects` table (e.g. `"ollama/ollama"`,
`"vllm/vllm-openai"`, `"ghcr.io/open-webui/open-webui"` — though we only support
Docker Hub initially, not GHCR).

### Initial mappings (added to `seeds/projects.json`):

| Project | Docker Image |
|---------|-------------|
| Ollama | `ollama/ollama` |
| vLLM | `vllm/vllm-openai` |
| TGI | `ghcr.io/huggingface/text-generation-inference` (skip — not Docker Hub) |
| LocalAI | `localai/localai` |
| Open WebUI | `ghcr.io/open-webui/open-webui` (skip — not Docker Hub) |
| AnythingLLM | `mintplexlabs/anythingllm` |
| LibreChat | `ghcr.io/danny-avila/librechat` (skip — not Docker Hub) |
| ChromaDB | `chromadb/chroma` |
| Qdrant | `qdrant/qdrant` |
| Weaviate | `semitechnologies/weaviate` |
| Milvus | `milvusdb/milvus` |
| LanceDB | (no official Docker image) |
| Jan | (Electron app, no Docker image) |

Projects on GHCR are skipped for now — Docker Hub API only. Can extend later.

## Schema Changes

### Migration 014: Add `docker_image` to projects

```sql
ALTER TABLE projects ADD COLUMN docker_image VARCHAR(200);
```

No new tables needed. Docker Hub pulls go into the existing `download_snapshots` table
with `source = 'dockerhub'`, matching the pattern used by `huggingface`, `pypi`, `npm`.

## Implementation

### 1. `app/ingest/dockerhub.py` (new file)

Follow the exact pattern of `app/ingest/huggingface.py`:

- `fetch_dockerhub_pulls(client, image)` → `int | None`
  - `GET https://hub.docker.com/v2/repositories/{image}`
  - Extract `pull_count`
- `collect_dockerhub_pulls_for_project(client, project, semaphore)` → `dict | None`
  - Skip if `project.docker_image` is None
  - Return snapshot dict with `source="dockerhub"`
  - `downloads_monthly = pull_count` (cumulative; deltas computed by views)
  - `downloads_daily = 0`, `downloads_weekly = 0`
- `ingest_dockerhub()` → `dict`
  - Query active projects where `docker_image IS NOT NULL`
  - Semaphore(3), 0.5s delay between requests
  - Batch upsert into `download_snapshots` with ON CONFLICT
  - Write SyncLog entry with `sync_type="dockerhub"`

### 2. `app/models/core.py` — Add field

```python
docker_image: Mapped[str | None] = mapped_column(String(200), nullable=True)
```

### 3. `app/ingest/runner.py` — Register in pipeline

Add `("dockerhub", ingest_dockerhub())` to the `run_all()` loop, after `downloads`.

### 4. `seeds/projects.json` — Add docker_image field

Add `"docker_image"` to projects that have Docker Hub images.

### 5. `scripts/seed.py` — Handle new field

Ensure the seed script picks up `docker_image` from JSON (check if it already handles
arbitrary fields or needs explicit support).

### 6. `scripts/ingest_dockerhub.py` (new file)

Standalone script matching existing pattern:
```python
import asyncio, logging
from app.ingest.dockerhub import ingest_dockerhub
logging.basicConfig(level=logging.INFO)
asyncio.run(ingest_dockerhub())
```

### 7. Migration `014_docker_image.py`

- Add `docker_image` column to projects table

### 8. Materialized views — No changes needed

The `download_snapshots` table already supports multiple sources per project. The
`LATEST_DL_CTE` pattern in migration 004 already aggregates across all sources:

```sql
SELECT project_id, SUM(downloads_monthly) AS downloads_monthly
FROM (
    SELECT DISTINCT ON (project_id, source)
        project_id, source, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, source, snapshot_date DESC
) per_source
GROUP BY project_id
```

Docker Hub snapshots with `source='dockerhub'` will be automatically included in the
SUM. The hype ratio, momentum, tier, and lifecycle views all consume this aggregated
CTE — no view changes required.

## Edge Cases & Risks

1. **Cumulative vs periodic counts**: Docker Hub `pull_count` is all-time, not
   last-30-days like PyPI. The first day's snapshot will inflate `downloads_monthly` in
   the aggregation. **Mitigation**: After 2+ days of data, the daily delta
   (`today - yesterday`) gives the true daily rate. For the initial snapshot, the views
   will show high numbers but this self-corrects. Alternatively, we could store 0 for
   the first snapshot and only start recording after we have a baseline — but this adds
   complexity for minimal benefit since views handle missing baselines.

2. **GHCR images**: Some projects (TGI, Open WebUI, LibreChat) use GitHub Container
   Registry, not Docker Hub. GHCR doesn't expose pull counts via API. We skip these
   for now.

3. **Multi-image projects**: Some projects publish multiple Docker images. We track
   one canonical image per project. The `docker_image` field is a single string.

4. **Rate limiting**: Docker Hub API rate limits for metadata queries are generous
   (not documented as restricted). Our semaphore(3) + 0.5s sleep keeps us well under
   any reasonable threshold.

## Tests

Add to `tests/test_smoke.py`:

- `test_dockerhub_ingest_imports` — verify `app.ingest.dockerhub` imports cleanly
- `test_docker_image_field` — verify `Project` model has `docker_image` attribute
- `test_dockerhub_in_runner` — verify `ingest_dockerhub` is called in the runner pipeline

## Verification

1. Run `pytest tests/` — all existing + new tests pass
2. Run migration against local DB: `alembic upgrade head`
3. Seed updated projects: `python scripts/seed.py`
4. Run ingest: `python scripts/ingest_dockerhub.py`
5. Check data: `SELECT * FROM download_snapshots WHERE source = 'dockerhub'`
6. Refresh views: `python scripts/refresh_views.py`
7. Check hype ratio for formerly-no_downloads projects:
   `SELECT name, hype_bucket FROM mv_hype_ratio WHERE project_id IN (SELECT id FROM projects WHERE docker_image IS NOT NULL)`

## Files to Create/Modify

| File | Action |
|------|--------|
| `app/models/core.py` | Add `docker_image` field |
| `app/ingest/dockerhub.py` | **New** — Docker Hub API client + ingest |
| `app/ingest/runner.py` | Register dockerhub in pipeline |
| `app/migrations/versions/014_docker_image.py` | **New** — add column |
| `seeds/projects.json` | Add `docker_image` to relevant projects |
| `scripts/seed.py` | Handle `docker_image` field (if needed) |
| `scripts/ingest_dockerhub.py` | **New** — standalone script |
| `tests/test_smoke.py` | Add Docker Hub tests |
