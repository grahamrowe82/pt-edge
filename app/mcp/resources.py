"""MCP Resources — browsable reference data and parameterized project lookups."""

import re

from sqlalchemy import text, func

from app.mcp.instance import mcp
from app.db import SessionLocal, readonly_engine
from app.models import Project, Lab, GitHubSnapshot, DownloadSnapshot, SyncLog


# ---------------------------------------------------------------------------
# Static Resources
# ---------------------------------------------------------------------------

async def methodology_resource() -> str:
    """How PT-Edge metrics work: tier system, hype ratio, lifecycle stages, and data sources."""
    return "\n".join([
        "PT-EDGE METHODOLOGY REFERENCE",
        "=" * 50,
        "",
        "TIER SYSTEM",
        "-" * 30,
        "T1 Foundational: >10M monthly downloads. Infrastructure the ecosystem runs on.",
        "T2 Major: >100K monthly downloads. Widely adopted, significant community.",
        "T3 Notable: >10K monthly downloads. Growing adoption, active development.",
        "T4 Emerging: <10K monthly downloads or new. Early stage, watch for breakout.",
        "Tiers are computed from download data. Manual overrides available via set_tier().",
        "",
        "HYPE RATIO",
        "-" * 30,
        "Formula: GitHub stars / monthly downloads.",
        "High ratio (>1.0): More stargazers than users. GitHub tourism, README-driven hype.",
        "Low ratio (<0.01): Invisible infrastructure. Real adoption, low awareness.",
        "Normal range: 0.01 - 1.0. Healthy balance of awareness and usage.",
        "Use hype_check() on any project to see the breakdown.",
        "",
        "LIFECYCLE STAGES",
        "-" * 30,
        "emerging: New project, low activity, building initial traction.",
        "launching: Recent spike in stars/downloads, first releases shipping.",
        "growing: Sustained upward trajectory in both stars and downloads.",
        "established: Stable high metrics, regular releases, large community.",
        "fading: Declining momentum — fewer commits, slowing downloads.",
        "dormant: No recent activity. May be abandoned or feature-complete.",
        "",
        "DATA SOURCES",
        "-" * 30,
        "GitHub: Stars, forks, open issues, contributors, commit activity (daily snapshots).",
        "PyPI: Monthly download counts for Python packages.",
        "npm: Monthly download counts for JavaScript packages.",
        "Hacker News: Posts and comments mentioning tracked projects.",
        "HuggingFace: Model and dataset metadata via Hub API.",
        "APIs.guru: ~2,500 indexed public REST API specs.",
        "",
        "DERIVED METRICS",
        "-" * 30,
        "Momentum: Star and download deltas over 7-day and 30-day windows.",
        "Acceleration: Change in delta between consecutive windows (movers tool).",
        "Co-occurrence: How often projects appear together in HN discussions (related tool).",
        "",
        "For deep documentation on any specific metric, use explain(topic).",
        "For the full methodology topic list, use explain() with no arguments.",
    ])


async def categories_resource() -> str:
    """Valid project categories used by PT-Edge for classification."""
    categories = [
        ("agent", "Autonomous AI agents and agent frameworks"),
        ("dataset", "Training and evaluation datasets"),
        ("eval", "Evaluation tools, benchmarks, and testing frameworks"),
        ("framework", "Full-stack AI/ML frameworks"),
        ("infra", "Infrastructure — serving, orchestration, deployment"),
        ("library", "Focused libraries for specific AI/ML tasks"),
        ("mcp-server", "Model Context Protocol server implementations"),
        ("model", "Pre-trained models and model architectures"),
        ("security", "AI safety, guardrails, and security tools"),
        ("tool", "Developer tools, CLIs, and utilities for AI workflows"),
    ]
    lines = [
        "PT-EDGE PROJECT CATEGORIES",
        "=" * 50,
        "",
    ]
    for cat, desc in categories:
        lines.append(f"  {cat:<15} {desc}")
    lines.extend([
        "",
        "Use these with: scout(category=...), lifecycle_map(category=...),",
        "hype_landscape(category=...), trending(category=...), accept_candidate(category=...)",
    ])
    return "\n".join(lines)


async def coverage_resource() -> str:
    """Current PT-Edge data coverage: project count, snapshot depth, data freshness."""
    session = SessionLocal()
    try:
        total = session.query(func.count(Project.id)).filter(
            Project.is_active == True  # noqa: E712
        ).scalar() or 0

        with readonly_engine.connect() as conn:
            with_gh = conn.execute(text(
                "SELECT COUNT(DISTINCT project_id) FROM github_snapshots"
            )).scalar() or 0
            with_dl = conn.execute(text(
                "SELECT COUNT(DISTINCT project_id) FROM download_snapshots"
            )).scalar() or 0
            snapshot_days = conn.execute(text(
                "SELECT COUNT(DISTINCT snapshot_date) FROM github_snapshots"
            )).scalar() or 0
            candidates = conn.execute(text(
                "SELECT COUNT(*) FROM project_candidates WHERE status = 'pending'"
            )).scalar() or 0
            ai_repos = conn.execute(text(
                "SELECT COUNT(*) FROM ai_repos"
            )).scalar() or 0
            public_apis = conn.execute(text(
                "SELECT COUNT(*) FROM public_apis"
            )).scalar() or 0
            hf_datasets = conn.execute(text(
                "SELECT COUNT(*) FROM hf_datasets"
            )).scalar() or 0
            hf_models = conn.execute(text(
                "SELECT COUNT(*) FROM hf_models"
            )).scalar() or 0

        lab_count = session.query(func.count(Lab.id)).scalar() or 0

        # Data freshness
        syncs = session.query(SyncLog).filter(
            SyncLog.status == "success"
        ).order_by(SyncLog.finished_at.desc()).all()
        seen_types = set()
        freshness_lines = []
        for s in syncs:
            if s.sync_type not in seen_types:
                seen_types.add(s.sync_type)
                ts = s.finished_at.strftime("%Y-%m-%d %H:%M UTC") if s.finished_at else "n/a"
                freshness_lines.append(f"  {s.sync_type:<20} {ts}")

        lines = [
            "PT-EDGE DATA COVERAGE",
            "=" * 50,
            "",
            "TRACKED DATA",
            "-" * 30,
            f"  Labs:                {lab_count}",
            f"  Projects:            {total}",
            f"  With GitHub data:    {with_gh}",
            f"  With download data:  {with_dl}",
            f"  Snapshot depth:      {snapshot_days} day(s)",
            f"  Pending candidates:  {candidates}",
            "",
            "DISCOVERY INDEXES",
            "-" * 30,
            f"  AI repos:            {ai_repos:,}",
            f"  Public APIs:         {public_apis:,}",
            f"  HuggingFace datasets:{hf_datasets:,}",
            f"  HuggingFace models:  {hf_models:,}",
            "",
            "DATA FRESHNESS",
            "-" * 30,
        ]
        lines.extend(freshness_lines if freshness_lines else ["  No sync data available."])
        return "\n".join(lines)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Resource Templates (parameterized)
# ---------------------------------------------------------------------------

async def project_resource(slug: str) -> str:
    """Quick reference card for a tracked project."""
    session = SessionLocal()
    try:
        project = session.query(Project).filter(
            func.lower(Project.slug) == slug.lower()
        ).first()
        if not project:
            return f"Project '{slug}' not found. Use topic() or scout() to discover projects."

        lab_name = project.lab.name if project.lab else "n/a"

        gh = (
            session.query(GitHubSnapshot)
            .filter(GitHubSnapshot.project_id == project.id)
            .order_by(GitHubSnapshot.snapshot_date.desc())
            .first()
        )
        dl = (
            session.query(DownloadSnapshot)
            .filter(DownloadSnapshot.project_id == project.id)
            .order_by(DownloadSnapshot.snapshot_date.desc())
            .first()
        )

        tier_str = "n/a"
        lifecycle_str = "n/a"
        tier_labels = {1: "Foundational", 2: "Major", 3: "Notable", 4: "Emerging"}
        try:
            with readonly_engine.connect() as conn:
                tier_row = conn.execute(text(
                    "SELECT tier FROM mv_project_tier WHERE project_id = :pid"
                ), {"pid": project.id}).fetchone()
                lc_row = conn.execute(text(
                    "SELECT lifecycle_stage FROM mv_lifecycle WHERE project_id = :pid"
                ), {"pid": project.id}).fetchone()
                if tier_row:
                    t = tier_row._mapping["tier"]
                    tier_str = f"T{t} ({tier_labels.get(t, '?')})"
                if lc_row:
                    lifecycle_str = lc_row._mapping["lifecycle_stage"]
        except Exception:
            pass

        stars = f"{gh.stars:,}" if gh and gh.stars else "n/a"
        downloads = f"{dl.downloads_monthly:,}/mo" if dl and dl.downloads_monthly else "n/a"

        lines = [
            f"PROJECT: {project.name}",
            "=" * 40,
            f"  Slug:       {project.slug}",
            f"  Category:   {project.category}",
            f"  Lab:        {lab_name}",
            f"  Tier:       {tier_str}",
            f"  Lifecycle:  {lifecycle_str}",
            f"  Stars:      {stars}",
            f"  Downloads:  {downloads}",
            "",
            f"For full details: project_pulse('{project.slug}')",
        ]
        return "\n".join(lines)
    finally:
        session.close()


async def lab_resource(slug: str) -> str:
    """Lab overview: basic info and list of tracked projects."""
    session = SessionLocal()
    try:
        lab = session.query(Lab).filter(
            func.lower(Lab.slug) == slug.lower()
        ).first()
        if not lab:
            return f"Lab '{slug}' not found."

        projects = session.query(Project).filter(
            Project.lab_id == lab.id, Project.is_active == True  # noqa: E712
        ).order_by(Project.name).all()

        lines = [
            f"LAB: {lab.name}",
            "=" * 40,
            f"  Slug:       {lab.slug}",
            f"  URL:        {lab.url or 'n/a'}",
            f"  GitHub Org: {lab.github_org or 'n/a'}",
            f"  Projects:   {len(projects)}",
            "",
        ]
        for p in projects:
            lines.append(f"  - {p.name} [{p.category}] ({p.slug})")
        lines.extend([
            "",
            f"For full details: lab_pulse('{lab.slug}')",
        ])
        return "\n".join(lines)
    finally:
        session.close()


async def category_resource(category: str) -> str:
    """All projects in a specific category with key metrics."""
    valid = {"tool", "model", "framework", "library", "agent", "eval",
             "dataset", "infra", "mcp-server", "security"}
    if category.lower() not in valid:
        return f"Unknown category '{category}'. Valid: {', '.join(sorted(valid))}"

    session = SessionLocal()
    try:
        projects = session.query(Project).filter(
            Project.category == category.lower(),
            Project.is_active == True  # noqa: E712
        ).order_by(Project.name).all()

        lines = [
            f"CATEGORY: {category.lower()} ({len(projects)} projects)",
            "=" * 50,
            "",
        ]
        for p in projects:
            gh = (
                session.query(GitHubSnapshot)
                .filter(GitHubSnapshot.project_id == p.id)
                .order_by(GitHubSnapshot.snapshot_date.desc())
                .first()
            )
            dl = (
                session.query(DownloadSnapshot)
                .filter(DownloadSnapshot.project_id == p.id)
                .order_by(DownloadSnapshot.snapshot_date.desc())
                .first()
            )
            stars = f"{gh.stars:,}" if gh and gh.stars else "n/a"
            downloads = f"{dl.downloads_monthly:,}/mo" if dl and dl.downloads_monthly else "n/a"
            lab_name = p.lab.name if p.lab else "-"
            lines.append(
                f"  {p.name:<28} [{lab_name:<12}] stars: {stars:<10} dl: {downloads}"
            )

        if not projects:
            lines.append("  No active projects in this category.")
        return "\n".join(lines)
    finally:
        session.close()


# Register with FastMCP for Streamable HTTP transport
mcp.resource("resource://pt-edge/methodology")(methodology_resource)
mcp.resource("resource://pt-edge/categories")(categories_resource)
mcp.resource("resource://pt-edge/coverage")(coverage_resource)
mcp.resource("resource://pt-edge/project/{slug}")(project_resource)
mcp.resource("resource://pt-edge/lab/{slug}")(lab_resource)
mcp.resource("resource://pt-edge/category/{category}")(category_resource)

# ---------------------------------------------------------------------------
# Registry for JSON-RPC handler
# ---------------------------------------------------------------------------

RESOURCES = [
    {
        "uri": "resource://pt-edge/methodology",
        "name": "methodology",
        "description": "How PT-Edge metrics work: tier system, hype ratio, lifecycle stages, and data sources",
    },
    {
        "uri": "resource://pt-edge/categories",
        "name": "categories",
        "description": "Valid project categories used by PT-Edge for classification",
    },
    {
        "uri": "resource://pt-edge/coverage",
        "name": "coverage",
        "description": "Current data coverage: project count, index sizes, data freshness",
    },
]

RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "resource://pt-edge/project/{slug}",
        "name": "project",
        "description": "Quick reference card for a tracked project",
    },
    {
        "uriTemplate": "resource://pt-edge/lab/{slug}",
        "name": "lab",
        "description": "Lab overview with tracked projects",
    },
    {
        "uriTemplate": "resource://pt-edge/category/{category}",
        "name": "category",
        "description": "All projects in a category with key metrics",
    },
]

_RESOURCE_HANDLERS = {
    "resource://pt-edge/methodology": methodology_resource,
    "resource://pt-edge/categories": categories_resource,
    "resource://pt-edge/coverage": coverage_resource,
}

_TEMPLATE_PATTERNS = [
    ("resource://pt-edge/project/{slug}", project_resource),
    ("resource://pt-edge/lab/{slug}", lab_resource),
    ("resource://pt-edge/category/{category}", category_resource),
]


async def read_resource(uri: str) -> dict:
    """Dispatch a resource read by URI. Returns MCP-formatted result."""
    # Try static resources first
    handler = _RESOURCE_HANDLERS.get(uri)
    if handler:
        content = await handler()
        return {"contents": [{"uri": uri, "text": content}]}

    # Try templates
    for template_uri, handler_fn in _TEMPLATE_PATTERNS:
        pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template_uri)
        m = re.fullmatch(pattern, uri)
        if m:
            content = await handler_fn(**m.groupdict())
            return {"contents": [{"uri": uri, "text": content}]}

    return {"contents": [{"uri": uri, "text": f"Unknown resource: {uri}"}]}
