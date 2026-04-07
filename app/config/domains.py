"""Canonical domain-to-view mapping.

Every domain in ai_repo_domains.DOMAINS gets a materialized view named
``mv_{slug}_quality`` where hyphens become underscores.  One historical
exception (prompt-engineering -> mv_prompt_eng_quality) is handled via
an override dict.

Import DOMAIN_VIEW_MAP from here instead of hardcoding the mapping.
"""

from app.ingest.ai_repo_domains import DOMAINS

_VIEW_NAME_OVERRIDES = {
    "prompt-engineering": "mv_prompt_eng_quality",
}


def domain_view_name(domain: str) -> str:
    if domain in _VIEW_NAME_OVERRIDES:
        return _VIEW_NAME_OVERRIDES[domain]
    return f"mv_{domain.replace('-', '_')}_quality"


DOMAIN_VIEW_MAP: dict[str, str] = {
    d: domain_view_name(d) for d in DOMAINS
}
