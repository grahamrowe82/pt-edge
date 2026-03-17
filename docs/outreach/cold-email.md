# Cold Email Templates

Target: AI consultancies (5-50 people) who produce reports, recommendations, or tooling evaluations for clients.

---

## Initial Email

**Subject line variants:**
1. Live AI ecosystem data for your client work
2. 166K repos tracked — API access for your team
3. Replace manual GitHub research with one API call

**Body:**

Hi {first_name},

I saw {personalization_hook}. We built PT-Edge — a REST API that tracks 166,000+ AI repos across GitHub, PyPI, npm, Docker Hub, HuggingFace, and Hacker News in real time. Star velocity, download trends, lifecycle stages, hype ratios, release cadence — all queryable.

The docs are here: https://pt-edge.onrender.com/api/docs

I set up a trial key for you: `pte_{trial_key}` — 100 calls/day, no commitment. Try `GET /api/v1/trending` or look up any project by slug.

Worth a 15-minute call to see if this fits your workflow?

Graham
Phase Transitions
graham@phasetransitions.co

---

## Follow-Up (Day 5-7)

**Subject:** Re: {original_subject}

Hi {first_name},

Quick follow-up — since I sent that note, {specific_data_point}. That's the kind of signal PT-Edge surfaces automatically.

If your team is spending time manually tracking GitHub repos or compiling landscape reports, this could save hours per project. Happy to walk through how the data maps to your deliverables.

Graham

**Example data points to slot in:**
- "vLLM crossed 48K stars and their 7-day velocity is 2x the category average"
- "3 new agent frameworks launched this week — CrewAI and LangGraph are pulling away"
- "Ollama's download growth hit 15% week-over-week"

---

## Personalization Hooks

Before sending, check:

1. **Their blog/newsletter** — Do they publish AI landscape reports, tool comparisons, or "state of" posts? Reference a specific article. ("I read your piece on agent framework selection...")
2. **GitHub activity** — Are they starring/forking AI repos? ("I noticed your team has been tracking the inference space...")
3. **Client verticals** — What industries do they serve? Frame the value in terms of their clients. ("For your fintech clients evaluating LLM deployment options...")
4. **Conference talks** — Have they spoken about AI tooling evaluation? ("Your talk at {conference} on build-vs-buy for AI infrastructure resonated...")
5. **Job postings** — Are they hiring for AI/ML roles? Signals they're scaling AI practice. ("Saw you're growing the AI practice...")
