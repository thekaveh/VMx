"""Keep TypeScript host recipes tied to the files the recipe fixture runs.

Each guide fence carries a ``checked-snippet`` marker naming its fixture file;
``make docs-check`` (scripts/docs/check_docs.py) fails when a fence differs from
that file. These tests keep the markers in place and the fixture executed.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = REPO_ROOT / "docs" / "content" / "integration"
FIXTURE = REPO_ROOT / "examples" / "typescript" / "integration-recipes"

# (guide, adapter section heading, fence language, fixture file)
RECIPES = [
    ("vue.md", "## 9.9.3. Adapter skeleton", "ts", "src/vue/composables/useVm.ts"),
    ("vue.md", "## 9.9.3. Adapter skeleton", "vue", "src/vue/NoteView.vue"),
    ("solid.md", "## 9.11.3. Adapter skeleton", "tsx", "src/solid/NoteView.tsx"),
    ("svelte.md", "## 9.10.3. Adapter skeleton — store", "ts", "src/svelte/vmStore.ts"),
    ("svelte.md", "## 9.10.3. Adapter skeleton — store", "svelte", "src/svelte/NoteView.svelte"),
    (
        "svelte.md",
        "## 9.10.4. Adapter skeleton — Svelte 5",
        "svelte",
        "src/svelte/NoteViewRunes.svelte",
    ),
]


def _section(guide: str, heading: str) -> str:
    text = (INTEGRATION / guide).read_text(encoding="utf-8")
    assert heading in text, f"{guide} lost its '{heading}' section"
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


@pytest.mark.parametrize(("guide", "heading", "language", "fixture"), RECIPES)
def test_recipe_fence_is_checked_against_the_executed_fixture(
    guide: str, heading: str, language: str, fixture: str
) -> None:
    section = _section(guide, heading)
    assert len(re.findall(rf"```{language}\n", section)) == 1, (
        f"{guide} should show exactly one {language} block"
    )
    source = (FIXTURE / fixture).relative_to(REPO_ROOT).as_posix()
    marker = rf"<!-- checked-snippet: {re.escape(source)} -->\n\n```{language}\n"
    assert re.search(marker, section), f"{guide} lost the checked-snippet marker for {fixture}"


def test_fixture_pins_the_host_versions_the_guides_name() -> None:
    manifest = (FIXTURE / "package.json").read_text(encoding="utf-8")
    for guide, package in (("vue.md", "vue"), ("solid.md", "solid-js"), ("svelte.md", "svelte")):
        version = re.search(rf'"{re.escape(package)}": "(\d+\.\d+\.\d+)"', manifest)
        assert version is not None, f"{package} must be pinned to an exact version"
        text = (INTEGRATION / guide).read_text(encoding="utf-8")
        assert f"`{package}` {version.group(1)}" in text


def test_ci_executes_the_fixture_through_the_packed_package() -> None:
    assert (FIXTURE / ".npmrc").read_text(encoding="utf-8") == "install-links=true\n"
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!/examples/typescript/integration-recipes/package-lock.json" in gitignore
    workflow = (REPO_ROOT / ".github" / "workflows" / "typescript.yml").read_text(encoding="utf-8")
    prefix = "--prefix examples/typescript/integration-recipes"
    for command in (
        f"npm ci {prefix}",
        f"npm run check:deps {prefix}",
        f"npm audit {prefix} --package-lock-only --audit-level=moderate",
        f"npm test {prefix}",
        f"npm run typecheck {prefix}",
    ):
        assert command in workflow, command
    for automation in (".github/workflows/security-audit.yml", ".github/dependabot.yml"):
        assert "examples/typescript/integration-recipes" in (REPO_ROOT / automation).read_text(
            encoding="utf-8"
        )
