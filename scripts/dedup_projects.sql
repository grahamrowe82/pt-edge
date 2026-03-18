-- Dedup script: merge duplicate OpenHands project rows.
-- Keep project 258 (correct github_owner 'All-Hands-AI'),
-- absorb data from project 609 (wrong owner 'OpenHands').

BEGIN;

-- 1. Copy ai_repo_id link from 609 to 258
UPDATE projects SET ai_repo_id = (SELECT ai_repo_id FROM projects WHERE id = 609)
WHERE id = 258 AND ai_repo_id IS NULL;

-- 2. Move github_snapshots from 609 to 258 (skip date conflicts)
INSERT INTO github_snapshots (project_id, snapshot_date, captured_at, stars, forks, open_issues, watchers, commits_30d, contributors, last_commit_at, license)
SELECT 258, snapshot_date, captured_at, stars, forks, open_issues, watchers, commits_30d, contributors, last_commit_at, license
FROM github_snapshots WHERE project_id = 609
ON CONFLICT (project_id, snapshot_date) DO NOTHING;

-- 3. Move lifecycle_history from 609 to 258 (skip date conflicts)
INSERT INTO lifecycle_history (project_id, lifecycle_stage, snapshot_date)
SELECT 258, lifecycle_stage, snapshot_date
FROM lifecycle_history WHERE project_id = 609
ON CONFLICT (project_id, snapshot_date) DO NOTHING;

-- 4. Delete orphan foreign key rows
DELETE FROM github_snapshots WHERE project_id = 609;
DELETE FROM lifecycle_history WHERE project_id = 609;
DELETE FROM download_snapshots WHERE project_id = 609;
DELETE FROM hn_posts WHERE project_id = 609;
DELETE FROM releases WHERE project_id = 609;
DELETE FROM v2ex_posts WHERE project_id = 609;

-- 5. Delete orphan project
DELETE FROM projects WHERE id = 609;

-- 6. Rename slug on the kept project
UPDATE projects SET slug = 'openhands'
WHERE id = 258;

COMMIT;
