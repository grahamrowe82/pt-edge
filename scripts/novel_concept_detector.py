"""Novel Concept Detector for YC Lightcone Podcast Transcripts.

Detects genuinely new concepts in expert discourse by combining:
- Layer 1: Embedding anomaly detection (cosine distance from newsletter corpus centroid)
- Layer 4: Disfluency/hedging analysis (LLM-scored linguistic markers of conceptual novelty)

See docs/briefs/novel-concept-detection.md for theoretical grounding.
"""
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import engine
from app.embeddings import embed_batch, is_enabled as embeddings_enabled
from app.ingest.llm import call_haiku
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ─── Episodes to analyze ────────────────────────────────────────────

EPISODES = [
    ("8SVocWnDHwE", "AI Is Unlocking Millions Of New Builders", "2026-03-16"),
    ("k2ZLQC8P7dc", "Chollet: Why Scaling Alone Isn't Enough for AGI", "2026-03-27"),
    ("UPGB-hsAoVY", "The Powerful Alternative To Fine-Tuning", "2026-02-27"),
    ("Q8wVMdwhlh4", "The AI Agent Economy Is Here", "2026-02-21"),
    ("eCjYIj-fEDw", "What Boris Cherny Learned From Building Claude Code", "2026-02-20"),
]

# ─── Data structures ────────────────────────────────────────────────


@dataclass
class Segment:
    video_id: str
    episode_title: str
    text: str
    start_time: float
    end_time: float
    word_count: int = 0
    embedding: list[float] | None = None
    cosine_distance: float = 0.0
    lof_score: float = 0.0
    embedding_percentile: float = 0.0
    disfluency_score: float = 0.0
    disfluency_detail: dict = field(default_factory=dict)
    novelty_score: float = 0.0
    concept_description: str = ""


# ─── 1. Transcript fetching ─────────────────────────────────────────


def fetch_transcript(video_id: str) -> list[dict]:
    """Fetch raw transcript snippets. Preserves disfluencies (uh, um)."""
    from youtube_transcript_api import YouTubeTranscriptApi

    ytt = YouTubeTranscriptApi()
    transcript = ytt.fetch(video_id)
    return [{"text": entry.text, "start": entry.start, "duration": entry.duration}
            for entry in transcript]


# ─── 2. Segmentation ────────────────────────────────────────────────


def segment_transcript(
    snippets: list[dict],
    video_id: str,
    episode_title: str,
    target_words: int = 500,
    overlap_words: int = 100,
) -> list[Segment]:
    """Split transcript into overlapping word-based segments with timestamps."""
    # Build word list with timestamps
    words_with_time: list[tuple[str, float]] = []
    for snip in snippets:
        for w in snip["text"].split():
            words_with_time.append((w, snip["start"]))

    if not words_with_time:
        return []

    segments = []
    i = 0
    while i < len(words_with_time):
        end = min(i + target_words, len(words_with_time))
        chunk_words = words_with_time[i:end]
        text = " ".join(w for w, _ in chunk_words)
        start_time = chunk_words[0][1]
        end_time = chunk_words[-1][1]

        segments.append(Segment(
            video_id=video_id,
            episode_title=episode_title,
            text=text,
            start_time=start_time,
            end_time=end_time,
            word_count=len(chunk_words),
        ))

        step = target_words - overlap_words
        if end >= len(words_with_time):
            break
        i += step

    return segments


# ─── 3. Newsletter centroid (Layer 1 baseline) ──────────────────────


def compute_newsletter_centroid() -> np.ndarray:
    """Compute mean embedding vector from newsletter corpus (last 90 days)."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT embedding::text FROM newsletter_mentions "
            "WHERE embedding IS NOT NULL "
            "AND published_at >= NOW() - INTERVAL '90 days'"
        )).fetchall()

    logger.info(f"Newsletter corpus: {len(rows)} embeddings for centroid")
    if len(rows) < 10:
        raise RuntimeError(f"Only {len(rows)} newsletter embeddings — too few for a reliable centroid")

    vectors = []
    for (emb_text,) in rows:
        vec = np.fromstring(emb_text.strip("[]"), sep=",", dtype=np.float32)
        vectors.append(vec)

    centroid = np.mean(vectors, axis=0)
    centroid = centroid / np.linalg.norm(centroid)  # L2 normalize
    return centroid


# ─── 4. Embedding anomaly scoring (Layer 1) ─────────────────────────


async def embed_segments(segments: list[Segment]) -> None:
    """Embed all segments via OpenAI. Mutates in-place."""
    if not embeddings_enabled():
        logger.warning("Embeddings disabled (no OPENAI_API_KEY). Skipping Layer 1.")
        return

    texts = [s.text[:6000] for s in segments]
    vectors = await embed_batch(texts)
    for seg, vec in zip(segments, vectors):
        seg.embedding = vec


def score_embedding_anomaly(segments: list[Segment], centroid: np.ndarray) -> None:
    """Compute cosine distance from centroid + LOF. Mutates in-place."""
    embedded = [s for s in segments if s.embedding is not None]
    if not embedded:
        return

    # Build matrix
    matrix = np.array([s.embedding for s in embedded], dtype=np.float32)

    # Cosine distances from centroid
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normed = matrix / norms
    cosine_sims = normed @ centroid
    cosine_dists = 1 - cosine_sims

    for seg, dist in zip(embedded, cosine_dists):
        seg.cosine_distance = float(dist)

    # LOF scoring
    from scipy.stats import percentileofscore
    lof_percentiles = np.zeros(len(embedded))
    if len(embedded) >= 5:
        try:
            from sklearn.neighbors import LocalOutlierFactor
            n_neighbors = min(20, len(embedded) - 2)
            lof = LocalOutlierFactor(n_neighbors=n_neighbors, contamination="auto")
            lof.fit_predict(matrix)
            lof_scores = -lof.negative_outlier_factor_  # higher = more outlier
            for i, score in enumerate(lof_scores):
                lof_percentiles[i] = percentileofscore(lof_scores, score)
                embedded[i].lof_score = float(score)
        except Exception as e:
            logger.warning(f"LOF failed: {e}. Using cosine distance only.")

    # Cosine distance percentiles
    for i, seg in enumerate(embedded):
        cos_pct = percentileofscore(cosine_dists, seg.cosine_distance)
        seg.embedding_percentile = 0.7 * cos_pct + 0.3 * lof_percentiles[i]


# ─── 5. Disfluency/hedging scoring (Layer 4) ────────────────────────

DISFLUENCY_PROMPT = """Analyze this podcast transcript segment for signs that the speaker is trying to articulate a genuinely novel concept — something they don't yet have clean vocabulary for.

Context: This is from a Y Combinator podcast with experienced founders and investors. These speakers are normally precise and articulate. Disfluency from them is therefore INFORMATIVE — it suggests they're at the edge of what they can express.

Score each dimension 0-100:

1. **hedging_density**: Epistemic hedging ("I think", "sort of", "maybe", "kind of", "probably", "it seems like", "in a way"). 0 = no hedging, 100 = heavily hedged throughout.
2. **analogy_ratio**: How much does the speaker use analogy/comparison ("it's like X", "think of it as", "similar to", "the equivalent of") versus clean definition ("it is X", "this means", "specifically")? 0 = all definition, 100 = all analogy.
3. **uncertainty_markers**: Explicit metacognitive uncertainty ("I don't know what to call this", "I'm not sure how to explain", "it's hard to describe", "we're still figuring out"). 0 = none, 100 = pervasive.
4. **reformulations**: How often does the speaker restart, correct, or rephrase — attempting the same idea multiple times in different words? 0 = clean single expression, 100 = constant restating.
5. **conceptual_novelty**: Based on all signals above plus your judgment — is this segment describing something that doesn't yet have established vocabulary in the AI/tech ecosystem? 0 = well-known concept, 100 = genuinely pre-verbal concept.

Also count:
- filled_pauses: occurrences of "uh", "um", filler "like", "you know" used as fillers
- analogy_examples: list the specific analogies used (if any)

Return ONLY valid JSON:
{
  "hedging_density": <0-100>,
  "analogy_ratio": <0-100>,
  "uncertainty_markers": <0-100>,
  "reformulations": <0-100>,
  "conceptual_novelty": <0-100>,
  "filled_pauses": <int>,
  "analogy_examples": ["<analogy 1>", ...],
  "overall_disfluency_score": <0-100>,
  "reasoning": "<1-2 sentence explanation>"
}

TRANSCRIPT SEGMENT:
---
{segment_text}
---"""


async def score_disfluency(segments: list[Segment]) -> None:
    """Score each segment for disfluency markers via Haiku. Mutates in-place."""
    for i, seg in enumerate(segments):
        if i > 0 and i % 20 == 0:
            logger.info(f"  Disfluency scoring: {i}/{len(segments)}")

        prompt = DISFLUENCY_PROMPT.replace("{segment_text}", seg.text[:4000])
        result = await call_haiku(prompt, max_tokens=512, timeout=30.0)

        if result and isinstance(result, dict):
            seg.disfluency_score = result.get("overall_disfluency_score", 50)
            seg.disfluency_detail = result
        else:
            seg.disfluency_score = 50  # neutral fallback


# ─── 6. Composite scoring ───────────────────────────────────────────


def compute_composite_scores(segments: list[Segment]) -> None:
    """novelty_score = 0.5 * embedding_percentile + 0.5 * disfluency_score."""
    for seg in segments:
        seg.novelty_score = 0.5 * seg.embedding_percentile + 0.5 * seg.disfluency_score


# ─── 7. Novel concept extraction (top N only) ───────────────────────

CONCEPT_PROMPT = """This podcast transcript segment scored high for novelty — the speaker appears to be reaching for a concept that doesn't yet have established vocabulary.

Read the segment and extract:
1. What is the novel concept about? (2-3 sentences)
2. Why is it novel — what makes this different from established ideas in the AI/tech space?
3. A provisional name for the concept (something descriptive)
4. Existing concepts this could be confused with but is distinct from

Return ONLY valid JSON:
{
  "concept_summary": "<2-3 sentences>",
  "novelty_reason": "<why this is new>",
  "provisional_name": "<descriptive name>",
  "related_concepts": ["<concept 1>", "<concept 2>"]
}

TRANSCRIPT SEGMENT:
---
{segment_text}
---"""


async def extract_concepts(segments: list[Segment], top_n: int = 10) -> None:
    """Extract novel concept descriptions for top-scoring segments."""
    ranked = sorted(segments, key=lambda s: s.novelty_score, reverse=True)
    for seg in ranked[:top_n]:
        prompt = CONCEPT_PROMPT.replace("{segment_text}", seg.text[:4000])
        result = await call_haiku(prompt, max_tokens=512, timeout=30.0)
        if result and isinstance(result, dict):
            parts = []
            if result.get("provisional_name"):
                parts.append(f"**{result['provisional_name']}**")
            if result.get("concept_summary"):
                parts.append(result["concept_summary"])
            if result.get("novelty_reason"):
                parts.append(f"Novel because: {result['novelty_reason']}")
            seg.concept_description = " ".join(parts)
        else:
            seg.concept_description = "(extraction failed)"


# ─── 8. Report generation ───────────────────────────────────────────


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def generate_report(all_segments: list[Segment], output_path: str) -> None:
    """Write markdown report."""
    ranked = sorted(all_segments, key=lambda s: s.novelty_score, reverse=True)
    episodes = {}
    for seg in all_segments:
        episodes.setdefault(seg.video_id, []).append(seg)

    lines = [
        "# Novel Concept Detection Report",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Episodes analyzed: {len(episodes)}",
        f"Total segments: {len(all_segments)}",
        "",
        "## Methodology",
        "",
        "- **Layer 1 (Embedding Anomaly):** Each 500-word segment embedded via OpenAI text-embedding-3-large.",
        "  Cosine distance from newsletter corpus centroid (1,307 embeddings, last 90 days).",
        "  Local Outlier Factor for local density anomaly. Combined: 70% cosine + 30% LOF percentile.",
        "- **Layer 4 (Disfluency/Hedging):** Claude Haiku scores each segment on hedging density,",
        "  analogy ratio, uncertainty markers, reformulations, and conceptual novelty (0-100 each).",
        "- **Composite:** 50% embedding anomaly percentile + 50% disfluency score.",
        "",
        "---",
        "",
        "## Top 10 Most Novel Segments",
        "",
    ]

    for i, seg in enumerate(ranked[:10]):
        detail = seg.disfluency_detail
        lines.extend([
            f"### {i+1}. [{seg.episode_title}] at {fmt_time(seg.start_time)}–{fmt_time(seg.end_time)}",
            f"**Novelty score: {seg.novelty_score:.1f}** "
            f"(embedding: {seg.embedding_percentile:.1f}, disfluency: {seg.disfluency_score:.1f})",
            "",
            f"- Cosine distance: {seg.cosine_distance:.4f}",
            f"- Hedging: {detail.get('hedging_density', '?')}, "
            f"Analogy: {detail.get('analogy_ratio', '?')}, "
            f"Uncertainty: {detail.get('uncertainty_markers', '?')}, "
            f"Reformulations: {detail.get('reformulations', '?')}, "
            f"Conceptual novelty: {detail.get('conceptual_novelty', '?')}",
            f"- Filled pauses: {detail.get('filled_pauses', '?')}",
        ])
        if detail.get("analogy_examples"):
            lines.append(f"- Analogies: {', '.join(detail['analogy_examples'][:3])}")
        if detail.get("reasoning"):
            lines.append(f"- LLM reasoning: {detail['reasoning']}")
        lines.append("")
        if seg.concept_description:
            lines.append(f"**Concept:** {seg.concept_description}")
            lines.append("")
        # Truncated transcript
        preview = seg.text[:800]
        if len(seg.text) > 800:
            preview += "..."
        lines.extend([f"> {preview}", "", "---", ""])

    # Per-episode rankings
    lines.extend(["", "## Per-Episode Rankings", ""])
    for video_id, title, date in EPISODES:
        ep_segs = sorted(episodes.get(video_id, []), key=lambda s: s.novelty_score, reverse=True)
        lines.extend([
            f"### {title} ({date})",
            f"Segments: {len(ep_segs)}",
            "",
            "| Rank | Time | Novelty | Embed | Disfluency | Preview |",
            "|------|------|---------|-------|------------|---------|",
        ])
        for j, seg in enumerate(ep_segs[:10]):
            preview = seg.text[:80].replace("|", "/").replace("\n", " ")
            lines.append(
                f"| {j+1} | {fmt_time(seg.start_time)} | {seg.novelty_score:.1f} | "
                f"{seg.embedding_percentile:.1f} | {seg.disfluency_score:.1f} | {preview}... |"
            )
        lines.extend(["", ""])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines))
    logger.info(f"Report written to {output_path}")


# ─── Main ────────────────────────────────────────────────────────────


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # 1. Build baseline centroid
    logger.info("Computing newsletter corpus centroid...")
    centroid = compute_newsletter_centroid()

    # 2. Fetch and segment all transcripts
    all_segments: list[Segment] = []
    for video_id, title, date in EPISODES:
        logger.info(f"Fetching transcript: {title} ({video_id})")
        try:
            snippets = fetch_transcript(video_id)
            segments = segment_transcript(snippets, video_id, title)
            logger.info(f"  → {len(snippets)} caption entries → {len(segments)} segments")
            all_segments.extend(segments)
        except Exception as e:
            logger.error(f"  Failed to fetch {video_id}: {e}")

    logger.info(f"Total segments: {len(all_segments)}")

    # 3. Embed all segments
    logger.info("Embedding segments...")
    await embed_segments(all_segments)
    embedded_count = sum(1 for s in all_segments if s.embedding is not None)
    logger.info(f"  Embedded: {embedded_count}/{len(all_segments)}")

    # 4. Score embedding anomaly
    logger.info("Scoring embedding anomaly (Layer 1)...")
    score_embedding_anomaly(all_segments, centroid)

    # 5. Score disfluency
    logger.info("Scoring disfluency/hedging (Layer 4)...")
    await score_disfluency(all_segments)

    # 6. Composite scores
    compute_composite_scores(all_segments)

    # 7. Extract concepts for top segments
    logger.info("Extracting novel concepts for top 10...")
    await extract_concepts(all_segments, top_n=10)

    # 8. Generate report
    output_path = "scratch/novel_concept_analysis.md"
    generate_report(all_segments, output_path)

    # Quick summary to stdout
    ranked = sorted(all_segments, key=lambda s: s.novelty_score, reverse=True)
    print("\n" + "=" * 60)
    print("TOP 5 MOST NOVEL SEGMENTS")
    print("=" * 60)
    for i, seg in enumerate(ranked[:5]):
        print(f"\n{i+1}. [{seg.episode_title}] {fmt_time(seg.start_time)} — score {seg.novelty_score:.1f}")
        print(f"   embed={seg.embedding_percentile:.1f} disfluency={seg.disfluency_score:.1f}")
        if seg.concept_description:
            print(f"   {seg.concept_description[:150]}")


if __name__ == "__main__":
    asyncio.run(main())
