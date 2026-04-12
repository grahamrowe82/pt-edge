# Vision: Opinionated Wikipedia for Bots

PT-Edge is a scored, linked intelligence layer over public structured data. Each domain follows the same pattern: ingest canonical open data sources, extract entities and relationships, compute opinionated quality/risk scores, and publish the result as both a static directory (for humans and search engines) and structured data (for AI agents and APIs).

The first domain was open-source AI. The platform is designed for six.

## The Six Domains

| Domain | Entities | Key Sources | Status |
|--------|----------|-------------|--------|
| **Open Source AI** | Repos, packages, maintainers, categories | GitHub, PyPI, npm, Docker Hub, HuggingFace, Hacker News | Live — 220K+ repos |
| **Cybersecurity** | CVEs, software, vendors, weaknesses, techniques | NVD, MITRE ATT&CK, EPSS, KEV, GHSA, OSV, Exploit-DB | Bootstrap in progress |
| **Biomedical** | Genes, proteins, drugs, diseases, trials | UniProt, PubChem, ClinicalTrials.gov, OMIM, DrugBank | Planned |
| **Patents** | Patents, inventors, assignees, classifications | USPTO, EPO, Google Patents | Planned |
| **Equities** | Companies, filings, holders, sectors | SEC EDGAR, market data | Early (Signal Cascade) |
| **Regulation** | Rules, controls, frameworks, obligations | eCFR, Federal Register, EUR-Lex, NIST, FDA | Planned |

## How They Connect

The domains are not siloed. Entities in one domain link to entities in others, forming a cross-domain graph:

```
                    Regulation
                   /    |     \
                  /     |      \
    Open Source AI -- Cyber -- Bio
                \      |      /
                 \     |     /
                  Patents
                     |
                  Equities
```

- **OS AI + Cyber**: which repos have CVEs, which vendors ship vulnerable software
- **OS AI + Patents**: who is patenting around open-source AI techniques
- **Cyber + Patents**: security IP portfolios, defensive tech ownership
- **Bio + Patents**: pharma IP, gene patents, biotech method claims
- **Equities + Patents**: patent portfolio as company valuation signal
- **Equities + OS AI**: open-source strategy as company signal
- **Equities + Cyber**: breach exposure and vulnerability density as risk
- **Regulation + Cyber**: compliance frameworks mapped to vulnerabilities and controls
- **Regulation + Bio**: FDA approvals, clinical trial mandates, drug scheduling
- **Regulation + OS AI**: EU AI Act, export controls, licensing obligations
- **Regulation + Patents**: IPR proceedings, patent office rulings, trade secret law

## The Pattern

Every domain follows the same architecture:

1. **Entities** with canonical IDs (CVE-2024-1234, US11234567B2, ENSG00000141510)
2. **Relationships** between entities (exploits, citations, pathways, dependencies)
3. **Scores** — opinionated, multi-dimensional, daily-refreshed quality/risk signals computed from public data
4. **Pages** — one URL per entity, structured for AI agent extraction and human readability

The shared infrastructure (task queue, resource budgets, scoring framework, site generator, MCP tools) is domain-agnostic. Adding a domain means defining its entities, sources, and scoring dimensions — not rebuilding the platform.

## Why This Works

The data in each domain is **public, structured, bulk-downloadable, and entity-rich**. The raw data is freely available. The value is in scoring it, linking it, and presenting it as opinionated answers rather than raw records.

An agent that lands on a PT-Edge page gets a structured answer with numbers, confidence, freshness, and links to related entities it can follow — across domain boundaries. That's the product: not a database, but a precomputed reasoning layer that agents can traverse as one graph.

## Related Documents

- [strategy.md](strategy.md) — How the first domain (OS AI) operates: quality scores, two audiences, demand/supply gaps
- [strategy/master-plan.md](strategy/master-plan.md) — The thesis: agents are the primary discovery mechanism
- [roadmap.md](roadmap.md) — What's built, what's next, the content flywheel
- [commercial-plan.md](commercial-plan.md) — The 8-step user journey and pricing model
