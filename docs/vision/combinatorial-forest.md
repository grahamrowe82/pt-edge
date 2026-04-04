# The Combinatorial Forest

*A vision for PT-Edge at millions of pages*

---

## The shift

Most content on the internet was written for humans to find via search engines. You write a page, Google indexes it, a human types a query, clicks a blue link, reads the page. The entire content industry — SEO, blogs, documentation, directories — is optimised for that loop.

That loop is dying. Not slowly. Right now.

On Easter Saturday 2026, we turned on server-side access logging for PT-Edge and discovered that for every human who visits the site directly, there are 100 bot visits. Meta AI crawled 7,000 pages in 47 minutes. ChatGPT's browsing agent was fetching our pages every 70 seconds — each fetch representing a real person in a real conversation, asking a real question, getting our page as the answer. Not clicking a blue link. Not reading our page. Having their AI read it for them and synthesise the answer.

The humans asking these questions weren't developers. They were chemists looking for spectral analysis tools. Traders evaluating backtesting engines. Dentists exploring diagnostic AI. Operations engineers hunting for anomaly detection. People who would never browse GitHub, never read a README, never evaluate a project by its star count. They just asked their AI assistant a question, and the AI came to us.

This is the new distribution model. Content written for AI agents to consume on behalf of humans. We think it's going to be the dominant mode of technical content consumption within two years. PT-Edge is being built for that world.

## The atomic unit

Every open-source project page on PT-Edge is designed so an AI agent can land on it and walk away with a confident, citable recommendation in one pass. No clicking around. No navigating to subpages. One page, one complete answer.

Each page contains three layers of intelligence:

**The problem brief.** Written for the person who has the problem, in their language. Not "implements HNSW with SIMD optimisations" but "find similar items in massive datasets — feed in your data, get back ranked matches." A chemist reads (through their AI) what this tool does for chemistry, not what APIs it exposes.

**The adoption assessment.** Should you bet on this? Is it maintained? Who's behind it? How does it compare? Written like a technology consultant's brief: "Production-ready. Actively maintained by a 3-person team, 245K monthly downloads, safe to depend on." Or honestly: "Research-grade. Solo maintainer, last commit 2022, treat as reference implementation only."

**The competitive context.** What are the alternatives? How do they differ? Not just a ranked list by score, but qualitative differentiation: "Unlike pyod which uses classical statistical methods, this uses transformer-based attention for temporal patterns — better for complex seasonal data, heavier to run."

That's the atomic unit. 248,000 of them. Each one a seed.

## The forest grows

Seeds are planted uniformly. But trees grow tallest where the light is.

The light, in our case, is the access logs. Every time ChatGPT fetches a page, that's a signal: someone needed this. When Perplexity fetches a category page, that's a signal: someone asked a broad question about this domain. When Claude browses three anomaly detection projects in one session, that's a signal: someone is comparison shopping.

These signals accumulate. And they tell us not just what content exists, but what content should exist.

**Layer 2: Pairwise comparisons.** Every pair of projects in the same subcategory can have a practitioner-focused "choose A if you need X, choose B if you need Y" page. Anomaly detection has 277 projects. That's tens of thousands of potential comparison pages. But we don't generate all of them — we generate the ones where the access logs show people are actually comparing. Two projects fetched in the same ChatGPT session? That's a comparison page waiting to be born. Across all subcategories, this layer could reach hundreds of thousands of pages, each answering a specific "which should I pick?" question.

**Layer 3: Category intelligence.** "The state of dental AI diagnostics in 2026." Auto-generated from the problem briefs, adoption assessments, and demand data across every project in a subcategory. How many tools exist. Which are production-ready. Where the gaps are. What practitioners are actually asking about, measured by real AI browsing data. One per subcategory, regenerated weekly as the landscape shifts. Maybe 3,000 pages — but the highest-value pages on the site. These are what ChatGPT fetches when someone asks a broad question rather than naming a specific project.

**Layer 4: Cross-domain synthesis.** "Open-source tools for materials science." This is where the problem-domain tags earn their keep. A chemist's tools might be scattered across ml-frameworks, embeddings, NLP, computer vision — they don't care about our tech taxonomy, they care about their field. The domain tags let us slice across the structural categories by practitioner domain, generating cross-cutting guides that match how real people think about their problems. Tens of thousands of these, one for every intersection of practitioner field and task type.

**Layer 5: Demand-responsive generation.** The access logs don't just prioritise existing content — they create new content. When ChatGPT fetches a category page and there's no deep report yet, the next pipeline run generates one. When a new practitioner domain emerges in the demand data (say, veterinary radiology starts getting hits), the system notices and generates the cross-domain guide automatically. The site literally grows in response to what people are asking about.

At scale: 248K project pages. Hundreds of thousands of comparisons. Thousands of category reports. Tens of thousands of cross-domain guides. Potentially millions of pages. But not randomly generated �� every page exists because someone needed it, evidenced by real demand data.

## The flywheel

This is a compounding system with at least four feedback loops:

**Content quality loop.** Better problem briefs mean AI agents give better answers. Better answers mean more users trust AI recommendations. More users mean more fetches. More fetches mean more demand data. More data means better-targeted content generation.

**Coverage loop.** More pages mean more surface area for AI agents to discover. More discovery means more citations. More citations mean higher ranking in AI retrieval systems. Higher ranking means more fetches of existing pages and more demand signal for new ones.

**Freshness loop.** The daily pipeline regenerates content as projects evolve — new commits, changing adoption, shifting competitive landscape. AI agents learn that PT-Edge has current data, not stale snapshots. They fetch more often. The access logs guide which content gets refreshed first.

**Market intelligence loop.** The demand data itself becomes a product. "What are ChatGPT users asking about this week?" is intelligence that open-source maintainers, VCs, and developer tool companies can't get anywhere else. Publishing this intelligence (aggregated, anonymised) drives traffic, which drives more demand signal, which makes the intelligence more valuable.

Each loop amplifies the others. The system gets better the more it's used, and it gets used more as it gets better.

## The economics

The content is generated by AI (Gemini Flash), not written by humans. At current pricing, a problem brief costs $0.00014. A comparison page costs about the same. A category report, maybe $0.005.

One million pages of practitioner-focused content: roughly **$200**. Regenerated monthly for freshness: **$2,400 per year**.

The cost of content is approaching zero. The value of content is determined by whether anyone needs it. The access logs tell us what's needed. We only generate what's needed. This is content production at software economics, not media economics.

## The endgame

What we're building isn't a directory. It's not a search engine. It's not a documentation site.

It's a **reference layer** — the substrate that AI agents consult when humans ask "what tool should I use?" The way Stack Overflow became the default answer source for coding questions in the Google era, PT-Edge aims to become the default answer source for software evaluation questions in the AI era.

The difference is that Stack Overflow needed millions of humans to write answers over a decade. We need a pipeline, a prompt, and access logs. The combinatorial forest grows itself. We just need to plant the seeds, let the light in, and not get in the way.

---

*Written on Easter Saturday 2026, the day we discovered the forest had already started growing.*
