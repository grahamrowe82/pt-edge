"""Shared bot family classification SQL for all *-edge domains.

Used in mv_access_bot_demand materialized views. When a new bot appears
(e.g., GrokBot), add it here — all domains pick it up on next MV refresh.

Usage:
    from app.core.sql.bot_families import BOT_FAMILY_CASE
    sql = f"SELECT {BOT_FAMILY_CASE} AS bot_family FROM http_access_log"
"""

BOT_FAMILY_CASE = """
CASE
    -- Tier 1: AI user-action crawlers (demand signal: human asked an AI)
    WHEN user_agent ILIKE '%ChatGPT-User%'       THEN 'ChatGPT-User'
    WHEN user_agent ILIKE '%Claude-Web%'          THEN 'Claude-Web'
    WHEN user_agent ILIKE '%Perplexity-User%'     THEN 'Perplexity-User'
    WHEN user_agent ILIKE '%OAI-SearchBot%'       THEN 'OAI-SearchBot'
    WHEN user_agent ILIKE '%Claude-SearchBot%'    THEN 'Claude-SearchBot'
    WHEN user_agent ILIKE '%DuckAssistBot%'       THEN 'DuckAssistBot'
    WHEN user_agent ILIKE '%Claude-User%'         THEN 'Claude-User'
    -- Tier 2: AI training crawlers
    WHEN user_agent ILIKE '%GPTBot%'              THEN 'GPTBot'
    WHEN user_agent ILIKE '%ClaudeBot%'           THEN 'ClaudeBot'
    WHEN user_agent ILIKE '%PerplexityBot%'       THEN 'PerplexityBot'
    WHEN user_agent ILIKE '%Google-Extended%'     THEN 'Google-Extended'
    WHEN user_agent ILIKE '%GoogleOther%'         THEN 'GoogleOther'
    WHEN user_agent ILIKE '%Meta-ExternalAgent%'  THEN 'Meta-ExternalAgent'
    WHEN user_agent ILIKE '%Bytespider%'          THEN 'Bytespider'
    WHEN user_agent ILIKE '%Amazonbot%'           THEN 'Amazonbot'
    -- Search engines
    WHEN user_agent ILIKE '%Googlebot%'           THEN 'Googlebot'
    WHEN user_agent ILIKE '%Bingbot%'             THEN 'Bingbot'
    WHEN user_agent ILIKE '%YandexBot%'           THEN 'YandexBot'
    WHEN user_agent ILIKE '%Applebot%'            THEN 'Applebot'
    WHEN user_agent ILIKE '%DuckDuckBot%'         THEN 'DuckDuckBot'
    WHEN user_agent ILIKE '%AdsBot%'              THEN 'AdsBot-Google'
    WHEN user_agent ILIKE '%PetalBot%'            THEN 'PetalBot'
    WHEN user_agent ILIKE '%Qwant%'               THEN 'Qwantbot'
    -- Social / SEO
    WHEN user_agent ILIKE '%facebookexternalhit%' THEN 'FacebookBot'
    WHEN user_agent ILIKE '%Twitterbot%'          THEN 'TwitterBot'
    WHEN user_agent ILIKE '%LinkedInBot%'         THEN 'LinkedInBot'
    WHEN user_agent ILIKE '%SemrushBot%'          THEN 'SemrushBot'
    WHEN user_agent ILIKE '%AhrefsBot%'           THEN 'AhrefsBot'
    WHEN user_agent ILIKE '%MJ12bot%'             THEN 'MJ12bot'
    -- Catch-all bots
    WHEN user_agent ILIKE '%bot%'                 THEN 'other_bot'
    WHEN user_agent ILIKE '%crawler%'             THEN 'other_bot'
    WHEN user_agent ILIKE '%spider%'              THEN 'other_bot'
    ELSE 'human'
END
""".strip()
