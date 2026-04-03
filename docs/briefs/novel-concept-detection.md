# Novel Concept Detection in Expert Discourse

Design brief for detecting genuinely new concepts in YC founder podcast transcripts — the ideas that don't yet have names, categories, or consensus vocabulary.

## The core problem

When we run standard LLM extraction on expert podcasts, the LLM categorises everything into known topics. But the most valuable signal is the stuff that *doesn't fit* — the moments where experts are groping toward something they can't yet name. Our current pipeline is systematically discarding the signal we most want.

## The disfluency hypothesis

When normally articulate experts become vague, hedging, and analogical — when they're willing to be confused in public — they're likely encountering something genuinely new. Their disfluency is not noise; it's a high-confidence indicator that a concept is forming at the knowledge frontier.

Academic grounding (all well-established individually; the assembly is novel):
- **Schachter et al. (1991):** Disfluency rates correlate with knowledge domain branching factor. More possible things to say → more filled pauses. Experts entering uncharted conceptual territory face maximum branching.
- **Clark & Fox Tree (2002, Cognition):** "Um" signals a major expected delay; "uh" signals a minor one. These are communicative acts, not random noise. An expert producing "um" before describing something novel is signaling genuine processing difficulty.
- **Cognitive load research:** Fillers result from difficulties in *conceptual planning* rather than lexical retrieval or grammatical planning. The difficulty is at the idea level, not the word level.
- **Gentner's structure-mapping theory (1983):** Analogy is the primary cognitive mechanism for understanding novel domains. When experts shift from definition to analogy ("it's kind of like X but for Y"), they're performing structure-mapping — the way humans extend understanding into new territory.
- **Sperber et al. (2010, Mind & Language):** Epistemic vigilance — the credibility of the source makes their uncertainty *more* informative, not less.

Linguistic markers to detect:
- Increased filled pauses (um > uh, per Clark & Fox Tree)
- Hedging language (epistemic markers: "I think", "sort of", "maybe", "kind of")
- Analogy over definition ("it's like X" instead of "it is X")
- False starts and reformulations (multiple attempts to articulate the same idea)
- Explicit metacognitive commentary ("I don't know what to call this")
- Extended dwell time on a topic

## Proposed detection architecture (six layers)

These layers are complementary, not alternatives. Each narrows the set of candidates.

### Layer 1: Embedding anomaly detection (broadest net)

Embed all transcript segments. Flag segments distant from the running centroid of existing discourse, or identified as local outliers via Local Outlier Factor (LOF).

Prior art: "Semantic Novelty at Scale" (arxiv 2602.20647) — cosine distance from running centroid on 28K books. TAD-Bench (arxiv 2501.11960) — benchmark for embedding-based text anomaly detection.

Feasibility: **Very high.** Sentence transformers + LOF/Isolation Forest. Straightforward to implement.

### Layer 2: Information-theoretic scoring (filters noise)

Score flagged segments using cross-entropy against the baseline corpus (newsletter_mentions + existing media). High cross-entropy confirms the segment is surprising *relative to established discourse*, not just generically unusual.

Prior art: Surprisal-based OOD detection is well-established. LLM perplexity scoring is trivial to implement.

Feasibility: **High.** Requires a baseline corpus (we have newsletter_mentions) and any LLM for perplexity scoring.

### Layer 3: Bayesian topic surprise (captures emerging patterns)

Maintain a running topic model. Compute KL divergence between each new segment's topic distribution and the prior. High KL divergence = the segment shifts your beliefs about what's being discussed.

Prior art: Itti & Baldi (2005/2009) — formal Bayesian surprise framework. "Pattern Making and Pattern Breaking" (AEA 2022) — KL divergence for novelty in economics papers. BOCD (Adams & MacKay 2007) for changepoint detection.

Feasibility: **Medium-high.** BERTopic + online learning + KL divergence computation.

### Layer 4: Disfluency/hedging detector (highest-confidence signal)

For segments surviving layers 1-3, analyze linguistic markers: filled pause rate relative to speaker baseline, hedging density, analogy-to-definition ratio, explicit metacognitive uncertainty. Segments that are semantically novel AND accompanied by expert disfluency are highest-confidence.

Prior art: Individual components well-established (Schachter, Clark & Fox Tree, hedging detection in NLP). The composite detector is novel — no one has assembled these into a pre-narrative concept detector.

Feasibility: **Medium.** Requires ASR that preserves disfluencies (Whisper can do this with tuning), hedging detection (LLMs can do this), and a per-speaker baseline (need multiple episodes per speaker).

### Layer 5: Attention residual (validates importance)

Compare time spent on each topic against its current "importance" in the ecosystem (GitHub stars, media coverage, etc.). Topics receiving disproportionately more expert attention than their current importance predicts are candidates.

`attention_residual = actual_dwell_time - expected_dwell_time`

Feasibility: **Medium.** Requires topic segmentation + a baseline model of expected attention per topic.

### Layer 6: Temporal tracking (confirms persistence)

Track detected novel concepts across subsequent episodes. Concepts that reappear and grow are weak signals becoming strong. Concepts that appear once vanish are noise.

Prior art: BERTrend (Boutaleb et al., 2024) — pip-installable (`bertrend`). WISDOM framework — Topic Emergence Maps plotting proportion vs growth rate. "Pattern Making and Pattern Breaking" finding: most novel ideas are transient, but persistent novel ideas have higher impact.

Feasibility: **High.** BERTrend is literally a pip package. Needs tuning for podcast-sized corpus.

## Key tools and implementations

| Tool | What it does | Source |
|------|-------------|--------|
| BERTrend | Neural weak signal detection with temporal tracking | `pip install bertrend`, [GitHub](https://github.com/rte-france/BERTrend) |
| WISDOM | Topic Emergence Maps (weak/strong signal quadrants) | arxiv 2409.15340 |
| Emerging Concepts paper | Embedding heatmap + blob detection for early concept detection | arxiv 2502.21315 |
| BERTopic | Dynamic topic modeling backbone | `pip install bertopic` |
| LOF / Isolation Forest | Anomaly detection in embedding space | scikit-learn |
| youtube-transcript-api | Transcript extraction (already tested) | `pip install youtube-transcript-api` |

## Key references

- Schachter, Christenfeld, Ravina & Bilous (1991). "Speech Disfluency and the Structure of Knowledge"
- Clark & Fox Tree (2002). "Using uh and um in spontaneous speaking." Cognition
- Itti & Baldi (2005/2009). "Bayesian Surprise Attracts Human Attention." Vision Research
- Adams & MacKay (2007). "Bayesian Online Changepoint Detection"
- Gentner (1983). "Structure-Mapping: A Theoretical Framework for Analogy." Cognitive Science
- Sperber et al. (2010). "Epistemic Vigilance." Mind & Language
- Ansoff (1975). "Managing Strategic Surprise by Response to Weak Signals"
- Boutaleb et al. (2024). "BERTrend: Neural Topic Modeling for Emerging Trends Detection"
- "Identifying Emerging Concepts in Large Corpora" (2025). arxiv 2502.21315
- "Pattern Making and Pattern Breaking: Measuring Novelty in Brazilian Economics" (2022)
- Kuhn (1962). The Structure of Scientific Revolutions

## Implementation priority

Start with layers 1-2 (embedding anomaly + cross-entropy). These are quick to build and provide immediate value. Layer 4 (disfluency detection) is the most original and highest-confidence signal but needs ASR pipeline work. Layers 3, 5, 6 add precision but are additive rather than foundational.

The disfluency detector is the unique contribution — nobody else is building this. If it works, it's a genuine competitive advantage for identifying pre-narrative concepts.
