"""Keep the mdformat exclusion lists of the pre-commit hook and the CI step equal (#1817).

The hook (`.pre-commit-config.yaml`) and the CI backstop (`.github/workflows/conformance.yml`)
each hold a copy of the page list that mdformat must skip. This test fails when the two
copies select different pages, and when an excluded page has no reason to be excluded.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
CONFORMANCE = ROOT / ".github/workflows/conformance.yml"

# mdformat rewrites indented Material tab content (`=== "..."`) into separate fenced
# blocks, so a page with a tab marker must be excluded.
TAB_MARKER = re.compile(r'^\s*=== "', re.MULTILINE)
# Page -> reason, for an excluded page that has no tab marker. Empty today.
OTHER_REASONS: dict[str, str] = {}
CHANGELOGS = 6


def _hook_exclude() -> re.Pattern[str]:
    text = PRE_COMMIT.read_text(encoding="utf-8")
    mdformat_hook = text.split("- id: mdformat\n", 1)[1]
    block = mdformat_hook.split("exclude: |", 1)[1].split("additional_dependencies:", 1)[0]
    return re.compile(block.strip())  # the block starts with (?x)


def _ci_exclude() -> re.Pattern[str]:
    text = CONFORMANCE.read_text(encoding="utf-8")
    step = text.split("mdformat check (spec/ + docs/ + CHANGELOGs)", 1)[1]
    match = re.search(r"grep -Ev '([^']+)'", step)
    assert match is not None, "the mdformat step has no grep -Ev exclusion"
    return re.compile(match.group(1))


def _candidates() -> list[str]:
    """Every Markdown page the hook and the CI step can check (the spec/ and docs/ trees)."""
    pages = [p for folder in ("docs", "spec") for p in (ROOT / folder).rglob("*.md")]
    pages += [*ROOT.glob("langs/*/CHANGELOG.md"), ROOT / "packages/react/CHANGELOG.md"]
    return sorted(p.relative_to(ROOT).as_posix() for p in pages)


def test_candidates_include_the_six_changelogs() -> None:
    changelogs = [page for page in _candidates() if page.endswith("/CHANGELOG.md")]
    assert len(changelogs) == CHANGELOGS, changelogs


def test_hook_and_ci_exclude_the_same_pages() -> None:
    candidates = _candidates()
    hook = {page for page in candidates if _hook_exclude().match(page)}
    ci = {page for page in candidates if _ci_exclude().match(page)}
    assert hook == ci, {"only_in_hook": sorted(hook - ci), "only_in_ci": sorted(ci - hook)}


def test_each_excluded_page_has_tab_content_or_a_reason() -> None:
    hook = _hook_exclude()
    excluded = {page for page in _candidates() if hook.match(page)}
    stale = sorted(set(OTHER_REASONS) - excluded)
    assert not stale, f"OTHER_REASONS names pages that are not excluded: {stale}"
    for page in sorted(excluded - set(OTHER_REASONS)):
        text = (ROOT / page).read_text(encoding="utf-8")
        assert TAB_MARKER.search(text), f"{page} is excluded but has no tab marker"
