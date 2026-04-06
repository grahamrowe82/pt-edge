# Audit Implementation Plan

*6 April 2026 — companion to [audit-worker-to-site.md](audit-worker-to-site.md)*

This document maps every gap identified in the audit to a specific PR, ordered by dependency and priority.

---

## Phase 0: Fix the Broken Pipeline

Everything else depends on the pipeline working. Three tasks are failing with the same root cause, and they block the entire enrichment and site rebuild chain.

### PR 1: Fix JSONB cast syntax error in `mark_done`

**The problem:** `mark_done` uses `CAST(:result AS jsonb)` in raw SQL. When the result JSON contains colons (e.g. `':evidence:'`), psycopg2 interprets them as bind parameters and throws a syntax error. This is breaking:

- `compute_mv_refresh` — materialised views don't refresh (stale site data)
- `export_static_site` — site never rebuilds
- `compute_content_budget` — blocks all budget-gated enrichment
- `enrich_domain_brief` — 16 failures, all from colon-containing results
- `enrich_stack_layer`, `enrich_hn_match`, `enrich_package_detect` — same cause

**The fix:** Change the cast syntax in `worker.py` `mark_done`:

```python
# Before (broken when result contains colons):
SET state = 'done', completed_at = now(), result = CAST(:result AS jsonb)

# After:
SET state = 'done', completed_at = now(), result = :result::jsonb
```

Or use `json.dumps()` + pass as text and cast in Python before the query. The safest approach is to use SQLAlchemy's `type_coerce` or `cast` function rather than raw SQL casting.

**Files:**
- `app/queue/worker.py` — fix `mark_done` function

**Impact:** Unblocks the entire pipeline. MV refresh, site rebuild, content budget, domain briefs, stack layers, HN matching, and package detection all start working.

**This is the single most important PR. Everything below depends on it.**

---

## Phase 1: Display Data We Already Have

These PRs surface content that's already in the database but not rendered on the site. No new data generation needed.

### PR 2: Render `use_this_if` and `not_ideal_if` on project pages

**The problem:** 4,756 repos have `use_this_if` and `not_ideal_if` fields. These are in the MV (the site generator queries them). But `server_detail.html` has conditional blocks for them that may not be rendering, or the fields are empty for most repos.

**The fix:** Verify the template renders these fields. The template at lines 90-102 already has:
```jinja2
{% if server.use_this_if %}...{% endif %}
{% if server.not_ideal_if %}...{% endif %}
```

The issue may be that `enrich_summary` only populates these fields for some repos (4,756 out of 15,519 summaries). Check whether the summary prompt always returns them. If the template is correct, this is a data coverage issue, not a display issue — in which case, no PR needed.

**Files:**
- `templates/server_detail.html` — verify/fix rendering
- Possibly `app/queue/handlers/enrich_summary.py` — ensure prompt always returns `use_this_if`/`not_ideal_if`

### PR 3: Wire `repo_briefs` to project pages

**The problem:** 5,603 repo briefs with titles, summaries, and structured evidence sit in the `repo_briefs` table, completely disconnected from the site. The MVs don't join to `repo_briefs`. The template has no section for them.

**The fix — two parts:**

**Part A: Add repo brief columns to MVs.**

Update migration 077's MV definitions to LEFT JOIN `repo_briefs`:

```sql
LEFT JOIN repo_briefs rb ON rb.ai_repo_id = ar.id
```

Add columns: `rb.title AS brief_title`, `rb.summary AS brief_summary`, `rb.evidence AS brief_evidence`

This requires a new migration that rebuilds all 18 quality MVs (same pattern as 077).

**Part B: Add brief section to template.**

In `templates/server_detail.html`, add a section after the quality scores:

```jinja2
{% if server.brief_summary %}
<section class="brief">
  <h2>Assessment</h2>
  <p>{{ server.brief_summary }}</p>
  {% if server.brief_evidence %}
    <ul class="evidence">
    {% for e in server.brief_evidence %}
      <li>{{ e.metric }}: {{ e.value }} (as of {{ e.as_of }})</li>
    {% endfor %}
    </ul>
  {% endif %}
</section>
{% endif %}
```

**Part C: Update site generator query.**

In `generate_site.py` `fetch_servers()`, add `brief_title`, `brief_summary`, `brief_evidence` to the SELECT list.

**Files:**
- New migration — rebuild MVs with repo_briefs JOIN
- `scripts/generate_site.py` — add columns to fetch query
- `templates/server_detail.html` — add brief section

**Dependencies:** PR 1 (MV refresh must work)

### PR 4: Wire `domain_briefs` to domain landing pages

**The problem:** 17 domain briefs (one per domain) with landscape summaries sit in `domain_briefs`. Domain landing pages show a generic description but no analytical content.

**The fix:** In `generate_site.py`, when generating the domain homepage, query `domain_briefs` for the current domain and pass it to the template. Add a section to the domain landing template.

**Files:**
- `scripts/generate_site.py` — query `domain_briefs` in domain homepage generation
- Template for domain landing page (inline in `generate_site.py` or separate file) — add brief section

**Dependencies:** PR 1 (domain brief generation must work)

---

## Phase 2: Surface Community & Ecosystem Signals

These PRs add new sections to project pages using data that's already collected.

### PR 5: Add HN discussion links to project pages

**The problem:** 3,882 HN posts are linked to projects via `enrich_hn_match`. None appear on project pages.

**The fix:**

**Part A:** In `generate_site.py`, query HN posts for each project:
```sql
SELECT title, url, points, num_comments, posted_at
FROM hn_posts
WHERE project_id = :pid
ORDER BY points DESC LIMIT 5
```

Pass to template as `hn_posts`.

**Part B:** Add section to `server_detail.html`:
```jinja2
{% if hn_posts %}
<section class="community">
  <h2>Community Discussion</h2>
  {% for post in hn_posts %}
    <a href="{{ post.url }}">{{ post.title }}</a>
    <span>{{ post.points }} points, {{ post.num_comments }} comments</span>
  {% endfor %}
</section>
{% endif %}
```

**Files:**
- `scripts/generate_site.py` — query hn_posts per project
- `templates/server_detail.html` — add community section

**Dependencies:** PR 1 (enrich_hn_match must work)

### PR 6: Add release history to project pages

**The problem:** 8,414 releases collected but not displayed. Project pages show "last pushed" but not version history.

**The fix:** Similar pattern to PR 5. Query `releases` for each project, pass to template, add a "Recent Releases" section showing the last 5 releases with version, date, and changelog snippet.

**Files:**
- `scripts/generate_site.py` — query releases per project
- `templates/server_detail.html` — add releases section

**Dependencies:** None beyond PR 1

### PR 7: Link HuggingFace models/datasets to project pages

**The problem:** 25,656 HF models and 61,256 HF datasets are collected but not linked to project pages.

**The fix:** This requires a join strategy — HF models/datasets have source repo URLs that can be matched to `ai_repos.full_name`. Query matching HF entries per project and add a "Models & Datasets" section.

**Files:**
- `scripts/generate_site.py` — query hf_models/hf_datasets per project
- `templates/server_detail.html` — add HF section

**Dependencies:** None beyond PR 1. May need a pre-computed lookup table if the join is expensive at site-gen time.

---

## Phase 3: Fix Enrichment Coverage

These PRs address the low coverage rates identified in the audit.

### PR 8: Ensure `enrich_summary` always returns `use_this_if`/`not_ideal_if`

**The problem:** Only 4,756 of 15,519 summaries have `use_this_if` populated. The prompt may not consistently require these fields, or the handler may not be writing them.

**The fix:** Review the summary prompt and handler. Ensure the prompt requires `use_this_if` and `not_ideal_if` in every response, and the handler writes them even when the README is minimal.

**Files:**
- `app/queue/handlers/enrich_summary.py` — review prompt and field handling

### PR 9: Fix `enrich_landscape_brief` (0 rows)

**The problem:** The landscape_briefs table is empty. The task has been failing.

**The fix:** Investigate the handler error (likely the same JSONB cast issue as PR 1). Once PR 1 is deployed, retry the task and verify it populates.

**Files:**
- Possibly `app/queue/handlers/enrich_landscape_brief.py` or `app/ingest/landscape_briefs.py`

**Dependencies:** PR 1

### PR 10: Accelerate README caching

**The problem:** Only 17,516 of 245,616 repos have cached READMEs (7.1%). The summary pipeline is starved — it can't generate summaries without READMEs.

**The fix:** This is already addressed by the discovery expansion plan (PR 1: backlog throttle, already merged). With `PENDING_CAP=5000` and `BATCH_LIMIT=5000`, README caching should clear the backlog in days. Monitor and verify.

**Dependencies:** Already merged (PR 198)

---

## Phase 4: New Site Sections

These PRs create entirely new page types or site sections.

### PR 11: Create public API directory pages

**The problem:** 2,529 public APIs collected, only accessible via MCP `find_public_api` tool.

**The fix:** Generate static pages for the API directory, similar to the project pages. Each API gets a page with its description, categories, and OpenAPI spec link.

**Files:**
- New template for API pages
- `scripts/generate_site.py` or new script — generate API directory
- `scripts/start.sh` — add to build sequence

### PR 12: Surface briefings on domain pages

**The problem:** 38 weekly briefings generated for MCP consumption but not on the site.

**The fix:** Add a "Weekly Briefing" or "What's New" section to domain landing pages, pulling the latest briefing per domain.

**Files:**
- `scripts/generate_site.py` — query briefings per domain
- Domain landing template — add briefing section

---

## Dependency Graph

```
PR 1 (fix mark_done JSONB) ──────────────────────────────────────┐
  │                                                               │
  ├── PR 2 (use_this_if / not_ideal_if)                          │
  │                                                               │
  ├── PR 3 (repo_briefs on project pages)                        │
  │                                                               │
  ├── PR 4 (domain_briefs on landing pages)                      │
  │                                                               │
  ├── PR 5 (HN discussion links)                                 │
  │                                                               │
  ├── PR 6 (release history)                                     │
  │                                                               │
  ├── PR 7 (HuggingFace models/datasets)                         │
  │                                                               │
  ├── PR 8 (fix summary prompt for use_this_if)                  │
  │                                                               │
  ├── PR 9 (fix landscape briefs)                                │
  │                                                               │
  ├── PR 10 (README backlog — already merged, monitor)           │
  │                                                               │
  ├── PR 11 (public API directory)                               │
  │                                                               │
  └── PR 12 (briefings on domain pages)                          │
```

PR 1 is the root dependency. PRs 2-12 are largely independent of each other and can be done in any order after PR 1.

Within Phase 1 (PRs 2-4), PR 3 is the highest-value change — it surfaces 5,603 rich assessments.

---

## Summary Table

| PR | Phase | What | Key files | Depends on |
|----|-------|------|-----------|-----------|
| 1 | 0 | Fix JSONB cast in mark_done | `worker.py` | None |
| 2 | 1 | Render use_this_if/not_ideal_if | `server_detail.html` | PR 1 |
| 3 | 1 | Wire repo_briefs to project pages | Migration + `generate_site.py` + `server_detail.html` | PR 1 |
| 4 | 1 | Wire domain_briefs to landing pages | `generate_site.py` + template | PR 1 |
| 5 | 2 | HN discussion links on project pages | `generate_site.py` + `server_detail.html` | PR 1 |
| 6 | 2 | Release history on project pages | `generate_site.py` + `server_detail.html` | PR 1 |
| 7 | 2 | HuggingFace models/datasets linking | `generate_site.py` + `server_detail.html` | PR 1 |
| 8 | 3 | Fix summary prompt for use_this_if | `enrich_summary.py` | PR 1 |
| 9 | 3 | Fix landscape briefs | Handler/ingest code | PR 1 |
| 10 | 3 | README backlog (monitor) | Already merged | — |
| 11 | 4 | Public API directory pages | New template + script | PR 1 |
| 12 | 4 | Briefings on domain pages | `generate_site.py` + template | PR 1 |
