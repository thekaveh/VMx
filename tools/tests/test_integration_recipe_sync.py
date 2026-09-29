"""Keep TypeScript host recipes identical to the files the recipe fixture runs."""

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
]


def _section(guide: str, heading: str) -> str:
    text = (INTEGRATION / guide).read_text(encoding="utf-8")
    assert heading in text, f"{guide} lost its '{heading}' section"
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


@pytest.mark.parametrize(("guide", "heading", "language", "fixture"), RECIPES)
def test_recipe_snippet_matches_the_executed_fixture(
    guide: str, heading: str, language: str, fixture: str
) -> None:
    blocks = re.findall(rf"```{language}\n(.*?)```", _section(guide, heading), re.S)
    assert len(blocks) == 1, f"{guide} should show exactly one {language} block"
    assert blocks[0] == (FIXTURE / fixture).read_text(encoding="utf-8")


def test_fixture_pins_the_host_versions_the_guides_name() -> None:
    manifest = (FIXTURE / "package.json").read_text(encoding="utf-8")
    for guide, package in (("vue.md", "vue"), ("solid.md", "solid-js")):
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
