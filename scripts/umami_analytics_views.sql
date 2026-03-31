-- Umami Analytics View Layer
-- Reconstructs visitor identity, sessions, and intent classification
-- from cookieless Umami tracking data using device fingerprinting.
--
-- Deploy: psql $UMAMI_DATABASE_URL -f scripts/umami_analytics_views.sql
-- Views must be created in order (dependency chain).

-- ============================================================
-- View 1: v_visitors — Identity layer
-- ============================================================
-- Reconstructs unique visitors from device fingerprint hash.
-- One row per visitor per day. Classified as self/agent/human.
--
-- Self-traffic fingerprint (update when hardware changes):
--   ZA / chrome / Mac OS / laptop / 1440x900

CREATE OR REPLACE VIEW v_visitors AS
WITH fingerprinted AS (
    SELECT
        we.event_id,
        we.created_at,
        we.url_path,
        s.browser,
        s.os,
        s.device,
        s.screen,
        s.country,
        s.language,
        s.city,
        md5(
            COALESCE(s.country, '') || '|' ||
            COALESCE(s.browser, '') || '|' ||
            COALESCE(s.os, '')      || '|' ||
            COALESCE(s.device, '')  || '|' ||
            COALESCE(s.screen, '')  || '|' ||
            (we.created_at AT TIME ZONE 'UTC')::date::text
        ) AS visitor_id,
        (we.created_at AT TIME ZONE 'UTC')::date AS visit_date
    FROM website_event we
    JOIN session s ON we.session_id = s.session_id
    WHERE we.event_type = 1
),
with_gaps AS (
    SELECT
        *,
        EXTRACT(EPOCH FROM
            created_at - LAG(created_at) OVER (
                PARTITION BY visitor_id ORDER BY created_at
            )
        ) AS gap_secs
    FROM fingerprinted
),
visitor_stats AS (
    SELECT
        visitor_id,
        visit_date,
        MIN(country)    AS country,
        MIN(browser)    AS browser,
        MIN(os)         AS os,
        MIN(device)     AS device,
        MIN(screen)     AS screen,
        MIN(language)   AS language,
        MIN(city)       AS city,
        COUNT(*)        AS pageviews,
        MIN(created_at) AS first_seen,
        MAX(created_at) AS last_seen,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY gap_secs)
            FILTER (WHERE gap_secs IS NOT NULL) AS median_gap_secs
    FROM with_gaps
    GROUP BY visitor_id, visit_date
)
SELECT
    visitor_id,
    visit_date,
    country,
    browser,
    os,
    device,
    screen,
    language,
    city,
    pageviews,
    first_seen,
    last_seen,
    median_gap_secs,
    CASE
        -- Self-traffic: known owner fingerprint
        WHEN country = 'ZA'
         AND browser = 'chrome'
         AND os = 'Mac OS'
         AND device = 'laptop'
         AND screen = '1440x900'
        THEN 'self'
        -- Agent: headless-browser screen sizes
        WHEN screen IN ('800x600', '1024x768')
         AND device IN ('desktop', 'laptop')
        THEN 'agent'
        -- Agent: abnormally tall viewports (screenshot/crawler tools)
        WHEN screen ~ '^\d+x\d+$'
         AND split_part(screen, 'x', 2)::int > 2000
        THEN 'agent'
        -- Agent: rapid-fire browsing (median gap < 2s, 3+ pages)
        WHEN median_gap_secs IS NOT NULL
         AND median_gap_secs < 2.0
         AND pageviews >= 3
        THEN 'agent'
        ELSE 'human'
    END AS visitor_class
FROM visitor_stats;


-- ============================================================
-- View 2: v_sessions — Behavior layer
-- ============================================================
-- Reconstructs sessions using a 30-minute inactivity gap.
-- Inlines visitor classification to avoid circular dependency.

CREATE OR REPLACE VIEW v_sessions AS
WITH fingerprinted AS (
    SELECT
        we.event_id,
        we.created_at,
        we.url_path,
        we.referrer_domain,
        we.page_title,
        s.browser, s.os, s.device, s.screen, s.country,
        md5(
            COALESCE(s.country, '') || '|' ||
            COALESCE(s.browser, '') || '|' ||
            COALESCE(s.os, '')      || '|' ||
            COALESCE(s.device, '')  || '|' ||
            COALESCE(s.screen, '')  || '|' ||
            (we.created_at AT TIME ZONE 'UTC')::date::text
        ) AS visitor_id,
        (we.created_at AT TIME ZONE 'UTC')::date AS visit_date
    FROM website_event we
    JOIN session s ON we.session_id = s.session_id
    WHERE we.event_type = 1
),
with_gaps AS (
    SELECT
        *,
        EXTRACT(EPOCH FROM
            created_at - LAG(created_at) OVER (
                PARTITION BY visitor_id ORDER BY created_at
            )
        ) AS gap_secs
    FROM fingerprinted
),
session_boundaries AS (
    SELECT
        *,
        CASE
            WHEN gap_secs IS NULL OR gap_secs > 1800
            THEN 1
            ELSE 0
        END AS is_new_session
    FROM with_gaps
),
session_numbered AS (
    SELECT
        *,
        SUM(is_new_session) OVER (
            PARTITION BY visitor_id
            ORDER BY created_at
        ) AS session_num
    FROM session_boundaries
)
SELECT
    visitor_id,
    visit_date,
    session_num,
    visitor_id || '-' || session_num::text AS session_key,
    COUNT(*)            AS page_count,
    MIN(created_at)     AS session_start,
    MAX(created_at)     AS session_end,
    EXTRACT(EPOCH FROM MAX(created_at) - MIN(created_at))::int AS duration_secs,
    (ARRAY_AGG(url_path ORDER BY created_at))[1]        AS entry_page,
    (ARRAY_AGG(url_path ORDER BY created_at DESC))[1]   AS exit_page,
    (ARRAY_AGG(referrer_domain ORDER BY created_at)
        FILTER (WHERE referrer_domain IS NOT NULL AND referrer_domain != ''))[1] AS referrer_domain,
    ARRAY_AGG(url_path ORDER BY created_at)             AS page_journey,
    -- Inline visitor classification (mirrors v_visitors logic)
    CASE
        WHEN MIN(country) = 'ZA'
         AND MIN(browser) = 'chrome'
         AND MIN(os)      = 'Mac OS'
         AND MIN(device)  = 'laptop'
         AND MIN(screen)  = '1440x900'
        THEN 'self'
        WHEN MIN(screen) IN ('800x600', '1024x768')
         AND MIN(device) IN ('desktop', 'laptop')
        THEN 'agent'
        WHEN MIN(screen) ~ '^\d+x\d+$'
         AND split_part(MIN(screen), 'x', 2)::int > 2000
        THEN 'agent'
        WHEN COUNT(*) >= 3
         AND PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY gap_secs)
             FILTER (WHERE gap_secs IS NOT NULL) < 2.0
        THEN 'agent'
        ELSE 'human'
    END AS visitor_class
FROM session_numbered
GROUP BY visitor_id, visit_date, session_num;


-- ============================================================
-- View 3: v_page_classes — Intent layer
-- ============================================================
-- Classifies every pageview by intent tier, domain section,
-- and page type.

CREATE OR REPLACE VIEW v_page_classes AS
SELECT
    we.event_id,
    we.created_at,
    we.url_path,
    we.referrer_domain,
    we.page_title,
    we.session_id,
    md5(
        COALESCE(s.country, '') || '|' ||
        COALESCE(s.browser, '') || '|' ||
        COALESCE(s.os, '')      || '|' ||
        COALESCE(s.device, '')  || '|' ||
        COALESCE(s.screen, '')  || '|' ||
        (we.created_at AT TIME ZONE 'UTC')::date::text
    ) AS visitor_id,
    (we.created_at AT TIME ZONE 'UTC')::date AS visit_date,

    -- Intent classification
    CASE
        WHEN we.url_path ~ '^/api(/|$)'                THEN 'business'
        WHEN we.url_path ~ '^(/[^/]+)?/about/?$'       THEN 'business'
        WHEN we.url_path ~ '^(/[^/]+)?/methodology/?$' THEN 'business'
        WHEN we.url_path ~ '^(/[^/]+)?/compare/'       THEN 'research'
        WHEN we.url_path ~ '^(/[^/]+)?/categories/'    THEN 'research'
        WHEN we.url_path ~ '^(/[^/]+)?/deep_dives/'    THEN 'research'
        WHEN we.url_path ~ '^(/[^/]+)?/insights/'      THEN 'research'
        WHEN we.url_path ~ '^(/[^/]+)?/trending/?$'    THEN 'research'
        ELSE 'directory'
    END AS intent_tier,

    -- Domain section extraction
    CASE
        WHEN we.url_path ~ '^/agents/'            THEN 'agents'
        WHEN we.url_path ~ '^/rag/'               THEN 'rag'
        WHEN we.url_path ~ '^/ai-coding/'         THEN 'ai-coding'
        WHEN we.url_path ~ '^/voice-ai/'          THEN 'voice-ai'
        WHEN we.url_path ~ '^/diffusion/'         THEN 'diffusion'
        WHEN we.url_path ~ '^/vector-db/'         THEN 'vector-db'
        WHEN we.url_path ~ '^/embeddings/'        THEN 'embeddings'
        WHEN we.url_path ~ '^/prompt-engineering/' THEN 'prompt-engineering'
        WHEN we.url_path ~ '^/ml-frameworks/'     THEN 'ml-frameworks'
        WHEN we.url_path ~ '^/llm-tools/'         THEN 'llm-tools'
        WHEN we.url_path ~ '^/nlp/'               THEN 'nlp'
        WHEN we.url_path ~ '^/transformers/'      THEN 'transformers'
        WHEN we.url_path ~ '^/generative-ai/'     THEN 'generative-ai'
        WHEN we.url_path ~ '^/computer-vision/'   THEN 'computer-vision'
        WHEN we.url_path ~ '^/data-engineering/'  THEN 'data-engineering'
        WHEN we.url_path ~ '^/mlops/'             THEN 'mlops'
        ELSE 'mcp'
    END AS domain_section,

    -- Page type sub-classification
    CASE
        WHEN we.url_path = '' OR we.url_path = '/' THEN 'homepage'
        WHEN we.url_path ~ '^/api/docs'            THEN 'api_docs'
        WHEN we.url_path ~ '^/api/'                THEN 'api_other'
        WHEN we.url_path ~ '/about/?$'             THEN 'about'
        WHEN we.url_path ~ '/methodology/?$'       THEN 'methodology'
        WHEN we.url_path ~ '/compare/'             THEN 'comparison'
        WHEN we.url_path ~ '/categories/'          THEN 'category'
        WHEN we.url_path ~ '/deep_dives/'          THEN 'deep_dive'
        WHEN we.url_path ~ '/insights/'            THEN 'insight'
        WHEN we.url_path ~ '/trending/?$'          THEN 'trending'
        WHEN we.url_path ~ '/servers/'             THEN 'server_detail'
        ELSE 'other'
    END AS page_type

FROM website_event we
JOIN session s ON we.session_id = s.session_id
WHERE we.event_type = 1;


-- ============================================================
-- View 4: v_business_leads — Conversion layer
-- ============================================================
-- Every visitor who touched a business-intent page, with their
-- full journey reconstructed.

CREATE OR REPLACE VIEW v_business_leads AS
WITH business_visitors AS (
    SELECT DISTINCT visitor_id, visit_date
    FROM v_page_classes
    WHERE intent_tier = 'business'
),
journeys AS (
    SELECT
        pc.visitor_id,
        pc.visit_date,
        pc.created_at,
        pc.url_path,
        pc.intent_tier,
        pc.domain_section,
        pc.page_type,
        pc.referrer_domain
    FROM v_page_classes pc
    JOIN business_visitors bv
      ON pc.visitor_id = bv.visitor_id
     AND pc.visit_date = bv.visit_date
)
SELECT
    j.visitor_id,
    j.visit_date,
    v.visitor_class,
    v.country,
    v.browser,
    v.os,
    v.device,
    v.screen,
    v.language,
    v.pageviews AS total_pageviews,
    COUNT(*) FILTER (WHERE j.intent_tier = 'business')  AS business_pages,
    COUNT(*) FILTER (WHERE j.intent_tier = 'research')  AS research_pages,
    COUNT(*) FILTER (WHERE j.intent_tier = 'directory') AS directory_pages,
    ARRAY_AGG(DISTINCT j.url_path)
        FILTER (WHERE j.intent_tier = 'business')       AS business_urls,
    ARRAY_AGG(DISTINCT j.page_type)
        FILTER (WHERE j.intent_tier = 'business')       AS business_page_types,
    ARRAY_AGG(DISTINCT j.domain_section)                 AS domains_explored,
    ARRAY_AGG(j.url_path ORDER BY j.created_at)          AS full_journey,
    (ARRAY_AGG(j.referrer_domain ORDER BY j.created_at)
        FILTER (WHERE j.referrer_domain IS NOT NULL
                  AND j.referrer_domain != ''))[1]       AS referrer,
    MIN(j.created_at) AS first_seen,
    MAX(j.created_at) AS last_seen,
    EXTRACT(EPOCH FROM MAX(j.created_at) - MIN(j.created_at))::int AS visit_duration_secs
FROM journeys j
JOIN v_visitors v
  ON j.visitor_id = v.visitor_id
 AND j.visit_date = v.visit_date
GROUP BY
    j.visitor_id, j.visit_date,
    v.visitor_class, v.country, v.browser, v.os, v.device, v.screen,
    v.language, v.pageviews
ORDER BY j.visit_date DESC, business_pages DESC;


-- ============================================================
-- View 5: v_daily_summary — Dashboard layer
-- ============================================================
-- One row per day with headline metrics, intent breakdown,
-- top pages, and referrer sources.

CREATE OR REPLACE VIEW v_daily_summary AS
WITH daily_visitors AS (
    SELECT
        visit_date,
        visitor_class,
        COUNT(*)        AS unique_visitors,
        SUM(pageviews)  AS total_pageviews
    FROM v_visitors
    GROUP BY visit_date, visitor_class
),
daily_totals AS (
    SELECT
        visit_date,
        SUM(unique_visitors)  AS total_visitors,
        SUM(total_pageviews)  AS total_pageviews,
        COALESCE(SUM(unique_visitors)  FILTER (WHERE visitor_class = 'human'), 0)  AS human_visitors,
        COALESCE(SUM(total_pageviews)  FILTER (WHERE visitor_class = 'human'), 0)  AS human_pageviews,
        COALESCE(SUM(unique_visitors)  FILTER (WHERE visitor_class = 'agent'), 0)  AS agent_visitors,
        COALESCE(SUM(total_pageviews)  FILTER (WHERE visitor_class = 'agent'), 0)  AS agent_pageviews,
        COALESCE(SUM(unique_visitors)  FILTER (WHERE visitor_class = 'self'), 0)   AS self_visitors,
        COALESCE(SUM(total_pageviews)  FILTER (WHERE visitor_class = 'self'), 0)   AS self_pageviews
    FROM daily_visitors
    GROUP BY visit_date
),
daily_sessions AS (
    SELECT
        visit_date,
        COUNT(*)                          AS total_sessions,
        AVG(page_count)::numeric(5,1)     AS avg_pages_per_session,
        AVG(duration_secs)::int           AS avg_session_duration_secs,
        COUNT(*) FILTER (WHERE page_count = 1) AS bounce_sessions,
        COUNT(*) FILTER (WHERE visitor_class != 'self') AS non_self_sessions
    FROM v_sessions
    GROUP BY visit_date
),
daily_intents AS (
    SELECT
        visit_date,
        COUNT(*) FILTER (WHERE intent_tier = 'business')  AS business_pageviews,
        COUNT(*) FILTER (WHERE intent_tier = 'research')  AS research_pageviews,
        COUNT(*) FILTER (WHERE intent_tier = 'directory') AS directory_pageviews
    FROM v_page_classes
    GROUP BY visit_date
)
SELECT
    dt.visit_date,
    -- Visitor counts
    dt.total_visitors,
    dt.human_visitors,
    dt.agent_visitors,
    dt.self_visitors,
    -- Pageview counts
    dt.total_pageviews,
    dt.human_pageviews,
    dt.agent_pageviews,
    dt.self_pageviews,
    -- Engagement (excluding self)
    CASE
        WHEN dt.human_visitors + dt.agent_visitors > 0
        THEN ((dt.human_pageviews + dt.agent_pageviews)::numeric
              / (dt.human_visitors + dt.agent_visitors))::numeric(5,1)
        ELSE 0
    END AS pages_per_visitor_excl_self,
    -- Session metrics
    COALESCE(ds.total_sessions, 0)             AS total_sessions,
    COALESCE(ds.avg_pages_per_session, 0)      AS avg_pages_per_session,
    COALESCE(ds.avg_session_duration_secs, 0)  AS avg_session_duration_secs,
    COALESCE(ds.bounce_sessions, 0)            AS bounce_sessions,
    CASE
        WHEN COALESCE(ds.total_sessions, 0) > 0
        THEN (ds.bounce_sessions::numeric / ds.total_sessions * 100)::numeric(5,1)
        ELSE 0
    END AS bounce_rate_pct,
    -- Intent breakdown
    COALESCE(di.business_pageviews, 0)  AS business_pageviews,
    COALESCE(di.research_pageviews, 0)  AS research_pageviews,
    COALESCE(di.directory_pageviews, 0) AS directory_pageviews
FROM daily_totals dt
LEFT JOIN daily_sessions ds ON dt.visit_date = ds.visit_date
LEFT JOIN daily_intents di  ON dt.visit_date = di.visit_date
ORDER BY dt.visit_date DESC;
