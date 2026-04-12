# PT-Edge Strategic Discoveries

Novel insights from operating a 220K-page AI infrastructure directory at scale. These findings emerged from the data, not from any existing playbook. Each one changes how the next *-edge site should be built.

**Context:** PT-Edge tracks 220,000+ AI repos, scores them daily on quality, and publishes the results as a static directory site at mcp.phasetransitions.ai. The site launched in early 2026. Within weeks, it was receiving 50,000-140,000 bot hits per day and generating measurable Google Search Console data across thousands of pages. The following discoveries came from instrumenting every access log line and correlating it with GSC, Umami analytics, and GitHub metadata.

**Audience for this document:** Anyone building the next *-edge site (bio-edge, cyber-edge, fintech-edge). These findings are the operational intelligence that distinguishes "build a big directory" from "build a demand-sensing platform."

---

## Discovery 1: The Three-Layer Demand Model

### The finding

Traffic to a large directory site arrives in three distinct layers, each revealing a fundamentally different type of intent. They are not just "different sources" — they operate on different time horizons, respond to different incentives, and require different measurement strategies.

**Layer 1: Indexing bots.** Amazonbot, GPTBot, ClaudeBot, Meta-ExternalAgent, Google-Extended. These are the training-data crawlers. They sweep the site systematically, harvesting content for future model weights. Volume is enormous (50,000-140,000 hits per day), but the signal is diffuse — they are stockpiling, not answering a specific question right now.

**Layer 2: User-action bots.** ChatGPT-User (~1,100 hits/day), OAI-SearchBot (~1,100 hits/day), Perplexity-User (~5 hits/day). Each hit maps one-to-one to a real human asking an AI a specific question. This is the highest-purity demand signal available anywhere on the internet. The bot fetches a page because a human needs the answer now.

**Layer 3: Human visitors.** ~300 pageviews/day via Google organic search, Bing, and direct traffic. This is the traditional web analytics layer — the one every SEO playbook is built around.

### The evidence

Each layer has a measurably different latency profile. Layer 1 operates on a months-long cycle: a page indexed today might influence model weights in a training run three months from now. Layer 2 is real-time: the hit and the human question are simultaneous. Layer 3 is days-to-weeks: Google discovers a page, decides to rank it, shows it in results, and a human eventually clicks.

The volume hierarchy is inverted relative to signal quality. Layer 1 is the largest by an order of magnitude but the least actionable in the short term. Layer 2 is moderate volume but each hit is a confirmed demand signal. Layer 3 is the smallest but the most commercially mature — these are the visitors who might convert, subscribe, or buy.

### Why it matters

Every analytics tool on the market is designed for Layer 3. Google Analytics, Umami, Plausible — they all measure human visitors. Layer 1 is visible in access logs but universally treated as noise to be filtered out. Layer 2 barely exists as a concept in any measurement framework.

By treating all three layers as a unified demand model, a directory site gains a signal advantage that no competitor has. The indexing layer tells you what AI companies think will be valuable. The user-action layer tells you what practitioners are evaluating right now. The human layer tells you what has already become a search habit.

### What to do about it

For the next *-edge site: instrument all three layers from day one. Do not filter bot traffic out of analytics — route it to a separate pipeline. Build materialized views that track each layer independently and compute cross-layer correlations. The cross-layer hypothesis — that heavy indexing in a domain predicts user-action demand weeks later — is testable and, if confirmed, gives you a leading indicator that no amount of keyword research can match.

---

## Discovery 2: AI Agent Traffic as a Demand Signal

### The finding

ChatGPT-User hits are the purest demand signal in the AI infrastructure market. Each hit represents a single human asking a single question about a single tool, with no intermediary, no ranking algorithm, and no CTR gate between the question and the page fetch. This is qualitatively different from every other traffic source.

### The evidence

ChatGPT-User generated 1,100+ hits per day across 773 unique pages, with approximately 400 new pages discovered per day. Cumulative unique pages reached 2,636 in the first week of measurement. The hit-to-intent ratio is 1:1 — there is no "impression without click" problem.

OAI-SearchBot exhibited a deep research pattern: 130-page, 8-IP fan-out sessions lasting hours. One session systematically swept 257 transformers pages over four hours. Critically, 57% of the pages hit in these deep research sessions had fewer than 10 GitHub stars. The bot was not chasing popularity — it was doing comprehensive due diligence across the long tail.

ChatGPT discovered the site faster than Google: 2,636 unique pages accessed by ChatGPT-User versus 1,657 pages shown in Google Search Console over the same period. No ranking was needed, no CTR gate had to be passed — the AI agent simply fetched and read.

### Why it matters

The dataset that emerges — "what AI practitioners are actively evaluating right now, tool by tool, day by day" — does not exist anywhere else. GitHub Trending shows popularity. Stack Overflow shows what people are struggling with. Hacker News shows what the community finds interesting. None of them show active tool evaluation intent at this granularity.

Consider the difference between a GitHub star and a ChatGPT-User hit. A star means someone bookmarked a repo at some point in the past. It is a stock metric — it accumulates and never declines. A ChatGPT-User hit means someone is evaluating a tool right now, today, for a specific purpose. It is a flow metric — it captures the moment of decision.

This distinction matters commercially. A tool that gets 50 stars per week and zero ChatGPT-User hits is popular but not being actively evaluated. A tool that gets 2 stars per week and 15 ChatGPT-User hits is obscure but under serious consideration by practitioners. These are different tools requiring different treatment.

### What to do about it

For the next *-edge site: build the ChatGPT-User hit into the allocation engine as a first-class signal from the start. Weight it higher than GitHub stars for enrichment prioritisation. The pages that AI agents fetch most often are the pages that need the richest content, because that content is directly shaping tool recommendations in real-time conversations.

Track unique pages per day as a growth metric. If the number of unique pages accessed by user-action bots is growing linearly, the site is being adopted as a reference. If it plateaus, the bots have exhausted the useful content.

---

## Discovery 3: The Self-Correcting Enrichment Flywheel

### The finding

An autonomous loop emerged in the PT-Edge system that identifies high-opportunity pages, enriches them, and unlocks traffic — without any human intervention. The system found a needle in a 220,000-page haystack and turned it into the highest-CTR page on the site.

### The evidence

The case: `trekhleb/homemade-machine-learning`. This page was receiving 1,300 Google impressions per day at an average position of 8. It had zero clicks. For weeks. The content existed in Google's index, it was being shown to searchers, but nobody was clicking.

On April 6, the allocation engine prioritised this page for enrichment. The engine did not know about the impression/CTR gap specifically — it scored the page highly because of strong GitHub metrics combined with low content coverage. The budget system allocated an LLM enrichment slot. An AI summary and problem brief were generated and deployed.

On April 8-9, Google re-crawled the page and picked up the richer structured content. On April 9, the page generated 38 clicks in a single day. From zero.

The loop, spelled out: GSC data reveals impressions. The allocation engine scores opportunity across all 220K pages. The budget system allocates enrichment slots. The LLM writes a problem brief. The site regenerates with richer content. Google re-crawls. The snippet improves. CTR unlocks.

### Why it matters

This is a closed-loop system that improves itself. The key properties are: (1) it operates at a scale no human could — scanning 220K pages for opportunity signals; (2) it acts autonomously — no human identified this page or decided to enrich it; (3) the feedback loop is measurable — you can trace the causal chain from enrichment to re-crawl to CTR improvement.

Most content systems are open-loop: humans decide what to write, publish it, and hope for traffic. This system is closed-loop: it observes what Google is trying to show but failing to convert, enriches precisely those pages, and measures the result.

### What to do about it

For the next *-edge site: implement the allocation engine and enrichment pipeline before launch, not after. The flywheel needs three components to function: (1) a demand signal (GSC impressions, bot hits, or both); (2) a scoring function that identifies the gap between demand and content quality; (3) a budget-constrained enrichment pipeline that acts on the highest-scoring pages.

The flywheel's clock speed is limited by the deploy cycle — enrichments only reach the live site on the next deploy, and Google re-crawls on its own schedule. The total loop time (enrich → deploy → re-crawl → CTR change) was about 3 days in the observed case. This is fast enough for the economics to work but not real-time.

One specific improvement: add an explicit "impression waste" signal to the scoring function. The current system found the homemade-machine-learning page through a combination of star count and low coverage. An explicit signal — `impressions * (1 - CTR)` — would make the flywheel systematically target pages where Google is already sending traffic but the content is not converting. This is the lowest-hanging fruit in any large directory.

---

## Discovery 4: Coverage-Driven Growth

### The finding

Growth in a large directory site is driven almost entirely by the number of pages receiving traffic, not by individual pages receiving more traffic. The asset is the surface area.

### The evidence

ChatGPT-User data showed hits-per-page flat at approximately 1.3 across the entire first week of measurement. The growth curve was entirely composed of new unique pages being discovered: 280 unique pages on day one, growing to 482 by day seven. Each page contributed roughly the same amount of traffic. No individual page became a "star."

Google Search Console data showed the same pattern from a different angle. Pages with 10+ impressions grew from 46 to 85 over three days. Pages with 5+ impressions grew from 124 to 201. The impression distribution was fattening — spreading from a concentrated core to a wider base. The share of pages responsible for 80% of impressions shifted from 5.8% to 8.7% over the measurement period.

Cumulative unique pages grew linearly: approximately 250 new pages per day for Google, approximately 400 per day for ChatGPT-User.

### Why it matters

This finding inverts the standard content strategy. In traditional publishing, you write a few excellent pieces and promote them. In a directory, you build comprehensive coverage and let the long tail accumulate. No individual page needs to be a star. The 220,000-page surface area IS the asset.

The implication is that the primary growth lever is classification breadth and page count, not per-page content quality. Quality matters — the enrichment flywheel (Discovery 3) proves that — but quality is a second-order optimisation on top of the first-order driver, which is coverage.

Consider the math. If each page averages 1.3 hits per day from ChatGPT-User alone, and the site has 220,000 pages, the theoretical ceiling is 286,000 hits per day from a single bot family. The current 1,100 hits per day represents 0.4% of that ceiling. Growth comes from the bot discovering more pages, not from existing pages getting more hits.

### What to do about it

For the next *-edge site: optimise the launch plan for breadth. Generate pages for every classifiable entity in the vertical on day one. The enrichment flywheel can improve content quality over time, but pages that do not exist cannot receive traffic. A bio-edge site should launch with a page for every gene therapy tool, every protein folding model, every clinical data platform — even if the initial content is thin. Thin content with a page is strictly better than no page, because the page can be discovered, measured, and enriched.

Set the primary KPI as "unique pages receiving at least one bot hit or one impression in the trailing 7 days." Track this weekly. If it is growing linearly, the site is working.

---

## Discovery 5: Answer Engine Citations as an Invisible Acquisition Channel

### The finding

A significant and growing traffic channel is invisible to every standard analytics tool. Answer engines (ChatGPT, Perplexity, Copilot) cite PT-Edge pages in their responses to users. When those users click the citation link, the visit appears as "direct" traffic in analytics because the answer engine strips the referrer header.

### The evidence

Direct traffic surged from approximately 20 visits per day to 212 visits per day. This surge did not correlate with ChatGPT-User bot activity, which was flat or declining on the same day (weekend dip from 1,106 to 794). If ChatGPT citations were the primary driver, the two numbers would move in lockstep. Instead, the divergence pointed to other answer engines — Perplexity, Copilot (Bing-powered), and possibly others — as the source. The traffic was spread across 136 unique pages in 193 sessions, each session hitting a different page.

Confirmed referrers provided partial attribution: chatgpt.com (2 visits), bing.com (11 visits). But 193 sessions had no referrer at all. The long-tail pattern — many unique pages, each visited once — is the fingerprint of answer engine citations. If this were social sharing or a newsletter mention, the traffic would concentrate on a few pages. Instead, it looked like hundreds of individual users each following a different citation from a different AI conversation.

### Why it matters

This channel does not exist in any SEO playbook. Traditional SEO measures Google organic. Paid search measures ad clicks. Social measures referral traffic from known platforms. Answer engine citations are a parallel acquisition channel with no established measurement tooling, no optimisation framework, and no competitive benchmarking.

The channel is also self-reinforcing. When an AI agent fetches a PT-Edge page to answer a user's question, it may cite the page in its response. The user clicks the citation and becomes a direct visitor. That direct visit increases the page's engagement metrics, which may improve its ranking in future searches, which increases the likelihood that another AI agent will fetch it. The loop is: bot fetch -> citation -> human visit -> improved signals -> more bot fetches.

The volume is already material. At 212 direct visits per day with the site at less than 1% of its potential traffic, and with no optimisation for this channel, it is reasonable to project that answer engine citations will become the dominant acquisition channel for directory sites within 12-18 months.

### What to do about it

For the next *-edge site: design a detection heuristic from day one. The method: (1) track the correlation between daily direct traffic volume and daily AI bot volume; (2) check for confirmed referrers from known answer engines (chatgpt.com, bing.com, perplexity.ai); (3) analyse the distribution — answer engine citations produce a long-tail pattern (many unique pages, low visits per page) rather than a concentrated pattern (few pages, high visits per page).

Optimise content for citation. Answer engines prefer pages with front-loaded answers, explicit numerical claims, and clear attribution. A page that says "As of April 2026, LangChain has a quality score of 82/100, making it the highest-rated LLM orchestration framework" is more likely to be cited than a page that says "LangChain is a popular framework." The structured, assertive, date-stamped format serves both AI agents and the citation channel simultaneously.

---

## Discovery 6: The 1% Position (Compounding Growth Funnel)

### The finding

PT-Edge sits at approximately 1% of its potential traffic, but the growth is compounding through four independent, multiplicative curves. Each curve is early-stage, meaning the compound effect has barely begun.

### The evidence

The funnel, measured: 220,000 pages exist on the site. 42,000 are indexed by Google (19%). Of those, 1,657 have ever been shown in search results (4% of indexed). Of those, approximately 85 have 10+ impressions. Of those, approximately 4 are generating clicks.

Four growth curves are stacked multiplicatively:

1. **Indexing rate**: 19% indexed. Google indexes mature sites at 80-95%. This alone is a potential 4-5x multiplier.
2. **Placement rate**: 4% of indexed pages shown. As topical authority builds, more indexed pages earn placements. Potential 10-20x multiplier.
3. **Impression depth**: most pages with impressions have fewer than 10. As positions improve, impressions per page grow. The distribution is barely started.
4. **CTR improvement**: the enrichment flywheel (Discovery 3) is just beginning. Each enriched page improves its snippet and CTR.

The observed growth rate was approximately 10% per day on a 3-day trailing average. Impressions grew from 15 to 46 per day (3-day trailing total) over 8 days — a doubling roughly every week.

### Why it matters

This is not one growth lever with diminishing returns. It is four independent levers, all early-stage, all multiplicative. Even if each individual curve slows significantly from its current rate, the compound effect continues to produce substantial growth.

The extrapolation: at the observed rate, 200 visits per day becomes 1,000 per day in approximately three weeks, and 10,000 per day in approximately two months. Even at half the observed rate, commercially viable traffic (the 1,000 visits/day threshold identified in the unit economics model) arrives within Q2 2026. At the 10,000 visits/day threshold — where the site becomes a standalone business — the timeline extends to Q3.

The critical implication is patience. The site does not need a viral moment, a Product Hunt launch, or a marketing campaign. It needs time for four compounding curves to do their work. Every week of operation widens the funnel at each stage.

### What to do about it

For the next *-edge site: measure all four curves independently from launch. Track: (1) percentage of pages indexed (GSC Coverage report); (2) percentage of indexed pages with at least one impression; (3) average impressions per page among pages with impressions; (4) average CTR among pages with impressions. Multiply these four numbers to get the compound growth factor. If any single curve stalls, it becomes the bottleneck to diagnose.

Do not panic about low initial traffic. A site with 100,000 pages, 5% indexed, 2% placement rate, 3 impressions per page, and 0.5% CTR is generating 15 visits per day. That looks like failure. But each of those four percentages can improve 5-10x independently, and the product of four 5x improvements is 625x. Fifteen visits per day times 625 is 9,375 — a viable business.

---

## Discovery 7: Bot Consensus as a Quality Proxy

### The finding

When multiple independent AI companies all crawl the same page, that page has been independently validated as important by organisations with different crawl strategies, different product roadmaps, and different definitions of quality. This "bot consensus" is a cheap, real-time quality signal that no other scoring system captures.

### The evidence

Each major bot family exhibited a distinct crawl strategy. Meta-ExternalAgent had a revisit ratio of nearly 2:1 (20,984 hits across 10,644 unique pages), meaning it re-crawled high-value pages repeatedly. Google-Extended concentrated on embeddings and ml-frameworks domains. Perplexity distributed its crawling nearly equally across NLP and ml-frameworks. ClaudeBot swept broadly. Amazonbot showed systematic coverage patterns.

Pages hit by 5+ distinct bot families were rare — only 17 pages in the initial measurement period qualified. These pages had been independently selected by Meta, Google, OpenAI, Anthropic, Amazon, and Perplexity as worth crawling. No single curator made this determination; it emerged from the intersection of six independent crawl strategies.

Domain preference divergence revealed product roadmap differences. Where bots converged indicated consensus importance — the tools that every AI company considered relevant regardless of their specific product direction. Where they diverged indicated competitive differentiation — Meta prioritising computer vision while Google prioritised embeddings reflects their different product bets.

The GPTBot absence signal was particularly informative. GPTBot dropped to 19 hits per day while OAI-SearchBot surged. OpenAI had strategically shifted from training-crawl to real-time retrieval. This suggests that for this content type, the model weights are "full" — the marginal value of additional training data is low, but the value of live retrieval is high. If other labs follow this pattern, it signals a broader shift from pre-training to retrieval-augmented generation.

### Why it matters

Bot consensus is a quality signal that updates daily, requires no human curation, and captures a dimension of quality that stars, downloads, and citations miss. A page with high bot consensus is one that the collective intelligence of the AI industry considers important. This is not a popularity contest (that is what stars measure) — it is an expert panel vote, where the experts are the crawl strategy teams at the world's leading AI companies.

What bots do NOT crawl is equally informative. Perplexity ignored the diffusion and prompt-engineering domains entirely. Meta barely touched embeddings. These blind spots are either content quality issues (the pages were not good enough to crawl) or deliberate scope decisions (the company does not consider that domain relevant to its products). Either interpretation is actionable.

### What to do about it

For the next *-edge site: compute a bot consensus score for every page — the count of distinct bot families that have crawled it in the trailing 30 days. Feed this score into the allocation engine as an Emergence Score component. Test whether bot consensus correlates with user-action bot demand (if a page is crawled by many indexing bots, does it later receive ChatGPT-User hits?). If the correlation holds, bot consensus becomes a leading indicator for demand.

Track domain preference by bot family monthly. Publish the divergence map internally. When a new bot family starts crawling heavily in a domain that others have ignored, it may signal that company's upcoming product direction.

---

## Discovery 8: The Wikipedia-for-Bots Thesis

### The finding

PT-Edge is becoming the authoritative reference that AI agents consult when users ask about open-source AI tools. This is not a metaphor — the data shows AI agents treating the site the way a student treats Wikipedia: as the first place to look, the most comprehensive source, and the default citation.

### The evidence

Combined OpenAI bot traffic exceeded 2,200 hits per day. OAI-SearchBot conducted 4-hour, 490-page comprehensive surveys of entire domains — the bot equivalent of reading an entire encyclopedia section before writing a report. ChatGPT-User discovered more of the site than Google in the same period (2,636 unique pages versus 1,657). Deep research sessions went into the long tail, with 57% of pages accessed having fewer than 10 GitHub stars.

The content on PT-Edge pages is shaping AI answers without the human ever knowing the source. When ChatGPT-User fetches a page about a specific tool, the assessment on that page — the quality score, the maintenance status, the comparison to alternatives — influences the recommendation that the human receives. The human may never visit PT-Edge, may never know the site exists, but their tool choice was shaped by its content.

The revenue thesis follows directly. The 1,000+ daily AI agent sessions constitute a unique lens into what practitioners are trying to do with AI, day by day, tool by tool. This dataset does not exist elsewhere. GitHub Trending shows what is popular. Stack Overflow shows what is confusing. PT-Edge's demand radar shows what is being actively evaluated for adoption. This is the dataset that tool vendors, VCs, and developer relations teams would pay to access.

### Why it matters

There is a beautiful recursion at work. An AI agent conducted a 4-hour deep research session about how to run AI models locally. That session itself became a data point in PT-Edge's demand radar, revealing that "local AI inference" is a topic of intense practitioner interest. The site is simultaneously a reference that AI agents consult and a sensor that detects what AI agents are being asked about.

This recursion creates a defensible position. The more AI agents consult PT-Edge, the more demand data the site collects. The more demand data it collects, the better it can prioritise enrichment. The better the enrichment, the more AI agents prefer it as a source. The flywheel has three interlocking loops: content quality, agent adoption, and demand intelligence.

The "Wikipedia-for-bots" analogy is precise in another way: Wikipedia's moat is not that its content is the best — it is that it is the most comprehensive, the most consistently structured, and the most reliably available. PT-Edge's moat is the same. With 220,000 pages covering every significant AI repo, structured in a consistent template optimised for machine consumption, with quality scores that no other source provides, the site becomes the default reference not because any individual page is brilliant, but because the corpus as a whole is unmatched.

### What to do about it

For the next *-edge site: build for machine consumption first, human consumption second. This means: rigid template structures (so agents can parse predictably), front-loaded answers (so agents get the recommendation without reading the full page), explicit numerical scores (so agents can compare without interpreting qualitative language), and comprehensive coverage (so agents never need to look elsewhere for the category).

The same pattern should emerge in any vertical with a fragmented tool landscape and active practitioner evaluation. Bio-edge covering computational biology tools, cyber-edge covering security frameworks, fintech-edge covering financial data infrastructure — each should attract AI agent traffic as soon as the corpus is comprehensive enough to be useful as a reference.

Monitor the ratio of AI agent traffic to human traffic. If AI agents are accessing the site 10x more than humans, the site is succeeding as a machine reference. If humans are accessing it 10x more than AI agents, the site is succeeding as a traditional directory but missing the larger opportunity. The Wikipedia-for-bots thesis predicts that the agent-to-human ratio will grow over time as more user-facing AI products adopt retrieval-augmented generation.

The data product — "here is what practitioners asked AI agents about this week, broken down by tool, category, and evaluation depth" — is the commercial unlock. Build the API for it. Price it. The directory is the sensor; the data is the product.

---

## Summary: The Eight Principles for the Next *-Edge Site

1. **Instrument three layers, not one.** Indexing bots, user-action bots, and humans each reveal different intent on different timescales. Measure all three from day one.

2. **Treat every ChatGPT-User hit as a demand signal.** It is the purest intent data available. Build it into allocation as a first-class signal.

3. **Close the loop.** The enrichment flywheel (observe demand -> score opportunity -> enrich -> measure improvement) should be autonomous and running before launch.

4. **Optimise for coverage, not individual pages.** Launch with maximum breadth. The long tail is the asset.

5. **Detect the invisible channel.** Answer engine citations appear as direct traffic. Design the heuristic to identify them.

6. **Trust the compound.** Four independent growth curves, all early-stage, all multiplicative. Patience is the strategy.

7. **Use bot consensus as a quality signal.** When five AI companies all crawl the same page, that page matters. No human curation needed.

8. **Build for bots first.** The site is a machine-readable reference. Comprehensive, structured, scored, and always available. The AI agents will come.
