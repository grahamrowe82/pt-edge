# crewAI Dependency Assessment — Baseline (from general AI knowledge)

**Written without PT-Edge data. This is what an AI assistant would tell you if you asked "tell me about crewAI's dependencies." The value of the kairn audit is in the delta between this and what the data reveals.**

## What crewAI is

A Python framework for orchestrating multi-agent AI systems. You define agents with roles, give them tools, and let them collaborate on tasks. One of the most popular agent frameworks — direct competitor to AutoGen, LangGraph, and Agno.

## Dependencies I'd expect

- **LiteLLM** — crewAI uses this as its LLM abstraction layer rather than calling OpenAI/Anthropic directly. Smart choice: it lets users swap providers without code changes. LiteLLM is well-maintained and widely adopted. I'd consider this a solid dependency.

- **Pydantic** — for structured outputs and data validation. Standard choice, no concerns.

- **OpenAI SDK** — likely as a direct dependency or via LiteLLM. The default LLM backend.

- **Some embedding library** — for RAG capabilities. Could be OpenAI embeddings via LiteLLM, or something like sentence-transformers.

- **A vector store client** — crewAI has memory/knowledge features. I'd guess ChromaDB or FAISS for local, maybe Qdrant or Pinecone as options.

- **Tokenizers** (HuggingFace) — for token counting and context window management.

## What I'd tell someone asking "are crewAI's dependencies good?"

"crewAI uses well-known libraries, LiteLLM is a good abstraction choice, Pydantic is standard, the vector store options are reasonable." I'd probably mention that the agent framework space is competitive and moving fast, and that crewAI's main risk is more about the framework itself being overtaken than about its dependencies being problematic.

## Where my knowledge is vague or possibly wrong

- I'm not sure which vector store they actually default to. I'd guess Chroma but it might be LanceDB or something else.
- I don't know if they vendor any dependencies or use forks.
- I have no idea about the quality or maintenance status of their smaller, less famous dependencies — the ones that aren't LiteLLM or Pydantic.
- I can't tell you the momentum direction of any of these. Are any of them losing contributors? Slowing down on releases? I'd have to go check GitHub manually.
- I definitely can't tell you what the best alternative to each dependency is in its category, ranked by current data.

## The honest assessment of this baseline

It's surface-level. It's the kind of answer you'd get from any AI assistant or a medium-quality blog post. "LiteLLM is good, Pydantic is standard" — that's not insight, that's recognition. The things I *can't* answer from training data are exactly the things that would actually be useful: is LanceDB gaining on Chroma? Is tokenizers still the best choice or has something overtaken it? Are there dependencies in crewAI that nobody talks about but that are quietly unmaintained?

The interesting findings from the audit will be the surprises: dependencies that are more fragile than their reputation suggests, alternatives that are better than expected, and the small libraries nobody discusses that might be the real risk.
