# Haiku 4.5 vs Gemini 2.5 Flash: Problem Brief Comparison

Same prompt, same 10 projects, same READMEs. Which model produces better practitioner-oriented briefs?

---

## 1. marketing-agent-blueprints (marketing director persona)

**Haiku:**
Run marketing workflows through AI agents without writing code. Feed in customer data, campaign briefs, or sales records—get back segmented lists, email drafts, content calendars, and lead scoring. Marketing managers and operations teams use this to automate repetitive tasks like audience analysis, outreach sequencing, and campaign planning.
- Tags: marketing-automation, lead-qualification, campaign-planning, audience-segmentation, sales-operations

**Gemini:**
Quickly set up AI-powered marketing assistants for everyday tasks. Pick from over 100 ready-made system prompts covering competitive intelligence, SEO audits, content creation, email campaigns, and lead generation. Marketing managers, solo entrepreneurs, and small business owners use these blueprints to automate repetitive marketing work with AI tools they already have.
- Tags: Marketing automation, Sales operations, Operations management, AI workflow automation, Business efficiency

**Verdict:** Haiku is more specific about inputs/outputs ("feed in customer data, get back segmented lists"). Gemini is a bit vaguer ("pick from over 100 ready-made prompts") but better identifies the persona ("solo entrepreneurs, small business owners"). Haiku's tags are sharper. Close call — **Haiku slight edge**.

---

## 2. raman_spectra_matching (chemist persona)

**Haiku:**
Identify unknown mineral, organic, or bacterial samples from their Raman spectra by matching against known reference libraries. You provide raw spectral data; the system returns the closest matches with confidence scores. Materials scientists, chemists, and microbiologists use this to quickly classify samples without manual spectral analysis.
- Tags: Raman spectroscopy, mineral identification, sample classification, materials characterization, microbiology lab work

**Gemini:**
Quickly identify unknown substances by comparing their Raman spectra against a known database of minerals and organic compounds. You provide spectral data from your instrument, and the system returns the closest matching materials with confidence scores. Researchers in geoscience, chemistry, and materials science use this to accelerate sample identification, replacing tedious manual comparison of spectra.
- Tags: Raman spectroscopy, material identification, chemical analysis, spectral matching, scientific research

**Verdict:** Nearly identical quality. Both nail the domain language. Haiku mentions microbiologists; Gemini mentions geoscience. Both excellent. **Tie.**

---

## 3. vectorbt (trader persona)

**Haiku:**
Test trading strategies on historical market data and optimize parameters across multiple assets in seconds. Feed in price data and entry/exit signals; get back detailed performance metrics, drawdowns, win rates, and Sharpe ratios. Designed for traders and quantitative researchers who need to validate strategies before risking capital.
- Tags: strategy-backtesting, portfolio-optimization, algorithmic-trading, hyperparameter-search, performance-analysis

**Gemini:**
Rapidly test and compare hundreds of trading strategies on historical market data, all at once. You provide your price data and trading rules; it returns detailed performance reports including profit/loss, risk metrics, and visual charts. Ideal for active traders, quantitative analysts, and investment researchers who need to validate ideas before committing real capital.
- Tags: trading-strategy-backtesting, algorithmic-trading, quantitative-finance, portfolio-analysis, market-data-analysis

**Verdict:** Both strong. Gemini adds "visual charts" which is useful context. Haiku names specific metrics (Sharpe ratios, drawdowns). Both speak trader fluently. **Tie.**

---

## 4. CausalDiscoveryToolbox (researcher persona)

**Haiku:**
Discover cause-and-effect relationships hidden in your data. Feed in observational datasets, and this toolbox maps out which variables influence which others—revealing the causal structure without running controlled experiments. Researchers, data scientists, and analysts use this to understand dependencies in complex systems.
- Tags: causal-inference, causal-discovery, graph-structure-learning, observational-data-analysis, dependency-mapping

**Gemini:**
Uncover hidden cause-and-effect relationships within your data, going beyond simple correlations to map out which factors truly drive changes in others. You feed in your observational data, and the toolbox reveals the underlying causal graph, showing directional dependencies between variables. Researchers, policy analysts, and data teams investigating complex systems use this to understand true drivers without costly controlled experiments.
- Tags: causal-inference, observational-data-analysis, system-modeling, root-cause-analysis, impact-assessment

**Verdict:** Gemini adds "policy analysts" and "root-cause-analysis" which broadens the persona nicely. Haiku is more concise. Gemini's tags are slightly more practitioner-oriented ("root-cause-analysis", "impact-assessment" vs "graph-structure-learning"). **Gemini slight edge.**

---

## 5. ssl-wearables (health researcher persona)

**Haiku:**
Recognize what activities people are doing based on accelerometer data from wearables (smartwatches, fitness trackers). You feed in raw sensor readings and get back activity classifications like walking, running, or sitting. Researchers and health scientists use this to analyze movement patterns from large populations with minimal labeled training data.
- Tags: activity-recognition, wearable-sensors, health-monitoring, movement-analysis, clinical-research

**Gemini:**
Automatically classify human physical activities—like walking, running, or sleeping—from raw wrist-worn accelerometer data, even with very few labeled examples. You provide raw sensor data from smartwatches or research-grade devices, and the system identifies specific activities over time. Health researchers, sports scientists, and clinical study teams use this to process large-scale wearable data efficiently.
- Tags: Human Activity Recognition, Wearable Sensors, Digital Health, Sports Science, Behavioral Monitoring

**Verdict:** Gemini adds "sports scientists" and "sleeping" as an activity, and mentions "research-grade devices" which is relevant. Tags include "Digital Health" and "Sports Science" — more discoverable for those audiences. **Gemini slight edge.**

---

## 6. Satellite-Imagery-Datasets-Containing-Ships (maritime/defense persona)

**Haiku:**
Find and access satellite imagery datasets for detecting and tracking ships from space. You provide your research or operational need (detection, classification, or segmentation), and get curated lists of radar and optical datasets with thousands of ship images, metadata, and annotations ready to use. Maritime analysts, remote sensing researchers, and organizations monitoring ocean traffic use this.
- Tags: maritime-surveillance, ship-detection, remote-sensing, ocean-monitoring, naval-operations

**Gemini:**
A curated guide to publicly available satellite image datasets featuring ships, designed for anyone building or evaluating vessel detection capabilities. Browse a structured list of optical and radar (SAR) datasets, each described with key details like resolution, coverage area, number of images, and direct download links. Maritime analysts, defense researchers, and remote sensing professionals use this to quickly find the right training data.
- Tags: maritime surveillance, ship detection, remote sensing, naval operations, satellite imagery analysis

**Verdict:** Gemini explicitly mentions SAR, resolution, coverage area, download links — more useful detail for the practitioner. Adds "defense researchers" as persona. **Gemini edge.**

---

## 7. USearch (developer persona)

**Haiku:**
Find similar items in massive datasets by comparing numerical embeddings or text — like discovering similar images, documents, or products without scanning everything. You feed in vectors or text, and get back ranked matches. Data scientists, ML engineers, and search teams use this to power recommendation systems, semantic search, and similarity-based clustering.
- Tags: vector-search, semantic-search, recommendation-systems, similarity-clustering, embedding-matching

**Gemini:**
Need to quickly find similar items in large collections of data? USearch is a high-performance engine designed for discovering related vectors and text, delivering exceptional speed and memory efficiency. It takes in your data, processes it, and returns highly relevant matches or groups similar items together.
- Tags: Similarity Search, Data Clustering, Information Retrieval, Recommendation Systems, Large Data Analysis

**Verdict:** Haiku is clearly better here — specific about inputs/outputs, names the personas, and the tags are more precise. Gemini starts with a question (against the rules), mentions the project name, and the tags are vague ("Large Data Analysis"). **Haiku wins.**

---

## 8. SkillExtractionNER (HR persona)

**Haiku:**
Extract and rank skills mentioned in job descriptions or candidate profiles automatically. Feed in unstructured text (job postings, resumes, role descriptions) and get back a structured list of identified skills with relevance scores. HR teams, recruiters, and talent acquisition managers use this to standardize skill matching across hiring workflows.
- Tags: talent-acquisition, skills-matching, job-description-analysis, resume-screening, workforce-planning

**Gemini:**
This tool helps you automatically pinpoint and score specific skills mentioned in written text, like job descriptions or resumes. You provide the text, and it returns a list of identified skills, even highlighting potential career opportunities based on those skills. It's perfect for recruiters, HR professionals, or anyone analyzing skill requirements across many documents.
- Tags: Skill Extraction, Job Description Analysis, Recruitment Automation, Career Insights, Resume Screening

**Verdict:** Haiku is tighter and more specific ("structured list with relevance scores", "standardize skill matching across hiring workflows"). Gemini starts with "This tool" (against the rules) and is vaguer. Haiku's tags are better ("workforce-planning" is great). **Haiku wins.**

---

## 9. Anomaly-Transformer (operations/industrial persona)

**Haiku:**
Automatically find unusual patterns and anomalies in time series data (like sensor readings or system metrics over time) without needing labeled examples. Feed in your historical data and get back flagged time periods where something unexpected occurred — useful for monitoring systems, networks, and industrial equipment.
- Tags: anomaly-detection, time-series-monitoring, sensor-data-analysis, system-health-monitoring, outlier-detection

**Gemini:**
This helps you automatically find unusual or problematic events within data collected over time, such as sensor readings or system performance logs. You provide your time-series data, and it identifies specific points or periods that stand out as abnormal. It's designed for anyone needing to quickly spot errors, failures, or unexpected changes in their sequential data streams.
- Tags: Time Series Monitoring, Unusual Event Detection, System Health Checks, Data Irregularity Finder

**Verdict:** Very similar. Haiku is slightly more specific ("networks and industrial equipment"). Gemini starts with "This helps" and only has 4 tags. **Haiku slight edge.**

---

## 10. pyfuzzylite (automation engineer persona)

**Haiku:**
Build decision-making systems that handle imprecise or fuzzy inputs—like 'slightly warm' or 'moderately high'—and produce clear outputs for control tasks. You define linguistic rules (e.g., 'if obstacle is near, then steer left'), and the system converts real-world sensor data into actionable commands. Used by engineers and control system designers for robotics, HVAC systems, industrial automation.
- Tags: robotics-control, industrial-automation, process-control, sensor-fusion, rule-based-decision-making

**Gemini:**
This tool helps you build systems that make intelligent decisions using human-like reasoning, even with vague or uncertain information. You provide rules and descriptive terms, and it translates numeric inputs into actionable numeric outputs. It's for engineers, researchers, and hobbyists creating automated controls or smart decision-making applications.
- Tags: Smart Decisions, Automation, Intelligent Control, System Logic, Uncertainty Handling

**Verdict:** Haiku is dramatically better. The concrete examples ("slightly warm", "if obstacle is near, then steer left", "HVAC systems") make the use case immediately tangible. Gemini is abstract and its tags are useless ("Smart Decisions"?). **Haiku wins clearly.**

---

## Overall Assessment

| Project | Winner | Notes |
|---------|--------|-------|
| marketing-agent-blueprints | Haiku (slight) | More specific I/O |
| raman_spectra | Tie | Both excellent |
| vectorbt | Tie | Both speak trader |
| CausalDiscoveryToolbox | Gemini (slight) | Better personas and tags |
| ssl-wearables | Gemini (slight) | Broader personas |
| Satellite ships | Gemini | More useful detail |
| USearch | **Haiku** | Gemini too vague |
| SkillExtractionNER | **Haiku** | Tighter, better tags |
| Anomaly-Transformer | Haiku (slight) | More specific |
| pyfuzzylite | **Haiku** | Dramatically better |

**Score: Haiku 5.5 — Gemini 4.5**

Haiku is consistently more specific, follows the prompt rules more carefully (Gemini broke "don't start with This..." multiple times), and produces sharper domain tags. Gemini occasionally identifies broader personas and adds useful detail, but falls back to vague language more often.

**Recommendation:** Haiku produces noticeably better briefs, but Gemini is "good enough" for the long tail — maybe 80% of Haiku quality at 10% of the cost. A hybrid approach could work: Gemini for the initial bulk pass across 200K projects, then Haiku for the top-traffic pages that need polish. The domain tags from either model are valuable regardless.
