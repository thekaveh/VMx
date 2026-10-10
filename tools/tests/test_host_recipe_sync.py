"""Keep the WPF, MAUI and Textual recipes tied to the files CI executes.

Each guide fence carries a ``checked-snippet`` marker naming its source (or a
region of it); ``make docs-check`` (scripts/docs/check_docs.py) fails when a
fence differs. These tests keep the markers in place and the sources executed.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = REPO_ROOT / "docs" / "content" / "integration"
XAML_ADAPTER = "langs/csharp/tests/VMx.Tests/Integration/BindableVm.cs#xaml-adapter"
TEXTUAL_WIDGET = "examples/python/textual/notes_showcase/tests/views/textual_recipe.py"
TEXTUAL_GRID = "examples/python/textual/notes_showcase/tests/views/data_table_recipe.py"
NICEGUI = "examples/python/nicegui/notes_showcase/src/nicegui_notes"


def _checked_fences(guide: str, heading: str, language: str) -> list[str]:
    """The checked-snippet sources of the guide section's fences, in order."""
    text = (INTEGRATION / guide).read_text(encoding="utf-8")
    assert heading in text, f"{guide} lost its '{heading}' section"
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    fences = re.findall(rf"(?:<!-- checked-snippet: (\S+) -->\n\n)?```{language}\n", section)
    assert fences, f"{guide} shows no {language} block under '{heading}'"
    return fences


@pytest.mark.parametrize(
    ("guide", "heading", "usage"),
    [
        (
            "wpf.md",
            "## 9.3.3. Adapter skeleton",
            "examples/csharp/wpf/RecipeHostCheck/Program.cs#wpf-create-adapter",
        ),
        (
            "maui.md",
            "## 9.4.3. Adapter skeleton",
            "langs/csharp/tests/VMx.Tests/Integration/XamlRecipeTests.cs#maui-binding-context",
        ),
    ],
)
def test_xaml_recipe_fences_are_checked_against_executed_code(
    guide: str, heading: str, usage: str
) -> None:
    assert _checked_fences(guide, heading, "csharp") == [XAML_ADAPTER, usage]


def test_textual_recipe_is_checked_against_the_executed_widget() -> None:
    assert _checked_fences("textual.md", "## 9.5.3. Adapter skeleton", "python") == [TEXTUAL_WIDGET]


def test_textual_grid_recipe_is_checked_against_the_executed_grid() -> None:
    assert _checked_fences("textual.md", "## 9.5.4. Grids With DataTable", "python") == [
        TEXTUAL_GRID
    ]


def test_ci_runs_the_xaml_adapter_on_a_wpf_dispatcher() -> None:
    workflow = (REPO_ROOT / ".github/workflows/csharp.yml").read_text(encoding="utf-8")
    host_check = REPO_ROOT / "examples/csharp/wpf/RecipeHostCheck/RecipeHostCheck.csproj"
    assert (
        "dotnet run --project examples/csharp/wpf/RecipeHostCheck/RecipeHostCheck.csproj"
        in workflow
    )
    assert "langs/csharp/tests/VMx.Tests/Integration/BindableVm.cs" in host_check.read_text(
        encoding="utf-8"
    )


def test_nicegui_recipe_is_checked_against_the_executed_example() -> None:
    assert _checked_fences("nicegui.md", "## 9.6.3. Adapter skeleton", "python") == [
        f"{NICEGUI}/adapter/delivery.py#nicegui-delivery",
        f"{NICEGUI}/adapter/binding.py#nicegui-bind-property",
        f"{NICEGUI}/adapter/binding.py#nicegui-release",
    ]
    assert _checked_fences("nicegui.md", "## 9.6.4. Host lifetime", "python") == [
        f"{NICEGUI}/host.py#nicegui-host"
    ]
    assert _checked_fences("nicegui.md", "## 9.6.5. Page", "python") == [
        f"{NICEGUI}/page.py#nicegui-editor",
        f"{NICEGUI}/page.py#nicegui-page",
    ]


def test_ci_runs_the_nicegui_example_in_the_user_simulation() -> None:
    workflow = (REPO_ROOT / ".github/workflows/python.yml").read_text(encoding="utf-8")
    assert "name: examples (nicegui)" in workflow
    assert "uv sync --locked --directory examples/python/nicegui/notes_showcase" in workflow
    assert "needs: [build, examples, small-examples, inspector, nicegui, package]" in workflow
