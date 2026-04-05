# Agentic AI is Recapitulating the Ball of Mud

*Note: 5 April 2026. Idea to research separately.*

Most agentic AI systems today have the same fundamental architecture as a badly written cron job: a single ephemeral process, holding all state in local memory, executing steps sequentially, with no durable record of what it did or why.

The context window is the "memory." If it gets truncated, knowledge is lost. The LLM's next-token prediction is the "orchestrator." If it hallucinates a step, there's no checkpoint to roll back to. If the process crashes, you start from scratch. There's no idempotency, no separation of concerns, no observability beyond whatever the agent happens to print to stdout.

This is not a new failure mode. It's the same set of mistakes that backend engineering identified and solved over decades:

- **Ephemeral state instead of durable state.** The context window is process memory. It dies with the process. The fix has always been: put the truth in a database.
- **Sequential coupling with no dependency graph.** Steps execute in order because that's how the prompt was written, not because there's a real dependency. The fix: model dependencies explicitly, execute in parallel where possible.
- **No crash recovery.** If step 7 of 12 fails, you rerun 1-12. The fix: make each step atomic, record completion, resume from where you left off.
- **Orchestration by vibes.** The LLM decides what to do next based on a prompt and its own confidence. The fix: let the state of the world determine what needs doing. Query the database, not the model's feelings.

The projects that actually work well tend to rediscover these patterns by accident. Using git as the source of truth. Writing intermediate results to files or databases. Structuring work as discrete tasks rather than one long chain of thought. They're just reinventing the work queue — they don't call it that because the marketing says "agent."

The interesting research question is whether this is just an early-adoption mess that will get cleaned up, or whether there's something inherent in the LLM-as-orchestrator pattern that resists these fixes. Can you have a durable, observable, crash-recoverable agent that still benefits from LLM reasoning at each step? Probably yes — but it looks much more like a worker pulling tasks from a queue than an "autonomous agent" with a system prompt and a dream.

The analogy to our own `runner.py` is exact. We built a sequential pipeline, held everything in process memory, had no visibility, and wondered why it couldn't scale. The fix isn't smarter orchestration within the process. The fix is killing the process as the locus of truth and putting the truth somewhere that survives it.
