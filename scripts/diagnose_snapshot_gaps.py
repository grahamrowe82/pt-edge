#!/usr/bin/env python3
"""Diagnose snapshot coverage gaps in github_snapshots and download_snapshots.

Usage:
    python3 scripts/diagnose_snapshot_gaps.py
    # or with a custom DATABASE_URL:
    DATABASE_URL=... python3 scripts/diagnose_snapshot_gaps.py
"""

import os
import sys

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

# psycopg2 needs postgresql:// not postgresql+psycopg2://
dsn = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")


def run():
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    for table in ("github_snapshots", "download_snapshots"):
        print(f"\n{'=' * 60}")
        print(f"  {table}")
        print(f"{'=' * 60}")

        # Date range and total rows
        cur.execute(f"""
            SELECT MIN(snapshot_date), MAX(snapshot_date), COUNT(*)
            FROM {table}
        """)
        min_date, max_date, total = cur.fetchone()
        if not min_date:
            print("  No data.\n")
            continue
        print(f"  Range: {min_date} → {max_date}  ({total:,} rows)")

        # Distinct dates
        cur.execute(f"SELECT COUNT(DISTINCT snapshot_date) FROM {table}")
        distinct_days = cur.fetchone()[0]
        expected_days = (max_date - min_date).days + 1
        missing_days = expected_days - distinct_days
        print(f"  Distinct dates: {distinct_days} / {expected_days} expected  ({missing_days} gaps)")

        # List gap dates (up to 30)
        if missing_days > 0:
            cur.execute(f"""
                WITH date_range AS (
                    SELECT generate_series(
                        (SELECT MIN(snapshot_date) FROM {table}),
                        (SELECT MAX(snapshot_date) FROM {table}),
                        '1 day'::interval
                    )::date AS d
                )
                SELECT d FROM date_range
                WHERE d NOT IN (SELECT DISTINCT snapshot_date FROM {table})
                ORDER BY d
                LIMIT 30
            """)
            gaps = [row[0] for row in cur.fetchall()]
            print(f"  Gap dates (first 30): {', '.join(str(g) for g in gaps)}")

        # Projects with < 30 days of coverage (github_snapshots only)
        if table == "github_snapshots":
            cur.execute("""
                SELECT p.name, COUNT(DISTINCT gs.snapshot_date) AS days
                FROM projects p
                JOIN github_snapshots gs ON p.id = gs.project_id
                WHERE p.is_active = true
                GROUP BY p.name
                HAVING COUNT(DISTINCT gs.snapshot_date) < 30
                ORDER BY days
            """)
            sparse = cur.fetchall()
            if sparse:
                print(f"\n  Projects with < 30 days coverage ({len(sparse)}):")
                for name, days in sparse[:20]:
                    print(f"    {name}: {days} days")
                if len(sparse) > 20:
                    print(f"    ... and {len(sparse) - 20} more")

    cur.close()
    conn.close()
    print()


if __name__ == "__main__":
    run()
