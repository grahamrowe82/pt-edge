#!/usr/bin/env python3
"""CLI to create, list, revoke, and inspect usage of API keys.

Usage:
    python scripts/manage_api_keys.py create --company "Acme AI" --email "a@acme.ai" --tier pro
    python scripts/manage_api_keys.py list
    python scripts/manage_api_keys.py revoke pte_a3b1...
    python scripts/manage_api_keys.py usage pte_a3b1...
"""

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import text

# Allow running from repo root
sys.path.insert(0, ".")
from app.db import engine
from app.api.keys import generate_key, hash_key

# Keep old names for backward compat within this script
_generate_key = generate_key
_hash_key = hash_key


def cmd_create(args):
    raw_key = _generate_key()
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:8]

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO api_keys (key_hash, key_prefix, company_name, contact_email, tier)
                VALUES (:h, :p, :company, :email, :tier)
            """),
            {"h": key_hash, "p": key_prefix, "company": args.company, "email": args.email, "tier": args.tier},
        )

    print(f"Created API key for {args.company} ({args.tier} tier)")
    print(f"Key: {raw_key}")
    print(f"Prefix: {key_prefix}")
    print()
    print("IMPORTANT: Save this key now. It cannot be retrieved again.")


def cmd_list(args):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, key_prefix, company_name, contact_email, tier, is_active,
                   created_at, revoked_at, last_used_at
            FROM api_keys ORDER BY id
        """)).fetchall()

    if not rows:
        print("No API keys found.")
        return

    print(f"{'ID':<5} {'Prefix':<10} {'Company':<25} {'Tier':<6} {'Active':<8} {'Last Used':<22} {'Created':<22}")
    print("-" * 100)
    for r in rows:
        m = r._mapping
        last_used = m["last_used_at"].strftime("%Y-%m-%d %H:%M") if m["last_used_at"] else "never"
        created = m["created_at"].strftime("%Y-%m-%d %H:%M") if m["created_at"] else ""
        active = "yes" if m["is_active"] and not m["revoked_at"] else "REVOKED"
        print(f"{m['id']:<5} {m['key_prefix']:<10} {m['company_name']:<25} {m['tier']:<6} {active:<8} {last_used:<22} {created:<22}")


def cmd_revoke(args):
    key_prefix = args.key[:8] if len(args.key) >= 8 else args.key

    # If full key provided, use hash lookup; otherwise match prefix
    if args.key.startswith("pte_") and len(args.key) == 36:
        key_hash = _hash_key(args.key)
        where = "key_hash = :match"
        params = {"match": key_hash}
    else:
        where = "key_prefix = :match"
        params = {"match": key_prefix}

    with engine.begin() as conn:
        result = conn.execute(
            text(f"""
                UPDATE api_keys SET is_active = false, revoked_at = NOW()
                WHERE {where} AND revoked_at IS NULL
                RETURNING id, key_prefix, company_name
            """),
            params,
        ).fetchone()

    if result:
        m = result._mapping
        print(f"Revoked key {m['key_prefix']} (ID {m['id']}, {m['company_name']})")
    else:
        print(f"No active key found matching '{key_prefix}'")


def cmd_usage(args):
    key_prefix = args.key[:8] if len(args.key) >= 8 else args.key

    if args.key.startswith("pte_") and len(args.key) == 36:
        key_hash = _hash_key(args.key)
        key_where = "k.key_hash = :match"
        params = {"match": key_hash}
    else:
        key_where = "k.key_prefix = :match"
        params = {"match": key_prefix}

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT u.endpoint, u.params, u.duration_ms, u.status_code, u.created_at
            FROM api_usage u
            JOIN api_keys k ON u.api_key_id = k.id
            WHERE {key_where}
            ORDER BY u.created_at DESC
            LIMIT 50
        """), params).fetchall()

    if not rows:
        print(f"No usage found for key '{key_prefix}'")
        return

    print(f"Recent usage for {key_prefix} ({len(rows)} most recent):")
    print(f"{'Time':<22} {'Status':<7} {'ms':<6} {'Endpoint':<30} {'Params'}")
    print("-" * 100)
    for r in rows:
        m = r._mapping
        ts = m["created_at"].strftime("%Y-%m-%d %H:%M:%S") if m["created_at"] else ""
        params_str = str(m["params"] or "")[:40]
        print(f"{ts:<22} {m['status_code'] or '':<7} {m['duration_ms'] or '':<6} {m['endpoint']:<30} {params_str}")


def main():
    parser = argparse.ArgumentParser(description="Manage PT-Edge API keys")
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create", help="Create a new API key")
    create_p.add_argument("--company", required=True)
    create_p.add_argument("--email", required=True)
    create_p.add_argument("--tier", default="free", choices=["free", "pro"])

    sub.add_parser("list", help="List all API keys")

    revoke_p = sub.add_parser("revoke", help="Revoke an API key")
    revoke_p.add_argument("key", help="Full key (pte_...) or prefix")

    usage_p = sub.add_parser("usage", help="Show usage for an API key")
    usage_p.add_argument("key", help="Full key (pte_...) or prefix")

    args = parser.parse_args()
    {"create": cmd_create, "list": cmd_list, "revoke": cmd_revoke, "usage": cmd_usage}[args.command](args)


if __name__ == "__main__":
    main()
