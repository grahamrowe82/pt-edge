"""Ensure all domain registration points stay in sync.

The canonical domain list lives in ai_repo_domains.DOMAINS.  Every other
file that references domains must cover exactly the same set.  Files that
import from app.config.domains are tested implicitly (they derive from
DOMAINS).  This test covers the files that still need manual entries.
"""
import ast
import re
from pathlib import Path

from app.ingest.ai_repo_domains import DOMAINS


def _expected():
    return set(DOMAINS.keys())


def _extract_dict_keys(filepath: str, varname: str) -> set[str]:
    """Extract top-level keys from a dict assignment by parsing the source."""
    source = Path(filepath).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == varname:
                    if isinstance(node.value, ast.Dict):
                        return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


def _extract_list_field(filepath: str, varname: str, field: str) -> set[str]:
    """Extract a field value from each dict in a list assignment."""
    source = Path(filepath).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == varname:
                    if isinstance(node.value, ast.List):
                        values = set()
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Dict):
                                for k, v in zip(elt.keys, elt.values):
                                    if isinstance(k, ast.Constant) and k.value == field and isinstance(v, ast.Constant):
                                        values.add(v.value)
                        return values
    return set()


def test_generate_site_domain_config():
    found = _extract_dict_keys("scripts/generate_site.py", "DOMAIN_CONFIG")
    assert found == _expected(), (
        f"DOMAIN_CONFIG missing: {_expected() - found}; extra: {found - _expected()}"
    )


def test_generate_site_directories():
    dirs = _extract_list_field("scripts/generate_site.py", "DIRECTORIES", "domain")
    assert dirs == _expected(), (
        f"DIRECTORIES missing: {_expected() - dirs}; extra: {dirs - _expected()}"
    )


def test_docs_page_directories():
    dirs = _extract_list_field("app/api/docs_page.py", "_DIRECTORIES", "domain")
    assert dirs == _expected(), (
        f"_DIRECTORIES missing: {_expected() - dirs}; extra: {dirs - _expected()}"
    )


def test_start_sh_domains():
    start_sh = Path("scripts/start.sh").read_text()
    # Each domain has a line: python scripts/generate_site.py --domain X
    found = set(re.findall(r"--domain\s+(\S+)", start_sh))
    assert found == _expected(), (
        f"start.sh missing: {_expected() - found}; extra: {found - _expected()}"
    )


def test_smoke_expected_domains():
    """The hardcoded expected_domains in test_smoke.py must match DOMAINS."""
    source = Path("tests/test_smoke.py").read_text()
    match = re.search(r"expected_domains\s*=\s*\{([^}]+)\}", source)
    assert match, "Could not find expected_domains in test_smoke.py"
    found = set(re.findall(r'"([^"]+)"', match.group(1)))
    assert found == _expected(), (
        f"test_smoke.py expected_domains missing: {_expected() - found}; "
        f"extra: {found - _expected()}"
    )
