# Topic Discovery Methodology

How we use PT-Edge infrastructure to identify high-potential content topics. Based on the "nucleation hypothesis": find areas with high building activity but low narrative crystallisation, where a large audience has an unresolved frustration.

## The three-property signal

A good topic has all three:

1. **High building activity** — lots of repos being created, rapid star growth, active commits
2. **Low narrative crystallisation** — little newsletter coverage, fragmented naming, no consensus
3. **Large frustrated audience** — the problem is one many developers encounter personally

PT-Edge has purpose-built infrastructure for properties 1 and 2. Property 3 requires inference from the data plus editorial judgment.

## The pipeline

### Step 1: Nucleation scan

**Source:** `mv_nucleation_category` and `mv_nucleation_project` views (migration 069)

Query `mv_nucleation_category` for subcategories where `creation_without_buzz = true` and `new_repos_7d >= 2`. This surfaces areas where builders are shipping infrastructure but media hasn't noticed.

```sql
SELECT domain, subcategory, new_repos_7d, new_repos_14d,
       acceleration, hn_coverage_7d, newsletter_coverage_7d,
       creation_without_buzz
FROM mv_nucleation_category
WHERE new_repos_7d >= 2
ORDER BY new_repos_7d DESC
LIMIT 30;
```

Also query `mv_nucleation_project` for individual repos with `narrative_gap = true` (high GitHub velocity, zero media coverage). These can reveal topics the subcategory scan misses.

**Expect:** 20-30 candidates. Many will be noise (ML homework, tutorial repos). The next steps filter aggressively.

### Step 2: Audience size filter

**Source:** `mv_ai_repo_ecosystem`

For each candidate subcategory, check ecosystem size, star distribution, and download volume.

```sql
SELECT domain, subcategory, repo_count, repos_100_plus_stars,
       repos_1k_plus_stars, total_downloads_monthly, max_stars
FROM mv_ai_repo_ecosystem
WHERE (domain, subcategory) IN ((<candidates>))
ORDER BY repo_count DESC;
```

**Filter rules:**
- Drop subcategories with repo_count < 100 (too small for a compelling piece)
- Drop subcategories with 0 downloads AND 0 repos with 100+ stars (no real traction)
- Bonus: check `package_deps` for reverse dependency counts (how many projects depend on tools in this space)

**Why this works:** The amnesia piece covered 977 repos. Embeddings covered hundreds. The audience size correlates with ecosystem size — more repos means more developers making decisions in that space.

### Step 3: Fragmentation score

**Source:** Domain quality views + `ai_repos` top project query

Two checks:

**A) Leader concentration.** Query top 10 projects by stars in the subcategory. If #1 has >10x the stars of #2, the space has likely consolidated around a winner. There's no confusion to resolve — and no piece to write.

```sql
SELECT full_name, stars, downloads_monthly
FROM ai_repos
WHERE domain = '<domain>' AND subcategory = '<subcategory>'
ORDER BY stars DESC
LIMIT 10;
```

**B) Quality tier distribution.** Query the domain quality view. Best candidates have mostly experimental quality (<30 score) with a few emerging/established projects. If many projects are "verified" (>70), the space is mature.

**This is the strongest single filter.** In run 1, this eliminated local-rag (llama_index 100x dominant) and LLM-api-gateways (LiteLLM 3.5x dominant). The topics that passed all had competitive top-3 distributions.

### Step 4: Narrative gap confirmation

**Source:** `newsletter_mentions` and `hn_posts`

**A) Newsletter coverage.** Count mentions of topic keywords in `newsletter_mentions` over 90 days, across distinct `feed_slug` values.

```sql
SELECT feed_slug, COUNT(*) as mentions
FROM newsletter_mentions
WHERE (title || ' ' || COALESCE(summary,'')) ILIKE '%<keywords>%'
  AND published_at >= NOW() - INTERVAL '90 days'
GROUP BY feed_slug;
```

- 0-5 mentions: big narrative gap (ideal)
- 5-15 mentions: moderate coverage, window may be closing
- 15+ mentions across 4+ feeds: narrative likely crystallised, skip

**B) HN debate ratio.** For HN posts about the topic, compute `num_comments / points`. Ratio > 0.5 means contentious/unresolved (people argue). Ratio < 0.3 means consensus (people agree). High debate = opportunity.

**Caution:** ILIKE matching is noisy for newsletter search. "AI" + "os" matches "iOS". Embedding-based semantic search on newsletter_mentions would be more reliable when available.

### Step 5: Allocation cross-check

**Source:** `mv_allocation_scores`

Check `ehs` (established heat / demand) and `es` (emergence score / supply) for candidate subcategories. The ideal pattern: **high ES + low EHS** = building momentum without established audience = untapped demand.

```sql
SELECT domain, subcategory, ehs, es, opportunity_tier,
       github_new_repos_7d, hn_points_7d, newsletter_mentions_7d
FROM mv_allocation_scores
WHERE (domain, subcategory) IN ((<candidates>))
ORDER BY es DESC;
```

### Step 6: Editorial framing test

For surviving candidates, answer manually:

1. **Can I write "Your ___" in the title?** The topic must be a problem the reader has personally. "Your AI has no tests" works. "How agent evaluation benchmarks evolved" doesn't.
2. **Is there a clear decision the reader needs to make?** Which tool? Which approach? Which architecture? Decision-driven framing is our structural advantage.
3. **Is the stack layer accessible?** Orchestration/data/interface topics are closer to the developer's hands than model/infra topics. Closer = easier framing.
4. **Can PT-Edge data resolve the confusion?** Do we have quality scores, comparisons, and specific recommendations? If we can only describe the landscape but not tell the reader what to use, the piece is weaker.

## Signals ranked by predictive value

From run 1, ordered by how effectively they separated good topics from bad:

| Signal | Source | Predictive power |
|--------|--------|-----------------|
| Leader concentration (top project 10x #2?) | ai_repos query | Strongest — eliminated false positives reliably |
| Newsletter mention count (90 days) | newsletter_mentions | Directly measures narrative crystallisation |
| HN debate ratio (comments/points) | hn_posts | Measures contentiousness / unresolvedness |
| Monthly downloads | mv_ai_repo_ecosystem | Separates real tools from tutorials/homework |
| Repo count | mv_ai_repo_ecosystem | Weak proxy for audience size, produces false positives |
| creation_without_buzz flag | mv_nucleation_category | Good starting point but many false positives |

## Known limitations

1. **Cross-subcategory topics.** Some of the best topics span multiple subcategories (e.g., "inference cost" touches llm-inference-engines, model-compression-optimization, llm-inference-serving). The pipeline works per-subcategory but misses thematic patterns.
2. **Audience size estimation.** Repo count is a weak proxy. Reverse dependency count is better but expensive to compute. GSC impression data helps but only for topics where we already have pages.
3. **Newsletter ILIKE noise.** Keyword matching on newsletter content produces false positives. Semantic search would be more reliable.
4. **Subcategory taxonomy quality.** Some subcategories contain misclassified repos (ML homework, tutorials). A quality floor on the nucleation scan would reduce noise.

## Run history

- **Run 1 (2026-04-03):** Surfaced LLM evaluation, inference cost, Rust agents, agent runtime gap. Wrote eval piece first. Details in `docs/briefs/topic-discovery-run-1.md`.
