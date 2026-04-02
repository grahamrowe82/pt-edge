# Agent Memory Deep Dive — Research Data

Research date: 2026-04-01
Source: PT-Edge production database (220K+ AI repos)

---

## 1. Landscape Discovery

### 1a. All repos with memory-related subcategories (top 60 by stars)

| Repo | Stars | Forks | Language | Domain | Subcategory | Downloads/mo | Commits 30d | Created | Description |
|------|-------|-------|----------|--------|-------------|-------------|-------------|---------|-------------|
| mem0ai/mem0 | 49,646 | 5,542 | Python | rag | agent-memory-systems | 0 | 146 | 2023-06-20 | Universal memory layer for AI Agents |
| thedotmack/claude-mem | 34,460 | 2,414 | TypeScript | agents | agent-memory-systems | 6,486 | 53 | 2025-08-31 | Claude Code plugin that captures everything Claude does, compresses with AI |
| a2aproject/A2A | 22,488 | 2,283 | Shell | agents | model-context-protocol | 0 | 31 | 2025-03-25 | Agent2Agent open protocol for agent interoperability |
| memvid/memvid | 13,421 | 1,123 | Rust | vector-db | agent-memory-systems | 0 | 6 | 2025-05-27 | Serverless single-file memory layer replacing complex RAG pipelines |
| googleapis/genai-toolbox | 13,403 | 1,269 | Go | mcp | model-context-protocol | 0 | 158 | 2024-06-07 | MCP Toolbox for Databases |
| topoteretes/cognee | 13,204 | 1,336 | Python | vector-db | agent-memory-systems | 77,871 | 393 | 2023-08-16 | Knowledge Engine for AI Agent Memory in 6 lines of code |
| MemoriLabs/Memori | 12,351 | 1,112 | Python | rag | agent-memory-systems | 20,201 | 64 | - | SQL Native Memory Layer for LLMs, AI Agents & Multi-Agent Systems |
| reorproject/reor | 8,535 | 517 | JavaScript | vector-db | agent-memory-systems | 0 | - | - | Private & local AI personal knowledge management app |
| zilliztech/GPTCache | 7,963 | 570 | Python | embeddings | agent-memory-systems | 463,836 | - | - | Semantic cache for LLMs (LangChain + llama_index) |
| idosal/git-mcp | 7,755 | 683 | TypeScript | mcp | model-context-protocol | 0 | 2 | - | Remote MCP server for any GitHub project |
| volcengine/OpenViking | 7,606 | 541 | Python | rag | agent-memory-systems | 70,261 | 378 | - | Context database for AI Agents (OpenClaw compatible) |
| mufeedvh/code2prompt | 7,220 | 407 | Rust | prompt-engineering | codebase-context-extraction | 0 | 7 | - | CLI to convert codebase into single LLM prompt |
| MemTensor/MemOS | 6,790 | 608 | Python | rag | agent-memory-systems | 0 | 284 | - | AI memory OS for LLM and Agent systems, persistent Skill memory |
| volcengine/MineContext | 5,049 | 378 | Python | agents | agent-memory-systems | 0 | 7 | 2025-06-24 | Proactive context-aware AI partner |
| MemMachine/MemMachine | 4,826 | 155 | Python | agents | agent-memory-infrastructure | 0 | 68 | - | Universal memory layer with scalable, extensible storage |
| MCP-UI-Org/mcp-ui | 4,525 | 333 | TypeScript | mcp | model-context-protocol | 0 | 5 | - | UI over MCP |
| StructuredLabs/preswald | 4,303 | 649 | Python | data-engineering | code-context-packaging | 0 | - | - | WASM packager for Python data apps |
| memgraph/memgraph | 3,841 | 216 | C++ | vector-db | agent-memory-infrastructure | 0 | 82 | - | Open-source graph database for dynamic analytics |
| CaviraOSS/OpenMemory | 3,604 | 412 | TypeScript | vector-db | agent-memory-systems | 0 | 9 | 2025-10-19 | Local persistent memory store for LLM apps |
| aiming-lab/SimpleMem | 3,182 | 310 | Python | embeddings | agent-memory-systems | 1,854 | 0 | - | Efficient Lifelong Memory for LLM Agents |
| tw93/Kaku | 3,045 | 150 | Rust | ai-coding | claude-code-session-management | 0 | 350 | - | Fast terminal built for AI coding |
| stravu/crystal | 2,980 | 186 | TypeScript | ai-coding | claude-code-session-management | 0 | 0 | - | Run multiple Codex/Claude Code sessions in parallel worktrees |
| Meirtz/Awesome-Context-Engineering | 2,977 | 200 | - | rag | context-packaging-systems | 0 | 13 | - | Comprehensive survey on Context Engineering |
| google-agentic-commerce/AP2 | 2,847 | 402 | Python | generative-ai | model-context-protocol | 0 | 0 | - | Secure AI-Driven Payments protocol |
| batrachianai/toad | 2,660 | 115 | Python | agents | claude-code-session-management | 0 | 37 | - | Unified interface for AI in terminal |
| memodb-io/memobase | 2,599 | 197 | Python | rag | agent-memory-systems | 4,277 | 0 | - | User Profile-Based Long-Term Memory for AI Chatbot Apps |
| kingjulio8238/Memary | 2,576 | 193 | Jupyter Notebook | rag | agent-memory-systems | 39 | - | - | Open Source Memory Layer For Autonomous Agents |
| EverMind-AI/EverMemOS | 2,570 | 283 | Python | rag | agent-memory-systems | 0 | 16 | - | Long-term memory for 24/7 OpenClaw agents |
| srbhptl39/MCP-SuperAssistant | 2,337 | 307 | TypeScript | mcp | model-context-protocol | 0 | 0 | - | MCP for ChatGPT, DeepSeek, Perplexity, Grok, etc. |
| CortexReach/memory-lancedb-pro | 2,280 | 392 | TypeScript | vector-db | agent-memory-systems | 0 | 293 | - | Enhanced LanceDB memory plugin for OpenClaw |
| agentscope-ai/ReMe | 2,185 | 161 | Python | rag | agent-memory-systems | 0 | 79 | - | Memory Management Kit for Agents |
| microsoft/kernel-memory | 2,139 | 397 | C# | embeddings | agent-memory-systems | 0 | 0 | - | Memory solution for users, teams, and applications |
| cyberagiinc/DevDocs | 2,039 | 184 | TypeScript | mcp | model-context-protocol | 0 | 0 | - | Free, private Tech Documentation MCP server |
| kayba-ai/agentic-context-engine | 1,978 | 250 | Python | agents | agent-memory-infrastructure | 0 | 208 | - | Make your agents learn from experience |
| shcherbak-ai/contextgem | 1,810 | 145 | Python | prompt-engineering | codebase-context-extraction | 3,288 | 2 | - | Effortless LLM extraction from documents |
| MCPJam/inspector | 1,798 | 199 | TypeScript | mcp | model-context-protocol | 6,882 | 184 | - | Test & Debug MCP servers |
| abinthomasonline/repo2txt | 1,763 | 210 | TypeScript | llm-tools | code-context-packaging | 0 | 0 | - | Convert GitHub repos to single text file |
| a2aproject/a2a-python | 1,729 | 384 | Python | agents | model-context-protocol | 0 | 14 | - | Official Python SDK for A2A Protocol |
| allenai/bi-att-flow | 1,540 | 672 | Python | nlp | memory-networks-qa | 0 | - | - | Bi-directional Attention Flow for QA |
| doobidoo/mcp-memory-service | 1,504 | 215 | Python | mcp | agent-memory-systems | 0 | 167 | 2024-12-26 | Persistent memory for AI agent pipelines + Claude |
| a2aproject/a2a-samples | 1,385 | 602 | Jupyter Notebook | generative-ai | model-context-protocol | 0 | 8 | - | A2A Protocol samples |
| BAI-LAB/MemoryOS | 1,256 | 127 | Python | rag | agent-memory-systems | 0 | 5 | - | [EMNLP 2025 Oral] Memory operating system for personalized AI agents |
| Open-Source-Legal/OpenContracts | 1,235 | 133 | Python | agents | agent-memory-systems | 0 | 708 | - | Document annotation, version control, semantic search + MCP |
| yjacquin/fast-mcp | 1,149 | 102 | Ruby | mcp | model-context-protocol | 0 | - | - | Ruby MCP Implementation |
| arabold/docs-mcp-server | 1,127 | 132 | TypeScript | mcp | model-context-protocol | 3,839 | 43 | - | Grounded Docs MCP Server |
| CoderLuii/HolyClaude | 1,061 | 109 | Dockerfile | agents | claude-code-session-management | 0 | 11 | - | AI coding workstation |
| localminimum/QANet | 982 | 300 | Python | nlp | memory-networks-qa | 0 | - | - | QANet for machine reading comprehension |
| rohitg00/awesome-devops-mcp-servers | 961 | 180 | - | mcp | model-context-protocol | 0 | 37 | - | Curated list of DevOps MCP servers |
| kbwo/ccmanager | 946 | 76 | TypeScript | agents | claude-code-session-management | 3,779 | 47 | - | Session Manager for Claude Code / Gemini CLI / Codex CLI |
| pathintegral-institute/mcpm.sh | 906 | 94 | Python | mcp | model-context-protocol | 0 | 3 | - | CLI MCP package manager & registry |
| QuantGeekDev/mcp-framework | 905 | 103 | TypeScript | mcp | model-context-protocol | 251,866 | 0 | - | Framework for writing MCP servers in TypeScript |
| agiresearch/A-mem | 883 | 94 | Python | llm-tools | agent-memory-architectures | 0 | - | - | A-MEM: Agentic Memory for LLM Agents |
| alioshr/memory-bank-mcp | 877 | 84 | TypeScript | mcp | agent-memory-systems | 0 | - | - | MCP server for remote memory bank management |
| zilliztech/memsearch | 846 | 77 | Python | embeddings | agent-memory-systems | 0 | 128 | - | Markdown-first memory system for any AI agent |
| carpedm20/MemN2N-tensorflow | 827 | 248 | Python | nlp | memory-networks-qa | 0 | - | - | End-To-End Memory Networks in Tensorflow |
| context-space/context-space | 805 | 81 | Go | mcp | codebase-context-generation | 0 | - | - | Context Engineering Infrastructure |
| lich0821/ccNexus | 783 | 94 | Go | ai-coding | claude-code-session-management | 0 | 26 | - | Intelligent API gateway for Claude Code |
| six2dez/burp-ai-agent | 776 | 124 | Kotlin | mcp | model-context-protocol | 0 | 2 | - | Burp Suite MCP extension |
| yzfly/douyin-mcp-server | 759 | 148 | HTML | mcp | model-context-protocol | 0 | 0 | - | Douyin MCP server |
| chopratejas/headroom | 724 | 72 | Python | rag | context-packaging-systems | 0 | 164 | - | Context Optimization Layer for LLM Applications |

### 1b. Cross-domain: repos about agent memory regardless of subcategory (stars >= 10)

| Repo | Stars | Domain | Subcategory | Language | Commits 30d | Created | Description |
|------|-------|--------|-------------|----------|-------------|---------|-------------|
| mem0ai/mem0 | 49,646 | rag | agent-memory-systems | Python | 146 | 2023-06-20 | Universal memory layer for AI Agents |
| getzep/graphiti | 23,665 | rag | graph-database-rag | Python | 26 | - | Build Real-Time Knowledge Graphs for AI Agents |
| abhigyanpatwari/GitNexus | 19,233 | ai-coding | codebase-search-indexing | TypeScript | 278 | - | Zero-Server Code Intelligence Engine, client-side knowledge graph |
| memvid/memvid | 13,421 | vector-db | agent-memory-systems | Rust | 6 | 2025-05-27 | Serverless single-file memory layer |
| topoteretes/cognee | 13,204 | vector-db | agent-memory-systems | Python | 393 | 2023-08-16 | Knowledge Engine for AI Agent Memory |
| MemoriLabs/Memori | 12,351 | rag | agent-memory-systems | Python | 64 | - | SQL Native Memory Layer for LLMs |
| MemMachine/MemMachine | 4,826 | agents | agent-memory-infrastructure | Python | 68 | - | Universal memory layer, scalable storage |
| xerrors/Yuxi | 4,691 | rag | langraph-production-agents | Python | 232 | - | Agent harness with LightRAG knowledge base + knowledge graphs |
| xerrors/Yuxi-Know | 4,533 | rag | langraph-production-agents | Python | 232 | - | LightRAG knowledge base + knowledge graphs platform |
| CaviraOSS/OpenMemory | 3,604 | vector-db | agent-memory-systems | TypeScript | 9 | 2025-10-19 | Local persistent memory store for LLM apps |
| campfirein/cipher | 3,578 | mcp | claude-skill-orchestration | TypeScript | 8 | - | Memory layer for coding agents (Cursor, Codex, Claude Code) |
| pashpashpash/vault-ai | 3,400 | llm-tools | openai-api-quickstarts | JavaScript | - | - | Give ChatGPT long-term memory (OpenAI + Pinecone) |
| memodb-io/Acontext | 3,154 | agents | agent-skill-registry | TypeScript | 188 | 2025-07-16 | Agent Skills as a Memory Layer |
| memodb-io/memobase | 2,599 | rag | agent-memory-systems | Python | 0 | - | User Profile-Based Long-Term Memory |
| kingjulio8238/Memary | 2,576 | rag | agent-memory-systems | Jupyter Notebook | - | - | Open Source Memory Layer For Autonomous Agents |
| EverMind-AI/EverMemOS | 2,570 | rag | agent-memory-systems | Python | 16 | - | Long-term memory for 24/7 OpenClaw agents |
| doobidoo/mcp-memory-service | 1,504 | mcp | agent-memory-systems | Python | 167 | 2024-12-26 | Persistent memory for AI agent pipelines + Claude |
| moyangzhan/langchain4j-aideepin | 1,196 | rag | spring-boot-rag-apps | Java | 3 | - | AI productivity tools with long-term memory |
| morettt/my-neuro | 1,061 | llm-tools | ai-virtual-companions | JavaScript | 205 | - | AI desktop companion with voice + memory |
| ref-tools/ref-tools-mcp | 1,007 | mcp | mcp-client-configuration | TypeScript | 0 | - | Help coding agents avoid context window waste |
| Victorwz/LongMem | 822 | transformers | llm-scaling-architecture | Python | - | - | [NeurIPS 2023] Augmenting LLMs with Long-Term Memory |
| jmuncor/tokentap | 761 | llm-tools | llm-cost-tracking | Python | 0 | - | Intercept LLM API traffic, track token usage |
| RichmondAlake/memorizz | 692 | embeddings | agent-memory-systems | Python | 1 | - | Memory layer leveraging popular databases |
| caspianmoon/memoripy | 682 | embeddings | agent-memory-architectures | Python | - | - | Short- and long-term storage with semantic clustering |
| datamllab/LongLM | 666 | transformers | diffusion-language-models | Python | - | - | [ICML'24] Self-Extend LLM Context Window Without Tuning |
| mem0ai/mem0-chrome-extension | 656 | llm-tools | multi-ai-workspace | TypeScript | - | - | Long-term memory for ChatGPT, Claude, Perplexity, Grok |
| Dataojitori/nocturne_memory | 615 | mcp | agent-memory-systems | Python | 102 | - | Lightweight rollbackable Long-Term Memory MCP Server |
| IAAR-Shanghai/Awesome-AI-Memory | 499 | rag | agent-memory-systems | Python | - | - | Curated knowledge base on AI memory for LLMs and agents |
| oceanbase/powermem | 493 | agents | agent-memory-systems | Python | - | - | AI-Powered Long-Term Memory (OpenClaw compatible) |
| winstonkoh87/Athena-Public | 429 | agents | agent-memory-systems | Python | - | - | The Linux OS for AI Agents -- persistent memory + autonomy |
| samvallad33/vestige | 416 | mcp | agent-memory-systems | Rust | - | - | Cognitive memory with FSRS-6 spaced repetition, 29 brain modules |
| trvon/yams | 366 | vector-db | agent-memory-architectures | C++ | - | - | Persistent memory with content-addressed storage, vector search |
| agentic-box/memora | 322 | mcp | agent-memory-systems | Python | - | - | Persistent memory MCP server, knowledge graphs, cross-session |
| Dicklesworthstone/cass_memory_system | 275 | agents | agent-memory-infrastructure | TypeScript | - | - | Procedural memory for AI coding agents |
| Arvincreator/project-golem | 274 | agents | go-agent-frameworks | JavaScript | - | - | OS-level autonomous AI agent with long-term memory |
| MCG-NJU/MeMOTR | 218 | computer-vision | multi-object-tracking | Python | - | - | [ICCV 2023] Long-Term Memory-Augmented Transformer |
| AVIDS2/memorix | 208 | mcp | agent-memory-systems | TypeScript | - | - | Cross-Agent Memory Bridge for 10+ IDEs |
| savantskie/persistent-ai-memory | 207 | vector-db | agent-memory-systems | Python | - | - | Persistent local memory for AI in VS Code |
| ScottRBK/forgetful | 194 | agents | agent-memory-infrastructure | Python | - | - | Opensource Memory for Agents |
| davegoldblatt/total-recall | 185 | agents | claude-code-memory | Shell | - | - | Persistent memory plugin for Claude Code |
| LeDat98/NexusRAG | 179 | rag | enterprise-agentic-rag | Python | - | - | Hybrid RAG with knowledge graph |
| smixs/agent-second-brain | 172 | agents | claude-agent-frameworks | Python | - | - | Voice notes -> knowledge base with persistent memory |
| jw782cn/RepoChat-200k | 171 | llm-tools | streamlit-llm-interfaces | Python | - | - | Chat with GitHub Repo using 200k context window |
| bassimeledath/dispatch | 163 | agents | claude-code-development-templates | - | - | - | 10x context window by dispatching to background AI workers |
| tomasonjo-labs/legal-tech-chat | 152 | llm-tools | langgraph-agent-systems | Jupyter Notebook | - | - | Knowledge graph from legal contracts |
| jshuadvd/LongRoPE | 151 | transformers | transformer-training-optimization | Python | - | - | LongRoPE: Context Window Beyond 2 Million Tokens |
| JasonDocton/lucid-memory | 132 | vector-db | agent-memory-systems | TypeScript | - | - | Memory for AI, 13x faster than Pinecone, 5x leaner than RAG |
| varun29ankuS/shodh-memory | 124 | agents | agent-memory-systems | Rust | - | - | Cognitive memory, learns from use, forgets irrelevant |
| knowns-dev/knowns | 123 | agents | agent-memory-infrastructure | TypeScript | - | - | Memory layer for AI-native development |
| Intina47/context-sync | 120 | mcp | session-context-memory | TypeScript | - | - | Local persistent memory store for LLM apps |

### 1c. Infrastructure players: vector DBs & embeddings (stars >= 500)

| Repo | Stars | Domain | Subcategory | Language | Downloads/mo | Commits 30d | Description |
|------|-------|--------|-------------|----------|-------------|-------------|-------------|
| supabase/supabase | 98,969 | vector-db | agentic-workflow-orchestration | TypeScript | 0 | 587 | Postgres development platform for web, mobile, and AI |
| meilisearch/meilisearch | 56,362 | vector-db | semantic-search-engines | Rust | 2,138,678 | 222 | Lightning-fast search engine API with AI-powered hybrid search |
| Mintplex-Labs/anything-llm | 56,148 | vector-db | local-llm-orchestration | JavaScript | 0 | 94 | All-in-one AI productivity accelerator |
| pathwaycom/llm-app | 56,145 | vector-db | local-llm-orchestration | Jupyter Notebook | 110 | 0 | Cloud templates for RAG, AI pipelines, enterprise search |
| milvus-io/milvus | 43,332 | vector-db | milvus-vector-database | Go | 0 | 202 | High-performance cloud-native vector database |
| qdrant/qdrant | 29,544 | vector-db | qdrant-vector-search | Rust | 15,117,788 | 214 | High-performance Vector Database for next-gen AI |
| chroma-core/chroma | 26,607 | vector-db | chroma-database-tools | Rust | 13,607,187 | 139 | Open-source search and retrieval database for AI |
| srbhr/Resume-Matcher | 26,295 | embeddings | resume-screening-matching | TypeScript | 0 | 67 | Resume improvement with AI insights |
| typesense/typesense | 25,376 | embeddings | semantic-search-frontends | C++ | 3,495 | 32 | Alternative to Algolia + Pinecone |
| VectifyAI/PageIndex | 21,374 | vector-db | local-pdf-rag-systems | Python | 0 | 32 | Vectorless Reasoning-based RAG |
| amark/gun | 18,963 | vector-db | zero-knowledge-ml | JavaScript | 108,523 | 0 | Decentralized graph data sync protocol |
| weaviate/weaviate | 15,793 | vector-db | weaviate-ecosystem | Go | 50,144,883 | 660 | Open-source vector database with objects + vectors |
| memvid/memvid | 13,421 | vector-db | agent-memory-systems | Rust | 0 | 6 | Single-file memory layer for AI Agents |
| topoteretes/cognee | 13,204 | vector-db | agent-memory-systems | Python | 77,871 | 393 | Knowledge Engine for AI Agent Memory |
| jina-ai/clip-as-service | 12,825 | embeddings | clip-vision-language | Python | 1,438 | - | Scalable embedding for images and sentences |
| neuml/txtai | 12,281 | vector-db | local-llm-orchestration | Python | 60,341 | 22 | All-in-one AI framework for semantic search + LLM workflows |
| Embedding/Chinese-Word-Vectors | 12,188 | embeddings | pretrained-embedding-models | Python | 0 | - | 100+ Chinese Word Vectors |
| FlagOpen/FlagEmbedding | 11,395 | embeddings | self-hosted-embedding-servers | Python | 385,607 | 18 | Retrieval and Retrieval-augmented LLMs |
| langchain4j/langchain4j | 11,081 | vector-db | langchain-framework-guides | Java | 0 | 116 | Java library for LLM integration |
| yichuan-w/LEANN | 10,303 | vector-db | local-rag-stacks | Python | 5,822 | 9 | [MLsys 2026] RAG with 97% storage savings |
| oramasearch/orama | 10,221 | vector-db | semantic-search-engines | TypeScript | 0 | 0 | Search engine + RAG in browser/server/edge |
| oceanbase/oceanbase | 10,013 | vector-db | rust-native-vectordbs | C++ | 0 | 208 | Fastest Distributed DB for transactional + AI |
| gorse-io/gorse | 9,549 | embeddings | recommendation-system-frameworks | Go | 0 | 15 | AI recommender with classical/LLM rankers |
| lancedb/lancedb | 9,425 | vector-db | vector-db-benchmarking | HTML | 6,082,637 | 69 | Embedded retrieval library for multimodal AI |
| databendlabs/databend | 9,196 | vector-db | rust-native-vectordbs | Rust | 286 | 79 | Data Agent Ready Warehouse |
| activeloopai/deeplake | 9,033 | vector-db | vector-database-management | C++ | 218,428 | 0 | Database for AI with versioning |
| alibaba/zvec | 8,900 | vector-db | high-performance-vector-search | C++ | 0 | 57 | Lightweight, fast, in-process vector database |
| reorproject/reor | 8,535 | vector-db | agent-memory-systems | JavaScript | 0 | - | Local AI knowledge management |
| zilliztech/GPTCache | 7,963 | embeddings | agent-memory-systems | Python | 463,836 | - | Semantic cache for LLMs |
| zilliztech/deep-searcher | 7,700 | vector-db | claude-code-knowledge-systems | Python | 0 | - | Deep Research on Private Data |

---

## 2. Subcategory Quality Distribution

| Subcategory | Domain | Repo Count | Avg Stars | Max Stars | Total Downloads/mo |
|-------------|--------|-----------|-----------|-----------|-------------------|
| agent-memory-systems | mcp | 358 | 20 | 1,504 | 30,351 |
| model-context-protocol | llm-tools | 223 | 10 | 334 | 3,947 |
| agent-memory-systems | embeddings | 219 | 72 | 7,963 | 472,134 |
| agent-memory-infrastructure | agents | 208 | 43 | 4,826 | 1,816 |
| code-context-packaging | llm-tools | 199 | 28 | 1,763 | 18,524 |
| agent-memory-systems | vector-db | 146 | 302 | 13,421 | 82,823 |
| codebase-context-extraction | prompt-engineering | 140 | 76 | 7,220 | 8,019 |
| agent-memory-systems | rag | 132 | 691 | 49,646 | 103,698 |
| agent-memory-systems | agents | 122 | 358 | 34,460 | 11,683 |
| claude-code-session-management | ai-coding | 99 | 80 | 3,045 | 4,198 |
| codebase-context-generation | mcp | 80 | 32 | 805 | 0 |
| model-context-protocol | mcp | 76 | 650 | 13,403 | 445,291 |
| agent-context-compilation | agents | 72 | 22 | 444 | 11,422 |
| claude-code-memory | agents | 70 | 17 | 681 | 437 |
| memory-augmented-architectures | ml-frameworks | 62 | 7 | 86 | 43 |
| agent-memory-architectures | llm-tools | 61 | 20 | 883 | 1,118 |
| session-context-memory | mcp | 59 | 7 | 120 | 1,281 |
| context-packaging-systems | rag | 47 | 86 | 2,977 | 1,581 |
| agent-memory | mcp | 37 | 2 | 19 | 4,982 |
| model-context-protocol | generative-ai | 32 | 138 | 2,847 | 219 |
| ai-session-persistence | ai-coding | 32 | 5 | 64 | 76 |
| ai-agent-memory-systems | llm-tools | 30 | 4 | 37 | 15 |
| memory-networks-qa | nlp | 30 | 207 | 1,540 | 0 |
| ai-context-format | mcp | 18 | 3 | 21 | 0 |
| claude-code-session-management | agents | 4 | 1,180 | 2,660 | 3,779 |
| model-context-protocol | agents | 4 | 6,199 | 22,488 | 0 |
| code-context-packaging | ai-coding | 3 | 167 | 355 | 0 |
| memory-augmented-architectures | agents | 2 | 176 | 278 | 0 |

**Key finding:** "agent-memory-systems" spans 5 domains (mcp, embeddings, vector-db, rag, agents) totaling ~977 repos. This is a massive, fragmented category.

---

## 3. Nucleation Signals

### 3a. Category Creation Velocity

| Domain | Subcategory | New Repos 7d | New Repos 14d | New Stars 7d | Acceleration | Silent Creation? |
|--------|-------------|-------------|--------------|-------------|-------------|-----------------|
| mcp | agent-memory-systems | 55 | 77 | 220 | 2.50 | Yes |
| agents | agent-memory-infrastructure | 36 | 67 | 154 | 1.16 | Yes |
| embeddings | agent-memory-systems | 30 | 49 | 32 | 1.58 | Yes |
| agents | agent-memory-systems | 21 | 39 | 64 | 1.17 | Yes |
| ai-coding | claude-code-session-management | 19 | 43 | 122 | 0.79 | Yes |
| agents | claude-code-memory | 19 | 29 | 59 | 1.90 | Yes |
| rag | agent-memory-systems | 17 | 30 | 16 | 1.31 | Yes |
| llm-tools | model-context-protocol | 14 | 53 | 61 | 0.36 | Yes |
| mcp | session-context-memory | 12 | 13 | 14 | 12.00 | Yes |
| llm-tools | agent-memory-architectures | 11 | 31 | 33 | 0.55 | Yes |
| mcp | codebase-context-generation | 9 | 14 | 20 | 1.80 | Yes |
| llm-tools | code-context-packaging | 9 | 27 | 15 | 0.50 | Yes |
| mcp | agent-memory | 9 | 14 | 9 | 1.80 | Yes |
| vector-db | agent-memory-systems | 8 | 14 | 7 | 1.33 | Yes |
| rag | context-packaging-systems | 6 | 9 | 2 | 2.00 | Yes |
| prompt-engineering | codebase-context-extraction | 6 | 9 | 3 | 2.00 | Yes |
| agents | agent-context-compilation | 5 | 10 | 39 | 1.00 | Yes |
| ai-coding | ai-session-persistence | 4 | 7 | 3 | 1.33 | Yes |

**Key finding:** 55 new agent-memory MCP repos in 7 days. Session-context-memory has 12x acceleration. All categories show "creation without buzz" -- builders are shipping memory infrastructure before the narrative catches up.

### 3b. Project-Level Nucleation Signals

| Repo | Nucleation Score | Narrative Gap | Star Delta 7d | Stars | Domain | Subcategory |
|------|-----------------|---------------|---------------|-------|--------|-------------|
| topoteretes/cognee | 37 | No | 0 | 13,204 | vector-db | agent-memory-systems |
| doobidoo/mcp-memory-service | 37 | No | 0 | 1,504 | mcp | agent-memory-systems |
| googleapis/genai-toolbox | 37 | No | 0 | 13,403 | mcp | model-context-protocol |
| mem0ai/mem0 | 37 | No | 0 | 49,646 | rag | agent-memory-systems |
| thedotmack/claude-mem | 35 | No | 0 | 34,460 | agents | agent-memory-systems |
| doobidoo/MCP-Context-Provider | 34 | Yes | 28 | 28 | llm-tools | model-context-protocol |
| garan0613/ai-memory-gateway | 30 | Yes | 15 | 15 | llm-tools | agent-memory-architectures |

---

## 4. Hacker News Signal (Last 90 Days)

| Title | Points | Comments | Date | Project |
|-------|--------|----------|------|---------|
| Zvec: A lightweight, fast, in-process vector database | 226 | 45 | 2026-02-13 | - |
| Show HN: Rowboat -- AI coworker with knowledge graph (OSS) | 205 | 56 | 2026-02-10 | - |
| Show HN: Badge showing codebase fit in LLM context window | 88 | 41 | 2026-02-27 | openclaw |
| A header-only C vector database library | 88 | 53 | 2026-02-14 | - |
| Lat.md: Agent Lattice: knowledge graph for codebase | 83 | 56 | 2026-03-29 | agent |
| Show HN: FaceTime-style calls with AI (long-term memory) | 34 | 25 | 2026-01-25 | - |
| Show HN: Pinecone Explorer -- Desktop GUI for Pinecone | 31 | 6 | 2026-01-28 | Pinecone |
| You Don't Need a Vector Database | 20 | 24 | 2026-03-08 | - |
| Added 1M context window for Opus 4.6 by default | 20 | 4 | 2026-03-13 | Claude |
| Zvec: SQLite-like simplicity in embedded vector DB (Alibaba) | 15 | 2 | 2026-02-12 | sim |
| Show HN: TraceMem -- trace-native memory layer for agents | 15 | 1 | 2026-01-12 | agent |
| Zvec is a lightweight, fast, in-process vector database | 13 | 0 | 2026-02-14 | - |
| Show HN: NERDs -- Entity-centered long-term memory for LLM agents | 13 | 5 | 2026-03-06 | agent |
| Show HN: A file-based agent memory framework | 11 | 4 | 2026-01-06 | agent |
| Google PM open-sources Always On Memory Agent, ditching vector DBs | 11 | 4 | 2026-03-07 | go |

**Key finding:** "You Don't Need a Vector Database" post + Zvec (SQLite-like simplicity) + file-based memory frameworks = narrative shift toward simpler, embedded memory over managed vector DB infrastructure.

---

## 5. Newsletter Coverage (Last 90 Days)

| Title | Feed | Date | Sentiment | Summary |
|-------|------|------|-----------|---------|
| Claude Code source code leak exposure | latent-space | 2026-04-01 | negative | Exposed architecture details on agent orchestration, memory systems, planning logic |
| Long-Form Speech Generation: 30K Context Window | latent-space | 2026-03-30 | positive | Voxtral extends context from 32s to 40min via causal encoding |
| Claude 1M Context Window and Memory Features Released | zvi | 2026-03-25 | positive | Claude supports 1M token context + free memory features |
| HF releases hf-mount filesystem for agents | latent-space | 2026-03-25 | positive | Agents effective at filesystem operations |
| Agent Memory and Personalization Systems | latent-space | 2026-03-20 | positive | Dreamer invests in agentic memory, moving from vector/RAG to more efficient techniques |
| Claude 1M context window becomes default | zvi | 2026-03-19 | mixed | Some users report performance degradation at max capacity |
| Context Window Limitations Drive Subagent Design | simon-willison | 2026-03-17 | neutral | LLMs capped at ~1M, driving subagent patterns |
| Claude 1M Context Window GA with SOTA Performance | latent-space | 2026-03-14 | positive | 78.3% on MRCR v2 benchmark, no API charges for long context |
| 1M Context Window Plateau: Hardware Constraints | latent-space | 2026-03-14 | negative | Context windows stalled at 1M for 2 years; HBM/DRAM limits |
| Agent Persistent Memory Becomes Key Differentiator | latent-space | 2026-03-14 | positive | IBM shows reusing agent strategies improves task completion |
| Context window decay limits practical usability above 256K | latent-space | 2026-03-06 | negative | GPT-5.4 degrades beyond 256K; 36% accuracy at 512K-1M |
| Dynamic file context for agent memory management | latent-space | 2026-03-06 | positive | Cursor explored dynamic file systems for agent memory |
| GitNexus enables browser-based repo knowledge graphs | latent-space | 2026-03-03 | positive | Graph-RAG in-browser with embedded KuzuDB |
| Claude Memory Export Feature Launch | simon-willison | 2026-03-01 | positive | Import/export for Claude's memory system |
| Microsoft Copilot Tasks adds persistent memory | latent-space | 2026-02-27 | positive | Task delegation with persistent multi-session memory |
| Qwen 3.5-397B released with 1M context window | zvi | 2026-02-19 | neutral | Competing on extended context capabilities |
| Anthropic adjusts Claude pricing for 1M context | zvi | 2026-02-19 | neutral | Ends discounted 1M context, moves to API pricing |
| Context window management through compacting | oneusefulthing | 2026-01-07 | positive | Claude Code compacting: creates notes, clears memory for long work |

**Key finding:** Massive newsletter signal -- 18 articles in 90 days. The dominant narrative: context windows have plateaued at 1M tokens, performance degrades above 256K, so persistent memory systems are becoming THE way to give agents long-term state. Multiple major players (Microsoft, Anthropic, IBM) are shipping memory features.

---

## 6. Top Repos Detail (Featured List Candidates)

| Repo | Stars | Forks | Language | License | Downloads/mo | Commits 30d | Created | Last Push | Subcategory | AI Summary |
|------|-------|-------|----------|---------|-------------|-------------|---------|-----------|-------------|------------|
| mem0ai/mem0 | 49,646 | 5,542 | Python | Apache-2.0 | 0 | 146 | 2023-06-20 | 2026-03-13 | agent-memory-systems | Multi-level memory (user, session, agent state) with 26% higher accuracy and 90% lower token usage. Python/JS SDKs, LangGraph + CrewAI integrations. |
| thedotmack/claude-mem | 34,460 | 2,414 | TypeScript | NOASSERTION | 6,486 | 53 | 2025-08-31 | 2026-03-13 | agent-memory-systems | Persistent memory with progressive disclosure, skill-based search, web UI viewer. Built on Claude's agent-sdk. |
| memvid/memvid | 13,421 | 1,123 | Rust | Apache-2.0 | 0 | 6 | 2025-05-27 | 2026-03-03 | agent-memory-systems | Append-only frame-based architecture in single `.mv2` file with sub-5ms retrieval. Node.js/Python/Rust SDKs. |
| topoteretes/cognee | 13,204 | 1,336 | Python | Apache-2.0 | 77,871 | 393 | 2023-08-16 | 2026-03-12 | agent-memory-systems | Vector + graph hybrid retrieval, multimodal ingestion, ontology grounding, audit trails. CLI + web UI. |
| MemoriLabs/Memori | 12,351 | 1,112 | Python | NOASSERTION | 20,201 | 64 | - | 2026-03-13 | agent-memory-systems | SQL-native, intercepts LLM conversations automatically. 81.95% accuracy, ~5% token usage vs full context. |
| volcengine/OpenViking | 7,606 | 541 | Python | Apache-2.0 | 70,261 | 378 | - | 2026-03-13 | agent-memory-systems | Three-tier hierarchical storage (L0/L1/L2), directory-based + semantic retrieval, visualization. |
| MemTensor/MemOS | 6,790 | 608 | Python | Apache-2.0 | 0 | 284 | - | 2026-03-12 | agent-memory-systems | Graph-based memory with multi-modal support, 43.70% accuracy gains over OpenAI Memory, 35.24% token reduction. |
| volcengine/MineContext | 5,049 | 378 | Python | Apache-2.0 | 0 | 7 | 2025-06-24 | 2026-03-12 | agent-memory-systems | Captures screenshots, builds multimodal context DB, proactive resurfacing. Local-first. |
| MemMachine/MemMachine | 4,826 | 155 | Python | Apache-2.0 | 0 | 68 | - | 2026-03-13 | agent-memory-infrastructure | Three memory types (episodic/graph, profile/SQL, working/session). MCP server, LangChain/LangGraph/CrewAI support. |
| CaviraOSS/OpenMemory | 3,604 | 412 | TypeScript | Apache-2.0 | 0 | 9 | 2025-10-19 | 2026-03-04 | agent-memory-systems | Multi-sector memory (episodic, semantic, procedural) with temporal reasoning. Self-hosted SQLite/Postgres. |
| campfirein/cipher | 3,578 | 360 | TypeScript | NOASSERTION | 0 | 8 | - | 2026-01-25 | claude-skill-orchestration | Dual-layer memory for code concepts + AI reasoning traces. Multi-LLM, multi-vector-store support. |
| aiming-lab/SimpleMem | 3,182 | 310 | Python | MIT | 1,854 | 0 | - | 2026-03-10 | agent-memory-systems | Three-stage semantic compression pipeline. MCP servers for Claude Desktop, Cursor. 64% better than Claude native memory. |
| memodb-io/Acontext | 3,154 | 296 | TypeScript | Apache-2.0 | 0 | 188 | 2025-07-16 | 2026-03-13 | agent-skill-registry | Skills as memory: extracts conversation traces into editable Markdown files. No embeddings needed. |
| memodb-io/memobase | 2,599 | 197 | Python | Apache-2.0 | 4,277 | 0 | - | 2026-01-11 | agent-memory-systems | User profiles + timestamped timelines, sub-100ms SQL retrieval. 40-50% token cost reduction. |
| kingjulio8238/Memary | 2,576 | 193 | Jupyter Notebook | MIT | 39 | - | - | 2024-10-22 | agent-memory-systems | Multi-layer: episodic streams, entity knowledge graphs, dynamic personas. FalkorDB/Neo4j + Ollama. |
| EverMind-AI/EverMemOS | 2,570 | 283 | Python | Apache-2.0 | 0 | 16 | - | 2026-03-08 | agent-memory-systems | Structured extraction, MongoDB/Milvus/Elasticsearch storage, BM25 + semantic + agentic search. |
| CortexReach/memory-lancedb-pro | 2,280 | 392 | TypeScript | - | 0 | 293 | - | 2026-03-13 | agent-memory-systems | Weibull decay model, 6 semantic categories, fused vector+BM25 with cross-encoder reranking. |
| agentscope-ai/ReMe | 2,185 | 161 | Python | Apache-2.0 | 0 | 79 | - | 2026-03-12 | agent-memory-systems | Dual file + vector memory, compactor for context windows, human-readable Markdown persistence. |

---

## 7. OpenClaw/Hermes/Claude Code Memory Ecosystem

| Repo | Stars | Subcategory | Description | Created |
|------|-------|-------------|-------------|---------|
| thedotmack/claude-mem | 34,460 | agent-memory-systems | Claude Code plugin, captures + compresses sessions | 2025-08-31 |
| qwibitai/nanoclaw | 22,150 | personal-ai-agents | Lightweight OpenClaw alternative in containers | - |
| volcengine/OpenViking | 7,606 | agent-memory-systems | Context database for OpenClaw agents | - |
| MemTensor/MemOS | 6,790 | agent-memory-systems | Memory OS for OpenClaw, persistent Skill memory | - |
| MemMachine/MemMachine | 4,826 | agent-memory-infrastructure | Universal memory layer for AI Agents | - |
| memodb-io/Acontext | 3,154 | agent-skill-registry | Agent Skills as a Memory Layer | 2025-07-16 |
| Mozilla-Ocho/Memory-Cache | 563 | ai-workflow-automation | MemoryCache: local desktop as on-device AI agent | - |
| oceanbase/powermem | 493 | agent-memory-systems | AI-Powered Long-Term Memory (OpenClaw compatible) | - |
| tugcantopaloglu/openclaw-dashboard | 415 | agent-monitoring-dashboards | Secure monitoring for OpenClaw agents with memory browser | - |
| aj-geddes/claude-code-bmad-skills | 338 | claude-skill-orchestration | BMAD skills for Claude Code with memory integration | - |
| memvid/claude-brain | 322 | agent-memory-systems | Give Claude Code photographic memory in single .mv2 file | - |
| Dicklesworthstone/cass_memory_system | 275 | agent-memory-infrastructure | Procedural memory for AI coding agents | - |
| jihe520/Agentic-Desktop-Pet | 225 | claude-agent-frameworks | Desktop pet with LLM + Memory + Emotion + Claude Code | - |
| xvirobotics/metabot | 222 | claude-code-platforms | Agent organization with shared memory + agent factory | - |
| Intrect-io/OpenSwarm | 212 | agent-memory-systems | AI dev team orchestrator with cognitive memory | - |
| freddy-schuetz/n8n-claw | 194 | personal-ai-agents | OpenClaw-inspired agent in n8n with RAG memory | - |
| davegoldblatt/total-recall | 185 | claude-code-memory | Persistent memory plugin for Claude Code | - |
| VAMFI/claude-user-memory | 162 | claude-code-development-templates | Autonomous agent substrate with TDD + multi-agent | - |
| memovai/memov | 162 | coding-agent | Git-like traceable memory for OpenClaw agents | - |
| pi22by7/In-Memoria | 158 | agent-memory-systems | Persistent Intelligence Infrastructure for AI Agents | - |

---

## 8. Release Activity (Last 30 Days)

| Repo | Releases in 30d | Latest Release |
|------|----------------|----------------|
| doobidoo/mcp-memory-service | 25 | 2026-03-31 |
| thedotmack/claude-mem | 8 | 2026-03-29 |
| topoteretes/cognee | 7 | 2026-03-30 |
| mem0ai/mem0 | 5 | 2026-03-28 |
| googleapis/genai-toolbox | 4 | 2026-03-27 |
| memvid/memvid | 2 | 2026-03-13 |
| a2aproject/A2A | 1 | 2026-03-12 |

**Key finding:** doobidoo/mcp-memory-service is shipping at breakneck pace (25 releases in 30 days). The top 4 memory-focused repos all released in the last 3 days. This is an extremely active space.

---

## Summary Observations for Deep Dive

1. **Scale:** ~977 repos tagged under "agent-memory-systems" across 5 domains. This is one of the largest emergent categories in the AI ecosystem.

2. **Clear leader:** mem0ai/mem0 at 49.6K stars is the category-defining project, but claude-mem (34.5K) shows the Claude Code ecosystem is driving massive demand.

3. **Architecture fragmentation:** Memory approaches span vector DBs (Milvus, Qdrant, Chroma), graph DBs (Memgraph, Neo4j via Cognee), SQL-native (Memori, Memobase), file-based (Memvid, ReMe), and hybrid systems. No single approach dominates.

4. **Context window paradox:** Despite 1M token windows being standard, newsletter coverage shows performance degrades above 256K. This creates ongoing demand for memory/compression systems.

5. **Nucleation signal:** 55 new MCP memory repos per week with "creation without buzz" -- builders are shipping infrastructure before the narrative catches up. Session-context-memory has 12x acceleration.

6. **OpenClaw ecosystem:** A rich ecosystem of memory plugins is forming around OpenClaw/Claude Code, with claude-mem, OpenViking, MemOS, and memory-lancedb-pro as the leading integrations.

7. **Shipping velocity:** The top memory repos are releasing constantly (25 releases/month for mcp-memory-service). This is not vaporware -- teams are actively iterating.

8. **Emerging pattern:** Move away from pure vector DB toward hybrid approaches (vector+graph+BM25+SQL) and toward simpler file-based systems (Memvid, ReMe, Acontext's Markdown-based skills).
