"""PT-Edge CLI — query the AI ecosystem from your terminal.

Usage:
    ptedge status                              # what's available
    ptedge tables                              # list all tables
    ptedge describe ai_repos                   # column details
    ptedge search-tables embedding             # find tables
    ptedge query "SELECT ..."                  # run SQL
    ptedge workflows                           # pre-built recipes
    ptedge search "code generation agent"      # semantic search
    ptedge feedback "topic" "your feedback"    # submit feedback
    ptedge login                               # store API key
"""

import json
import sys

import click

from ptedge.client import PTEdgeClient, _save_config, _load_config


def _format_json(data, pretty: bool = False):
    """Format data as JSON."""
    if pretty:
        return json.dumps(data, indent=2, default=str)
    return json.dumps(data, default=str)


def _format_table(rows: list[dict], columns: list[str] | None = None):
    """Simple aligned table output."""
    if not rows:
        return "No results."
    if columns is None:
        columns = list(rows[0].keys())

    # Compute column widths
    widths = {c: len(c) for c in columns}
    for row in rows:
        for c in columns:
            val = str(row.get(c, ""))[:60]
            widths[c] = max(widths[c], len(val))

    # Header
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    lines = [header, sep]

    for row in rows:
        line = "  ".join(str(row.get(c, ""))[:60].ljust(widths[c]) for c in columns)
        lines.append(line)

    return "\n".join(lines)


@click.group()
@click.option("--key", envvar="PTEDGE_API_KEY", default=None, help="API key (or set PTEDGE_API_KEY)")
@click.option("--url", envvar="PTEDGE_BASE_URL", default=None, help="API base URL")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.pass_context
def main(ctx, key, url, fmt):
    """PT-Edge CLI — AI ecosystem intelligence from your terminal."""
    ctx.ensure_object(dict)
    ctx.obj["client"] = PTEdgeClient(base_url=url, api_key=key)
    ctx.obj["fmt"] = fmt


@main.command()
@click.pass_context
def status(ctx):
    """Show what data is available."""
    data = ctx.obj["client"].status()["data"]
    if ctx.obj["fmt"] == "json":
        click.echo(_format_json(data, pretty=True))
        return
    click.echo(f"Tables: {data['tables']}")
    click.echo(f"AI repos: {data['ai_repos']:,}")
    if data.get("last_sync"):
        click.echo(f"Last sync: {data['last_sync']['type']} at {data['last_sync']['at']}")
    click.echo(f"\nDomains ({len(data['domains'])}):")
    for d in data["domains"]:
        click.echo(f"  {d['name']:<30} {d['count']:,}")


@main.command()
@click.pass_context
def tables(ctx):
    """List all database tables."""
    data = ctx.obj["client"].list_tables()["data"]
    if ctx.obj["fmt"] == "json":
        click.echo(_format_json(data, pretty=True))
        return
    click.echo(_format_table(data, ["table_name", "row_estimate", "column_count"]))


@main.command()
@click.argument("table_name")
@click.pass_context
def describe(ctx, table_name):
    """Show columns for a table."""
    data = ctx.obj["client"].describe_table(table_name)["data"]
    if ctx.obj["fmt"] == "json":
        click.echo(_format_json(data, pretty=True))
        return
    click.echo(f"TABLE: {data['table_name']}  (~{data['row_estimate']:,} rows)\n")
    click.echo(_format_table(data["columns"], ["name", "type", "nullable"]))


@main.command("search-tables")
@click.argument("keyword")
@click.pass_context
def search_tables(ctx, keyword):
    """Find tables by keyword."""
    data = ctx.obj["client"].search_tables(keyword)["data"]
    if ctx.obj["fmt"] == "json":
        click.echo(_format_json(data, pretty=True))
        return
    if not data:
        click.echo(f"No tables matching '{keyword}'.")
        return
    for t in data:
        click.echo(f"  {t['table_name']}")


@main.command()
@click.argument("sql")
@click.pass_context
def query(ctx, sql):
    """Run a read-only SQL query."""
    data = ctx.obj["client"].query(sql)["data"]
    if ctx.obj["fmt"] == "json":
        click.echo(_format_json(data, pretty=True))
        return
    if not data:
        click.echo("No results.")
        return
    click.echo(_format_table(data))


@main.command()
@click.pass_context
def workflows(ctx):
    """Show pre-built SQL recipe workflows."""
    data = ctx.obj["client"].workflows()["data"]
    if ctx.obj["fmt"] == "json":
        click.echo(_format_json(data, pretty=True))
        return
    if not data:
        click.echo("No workflows available.")
        return
    for w in data:
        click.echo(f"\n{w['name']}  [{w.get('category', 'general')}]")
        click.echo(f"  {w['description']}")
        if w.get("parameters"):
            params = w["parameters"] if isinstance(w["parameters"], dict) else {}
            if params:
                click.echo(f"  Parameters: {', '.join(params.keys())}")


@main.command()
@click.argument("q")
@click.option("--domain", default="", help="Domain filter (e.g. mcp, agents, rag)")
@click.option("--limit", default=5, help="Max results (1-20)")
@click.pass_context
def search(ctx, q, domain, limit):
    """Search AI repos by description."""
    data = ctx.obj["client"].search(q, domain=domain, limit=limit)["data"]
    if ctx.obj["fmt"] == "json":
        click.echo(_format_json(data, pretty=True))
        return
    if not data:
        click.echo(f"No results for '{q}'.")
        return
    for i, r in enumerate(data, 1):
        stars = f"{r['stars']:,}" if r.get("stars") else "?"
        lang = f" · {r['language']}" if r.get("language") else ""
        click.echo(f"\n{i}. {r['full_name']}  ({stars} stars{lang})")
        if r.get("description"):
            click.echo(f"   {r['description'][:120]}")
        if r.get("domain"):
            click.echo(f"   [{r['domain']}]  https://github.com/{r['full_name']}")


@main.command()
@click.argument("topic")
@click.argument("text")
@click.option("--category", default="observation", type=click.Choice(["bug", "feature", "observation", "insight"]))
@click.pass_context
def feedback(ctx, topic, text, category):
    """Submit feedback about the data."""
    data = ctx.obj["client"].feedback(topic, text, category)["data"]
    click.echo(f"Feedback submitted (ID: {data['id']})")


@main.command()
@click.pass_context
def login(ctx):
    """Store your API key for future use."""
    click.echo("Get a free API key at: https://mcp.phasetransitions.ai/api/docs")
    click.echo("Or create one: curl -X POST https://mcp.phasetransitions.ai/api/v1/keys")
    click.echo()
    key = click.prompt("API key (pte_...)")
    if not key.startswith("pte_"):
        click.echo("Error: API keys start with pte_", err=True)
        sys.exit(1)
    config = _load_config()
    config["api_key"] = key
    _save_config(config)
    click.echo("Saved to ~/.ptedge/config.json")


if __name__ == "__main__":
    main()
