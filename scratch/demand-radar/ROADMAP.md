# Demand Radar: ML Infrastructure Roadmap

**Created:** 2026-04-05
**Updated:** 2026-04-06
**Branch:** `demand-radar`
**Context:** [LAB-NOTES.md](LAB-NOTES.md) contains the research findings. [RESEARCH-PLAN.md](RESEARCH-PLAN.md) contains the detailed research threads that feed this plan.

---

## Philosophy

Build correct infrastructure end-to-end now, accept garbage outputs for weeks,
define quality thresholds so we know when data is ready. Build once, wait for data.

Every day without snapshot tables is a day of lost training data. The models below
require weeks-to-months of temporal features before they can train. The cost of
starting late is permanent; the cost of starting with imperfect schemas is a
migration.

---

## End-state models (in order of value)

### 1. Demand Predictor

Per-(domain, subcategory) features -> probability of user-action hit next 7 days.

- **Algorithm:** LightGBM
- **Quality threshold:** AUC > 0.70
- **Features:** bot consensus count, Meta revisit ratio, indexing velocity (7d delta),
  ClaudeBot coverage ratio, GSC impressions, content coverage ratio, repo quality
  distribution
- **Labels:** `had_user_action_hit_next_7d` (binary), `user_action_count_next_7d`
- **Value:** Prioritises enrichment budget toward categories about to see demand,
  not categories that already had demand

### 2. Page Ranker (Learning to Rank)

Per-page features -> ranked enrichment priority list.

- **Algorithm:** LightGBM LambdaRank
- **Quality threshold:** NDCG@100 > 0.60
- **Features:** repo quality score, bot family hit count (per family), session
  inclusion count, comparison page appearances, content freshness, GitHub activity
  signals
- **Labels:** user-action hits as relevance grades
- **Value:** Within a category, tells us which specific pages to enrich first

### 3. Latent Theme Discovery

(bot_family x subcategory) matrix factorisation -> emergent demand themes.

- **Algorithm:** NMF or SVD on the bot-subcategory hit matrix
- **Quality threshold:** qualitative assessment (do the latent factors correspond
  to recognisable practitioner themes?)
- **Value:** Discovers cross-domain demand patterns invisible in per-category analysis
  (e.g., "healthcare ML" spanning chest-xray, clinical-risk, medical-imaging)

---

## Infrastructure to build

### 1. `bot_activity_daily` snapshot table

One row per (date, domain, subcategory, bot_family) with aggregate metrics.
**Start immediately — this is the foundation everything else depends on.**

| Column | Type | Notes |
|---|---|---|
| id | serial | |
| snapshot_date | date | |
| domain | varchar | |
| subcategory | varchar | |
| bot_family | varchar(30) | |
| hits | int | |
| unique_pages | int | |
| unique_ips | int | |
| revisit_ratio | numeric(4,2) | hits / unique_pages |

Estimated volume: ~10-15K rows/day. Negligible storage.

**Implementation:** Daily worker task that queries the raw access log, aggregates,
and inserts. Runs after the MV refresh.

### 2. `category_features_daily` feature store

One row per (date, domain, subcategory) with all features needed for model training.

| Column | Type | Notes |
|---|---|---|
| snapshot_date | date | |
| domain | varchar | |
| subcategory | varchar | |
| bot_consensus_count | smallint | Distinct bot families that crawled |
| meta_revisit_ratio | numeric(4,2) | Meta hits / Meta unique pages |
| claudebot_coverage | numeric(4,2) | ClaudeBot unique pages / total pages in category |
| indexing_hits_total | int | All indexing bot hits |
| indexing_velocity_7d | numeric | 7d change in indexing hits |
| user_action_hits | int | Tier 1 bot hits |
| user_action_sessions | int | Detected sessions touching this category |
| gsc_impressions_7d | int | From GSC data if available |
| gsc_clicks_7d | int | |
| content_coverage | numeric(4,2) | Enriched repos / total repos |
| avg_repo_quality | numeric(4,2) | Mean quality score in category |
| repo_count | int | Total repos |

**Implementation:** Daily worker task that joins bot_activity_daily, mv_access_bot_demand,
ai_repos, and GSC tables. Runs after bot_activity_daily is populated.

### 3. `category_demand_labels` retrospective labels

Generated retrospectively — for each (date, domain, subcategory), look forward 7 days
and record what actually happened.

| Column | Type |
|---|---|
| snapshot_date | date |
| domain | varchar |
| subcategory | varchar |
| had_user_action_hit_next_7d | boolean |
| user_action_count_next_7d | int |
| had_deep_research_session_next_7d | boolean |

**Implementation:** Weekly worker task that fills in labels for dates 7+ days in the
past. Always looking backward to create forward-looking labels.

### 4. Training pipeline

Weekly worker task that:
1. Joins `category_features_daily` to `category_demand_labels`
2. Trains LightGBM with 80/20 temporal split (no future leakage)
3. Computes AUC on held-out set
4. Logs results to a `model_runs` table (run_date, model_type, auc, ndcg, params_json)
5. Flags model as production-ready if AUC > 0.70

**Implementation:** Worker task type `train_demand_model`. Python script using
lightgbm + scikit-learn. Model artifacts stored as JSON (feature importances,
thresholds) in the database, not on disk.

### 5. Feedback loop

Once a model passes the quality threshold:
- Model outputs replace/supplement hand-weighted allocation scores
- The allocation engine consumes predicted demand probabilities alongside existing
  GSC and quality signals
- Enrichment budget flows to categories the model predicts will see demand,
  not just categories that already saw demand

---

## IMPORTANT: All recurring jobs must be worker tasks

The project uses an always-on worker with a scheduler that creates task rows. Any
daily/weekly computation must be integrated as a task type in the existing worker
infrastructure. See `docs/design/worker-architecture.md` for the architecture.

**Do NOT use cron jobs.** The worker scheduler handles scheduling. Each computation
above becomes a task type (e.g., `snapshot_bot_activity`, `build_category_features`,
`label_demand`, `train_demand_model`).

---

## Tactical fixes (can be done in parallel with infrastructure)

These don't require temporal data and can ship immediately:

1. **Bot classification CASE statement updates** — add GoogleOther, Claude-User,
   DuckAssistBot to the materialized view. Consider IP-based classification for
   Google stealth renderer.

2. **Cross-IP fan-out session detection** — the 251-page ChatGPT Pro burst fanned
   out across 8 OAI-SearchBot IPs. Session detection needs a secondary heuristic:
   if N IPs from the same bot family hit pages in the same subcategory within a
   30-second window, merge into one session.

3. **Commercial entity detection heuristic** — org owner + company website = likely
   commercial. Cross-reference with user-action demand for "warm lead" list.
   Foundation of claim-your-page business model.

---

## Timeline expectations

| Period | What happens |
|---|---|
| **Weeks 1-2** | Snapshot infrastructure ships. Descriptive stats from snapshots. Hand-tuned weights in allocation engine based on research findings. |
| **Weeks 3-6** | Rolling z-score anomaly detection on snapshot data. Enough temporal data accumulating for feature engineering. First feature store populated. |
| **Weeks 6-12** | First LTR and demand prediction models trainable. Quality thresholds evaluated. Feature importance reveals which signals actually matter. |
| **Months 3+** | Collaborative filtering / matrix factorisation for latent theme discovery. Model outputs feeding allocation engine in production. |

The key insight: we're not blocked on code, we're blocked on data accumulation.
The infrastructure needs to ship now so the clock starts ticking.
