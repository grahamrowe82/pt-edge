"""Seed the methodology table with deep explanations of how PT-Edge works.

Run with: python -m app.methodology_seed

This populates documentation that users can query via explain() to understand
our algorithms, metrics, thresholds, and design decisions — and to tell us
where we're wrong.
"""
from sqlalchemy import text
from app.db import engine

ENTRIES = [
    # -----------------------------------------------------------------------
    # METRICS
    # -----------------------------------------------------------------------
    {
        "topic": "hype_ratio",
        "category": "metric",
        "title": "Hype Ratio: Stars / Monthly Downloads",
        "summary": "Measures the gap between GitHub attention and real-world adoption. High ratio = overhyped (GitHub tourism). Low ratio = invisible infrastructure.",
        "detail": """## Hype Ratio

**Formula:** `stars / monthly_downloads`

**Why it matters:** Stars are free. Downloads mean someone put it in their requirements.txt and bet their production system on it. The ratio reveals the gap between attention and adoption.

**Bucket thresholds:**
- `overhyped`: ratio > 1.0 — more stars than monthly downloads (e.g. cool demo repos)
- `balanced`: ratio 0.01 - 1.0 — healthy attention-to-adoption ratio
- `underrated`: ratio < 0.01 — millions of downloads, few stars (the invisible infrastructure that actually runs AI)

**Known limitations:**
1. **Binary/self-hosted projects score as infinitely hyped** because they have 0 package downloads. OpenClaw, Stable Diffusion WebUI, and similar distributed-as-Docker or git-clone projects will always show as overhyped by this metric. We track `distribution_type` to flag these.
2. **PyPI/npm downloads are noisy.** CI/CD bots, mirror syncs, and automated installs inflate download counts. A project with 10M downloads/month might have 500K real human users. We don't de-duplicate.
3. **Stars can be gamed.** Star-buying services exist. We don't detect or filter for this.
4. **Cross-registry blindness.** A project on both PyPI and conda-forge will have split download counts. We aggregate across sources but may miss registries we don't track.
5. **The ratio compresses over time.** As a project matures, downloads grow faster than stars (people stop starring things they already use). This makes old projects look increasingly underrated.

**Category averages differ wildly.** A hype ratio of 0.5 might be normal for a framework but extreme for a utility library. Always compare within category.

**What we'd change if we could:** Weight downloads by uniqueness (de-duplicate CI bots), and add a "momentum hype ratio" that uses download *growth* instead of absolute counts.""",
    },
    {
        "topic": "star_velocity",
        "category": "metric",
        "title": "Star Velocity: Daily Star Gain Rate",
        "summary": "Measures how fast a project's GitHub stars are growing. Used by radar() to detect breakout candidates.",
        "detail": """## Star Velocity

**Formula:** `(current_stars - previous_stars) / days_since_last_check`

**Where it's used:** The `radar()` tool uses star velocity to surface candidates that are exploding in popularity. The candidate re-scoring job (`ingest_candidate_velocity`) updates star counts for all pending candidates.

**How it works:**
1. When a candidate is first discovered (via HN post URL or GitHub trending), we record its star count
2. After 24 hours (MIN_AGE guard), the re-scoring job fetches the current star count from GitHub API
3. Old count moves to `stars_previous`, new count goes to `stars`
4. Velocity = delta / elapsed days

**Known limitations:**
1. **24-hour minimum baseline.** A project discovered 2 hours ago has no velocity data yet. We show it in "Fresh Candidates" instead.
2. **Single data point.** We compare exactly two snapshots. A project that gained 10K stars in one hour and then plateaued for 3 days looks slow at the 3-day mark. More frequent sampling would help.
3. **Star count API lag.** GitHub's API sometimes returns stale star counts. Counts can be off by ~1-5% from what the web UI shows.
4. **We don't distinguish organic from viral.** A project on the front page of HN for 24 hours will have a massive velocity spike that isn't sustainable. We don't try to predict whether velocity will persist.

**What we'd change:** Sample velocity at multiple intervals (1h, 6h, 24h, 7d) to detect whether growth is a one-day spike or sustained acceleration.""",
    },
    {
        "topic": "momentum",
        "category": "metric",
        "title": "Momentum: Star and Download Deltas Over Time Windows",
        "summary": "7-day and 30-day deltas for stars and downloads, computed from daily snapshots. Powers trending() and movers().",
        "detail": """## Momentum

**Computed in:** `mv_momentum` materialized view

**Star deltas:**
- `stars_7d_delta`: current stars minus stars from 7 days ago
- `stars_30d_delta`: current stars minus stars from 30 days ago
- `has_7d_baseline` / `has_30d_baseline`: whether we actually have a snapshot that old (if not, delta is unreliable)

**Download deltas:**
- `dl_30d_delta`: current monthly downloads minus 30 days ago

**How snapshots work:**
- GitHub stats are ingested daily by `ingest_github()`
- Each run creates one `github_snapshots` row per active project with that day's stars, forks, open issues, contributors, commits_30d
- Delta = today's row minus the row from N days ago, matched by `project_id`

**Known limitations:**
1. **Gaps in snapshot history.** If the ingest job fails for a day, the 7d delta compares today to 8 days ago. We don't interpolate.
2. **Commits_30d is GitHub's own window.** We record GitHub's "commits in the last year" divided by timeframe — it's their calculation, not ours. It can include bot commits, merge commits, etc.
3. **No velocity normalization.** A project at 200K stars gaining 1K/week looks identical in absolute terms to a project at 5K stars gaining 1K/week, even though the latter is growing 40x faster in relative terms. We show absolute deltas, not percentages.
4. **Download deltas are monthly resolution.** PyPI/npm provide monthly aggregates, not daily. Our "30d delta" compares two monthly snapshots which may represent overlapping windows.

**What we'd change:** Add percentage-based momentum (delta / total * 100) alongside absolute deltas. Small projects gaining 50% in a week are more newsworthy than big projects gaining 0.5%.""",
    },
    {
        "topic": "tiers",
        "category": "metric",
        "title": "Project Tiers: T1-T4 Classification",
        "summary": "Projects are classified into tiers based on monthly downloads. T1 = foundational infrastructure, T4 = emerging experiments.",
        "detail": """## Project Tiers

**Computed in:** `mv_project_tier` materialized view, with manual override via `set_tier()`

**Thresholds (based on monthly downloads):**
- **T1 Foundational** (>10M downloads/mo): The load-bearing walls of AI. PyTorch, transformers, numpy-level dependencies.
- **T2 Major** (>100K downloads/mo): Widely adopted in production. LangChain, vLLM, Hugging Face libraries.
- **T3 Notable** (>10K downloads/mo): Significant projects with real users but not yet mainstream.
- **T4 Emerging** (<10K downloads/mo or no download data): New, niche, or binary-distributed projects.

**Why downloads, not stars?**
Stars measure attention. Downloads measure adoption. A T1 project is one that breaks thousands of CI pipelines if it ships a bad release. That's defined by dependency graphs, which correlate with downloads far better than with stars.

**Known limitations:**
1. **Binary projects are always T4.** Docker-distributed tools like Stable Diffusion WebUI, Ollama, or OpenClaw have zero package downloads regardless of their actual user base. This is a fundamental gap — we can't measure binary adoption.
2. **Download thresholds are arbitrary.** The 10M/100K/10K boundaries are editorial choices, not statistically derived. They roughly correspond to "PyTorch-class", "LangChain-class", and "notable" in the current AI ecosystem, but they'll need recalibrating as the ecosystem grows.
3. **No category adjustment.** 100K downloads/mo means different things in different categories. A data loading utility at 100K is middling; a vector database at 100K is market-leading.
4. **Manual overrides create inconsistency.** `set_tier()` lets editors override the computed tier, which means the same project can appear at different tiers depending on whether the override or the formula is newer.

**What we'd change:** Add category-relative tiers (percentile within category) alongside absolute tiers. A project at the 95th percentile of its category is T1-equivalent even if the category overall has lower download volumes.""",
    },
    {
        "topic": "lifecycle",
        "category": "metric",
        "title": "Lifecycle Stages: Emerging to Dormant",
        "summary": "Six-stage classification of project maturity based on downloads, commits, releases, and age.",
        "detail": """## Lifecycle Stages

**Computed in:** `mv_lifecycle` materialized view

**Stages and rules:**
1. **Emerging**: <1,000 downloads/mo OR first release within 90 days. Brand new or pre-adoption.
2. **Launching**: First release within 90 days AND >1,000 downloads/mo. The critical growth phase.
3. **Growing**: Active commits (>10 in 30d), positive star momentum, regular releases. Healthy and accelerating.
4. **Established**: >100,000 downloads/mo, regular maintenance. The steady state.
5. **Fading**: Commits declining (<5 in 30d), no recent releases (>90 days). Starting to lose momentum.
6. **Dormant**: No commits in 90+ days, no releases in 180+ days. Potentially abandoned.

**Design philosophy:** These stages describe engineering trajectory, not quality. A "fading" project might be perfectly stable and complete (sqlite doesn't need weekly releases). The lifecycle is descriptive, not prescriptive.

**Known limitations:**
1. **Single-maintainer projects look dormant during vacations.** A solo developer taking a month off will push a healthy project into "fading." We don't account for team size.
2. **Monorepo blindness.** Projects in monorepos (e.g. Hugging Face's `transformers` vs `tokenizers`) may share commit histories, making it hard to isolate per-project activity.
3. **Release cadence varies by type.** Frameworks release monthly; models release rarely. A model repo with one release is complete, not dormant.
4. **Binary projects may lack release data.** If releases are GitHub Releases (not PyPI uploads), we only capture them if `ingest_releases()` can parse them.
5. **No "mature" stage.** We should distinguish "established and actively maintained" from "established and in maintenance mode." Currently both are "established."

**What we'd change:** Add team size heuristic (from GitHub contributors), and add a "mature" stage for projects with high downloads + low but consistent commit activity (bug fixes, security patches, not feature development).""",
    },
    # -----------------------------------------------------------------------
    # TOOLS
    # -----------------------------------------------------------------------
    {
        "topic": "radar",
        "category": "tool",
        "title": "Radar: Early Detection for Untracked Breakout Projects",
        "summary": "Surfaces projects we're NOT tracking that are exploding in popularity. Combines candidate velocity, unmatched HN buzz, and fresh discoveries.",
        "detail": """## Radar

**Purpose:** Answer "what should I be paying attention to that I'm not tracking yet?"

**Three sections:**

### 1. VELOCITY ALERTS
Shows candidates with the biggest star acceleration since discovery. Sorted by absolute star delta (or by total stars if no velocity data yet).

**Data source:** `project_candidates` table, filtered to `status = 'pending'` with non-null stars.
**Algorithm:** Simple sort by `stars - stars_previous` descending. Shows top 10.

### 2. HN BUZZ (UNTRACKED)
Highest-engagement HN posts from the last 14 days that aren't matched to any tracked project. These represent discussions about projects or topics we're blind to.

**Data source:** `hn_posts` table where `project_id IS NULL`.
**Algorithm:** Sort by points descending, limit 10. No deduplication by project (multiple posts about the same tool will appear separately).

### 3. FRESH CANDIDATES
Most recently discovered candidates with their source context. Helps you see what the discovery pipeline found today.

**Data source:** `project_candidates` where `status = 'pending'`, ordered by `discovered_at DESC`.

### 4. NARRATIVES
Auto-generated one-liners summarizing the radar state:
- Candidate with highest velocity and computed daily rate
- Count + percentage of unmatched HN posts
- Auto-promoted projects from the past week

**Known limitations:**
1. **Velocity alerts require 24h baseline.** Candidates discovered today won't have velocity data until tomorrow's re-scoring run.
2. **HN buzz is keyword-dependent.** We only find HN posts matching our SEARCH_TERMS list. A viral AI project discussed using different terminology will be missed.
3. **No cross-signal correlation.** We don't automatically link a velocity alert for "clawdbot" to an HN post titled "Show HN: Clawdbot." A human needs to connect the dots.
4. **No scoring/ranking model.** We sort by raw metrics (stars, points) rather than a composite "interestingness" score. A 5K-star project gaining 4K stars in a day is more interesting than a 200K-star project gaining 5K, but the latter ranks higher.

**What we'd change:** Build a composite interestingness score: `(velocity_percentile * 0.4) + (hn_mentions * 0.3) + (recency * 0.3)` to surface the truly surprising signals rather than just the biggest absolute numbers.""",
    },
    {
        "topic": "auto_promotion",
        "category": "algorithm",
        "title": "Auto-Promotion: Automatic Candidate-to-Project Promotion",
        "summary": "Candidates crossing star thresholds are automatically promoted to tracked projects. Generous thresholds because false positives are cheap, false negatives mean missing the story.",
        "detail": """## Auto-Promotion

**Purpose:** Remove the human bottleneck from project discovery. When the ingest pipeline finds a candidate that's clearly significant, promote it immediately rather than waiting for a human to call `accept_candidate()`.

**Thresholds:**
- **>1,000 stars + HN source** = someone in the AI community posted it AND it has real traction
- **>5,000 stars from any source** = significant project regardless of how we found it

**Why these numbers?**
- At 1K stars, a project has ~500-2000 real users (rough rule of thumb). If it came from HN, there's editorial signal on top.
- At 5K stars, a project is in the top 0.1% of GitHub repos. Missing a 5K+ star AI project is worse than tracking one that turns out to be uninteresting.

**Cost asymmetry:**
- **False positive cost:** ~5 seconds. Set `is_active = false` or `set_tier(project, 4)`. The project sits quietly in the database doing nothing.
- **False negative cost:** We miss the next OpenClaw. By the time someone notices, the story is two weeks old and we've lost credibility as an intelligence source.

**Implementation details:**
1. Runs at the end of `ingest_candidate_velocity()`
2. Queries all pending candidates above thresholds
3. Generates slug from `github_repo` name
4. Skips if slug already exists in `projects` table (marks candidate as accepted)
5. Guesses category from primary language (Python → library, TypeScript → tool, etc.)
6. Sets `distribution_type = 'binary'` (most HN/trending discoveries are apps, not pip-installable)
7. Each promotion uses its own DB session/commit to avoid long transaction timeouts

**Known limitations:**
1. **Language → category is a rough heuristic.** A Python CLI tool gets classified as "library." The mapping doesn't understand what the project actually does.
2. **Slug collision risk.** Two different repos named "agent" would collide. We skip on collision, which means the second one gets silently ignored.
3. **No de-promotion.** Once promoted, a project stays tracked forever unless manually deactivated. A project that was hot for a week and then abandoned will linger in the database.
4. **5K threshold may be too low for non-AI projects.** Our HN search terms are broad enough to capture non-AI repos. A React component library at 6K stars is not relevant to AI intelligence.
5. **Binary distribution assumption.** We default to `distribution_type = 'binary'` but many auto-promoted projects are actually on PyPI/npm. This means their download stats won't be collected until someone manually sets the distribution type.

**What we'd change:** Add topic detection from GitHub repo topics/description. Filter candidates by AI-relevance before promotion. Add a "probation" period where promoted projects are tracked but flagged for review after 7 days.""",
    },
    {
        "topic": "trending",
        "category": "tool",
        "title": "Trending: Top Projects by Star Growth",
        "summary": "Shows top 20 projects sorted by star delta over a configurable window (7d or 30d). Uses mv_project_summary materialized view.",
        "detail": """## Trending

**What it shows:** Top 20 tracked projects ranked by absolute star growth over the selected window.

**Windows:**
- `7d`: Last 7 days of star growth (default)
- `30d`: Last 30 days of star growth

**Data source:** `mv_project_summary` materialized view, which aggregates data from `mv_momentum`, `mv_hype_ratio`, `mv_project_tier`, and `mv_lifecycle`.

**Algorithm:** Simple `ORDER BY stars_Xd_delta DESC NULLS LAST LIMIT 20`. No weighting, no normalization.

**Output includes per project:**
- Tier (T1-T4), lifecycle stage, category
- Total stars, 7d delta, 30d delta
- Monthly downloads, hype bucket

**Fallback behavior:** If materialized views don't exist, falls back to raw `github_snapshots` table (stars only, no deltas).

**Known limitations:**
1. **Absolute deltas favor large projects.** PyTorch gaining 2K stars/week always outranks a 500-star project gaining 400/week, even though the smaller project is growing 4x faster proportionally.
2. **Only shows tracked projects.** Untracked candidates (the ones that might be most interesting) don't appear here. Use `radar()` for those.
3. **No category normalization.** "Trending in vector databases" and "trending in frameworks" mean very different absolute numbers. There's no within-category ranking.
4. **Snapshot gaps create artifacts.** If GitHub ingest fails for 2 days, the 7d delta is actually a 5d delta, making everything look like it's slowing down.

**What we'd change:** Add percentage-based trending alongside absolute. Show rank change (was #5 last week, now #2). Add per-category trending.""",
    },
    {
        "topic": "movers",
        "category": "tool",
        "title": "Movers: Acceleration/Deceleration Detector",
        "summary": "Compares this window's star delta to the prior window's delta. Shows which projects are gaining or losing momentum.",
        "detail": """## Movers

**What it shows:** Projects where the rate of star growth is itself changing — accelerating (gaining momentum) or decelerating (losing momentum).

**Algorithm:**
1. Take 3 snapshots: today (rn=1), N days ago (rn=N+1), 2N days ago (rn=2N+1)
2. `current_delta = stars_today - stars_N_days_ago`
3. `prior_delta = stars_N_days_ago - stars_2N_days_ago`
4. `acceleration = current_delta - prior_delta`
5. Sort by acceleration (positive = accelerating, negative = decelerating)

**Minimum data requirement:** Need `2 * window` days of snapshot history. For 7d window, need 14+ days. For 30d window, need 60+ days.

**Two sections:**
- **ACCELERATING:** Projects where this period's growth exceeds the prior period's growth
- **DECELERATING:** Projects where growth has slowed relative to the prior period

**Known limitations:**
1. **Requires double the window in history.** A fresh PT-Edge deployment can't run movers() for at least 14 days.
2. **Acceleration != quality.** A project accelerating because of a controversy (security vulnerability, license change drama) will rank highly. The signal is directional, not qualitative.
3. **Mean reversion noise.** A project that had an unusually quiet week followed by a normal week looks like it's "accelerating." It's really just reverting to the mean.
4. **Binary comparison.** We compare exactly two windows. A more sophisticated approach would fit a trend line across multiple windows to detect sustained acceleration vs noise.

**What we'd change:** Add a 3-window trend (is acceleration itself accelerating?) and annotate likely causes (new release? HN post? conference talk?) using temporal correlation with our other data sources.""",
    },
    {
        "topic": "hype_check",
        "category": "tool",
        "title": "Hype Check: Stars vs Downloads Reality Check",
        "summary": "Deep dive into a single project's hype ratio with category context, multi-source download breakdown, and interpretation.",
        "detail": """## Hype Check

**What it shows:** For a specific project: stars, monthly downloads, hype ratio, bucket classification, download source breakdown, and category comparison.

**Data sources:**
- `mv_hype_ratio` for the project's ratio and bucket
- `mv_hype_ratio` category average for context
- `download_snapshots` for per-registry breakdown (PyPI, npm, conda-forge, etc.)

**Bucket interpretation:**
- **overhyped**: "This project has significantly more GitHub attention than real-world adoption. The star count may reflect demo curiosity, tutorial inclusion, or trending visibility rather than production usage."
- **balanced**: "Attention and adoption are roughly proportional. This is a healthy signal."
- **underrated**: "This project is used far more than its star count suggests. It's likely critical infrastructure that people depend on without starring."

**Multi-source download breakdown:** Shows downloads from each registry separately. A project with 5M PyPI downloads and 500K conda-forge downloads has different adoption patterns than one with all downloads from a single source.

**Known limitations:**
1. **All the hype_ratio limitations apply** (see `explain('hype_ratio')`).
2. **Category averages can be skewed by outliers.** If a category has one project with 100M downloads, the "average" hype ratio is meaningless for comparing smaller projects.
3. **No time series.** Shows current snapshot only. Is the project becoming more or less hyped over time? You'd need to query() the raw snapshots to find out.
4. **Download source may be incomplete.** We track PyPI, npm, and conda-forge. Projects distributed via Homebrew, Docker Hub, GitHub Releases, or apt/yum are invisible.

**What we'd change:** Add trend direction (ratio moving up/down over last 30 days). Add peer comparison (show 3-5 projects at similar scale in the same category).""",
    },
    {
        "topic": "market_map",
        "category": "tool",
        "title": "Market Map: Category Concentration and Power Law Analysis",
        "summary": "Shows which categories are winner-take-all, which labs dominate, and where downloads concentrate across the ecosystem.",
        "detail": """## Market Map

**Three sections:**

### Category Concentration
For each category: number of projects, total monthly downloads, the #1 project's name and market share, and the top-3 combined share. High top-1 share = winner-take-all market (e.g. PyTorch in frameworks). Low top-1 share = competitive/fragmented market.

### Power Law
Shows what percentage of total downloads come from the top 5, 10, and 20 projects. A steep power law (top 5 = 80%) means the AI ecosystem is concentrated in a few critical dependencies. A flat distribution means a healthier long tail.

### Lab Dominance
Aggregates stars, downloads, and commits by lab (Meta, Google, OpenAI, etc.). Shows which organizations are most active and most adopted. Independent/community projects are grouped separately.

### Key Narratives
Auto-generated observations:
- Biggest category leader and their market share
- Stars-downloads disconnect (high stars, zero downloads = binary distribution)
- Invisible infrastructure (high downloads, low stars)
- Lab output efficiency (downloads per project)
- High-interest low-adoption categories

**Known limitations:**
1. **Category assignment is editorial.** We assign categories manually. A project like LangChain could be "framework", "library", or "tool" depending on perspective. This changes concentration metrics significantly.
2. **Lab assignment misses affiliations.** An ex-Google engineer's personal project isn't tagged as Google, even if it's clearly Google-influenced. We only track official lab repos.
3. **Download totals across categories aren't comparable.** Frameworks have vastly more downloads than vector databases because they're lower in the dependency stack. Comparing category sizes is misleading.
4. **Power law analysis uses monthly downloads only.** Stars, commits, and community size would give different power law distributions.

**What we'd change:** Add time-series concentration tracking (is the power law getting steeper or flatter?). Add a "rising challengers" section showing projects that are gaining share within their category.""",
    },
    {
        "topic": "project_pulse",
        "category": "tool",
        "title": "Project Pulse: Everything About One Project",
        "summary": "Comprehensive single-project view combining GitHub stats, downloads, releases, HN discussion, tier, lifecycle stage, and hype analysis.",
        "detail": """## Project Pulse

**What it shows:** Everything we know about a single project in one view.

**Sections:**
1. **Overview:** Name, category, tier, lifecycle stage, lab affiliation, description
2. **GitHub Stats:** Stars, forks, open issues, contributors, commits (30d), last push date
3. **Momentum:** 7d and 30d star deltas with baseline indicators
4. **Downloads:** Monthly downloads from each source (PyPI, npm, conda-forge), with 30d delta
5. **Hype Analysis:** Hype ratio, bucket, category comparison
6. **Recent Releases:** Last 5 releases with dates
7. **HN Discussion:** Recent HN posts mentioning this project with points and comments

**Data sources:** Joins across `projects`, `github_snapshots`, `download_snapshots`, `releases`, `hn_posts`, and materialized views. Falls back to raw tables if views aren't available.

**Project matching:** Uses fuzzy matching — searches by slug, name, and GitHub repo name. If no exact match, suggests closest alternatives using edit distance.

**Known limitations:**
1. **Single snapshot per metric.** Shows the latest snapshot only, not history. For time series, use query() directly.
2. **HN matching is exact string match.** If an HN post mentions "HuggingFace" but the project name is "Hugging Face Transformers," it won't match. HN post matching happens at ingest time, not query time.
3. **Missing data shows as "n/a" not "0".** A project with no download data might have millions of users via binary distribution. Absence of data ≠ absence of usage.
4. **Release data depends on GitHub Releases.** Projects that don't use GitHub Releases (publish to PyPI only, or use a different changelog format) will show no release history.

**What we'd change:** Add sparklines for key metrics (mini ASCII charts of stars/downloads over last 30 days). Add "similar projects" section using category + scale matching.""",
    },
    {
        "topic": "lifecycle_map",
        "category": "tool",
        "title": "Lifecycle Map: Projects Grouped by Maturity Stage",
        "summary": "Visual overview of all projects organized by lifecycle stage (emerging → dormant), filterable by category and tier.",
        "detail": """## Lifecycle Map

**What it shows:** All tracked projects grouped into 6 lifecycle stages, showing their key vital signs.

**Per-project info:** Tier, name, category, stars, monthly downloads, commits (30d), releases (30d).

**Stage descriptions are opinionated.** We include editorial descriptions of what each stage means, which may not match how project maintainers see themselves. A "fading" label can feel harsh for a project that's simply complete and stable.

**Filtering:** Optional `category` and/or `tier` filters narrow the view. `lifecycle_map(category='framework')` shows only frameworks. `lifecycle_map(tier=1)` shows only foundational projects.

**Data source:** `mv_lifecycle` view joined with `mv_project_tier`.

**Known limitations:**
1. **All lifecycle stage limitations apply** (see `explain('lifecycle')`).
2. **No transition tracking.** We show current stage but not when projects moved between stages. Was this project "growing" last month and "fading" now? You'd have to query historical snapshots.
3. **Grouping hides nuance.** Two "established" projects might be very different — one actively innovating, one in pure maintenance mode.

**What we'd change:** Add stage transition arrows showing recent movements (e.g., "3 projects moved from growing → established this month"). Add a "watch list" for projects at stage boundaries.""",
    },
    {
        "topic": "compare",
        "category": "tool",
        "title": "Compare: Side-by-Side Project Comparison",
        "summary": "Compare 2-5 projects across all metrics in a standardized table format.",
        "detail": """## Compare

**What it shows:** Side-by-side comparison table for 2-5 projects across: stars, forks, monthly downloads, star momentum (7d/30d), hype ratio, commits (30d), tier, and lifecycle stage.

**Input:** Comma-separated project names or slugs. e.g., `compare('pytorch, tensorflow, jax')`

**Matching:** Each name is matched using the same fuzzy logic as project_pulse(). If a name doesn't match, it's listed as "not found" with suggestions.

**Algorithm:** Queries `mv_project_summary` for all matched projects in a single query, then formats into a comparison table.

**Known limitations:**
1. **Apples-to-oranges.** Comparing a T1 framework with a T4 emerging tool is technically possible but not very informative. No normalization is applied.
2. **Max 5 projects.** Formatting constraint — the table becomes unreadable beyond 5 columns. For broader comparison, use market_map() or query() directly.
3. **Missing data shows as dashes.** If one project has no download data and another does, the comparison can be misleading.
4. **No percentile context.** "100K downloads/mo" sounds like a lot until you compare it to PyTorch's 200M. There's no ecosystem percentile shown.

**What we'd change:** Add percentile ranks alongside absolute numbers. Add a "winner" indicator for each metric. Add historical trend direction (↑↓→) for each metric.""",
    },
    {
        "topic": "related",
        "category": "tool",
        "title": "Related: HN Co-occurrence Analysis",
        "summary": "Finds projects that are frequently discussed together on HN. Shows co-mention patterns from the last 90 days.",
        "detail": """## Related

**What it shows:** For a given project, which other tracked projects appear in HN discussions during the same time periods? This reveals competitive/complementary relationships.

**Algorithm:**
1. Find all HN posts matched to the target project
2. For each post, look at other posts within a 48-hour window
3. Count how often each other project appears in those nearby posts
4. Rank by co-occurrence frequency

**Why this works:** When HN discusses PyTorch, what else comes up? If JAX frequently appears in the same discussion clusters, they're competitively linked. If Hugging Face Transformers always appears alongside, they're complementarily linked.

**Known limitations:**
1. **HN matching is imperfect.** Many HN posts about a project don't get matched because the title doesn't contain the project name exactly.
2. **48-hour window is arbitrary.** Two unrelated viral posts happening to appear on the same day will show as "related."
3. **Popularity bias.** Projects with many HN mentions (like OpenAI) will appear as "related" to everything because they're always being discussed.
4. **No sentiment analysis.** "Project X is terrible compared to Y" and "Project X is the best alternative to Y" both count as co-occurrence.
5. **Only HN signal.** Reddit, Twitter/X, and blog discussions are not captured.

**What we'd change:** Add direction detection (is A mentioned as better/worse than B?). Add non-HN sources. Weight by comment depth (deep thread = stronger signal than passing mention).""",
    },
    # -----------------------------------------------------------------------
    # ALGORITHMS & DATA PIPELINE
    # -----------------------------------------------------------------------
    {
        "topic": "discovery_pipeline",
        "category": "algorithm",
        "title": "Project Discovery Pipeline: How We Find New Projects",
        "summary": "Two discovery channels feed the candidate pipeline: HN post URL extraction and GitHub trending topic search.",
        "detail": """## Project Discovery Pipeline

**Two discovery channels:**

### 1. HN Post Extraction (`ingest_hn` → `_extract_candidates`)
- Searches HN Algolia API for 18 AI-related terms every ingest cycle
- For each post URL, checks if it's a GitHub repo URL (regex: `github.com/owner/repo`)
- If the repo isn't already tracked or known as a candidate, fetches GitHub stats and inserts into `project_candidates`
- Source is tagged as `'hn'` with link to the HN discussion

**Search terms:** LLM, GPT, Claude, Anthropic, OpenAI, Gemini, AI model, machine learning, transformer model, fine-tuning, RAG, vector database, AI agent, AI assistant, personal AI, autonomous agent, MCP server, open source AI

### 2. GitHub Trending Topic Search (`ingest_trending`)
- Searches GitHub API for repos tagged with AI-related topics
- Topics: machine-learning, llm, ai, deep-learning, generative-ai, large-language-model, ai-agent, chatbot, autonomous-agent, mcp, rag, vector-database
- Filters to repos with >100 stars
- Source is tagged as `'trending'`

### Candidate → Project promotion
After discovery:
1. **Auto-promotion** (immediate): >1K stars + HN source, or >5K stars from any source
2. **Manual promotion**: `accept_candidate(id, category)` via MCP tool
3. **Velocity tracking**: `ingest_candidate_velocity` re-fetches star counts for all pending candidates to detect breakouts

**Known limitations:**
1. **Keyword dependency.** Both channels rely on fixed keyword lists. A breakthrough AI project using novel terminology won't be found until we add the right term.
2. **GitHub-only.** Projects hosted on GitLab, Bitbucket, or self-hosted git are invisible.
3. **English-centric.** HN searches and GitHub topics are English. Chinese AI projects (Qwen, DeepSeek) are only found via trending if they have English topics.
4. **HN URL extraction is simplistic.** Only direct GitHub URLs in the post URL field are captured. GitHub links mentioned in HN comments are not scanned.
5. **No deduplication across renames.** A project that renames its repo (Clawdbot → OpenClaw → Moltbot) may appear as three separate candidates.

**What we'd change:** Add RSS/Atom feed monitoring for key AI blogs. Scan HN comments (not just post URLs) for GitHub links. Add GitLab and Hugging Face Spaces as discovery sources. Use LLM to classify whether a candidate is AI-related before promoting.""",
    },
    {
        "topic": "data_pipeline",
        "category": "algorithm",
        "title": "Data Pipeline: Ingest → Views → Tools",
        "summary": "Seven ingest jobs run sequentially, followed by materialized view refresh. MCP tools query the views. Runs daily via cron.",
        "detail": """## Data Pipeline

**Architecture:** ETL (Extract-Transform-Load) with materialized views as the transform layer.

### Ingest Jobs (run sequentially via `run_all()`)
1. **`ingest_github()`** — Fetches stars, forks, open issues, contributors, commits_30d for all active projects. One GitHub API call per project. Rate-limited with semaphore (5 concurrent).
2. **`ingest_downloads()`** — Fetches monthly downloads from PyPI, npm, and conda-forge. Multi-source aggregation: takes the max across sources for each project.
3. **`ingest_huggingface()`** — Fetches download counts from Hugging Face Hub for model repos.
4. **`ingest_releases()`** — Fetches latest GitHub releases per project. Records title, tag, date.
5. **`ingest_hn()`** — Searches HN Algolia for AI-related posts. Extracts GitHub URLs for candidate discovery.
6. **`ingest_trending()`** — Searches GitHub for repos tagged with AI topics. Creates new candidates.
7. **`ingest_candidate_velocity()`** — Re-fetches star counts for pending candidates. Auto-promotes those above thresholds.

### Materialized Views (refreshed after ingest)
Dependency order:
1. `mv_momentum` — star and download deltas (7d, 30d)
2. `mv_hype_ratio` — stars/downloads ratio and bucket classification
3. `mv_lab_velocity` — per-lab aggregate metrics
4. `mv_project_tier` — T1-T4 based on download volume
5. `mv_lifecycle` — lifecycle stage classification (depends on mv_momentum)
6. `mv_project_summary` — joined summary of all views (depends on all above)

### MCP Tools
All 21 tools query the materialized views (with fallback to base tables). Tools never write data — they're read-only projections of the ingested data.

**Error handling:** Each ingest job is independent. If `ingest_github()` fails, the others still run. Partial failures are logged in `sync_log` with status 'partial'.

**Rate limiting:**
- GitHub API: semaphore(5) + 0.1s delay per request. With ~100 projects, GitHub ingest takes ~2 minutes.
- HN Algolia: semaphore(2) + 1.0s delay per term. 18 terms = ~30 seconds.
- GitHub Trending: semaphore(3) + 0.5s delay per topic.

**Known limitations:**
1. **Sequential execution.** Jobs run one after another. Total ingest time is ~5-10 minutes. Could be parallelized for jobs with independent data sources.
2. **No incremental updates.** Each job fetches all data from scratch. No "only fetch projects that changed" logic.
3. **Single GitHub token.** Rate-limited to 5,000 requests/hour. With 100+ tracked projects + 250+ candidates, we're approaching the limit per ingest cycle.
4. **No retry on transient failure.** If the GitHub API returns 502, we log the error and move on. No backoff/retry.
5. **View refresh is blocking.** `REFRESH MATERIALIZED VIEW` locks the view. Queries during refresh will either wait or return stale data (CONCURRENTLY refresh avoids this but requires unique indices).

**What we'd change:** Parallelize independent ingest jobs. Add exponential backoff on transient errors. Use conditional requests (If-Modified-Since) to skip unchanged repos. Monitor GitHub API rate limit remaining and throttle accordingly.""",
    },
    {
        "topic": "corrections_system",
        "category": "algorithm",
        "title": "Corrections System: Practitioner Pushback",
        "summary": "Users can submit corrections, upvote existing ones, and browse active corrections. Designed to let domain experts flag where PT-Edge is wrong.",
        "detail": """## Corrections System

**Purpose:** PT-Edge will be wrong about things. The corrections system lets practitioners push back with structured feedback that persists and accumulates.

**Three tools:**
1. **`submit_correction(topic, correction, context)`** — Create a new correction. Topic is the project or concept being corrected. Context is optional supporting evidence.
2. **`upvote_correction(id)`** — Confirm someone else's correction. Adds weight to the signal.
3. **`list_corrections(topic, status)`** — Browse existing corrections, optionally filtered by topic or status.

**Correction lifecycle:**
- `active` — Newly submitted, awaiting review or resolution
- `resolved` — Acknowledged and addressed by the PT-Edge team
- `rejected` — Reviewed and determined to be incorrect

**Design decisions:**
1. **No authentication.** Anyone using the MCP tools can submit corrections. This means spam is possible but the barrier to participation is zero.
2. **Topic-based, not project-based.** Corrections can be about anything — a metric definition, a category assignment, a lifecycle classification, a market narrative. Not just individual projects.
3. **Upvotes are simple counters.** No user tracking, no "who upvoted" log. One conversation could upvote the same correction multiple times.

**Known limitations:**
1. **No notification system.** When a correction is submitted, nobody is alerted. It sits in the database until someone queries list_corrections().
2. **No auto-correction.** A correction with 50 upvotes doesn't automatically change anything. A human still needs to act on it.
3. **Text-only.** Can't submit screenshots, links, or structured data as evidence. The context field is free text.
4. **No threading.** Can't reply to a correction or discuss it. Each correction is standalone.

**What we'd change:** Add webhook/email notifications for new corrections. Add a weekly digest of unresolved corrections. Allow corrections to link to specific metrics or snapshots.""",
    },
    {
        "topic": "whats_new",
        "category": "tool",
        "title": "What's New: Recent Activity Digest",
        "summary": "Shows new releases, trending projects, and HN discussion from the last N days. The daily briefing tool.",
        "detail": """## What's New

**Purpose:** Quick daily briefing. What happened in the AI project ecosystem in the last N days?

**Three sections:**
1. **Recent Releases:** All tracked project releases in the time window, sorted by date descending. Shows project name, version tag, release title, and date.
2. **Trending:** Top 10 projects by star growth in the window. Same data as trending() but limited to top 10.
3. **HN Discussion:** Top 10 highest-engagement HN posts in the window, showing title, points, comments, and matched project (if any).

**Default window:** 7 days. Configurable via `days` parameter.

**Data sources:** `releases`, `github_snapshots` (for star deltas), `hn_posts`.

**Known limitations:**
1. **Release detection depends on GitHub Releases.** Projects that only push to PyPI without creating a GitHub Release won't appear.
2. **HN posts are keyword-filtered at ingest time.** Posts not matching our search terms won't appear even if they're about AI.
3. **No prioritization.** A T1 project releasing a major version and a T4 project releasing a patch are shown with equal prominence.
4. **Window is calendar-based.** "Last 7 days" means exactly 7 * 24h, which may cut off a release at 7 days and 1 hour ago.

**What we'd change:** Add priority weighting by tier. Highlight major version bumps. Add a "significance score" combining tier, version jump magnitude, and HN engagement.""",
    },
    {
        "topic": "sniff_projects",
        "category": "tool",
        "title": "Sniff Projects: Browse Candidate Queue",
        "summary": "Lists pending project candidates with their GitHub stats and discovery source. Use accept_candidate() to promote or just let auto-promotion handle it.",
        "detail": """## Sniff Projects

**What it shows:** All pending candidates from the discovery pipeline, sorted by stars descending.

**Per candidate:** ID, name, stars, language, discovery source, source URL, description, discovered_at.

**Workflow:**
1. Discovery pipeline finds candidates via HN + trending
2. Auto-promotion handles candidates above thresholds (>1K stars HN, >5K any)
3. Remaining candidates sit in pending queue
4. `sniff_projects()` shows the queue
5. `accept_candidate(id, category)` manually promotes one
6. Or just wait — next ingest cycle may auto-promote if stars grow

**Known limitations:**
1. **Sorted by absolute stars.** The most interesting candidates (small but growing fast) may be buried below large but stale repos.
2. **No filtering.** Can't filter by language, source, or star range. Use query() for that.
3. **No reject mechanism.** You can accept but there's no "reject_candidate()" to permanently hide uninteresting ones. They stay in pending forever.
4. **Descriptions are truncated.** GitHub descriptions are capped at 500 characters.

**What we'd change:** Add sorting by velocity (fastest-growing first). Add reject/dismiss capability. Add language and source filters.""",
    },
    {
        "topic": "materialized_views",
        "category": "design",
        "title": "Why Materialized Views Instead of Live Queries",
        "summary": "Performance and consistency: pre-compute expensive joins and aggregations once, then query cheaply. Refresh daily after ingest.",
        "detail": """## Materialized Views Design Decision

**Why not just query the base tables directly?**

1. **Performance.** Joining `github_snapshots` × `download_snapshots` × `releases` × `hn_posts` for 100+ projects across 30+ days of snapshots is expensive. Materialized views pre-compute the joins once.

2. **Consistency.** Multiple tools showing the same project should show the same numbers. If trending() queries at 10:00:01 and project_pulse() queries at 10:00:02, and a new snapshot arrived at 10:00:01.5, they'd disagree. Views ensure all tools see the same snapshot.

3. **Derived metrics.** Hype ratio, lifecycle stage, and tier are computed from multiple signals. Embedding these calculations in every tool would be error-prone and hard to maintain.

**The 6 views:**
1. `mv_momentum` — star/download deltas (joins github_snapshots across dates)
2. `mv_hype_ratio` — stars/downloads ratio (joins github + download snapshots)
3. `mv_lab_velocity` — per-lab aggregates (groups projects by lab)
4. `mv_project_tier` — T1-T4 classification (from download volume)
5. `mv_lifecycle` — maturity stage (combines commits, releases, downloads, age)
6. `mv_project_summary` — master join of all above (the "one query to rule them all")

**Refresh strategy:** All views are refreshed after ingest, in dependency order. `mv_project_summary` is last because it depends on all others.

**Trade-off:** Views are stale between refreshes. If you ingest new data but don't refresh views, tools will show yesterday's numbers. This is intentional — we prefer consistency over immediate freshness.

**CONCURRENTLY vs regular refresh:** We try `REFRESH MATERIALIZED VIEW CONCURRENTLY` first (non-blocking, requires unique index) and fall back to regular refresh (briefly blocks reads).

**What we'd change:** Consider incremental materialized views (only recompute changed rows). Or switch to dbt for the transformation layer for better lineage tracking and testing.""",
    },
    {
        "topic": "data_sources",
        "category": "design",
        "title": "Data Sources and Their Limitations",
        "summary": "PT-Edge pulls from GitHub API, PyPI, npm, conda-forge, Hugging Face Hub, and HN Algolia. Each has specific blindnesses.",
        "detail": """## Data Sources

### GitHub API (REST v3)
- **What we get:** Stars, forks, open issues, watchers, subscribers, language, topics, description, default branch, created/updated/pushed dates
- **What we don't get:** Clones (requires push access), traffic (requires push access), contributor activity beyond count, dependency graph
- **Rate limit:** 5,000 requests/hour with token, 60/hour without
- **Freshness:** Real-time (within minutes of actual state)
- **Blindness:** GitHub only. GitLab, Bitbucket, self-hosted repos are invisible.

### PyPI (JSON API)
- **What we get:** Last 30 days of downloads (via pypistats API or BigQuery)
- **What we don't get:** Unique users, geographic distribution, Python version breakdown
- **Rate limit:** Generous, no token needed
- **Blindness:** Only Python packages. And only packages on PyPI — conda-only packages are missed.

### npm (Registry API)
- **What we get:** Weekly downloads, last 30 days
- **What we don't get:** Unique users, where downloads are coming from
- **Blindness:** Only JavaScript/TypeScript packages.

### conda-forge (GitHub stats)
- **What we get:** Download counts from conda-forge feedstock stats
- **Blindness:** Only conda-forge channel. Other Anaconda channels (defaults, bioconda) are missed.

### Hugging Face Hub API
- **What we get:** Model download counts, likes
- **What we don't get:** Inference API calls, Spaces usage
- **Blindness:** Only models. Datasets and Spaces have separate metrics we don't track.

### HN Algolia API
- **What we get:** Stories matching search terms, with points, comments, author, URL
- **What we don't get:** Comment content, vote patterns, user demographics
- **Rate limit:** No auth needed, reasonable limits
- **Blindness:** Only HN. Reddit, Twitter/X, Lobsters, and other communities are invisible.

### What's missing entirely
- **Docker Hub pulls** — Critical for binary-distributed AI tools
- **GitHub Discussions/Issues sentiment** — Are users happy or frustrated?
- **Academic citations** — Is the research community adopting it?
- **Job postings** — How many companies list the tool in job requirements?
- **Stack Overflow questions** — Volume and answer rate as adoption proxy

**What we'd change:** Add Docker Hub pull counts for binary projects. Add GitHub Discussions summary. Add academic citation counts from Semantic Scholar.""",
    },
    {
        "topic": "lab_pulse",
        "category": "tool",
        "title": "Lab Pulse: What a Research Lab is Shipping",
        "summary": "Aggregated view of all projects belonging to a specific lab (Meta, Google, OpenAI, etc.) with combined stats and recent activity.",
        "detail": """## Lab Pulse

**What it shows:** Aggregated stats for all projects belonging to a lab, plus per-project breakdown and recent releases.

**Sections:**
1. **Lab overview:** Total projects, combined stars, combined monthly downloads
2. **Projects by tier:** Grouped by T1-T4, showing key metrics per project
3. **Recent releases:** Latest releases across all lab projects
4. **HN buzz:** Recent HN posts mentioning the lab's projects

**Lab matching:** Fuzzy match on lab name or slug. e.g., `lab_pulse('meta')` or `lab_pulse('google deepmind')`.

**Data source:** `projects` filtered by `lab_id`, joined with materialized views.

**Known limitations:**
1. **Lab assignment is manual.** Projects must be explicitly assigned to a lab via the `lab_id` field. Community forks and unofficial projects aren't linked.
2. **Lab boundaries are fuzzy.** Is vLLM a "Berkeley" project or a "community" project? It started at Berkeley but has broad contributor base. We make editorial choices.
3. **No cross-lab collaboration tracking.** Joint projects (e.g., GGML/llama.cpp with contributors from multiple labs) are assigned to a single lab.
4. **No org-level GitHub stats.** We don't scrape GitHub organization pages for overall activity — just individual repo stats.

**What we'd change:** Add contributor diversity analysis (what percentage of commits come from non-lab contributors?). Track lab-level release cadence and compare across labs.""",
    },
    {
        "topic": "hype_landscape",
        "category": "tool",
        "title": "Hype Landscape: Bulk Overhyped vs Underrated Analysis",
        "summary": "Shows the most overhyped and most underrated projects across the ecosystem, ranked by hype ratio extremes.",
        "detail": """## Hype Landscape

**What it shows:** Two ranked lists — the projects with the highest hype ratios (most overhyped) and the lowest hype ratios (most underrated).

**Algorithm:** Queries `mv_hype_ratio`, sorts by ratio DESC for overhyped and ASC for underrated. Excludes projects with null or zero ratio.

**Optional filter:** `category` parameter to compare within a single category.

**Per-project info:** Name, category, hype ratio, stars, monthly downloads, hype bucket.

**Known limitations:**
1. **Extremes aren't always meaningful.** A project with 50K stars and 10 downloads has a ratio of 5,000 — but the 10 downloads might just mean it was published to PyPI yesterday. The ratio is mathematically correct but practically misleading for very new projects.
2. **Binary projects dominate the overhyped list.** Projects distributed as binaries (Docker, AppImage, etc.) have zero package downloads and thus infinite effective hype ratios. They're not "overhyped" — they just have different distribution channels.
3. **No threshold for meaningful comparison.** A project with 50 stars and 5,000 downloads has a ratio of 0.01 — technically "underrated" but really just obscure.

**What we'd change:** Add minimum star and download thresholds for inclusion (e.g., >1K stars and >1K downloads). Flag binary-distributed projects separately. Add a "most improved" section showing projects whose ratio changed the most in the last 30 days.""",
    },
]


def seed():
    """Insert or update all methodology entries."""
    with engine.connect() as conn:
        for entry in ENTRIES:
            conn.execute(text("""
                INSERT INTO methodology (topic, category, title, summary, detail, updated_at)
                VALUES (:topic, :category, :title, :summary, :detail, NOW())
                ON CONFLICT (topic)
                DO UPDATE SET
                    category = EXCLUDED.category,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    detail = EXCLUDED.detail,
                    updated_at = NOW()
            """), entry)
        conn.commit()
    print(f"Seeded {len(ENTRIES)} methodology entries")


async def seed_with_embeddings():
    """Seed methodology entries and generate embeddings if API key is set."""
    seed()

    from app.embeddings import is_enabled
    if not is_enabled():
        print("OPENAI_API_KEY not set — skipping embedding generation.")
        return

    from app.backfill_embeddings import backfill_methodology
    count = await backfill_methodology(force=True)
    print(f"Generated embeddings for {count} methodology entries.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(seed_with_embeddings())
