# Roadmap Audit — 2026-04-02

Line-by-line verification of every roadmap item against the actual codebase and database.

## "What's Done" Section

| # | Claim | Verdict | Notes |
|---|-------|---------|-------|
| 1 | 165,000+ page directory across 17 domains | **STALE** | 18 domains (perception added). 226K repos. Page count roughly correct but domain count wrong. |
| 2 | Quality scoring (0-100) with 4 sub-dimensions, daily refresh | **CORRECT** | maintenance, adoption, maturity, community sub-scores confirmed across all 18 quality MVs. |
| 3 | 2,400 embedding-discovered categories | **STALE** | Actual count is 2,267. Should say "2,200+" or "2,267". |
| 4 | Decision paragraphs on every category page | **CORRECT** | `decision_paragraph()` called in category.html. |
| 5 | AI summaries from READMEs (Haiku-generated, 2K/day backfill) | **STALE** | MAX_PER_RUN is still 2,000 in code but LLM_BUDGET_MULTIPLIER is 2.0, so effective budget is 4K/day. Roadmap should say 4K/day. However, only 9,757 of 226,017 repos have summaries (4.3%). |
| 6 | Daily metric snapshots for all 220K repos | **CORRECT** | 226,017 distinct repo_ids in snapshots, latest date 2026-04-01. |
| 7 | 1536d embeddings for 220K+ repos | **STALE** | 219,356 have embeddings (~97%). Should say "219K+" not "220K+". 6,661 repos lack embeddings. |
| 8 | JSON-LD structured data, sitemaps, cross-domain navigation | **CORRECT** | JSON-LD in 5 templates, sitemap generation confirmed, 18-entry DIRECTORIES array for navigation. |
| 9 | MCP server (47 tools) + REST API with keyed access | **STALE** | Now 51+ tools (one agent counted 51, another counted 62 — depends on counting method). Should say "50+ tools". |
| 10 | Comparison pages: embedding-similarity pairs within categories | **CORRECT** | build_comparison_pairs() confirmed. 9,422 comparison sentences in DB. |
| 11 | Domain reassignment via centroid similarity (10K/day) | **CORRECT** | reassign_domains in runner.py confirmed. |
| 12 | Allocation engine with Bayesian surprise etc. | **CORRECT** | mv_allocation_scores has ehs, es, surprise_ratio, position_strength, ctr_vs_benchmark columns. allocation_score_snapshots table exists. |
| 13 | Umami self-hosted analytics | **CORRECT** | umami_page_stats table exists, UMAMI_DATABASE_URL in settings, Umami ETL in runner.py. |
| 14 | CTR-optimised title tags and meta descriptions | **CORRECT** | human_stars filter in generate_site.py, used in server_detail.html and comparison.html. |
| 15 | Deep dive infrastructure: reverse links | **CORRECT** | fetch_deep_dive_links() in generate_site.py builds reverse lookups from featured_repos and featured_categories. |
| 16 | Voice AI deep dive | **CORRECT** | voice-ai-landscape and voice-app-stack both published in deep_dives table. |
| 17 | Google Search Console pipeline wired into daily ingest | **CORRECT but misleading** | Pipeline is wired and running. gsc_search_data has 48 rows — not empty but barely anything. The "Immediate" section says it's empty which is now wrong. |

### Items missing from "What's Done"

| Item | Evidence |
|------|----------|
| Coverage audit infrastructure | scripts/audit_coverage.py, migration 068, wired into weekly_structural.py |
| LLM throughput ramp (3x RPM + 2x budget) | ANTHROPIC_RPM=120, LLM_BUDGET_MULTIPLIER=2.0 in settings.py |
| 9 published deep dives (not just voice-ai) | openclaw-ecosystem, voice-ai-landscape, voice-app-stack, embeddings-shortcut, agent-governance-landscape, agent-memory-landscape, agent-skills-architecture, obsidian-pkm-agents, perception-browser-automation |
| Commercial plan document | docs/commercial-plan.md exists, referenced from roadmap |
| Strategy + allocation engine briefs updated | docs/strategy.md has "Where we win" section, docs/briefs/allocation-engine.md has Bayesian framework |
| Deep dive process documented | docs/briefs/deep-dive-process.md with full 7-step process |

## "Immediate" Section

| # | Item | Verdict | Notes |
|---|------|---------|-------|
| 1 | GSC data flowing — "gsc_search_data is empty" | **STALE** | Has 48 rows now. Not empty but barely flowing. Description needs updating — the issue is volume, not absence. |
| 2 | Sitemap/generation alignment | **POSSIBLY DONE** | One agent found that generate_sitemap() receives the same filtered `servers` list used for page generation. If true, sitemap and pages share one source of truth already. But we have 3 confirmed 404s from GSC, which contradicts this. Needs deeper investigation — the 404s might come from stale Google cache or domain reassignment, not sitemap misalignment. |
| 3 | Domain reassignment redirects | **CORRECT** | No domain_reassignment_log table exists. Not built yet. |
| 4 | Subcategory classifier quality | **CORRECT** | ElevenLabs confirmed still in `ai-workflow-automation`. Problem persists. |
| 5 | Cross-category comparison discovery | **CORRECT** | build_comparison_pairs() only runs within subcategories. No domain-level pass. |

## "Data-Driven" Section

| # | Item | Verdict | Notes |
|---|------|---------|-------|
| 1 | Deep dives — "Embeddings landscape" as candidate | **DONE** | embeddings-shortcut is published. Should be moved to done. |
| 2 | Deep dives — "Data engineering, Computer vision, MLOps" as candidates | **CORRECT** | None of these exist in deep_dives table. Still candidates. |
| 3 | Language pages | **CORRECT** | No language-page generation exists. Still a future item. |
| 4 | Temporal layer — "30+ days late April 2026" | **CORRECT but tight** | Only 4 days of snapshots exist (Mar 28 – Apr 1). 30 days arrives ~Apr 27. Timeline still plausible. |
| 5 | Cross-vertical stack pages — "speculative" | **STALE** | voice-app-stack deep dive already validated the concept (cross-domain linking, architecture guide). The roadmap still says "speculative until GSC data shows cross-vertical search intent" — but we've already proven demand via Umami data (5x voice overrepresentation across domains). Not speculative anymore. |

## "Infrastructure Quality" Section

| # | Item | Verdict | Notes |
|---|------|---------|-------|
| 1 | Cross-vertical links for projects in multiple domains | **CORRECT** | Not built. Each repo lives in exactly one domain. |
| 2 | Open Graph tag verification | **STALE** | OG tags are implemented in index.html, server_detail.html, comparison.html. Implementation is done. What might remain is visual verification on Twitter/LinkedIn. Could arguably move to done. |
| 3 | RSS feeds per domain | **CORRECT** | Not built. Site consumes RSS (newsletter ingest) but doesn't generate feeds. |

### Missing from this section

| Item | Evidence |
|------|----------|
| Coverage audit (weekly awesome-list reconciliation) | Built but not mentioned anywhere in the roadmap. |

## "Commercial Progression" Section

| # | Item | Verdict | Notes |
|---|------|---------|-------|
| 1 | Automated topical email digests | **CORRECT** | Not built. No email sending infrastructure exists. |
| 2 | API and key system exist but aren't promoted | **CORRECT** | API key system exists (app/api/auth.py, manage_api_keys.py). No CTA or promotional link on any site page. |

## "Long-Term" Section

| # | Item | Verdict | Notes |
|---|------|---------|-------|
| 1 | Quantitative analytics layer | **CORRECT** | Not built. |
| 2 | Enterprise data API | **CORRECT** | API exists, pricing model described, not at scale yet. |
| 3 | Community features (claim project, feedback, search) | **CORRECT** | None built. |

## Summary

| Verdict | Count |
|---------|-------|
| CORRECT | 17 |
| STALE (needs updating) | 10 |
| POSSIBLY DONE (needs investigation) | 1 |
| DONE (should move to done list) | 1 |
| Missing from roadmap entirely | 7 |

### Key discrepancies

1. **"What's Done" is significantly behind** — 9 deep dives, coverage audit, LLM ramp, commercial plan, strategy docs all missing.
2. **Numbers are stale** — 17 domains (should be 18), 47 tools (should be 50+), 2,400 categories (should be 2,267), 2K/day summaries (now 4K).
3. **GSC description contradicts reality** — says "empty" but has 48 rows.
4. **Sitemap alignment may already be fixed** — conflicting evidence between code structure (shared server list) and actual 404s (possibly from domain reassignment, not sitemap).
5. **Cross-vertical stack pages are no longer speculative** — voice-app-stack proved the concept.
6. **Coverage audit infrastructure is built but invisible** — not mentioned in the roadmap at all.
