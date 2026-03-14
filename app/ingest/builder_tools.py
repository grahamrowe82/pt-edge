"""Seed builder_tools from a curated list and enrich with MCP status.

Phase 1 (seed): Upsert curated developer tools into builder_tools.
Phase 2 (enrich): Cross-reference each unchecked/stale builder_tool against
    ai_repos WHERE domain='mcp' using name matching + LLM fallback.

Run standalone:  python -m app.ingest.builder_tools
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.llm import call_haiku
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

STALE_DAYS = 7  # re-check MCP status after this many days

# ---------------------------------------------------------------------------
# Curated list of developer tools/services.
# (slug, name, category, website, description)
# ---------------------------------------------------------------------------
_CURATED_TOOLS: list[tuple[str, str, str, str, str]] = [
    # Cloud / Deploy
    ("aws", "AWS", "cloud", "https://aws.amazon.com", "Amazon's cloud platform offering compute, storage, networking, and 200+ managed services."),
    ("gcp", "Google Cloud", "cloud", "https://cloud.google.com", "Google's cloud platform for compute, data, ML, and infrastructure services."),
    ("azure", "Azure", "cloud", "https://azure.microsoft.com", "Microsoft's cloud platform integrating with Windows, Active Directory, and enterprise tooling."),
    ("render", "Render", "cloud", "https://render.com", "Platform for deploying web services, static sites, cron jobs, and databases with Git-based deploys."),
    ("vercel", "Vercel", "cloud", "https://vercel.com", "Frontend cloud platform optimized for Next.js with edge deploys and serverless functions."),
    ("netlify", "Netlify", "cloud", "https://netlify.com", "Platform for deploying static sites and serverless functions with Git-triggered builds."),
    ("fly", "Fly.io", "cloud", "https://fly.io", "Run Docker containers close to users across global edge locations with persistent volumes."),
    ("railway", "Railway", "cloud", "https://railway.app", "Deploy services and databases from Git repos or Docker images with minimal configuration."),
    ("cloudflare", "Cloudflare", "cloud", "https://cloudflare.com", "CDN, DNS, DDoS protection, and edge compute platform via Workers and Pages."),
    ("digitalocean", "DigitalOcean", "cloud", "https://digitalocean.com", "Cloud provider offering VMs, managed Kubernetes, databases, and object storage for developers."),
    ("heroku", "Heroku", "cloud", "https://heroku.com", "PaaS for deploying apps in multiple languages via Git push with managed add-ons."),
    ("hetzner", "Hetzner", "cloud", "https://hetzner.com", "European cloud provider offering low-cost dedicated servers and VMs with good price-to-performance."),
    ("linode", "Linode", "cloud", "https://linode.com", "Akamai-owned cloud platform offering VMs, Kubernetes, object storage, and managed databases."),
    ("vultr", "Vultr", "cloud", "https://vultr.com", "Global cloud provider offering bare metal, VMs, and Kubernetes across 32 locations."),
    ("coolify", "Coolify", "cloud", "https://coolify.io", "Self-hostable open-source PaaS for deploying apps and databases on your own servers."),

    # Databases
    ("supabase", "Supabase", "database", "https://supabase.com", "Open-source Firebase alternative providing Postgres, auth, storage, and realtime subscriptions."),
    ("neon", "Neon", "database", "https://neon.tech", "Serverless Postgres with branching, autoscaling, and scale-to-zero for cost efficiency."),
    ("planetscale", "PlanetScale", "database", "https://planetscale.com", "MySQL-compatible serverless database with non-blocking schema changes and branching workflow."),
    ("mongodb", "MongoDB", "database", "https://mongodb.com", "Document-oriented NoSQL database storing data as flexible JSON-like BSON documents."),
    ("redis", "Redis", "database", "https://redis.io", "In-memory data store used as a cache, message broker, and key-value database."),
    ("turso", "Turso", "database", "https://turso.tech", "Edge SQLite database built on libSQL, supporting per-user databases with low-latency reads."),
    ("upstash", "Upstash", "database", "https://upstash.com", "Serverless Redis and Kafka with per-request pricing and HTTP-based edge-compatible access."),
    ("cockroachdb", "CockroachDB", "database", "https://cockroachlabs.com", "Distributed SQL database designed for horizontal scaling, geo-partitioning, and high availability."),
    ("timescale", "Timescale", "database", "https://timescale.com", "PostgreSQL extension and managed service optimized for time-series data and analytics."),
    ("fauna", "Fauna", "database", "https://fauna.com", "Distributed document-relational database with a GraphQL API and multi-region replication."),
    ("xata", "Xata", "database", "https://xata.io", "Serverless Postgres platform with built-in search, branching, and a spreadsheet-like UI."),
    ("convex", "Convex", "database", "https://convex.dev", "Backend platform with a reactive database, server functions, and real-time sync for web apps."),
    ("firebase", "Firebase", "database", "https://firebase.google.com", "Google's app backend providing realtime NoSQL database, auth, hosting, and cloud functions."),
    ("dynamodb", "DynamoDB", "database", "https://aws.amazon.com/dynamodb", "AWS managed NoSQL key-value and document database with single-digit millisecond performance at scale."),
    ("elasticsearch", "Elasticsearch", "database", "https://elastic.co", "Distributed search and analytics engine built on Lucene for full-text and vector search."),
    ("pinecone", "Pinecone", "database", "https://pinecone.io", "Managed vector database for storing and querying high-dimensional embeddings in ML applications."),
    ("weaviate", "Weaviate", "database", "https://weaviate.io", "Open-source vector database with built-in ML model integration for semantic and hybrid search."),
    ("qdrant", "Qdrant", "database", "https://qdrant.tech", "Open-source vector similarity search engine written in Rust with filtering and payload support."),
    ("chromadb", "ChromaDB", "database", "https://trychroma.com", "Open-source embedding database designed for building LLM applications with simple Python and JS APIs."),
    ("milvus", "Milvus", "database", "https://milvus.io", "Open-source vector database built for billion-scale similarity search and AI applications."),

    # Dev tools / Version control
    ("github", "GitHub", "dev_tools", "https://github.com", "Git hosting platform with code review, issues, Actions CI/CD, and package registry."),
    ("gitlab", "GitLab", "dev_tools", "https://gitlab.com", "DevOps platform combining Git hosting, CI/CD pipelines, issue tracking, and container registry."),
    ("bitbucket", "Bitbucket", "dev_tools", "https://bitbucket.org", "Atlassian's Git hosting service integrated with Jira and Confluence for team collaboration."),
    ("docker", "Docker", "dev_tools", "https://docker.com", "Platform for building, packaging, and running applications in portable containers."),
    ("terraform", "Terraform", "dev_tools", "https://terraform.io", "HashiCorp's infrastructure-as-code tool for provisioning cloud resources via declarative HCL configuration."),
    ("pulumi", "Pulumi", "dev_tools", "https://pulumi.com", "Infrastructure-as-code platform letting developers define cloud resources using Python, TypeScript, or Go."),
    ("npm", "npm", "dev_tools", "https://npmjs.com", "Default package manager and registry for JavaScript and Node.js with 2M+ public packages."),
    ("pypi", "PyPI", "dev_tools", "https://pypi.org", "Official Python package index hosting 500K+ installable packages for the Python ecosystem."),

    # CI/CD
    ("circleci", "CircleCI", "ci_cd", "https://circleci.com", "Cloud CI/CD platform running pipelines in Docker or VM executors with parallelism support."),
    ("github-actions", "GitHub Actions", "ci_cd", "https://github.com/features/actions", "GitHub's built-in CI/CD system for automating builds, tests, and deployments via YAML workflows."),
    ("jenkins", "Jenkins", "ci_cd", "https://jenkins.io", "Open-source self-hosted automation server for building, testing, and deploying via plugins."),
    ("buildkite", "Buildkite", "ci_cd", "https://buildkite.com", "CI/CD platform running pipelines on your own infrastructure with a hosted control plane."),
    ("travis-ci", "Travis CI", "ci_cd", "https://travis-ci.com", "Hosted CI service that builds and tests projects from GitHub repositories via YAML config."),
    ("semaphore", "Semaphore", "ci_cd", "https://semaphoreci.com", "Fast cloud CI/CD platform with pipeline-as-code and reusable caching for test speed."),

    # Observability / Monitoring
    ("datadog", "Datadog", "observability", "https://datadoghq.com", "Cloud monitoring platform for metrics, traces, logs, and APM across infrastructure and apps."),
    ("sentry", "Sentry", "observability", "https://sentry.io", "Error tracking and performance monitoring platform that captures exceptions with full stack traces."),
    ("grafana", "Grafana", "observability", "https://grafana.com", "Open-source visualization platform for building dashboards from Prometheus, Loki, and other data sources."),
    ("pagerduty", "PagerDuty", "observability", "https://pagerduty.com", "Incident management platform for on-call scheduling, alerting, and escalation workflows."),
    ("newrelic", "New Relic", "observability", "https://newrelic.com", "Full-stack observability platform covering APM, infrastructure, logs, and browser monitoring."),
    ("posthog", "PostHog", "observability", "https://posthog.com", "Open-source product analytics platform with session replay, feature flags, and A/B testing."),
    ("honeycomb", "Honeycomb", "observability", "https://honeycomb.io", "Observability platform for querying high-cardinality distributed trace data to debug production systems."),
    ("betterstack", "Better Stack", "observability", "https://betterstack.com", "Uptime monitoring, incident management, and log management platform with status page hosting."),
    ("logflare", "Logflare", "observability", "https://logflare.app", "Log management service built on BigQuery for ingesting and querying structured application logs."),
    ("axiom", "Axiom", "observability", "https://axiom.co", "Serverless log and event data platform for ingesting, querying, and alerting on high-volume logs."),

    # Payments
    ("stripe", "Stripe", "payments", "https://stripe.com", "Payment processing API for accepting cards, subscriptions, invoicing, and global payment methods."),
    ("square", "Square", "payments", "https://squareup.com", "Payment platform for in-person POS and online payments with inventory and payroll tooling."),
    ("paypal", "PayPal", "payments", "https://paypal.com", "Online payment platform supporting wallet payments, card processing, and buy-now-pay-later."),
    ("adyen", "Adyen", "payments", "https://adyen.com", "Enterprise payment platform processing card-present and online payments across 200+ methods globally."),
    ("braintree", "Braintree", "payments", "https://braintreepayments.com", "PayPal-owned payment gateway SDK supporting cards, PayPal, Venmo, and digital wallets."),
    ("lemon-squeezy", "Lemon Squeezy", "payments", "https://lemonsqueezy.com", "Merchant of record platform handling payments, tax, and subscriptions for digital products and SaaS."),
    ("paddle", "Paddle", "payments", "https://paddle.com", "Merchant of record for SaaS handling global payments, tax compliance, and subscription billing."),

    # Auth
    ("auth0", "Auth0", "auth", "https://auth0.com", "Hosted authentication platform providing login, MFA, and SSO via SDK and APIs."),
    ("clerk", "Clerk", "auth", "https://clerk.com", "Drop-in authentication and user management with prebuilt React components and APIs."),
    ("okta", "Okta", "auth", "https://okta.com", "Enterprise identity platform for SSO, MFA, and lifecycle management across apps."),
    ("stytch", "Stytch", "auth", "https://stytch.com", "API-first authentication supporting passwordless, OAuth, and session management."),
    ("supertokens", "SuperTokens", "auth", "https://supertokens.com", "Open-source authentication backend you can self-host or run via managed cloud."),
    ("descope", "Descope", "auth", "https://descope.com", "No-code authentication flow builder with SDKs for passwordless and MFA login."),
    ("kinde", "Kinde", "auth", "https://kinde.com", "Authentication and user management platform with built-in feature flags and organizations."),
    ("workos", "WorkOS", "auth", "https://workos.com", "APIs for adding enterprise SSO, directory sync, and audit logs to SaaS products."),

    # Messaging / Communication
    ("twilio", "Twilio", "messaging", "https://twilio.com", "Cloud APIs for sending SMS, voice calls, WhatsApp, and email from applications."),
    ("sendgrid", "SendGrid", "messaging", "https://sendgrid.com", "Email delivery API and SMTP service for transactional and marketing email at scale."),
    ("resend", "Resend", "messaging", "https://resend.com", "Developer-focused transactional email API built around React Email templates."),
    ("postmark", "Postmark", "messaging", "https://postmarkapp.com", "Transactional email delivery service optimized for high inbox placement rates."),
    ("mailgun", "Mailgun", "messaging", "https://mailgun.com", "Email sending, receiving, and tracking API for developers sending transactional mail."),
    ("slack", "Slack", "messaging", "https://slack.com", "Team messaging platform with APIs and webhooks for building bots and integrations."),
    ("discord", "Discord", "messaging", "https://discord.com", "Chat platform with a bot API and webhook support for building community integrations."),
    ("telegram", "Telegram", "messaging", "https://telegram.org", "Messaging app with a Bot API for building bots that send messages and handle commands."),

    # Project management / Collaboration
    ("linear", "Linear", "project_mgmt", "https://linear.app", "Issue tracker for software teams with a fast UI, Git integrations, and a GraphQL API."),
    ("jira", "Jira", "project_mgmt", "https://atlassian.com/software/jira", "Enterprise issue and project tracker with customizable workflows and a REST API."),
    ("notion", "Notion", "project_mgmt", "https://notion.so", "Collaborative workspace for docs, databases, and wikis with a public REST API."),
    ("asana", "Asana", "project_mgmt", "https://asana.com", "Task and project management tool with timeline views and automation rules."),
    ("trello", "Trello", "project_mgmt", "https://trello.com", "Kanban board tool with a REST API and Power-Ups for extending functionality."),
    ("clickup", "ClickUp", "project_mgmt", "https://clickup.com", "All-in-one project management tool covering tasks, docs, goals, and time tracking."),
    ("shortcut", "Shortcut", "project_mgmt", "https://shortcut.com", "Issue tracker for software teams organized around stories, epics, and sprints."),
    ("height", "Height", "project_mgmt", "https://height.app", "Project management tool combining tasks, chat, and automation in a single interface."),
    ("todoist", "Todoist", "project_mgmt", "https://todoist.com", "Task management app with a REST and Sync API for building integrations and automations."),

    # Analytics
    ("amplitude", "Amplitude", "analytics", "https://amplitude.com", "Product analytics platform for tracking user behavior, funnels, and retention cohorts."),
    ("mixpanel", "Mixpanel", "analytics", "https://mixpanel.com", "Event-based analytics tool for querying user actions, funnels, and retention in real time."),
    ("segment", "Segment", "analytics", "https://segment.com", "Customer data platform that collects events and routes them to downstream analytics tools."),
    ("plausible", "Plausible", "analytics", "https://plausible.io", "Lightweight, privacy-friendly web analytics with no cookies and a simple dashboard."),
    ("google-analytics", "Google Analytics", "analytics", "https://analytics.google.com", "Web and app analytics platform tracking traffic, conversions, and audience behavior."),
    ("heap", "Heap", "analytics", "https://heap.io", "Auto-captures all user interactions retroactively, enabling analysis without pre-defined events."),
    ("june", "June", "analytics", "https://june.so", "B2B product analytics tool that surfaces per-company and per-user behavioral metrics."),

    # CMS / Content
    ("contentful", "Contentful", "cms", "https://contentful.com", "API-first headless CMS for managing and delivering structured content across platforms."),
    ("sanity", "Sanity", "cms", "https://sanity.io", "Headless CMS with a real-time collaborative editing studio and flexible content schemas."),
    ("strapi", "Strapi", "cms", "https://strapi.io", "Open-source headless CMS that auto-generates REST and GraphQL APIs from your content types."),
    ("wordpress", "WordPress", "cms", "https://wordpress.org", "Self-hosted PHP CMS powering ~43% of the web, with a plugin ecosystem and REST API."),
    ("ghost", "Ghost", "cms", "https://ghost.org", "Node.js CMS and publishing platform focused on newsletters and subscription-based content."),
    ("prismic", "Prismic", "cms", "https://prismic.io", "Headless CMS with a visual page builder and slice-based content modeling for frontend teams."),
    ("payload", "Payload", "cms", "https://payloadcms.com", "TypeScript-native headless CMS that runs in your own codebase with a code-first config approach."),

    # Storage / CDN / Media
    ("cloudinary", "Cloudinary", "storage", "https://cloudinary.com", "Cloud service for uploading, transforming, and delivering images and videos via URL parameters."),
    ("imgix", "imgix", "storage", "https://imgix.com", "Real-time image processing CDN that transforms and optimizes images on-the-fly via URL params."),
    ("uploadthing", "UploadThing", "storage", "https://uploadthing.com", "File upload service for Next.js and TypeScript apps with simple end-to-end type safety."),
    ("mux", "Mux", "storage", "https://mux.com", "API platform for video encoding, storage, streaming, and real-time analytics."),
    ("s3", "AWS S3", "storage", "https://aws.amazon.com/s3", "AWS object storage service for storing and retrieving arbitrary files and static assets at scale."),
    ("r2", "Cloudflare R2", "storage", "https://developers.cloudflare.com/r2", "S3-compatible object storage with no egress fees, served through Cloudflare's global network."),

    # Search
    ("algolia", "Algolia", "search", "https://algolia.com", "Hosted search API that indexes your data and returns ranked results in under 100ms."),
    ("typesense", "Typesense", "search", "https://typesense.org", "Open-source, typo-tolerant search engine with a simple API, self-hostable or cloud-hosted."),
    ("meilisearch", "Meilisearch", "search", "https://meilisearch.com", "Open-source search engine written in Rust, optimized for fast and relevant full-text search."),

    # Feature flags / Config
    ("launchdarkly", "LaunchDarkly", "feature_flags", "https://launchdarkly.com", "Feature flag platform for targeted rollouts, A/B testing, and runtime config without deploys."),
    ("statsig", "Statsig", "feature_flags", "https://statsig.com", "Feature flags and experimentation platform with built-in statistical analysis of feature impact."),
    ("flagsmith", "Flagsmith", "feature_flags", "https://flagsmith.com", "Open-source feature flag and remote config service, self-hostable or available as SaaS."),

    # CRM / Customer
    ("hubspot", "HubSpot", "crm", "https://hubspot.com", "CRM platform with APIs for syncing contacts, deals, and marketing data with your application."),
    ("salesforce", "Salesforce", "crm", "https://salesforce.com", "Enterprise CRM with extensive APIs for integrating sales, service, and customer data workflows."),
    ("intercom", "Intercom", "crm", "https://intercom.com", "Customer messaging platform with APIs for in-app chat, support tickets, and user engagement."),
    ("zendesk", "Zendesk", "crm", "https://zendesk.com", "Customer support platform with APIs for managing tickets, help centers, and agent workflows."),
    ("freshdesk", "Freshdesk", "crm", "https://freshdesk.com", "Cloud-based helpdesk with REST APIs for managing support tickets and customer conversations."),

    # AI / ML platforms
    ("openai", "OpenAI", "ai_ml", "https://openai.com", "API provider for GPT language models, embeddings, image generation, and speech transcription."),
    ("anthropic", "Anthropic", "ai_ml", "https://anthropic.com", "API provider for Claude language models, focused on safe and instruction-following AI assistants."),
    ("cohere", "Cohere", "ai_ml", "https://cohere.com", "API platform for text generation, embeddings, and reranking models aimed at enterprise search and RAG."),
    ("replicate", "Replicate", "ai_ml", "https://replicate.com", "API platform for running open-source ML models in the cloud with a simple HTTP interface."),
    ("huggingface", "Hugging Face", "ai_ml", "https://huggingface.co", "Hub for open-source ML models, datasets, and Spaces, with hosted inference APIs."),
    ("together", "Together AI", "ai_ml", "https://together.ai", "Inference API for running open-source LLMs at scale with competitive pricing per token."),
    ("fireworks", "Fireworks AI", "ai_ml", "https://fireworks.ai", "Low-latency inference API for open-source LLMs, optimized for production throughput and speed."),
    ("groq", "Groq", "ai_ml", "https://groq.com", "Inference API backed by custom LPU hardware, delivering unusually fast token generation speeds."),
    ("mistral", "Mistral AI", "ai_ml", "https://mistral.ai", "API and open-weight language models from a European lab, with strong multilingual performance."),
    ("deepseek", "DeepSeek", "ai_ml", "https://deepseek.com", "Chinese AI lab providing open-weight and API-accessible LLMs with strong coding and reasoning."),
    ("modal", "Modal", "ai_ml", "https://modal.com", "Python-native serverless cloud for running GPU workloads, ML inference, and batch jobs from code."),
    ("anyscale", "Anyscale", "ai_ml", "https://anyscale.com", "Managed platform for scaling Python and ML workloads using the Ray distributed computing framework."),
    ("weights-biases", "Weights & Biases", "ai_ml", "https://wandb.ai", "MLOps platform for tracking experiments, versioning datasets, and monitoring model training runs."),

    # Design / Frontend
    ("figma", "Figma", "design", "https://figma.com", "Browser-based collaborative design tool with a REST API for extracting assets and design tokens."),
    ("storybook", "Storybook", "design", "https://storybook.js.org", "Open-source tool for building and visually testing UI components in isolation from your application."),
    ("chromatic", "Chromatic", "design", "https://chromatic.com", "Visual regression testing service for Storybook that detects UI changes across every component story."),

    # Queues / Background jobs
    ("inngest", "Inngest", "queues", "https://inngest.com", "Event-driven background job platform with durable execution, retries, and step functions for serverless."),
    ("trigger-dev", "Trigger.dev", "queues", "https://trigger.dev", "Open-source background job framework for TypeScript with long-running task support and local dev tooling."),
    ("temporal", "Temporal", "queues", "https://temporal.io", "Durable workflow orchestration engine that persists execution state to survive process crashes and restarts."),
    ("rabbitmq", "RabbitMQ", "queues", "https://rabbitmq.com", "Open-source message broker implementing AMQP for routing messages between producers and consumers."),
    ("kafka", "Kafka", "queues", "https://kafka.apache.org", "Distributed event streaming platform for high-throughput, fault-tolerant log-based message passing."),
    ("sqs", "AWS SQS", "queues", "https://aws.amazon.com/sqs", "Fully managed AWS message queue service for decoupling distributed application components."),
    ("bullmq", "BullMQ", "queues", "https://bullmq.io", "Redis-backed Node.js queue library for processing background jobs with priorities, delays, and rate limiting."),

    # E-commerce
    ("shopify", "Shopify", "ecommerce", "https://shopify.com", "E-commerce platform with Storefront and Admin APIs for building custom storefronts and integrations."),
    ("bigcommerce", "BigCommerce", "ecommerce", "https://bigcommerce.com", "SaaS e-commerce platform with headless commerce APIs for catalog, cart, and checkout management."),
    ("medusa", "Medusa", "ecommerce", "https://medusajs.com", "Open-source Node.js e-commerce engine with modular architecture for building custom commerce backends."),
    ("saleor", "Saleor", "ecommerce", "https://saleor.io", "Open-source headless e-commerce platform built with Python and GraphQL for composable storefronts."),

    # Maps / Location
    ("mapbox", "Mapbox", "location", "https://mapbox.com", "Platform for embedding customizable vector maps, geocoding, and routing into web and mobile apps."),
    ("google-maps", "Google Maps", "location", "https://developers.google.com/maps", "APIs for embedding maps, geocoding addresses, calculating routes, and querying places data."),

    # Security
    ("snyk", "Snyk", "security", "https://snyk.io", "Developer security tool that scans code, dependencies, containers, and IaC for known vulnerabilities."),
    ("sonarqube", "SonarQube", "security", "https://sonarqube.org", "Static analysis tool that detects bugs, code smells, and security vulnerabilities across multiple languages."),
    ("vault", "HashiCorp Vault", "security", "https://vaultproject.io", "Secrets management tool for securely storing, accessing, and rotating credentials and API keys."),

    # DNS / Domains
    ("godaddy", "GoDaddy", "dns", "https://godaddy.com", "Domain registrar and DNS provider with APIs for managing domain registration and DNS records."),
    ("namecheap", "Namecheap", "dns", "https://namecheap.com", "Budget-friendly domain registrar with an API for programmatic domain and DNS record management."),
    ("dnsimple", "DNSimple", "dns", "https://dnsimple.com", "DNS management service with a developer-friendly API for automating domain and record operations."),

    # Other developer services
    ("twitch", "Twitch", "media", "https://twitch.tv", "Live streaming platform with APIs for accessing stream data, chat, and EventSub webhooks."),
    ("spotify", "Spotify", "media", "https://spotify.com", "Music streaming platform with a Web API for querying tracks, albums, playlists, and playback state."),
    ("youtube", "YouTube", "media", "https://youtube.com", "Video platform with Data and Player APIs for searching videos, managing uploads, and embedding playback."),
]


def _seed_curated() -> int:
    """Upsert the curated developer tools list into builder_tools."""
    from psycopg2.extras import execute_values

    tuples = [
        (slug, name, category, website, description, "manual", slug)
        for slug, name, category, website, description in _CURATED_TOOLS
    ]

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        execute_values(
            cur,
            """
            INSERT INTO builder_tools (
                slug, name, category, website, description,
                source, source_ref
            ) VALUES %s
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                category = COALESCE(EXCLUDED.category, builder_tools.category),
                website = COALESCE(EXCLUDED.website, builder_tools.website),
                description = COALESCE(EXCLUDED.description, builder_tools.description),
                updated_at = NOW()
            """,
            tuples,
            template="(%s, %s, %s, %s, %s, %s, %s)",
            page_size=500,
        )
        raw_conn.commit()
        return len(tuples)
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"Seed upsert failed: {e}")
        return 0
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


MCP_MATCH_PROMPT = """\
Match each developer tool to the MCP (Model Context Protocol) server \
repository that provides integration with it. A match means the MCP \
repo specifically integrates with that tool's API.

MCP repo names (pick from these only):
{repo_names}

Tools to match:
{tools_text}

Rules:
- Only match if you are confident the MCP repo provides integration.
- Return null for tools with no matching MCP repo.
- Return valid JSON only.

Return format:
[{{"id": <tool_id>, "repo_name": "<matched repo name or null>"}}, ...]"""

LLM_MCP_BATCH_SIZE = 30


async def _llm_match_mcp_repos(
    unmatched_tools: list[dict],
    repo_by_name: dict[str, dict],
    all_mcp: list[dict],
) -> dict[int, dict]:
    """Use LLM to match tools to MCP repos. Returns {tool_id: matched_repo}."""
    if not settings.ANTHROPIC_API_KEY or not unmatched_tools:
        return {}

    # Build repo name list (top 500 by stars, already sorted)
    repo_names = "\n".join(r["name"] for r in all_mcp[:500])

    matched: dict[int, dict] = {}
    batches = [
        unmatched_tools[i:i + LLM_MCP_BATCH_SIZE]
        for i in range(0, len(unmatched_tools), LLM_MCP_BATCH_SIZE)
    ]

    for batch in batches:
        lines = []
        for t in batch:
            desc = (t.get("description") or "")[:100]
            lines.append(f'{t["id"]}. {t["name"]} ({t.get("category", "")}) — "{desc}"')
        tools_text = "\n".join(lines)

        predictions = await call_haiku(
            MCP_MATCH_PROMPT.format(repo_names=repo_names, tools_text=tools_text)
        )
        if not predictions:
            continue

        tool_id_set = {t["id"] for t in batch}
        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            tid = pred.get("id")
            repo_name = pred.get("repo_name")
            if tid not in tool_id_set or not repo_name:
                continue
            repo_name_lower = repo_name.lower()
            if repo_name_lower in repo_by_name:
                matched[tid] = repo_by_name[repo_name_lower]

    return matched


async def _enrich_mcp_status() -> dict:
    """Cross-reference builder_tools against ai_repos (domain='mcp').

    Matching strategy:
    1. Exact name patterns: {slug}-mcp-server, {slug}-mcp, mcp-server-{slug}, mcp-{slug}
    2. Partial match: slug + 'mcp' both in repo name
    3. LLM fallback for unmatched tools
    Determines official vs community by comparing repo owner to tool slug.
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)

    with engine.connect() as conn:
        tools = conn.execute(text("""
            SELECT id, slug, name, source_ref, category, description
            FROM builder_tools
            WHERE mcp_status = 'unchecked'
               OR mcp_checked_at IS NULL
               OR mcp_checked_at < :cutoff
            ORDER BY
                CASE WHEN mcp_status = 'unchecked' THEN 0 ELSE 1 END,
                mcp_checked_at NULLS FIRST
            LIMIT 200
        """), {"cutoff": stale_cutoff}).fetchall()

        if not tools:
            return {"checked": 0, "found": 0}

        mcp_repos = conn.execute(text("""
            SELECT full_name, name, github_owner, npm_package, stars
            FROM ai_repos
            WHERE domain = 'mcp' AND archived = false
            ORDER BY stars DESC
        """)).fetchall()

    # Build lookup by lowercase name — keep highest-star match per name
    repo_by_name: dict[str, dict] = {}
    for r in mcp_repos:
        m = dict(r._mapping)
        key = m["name"].lower()
        if key not in repo_by_name or m["stars"] > repo_by_name[key]["stars"]:
            repo_by_name[key] = m

    all_mcp = [dict(r._mapping) for r in mcp_repos]
    updates = []
    found = 0
    unmatched_for_llm: list[dict] = []

    for tool_row in tools:
        t = tool_row._mapping
        slug = t["slug"]

        best_match = None

        # Strategy 1: exact name patterns
        for pattern in [f"{slug}-mcp-server", f"{slug}-mcp", f"mcp-server-{slug}", f"mcp-{slug}"]:
            if pattern in repo_by_name:
                best_match = repo_by_name[pattern]
                break

        # Strategy 2: partial match — slug + 'mcp' both in repo name
        if not best_match:
            candidates = []
            for repo in all_mcp:
                name_lower = repo["name"].lower()
                if slug in name_lower and ("mcp" in name_lower or "model-context-protocol" in name_lower):
                    candidates.append(repo)
            if candidates:
                candidates.sort(key=lambda x: x["stars"], reverse=True)
                best_match = candidates[0]

        if best_match:
            found += 1
            owner = best_match["github_owner"].lower()
            if owner == slug or owner.startswith(slug):
                mcp_status = "has_official"
                mcp_type = "official_repo"
            else:
                mcp_status = "has_community"
                mcp_type = "community_repo"
                if best_match.get("npm_package"):
                    mcp_type = "community_npm"

            updates.append((
                mcp_status, mcp_type, best_match["full_name"],
                best_match.get("npm_package") or None, t["id"],
            ))
        else:
            unmatched_for_llm.append(dict(t))

    # Strategy 3: LLM fallback for tools that pattern matching missed
    if unmatched_for_llm:
        llm_matches = await _llm_match_mcp_repos(unmatched_for_llm, repo_by_name, all_mcp)
        for t in unmatched_for_llm:
            tid = t["id"]
            if tid in llm_matches:
                found += 1
                best_match = llm_matches[tid]
                owner = best_match["github_owner"].lower()
                slug = t["slug"]
                if owner == slug or owner.startswith(slug):
                    mcp_status = "has_official"
                    mcp_type = "official_repo"
                else:
                    mcp_status = "has_community"
                    mcp_type = "community_repo"
                    if best_match.get("npm_package"):
                        mcp_type = "community_npm"
                updates.append((
                    mcp_status, mcp_type, best_match["full_name"],
                    best_match.get("npm_package") or None, tid,
                ))
            else:
                updates.append(("none_found", None, None, None, tid))

    # Batch update
    if updates:
        from psycopg2.extras import execute_values

        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            execute_values(
                cur,
                """
                UPDATE builder_tools AS bt SET
                    mcp_status = v.mcp_status,
                    mcp_type = v.mcp_type,
                    mcp_repo_slug = v.mcp_repo_slug,
                    mcp_npm_package = v.mcp_npm_package,
                    mcp_checked_at = NOW(),
                    updated_at = NOW()
                FROM (VALUES %s) AS v(mcp_status, mcp_type, mcp_repo_slug, mcp_npm_package, id)
                WHERE bt.id = v.id::int
                """,
                updates,
                template="(%s, %s, %s, %s, %s)",
            )
            raw_conn.commit()
        except Exception as e:
            try:
                raw_conn.rollback()
            except Exception:
                pass
            logger.error(f"MCP status update failed: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    return {"checked": len(tools), "found": found}


async def ingest_builder_tools() -> dict:
    """Seed curated builder tools and enrich MCP status."""
    started_at = datetime.now(timezone.utc)

    # Phase 1: Seed curated list
    seeded = _seed_curated()
    logger.info(f"Seeded {seeded} builder tools from curated list")

    # Phase 2: Enrich MCP status by cross-referencing ai_repos + LLM fallback
    enriched = await _enrich_mcp_status()
    logger.info(f"MCP enrichment: {enriched}")

    _log_sync(started_at, seeded, None)
    return {"seeded": seeded, **enriched}


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="builder_tools",
            status="success" if not error else "partial",
            records_written=records,
            error_message=error,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await ingest_builder_tools()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
