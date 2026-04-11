"""Tests for app.api.core — shared query layer."""
import pytest
from app.api.core import validate_sql, _name_boost, _serialize, _row_to_dict


# ---------------------------------------------------------------------------
# SQL validation
# ---------------------------------------------------------------------------

class TestValidateSql:
    def test_select_allowed(self):
        assert validate_sql("SELECT * FROM ai_repos LIMIT 10") is None

    def test_with_cte_allowed(self):
        assert validate_sql("WITH x AS (SELECT 1) SELECT * FROM x") is None

    def test_insert_blocked(self):
        assert validate_sql("INSERT INTO ai_repos VALUES (1)") is not None

    def test_update_blocked(self):
        assert validate_sql("UPDATE ai_repos SET stars = 0") is not None

    def test_delete_blocked(self):
        assert validate_sql("DELETE FROM ai_repos") is not None

    def test_drop_blocked(self):
        assert validate_sql("DROP TABLE ai_repos") is not None

    def test_forbidden_in_subquery(self):
        # DELETE hidden inside a valid-looking SELECT
        assert validate_sql("SELECT * FROM (DELETE FROM ai_repos RETURNING *)") is not None

    def test_only_select(self):
        err = validate_sql("CREATE TABLE foo (id int)")
        assert err is not None

    def test_stacked_queries_blocked(self):
        err = validate_sql("SELECT 1; DROP TABLE ai_repos")
        assert "Multiple" in err

    def test_trailing_semicolon_ok(self):
        assert validate_sql("SELECT 1;") is None

    def test_comment_obfuscation_blocked(self):
        # Try to hide DROP inside a comment-stripped query
        err = validate_sql("SELECT /* */ 1; DROP TABLE x")
        assert err is not None

    def test_line_comment_obfuscation_blocked(self):
        err = validate_sql("SELECT 1 -- harmless\n; DELETE FROM x")
        assert err is not None

    def test_pg_admin_functions_blocked(self):
        assert validate_sql("SELECT pg_read_file('/etc/passwd')") is not None
        assert validate_sql("SELECT pg_terminate_backend(1)") is not None
        assert validate_sql("SELECT set_config('x', 'y', false)") is not None

    def test_empty_string(self):
        err = validate_sql("")
        assert err is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestNameBoost:
    def test_exact_match(self):
        assert _name_boost("langchain", "langchain") == 0.15

    def test_exact_match_with_owner(self):
        assert _name_boost("langchain", "langchain-ai/langchain") == 0.15

    def test_partial_match(self):
        assert _name_boost("lang", "langchain") == 0.08

    def test_no_match(self):
        assert _name_boost("pytorch", "langchain") == 0.0

    def test_empty_query(self):
        assert _name_boost("", "langchain") == 0.0

    def test_case_insensitive(self):
        assert _name_boost("LangChain", "langchain") == 0.15


class TestSerialize:
    def test_datetime(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert "2026-01-01" in _serialize(dt)

    def test_date(self):
        from datetime import date
        d = date(2026, 1, 1)
        assert _serialize(d) == "2026-01-01"

    def test_float(self):
        import decimal
        assert _serialize(decimal.Decimal("3.14")) == 3.14

    def test_fallback(self):
        assert _serialize(object()) != ""  # str(obj) fallback
