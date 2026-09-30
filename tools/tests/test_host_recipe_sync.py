"""Keep the WPF, MAUI and Textual recipes identical to the files CI executes."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = REPO_ROOT / "docs" / "content" / "integration"
XAML_ADAPTER = REPO_ROOT / "langs/csharp/tests/VMx.Tests/Integration/BindableVm.cs"
TEXTUAL_WIDGET = REPO_ROOT / "examples/python/textual/notes_showcase/tests/views/textual_recipe.py"


def _fence(guide: str, heading: str, language: str) -> str:
    text = (INTEGRATION / guide).read_text(encoding="utf-8")
    assert heading in text, f"{guide} lost its '{heading}' section"
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    blocks = re.findall(rf"```{language}\n(.*?)```", section, re.S)
    assert blocks, f"{guide} shows no {language} block under '{heading}'"
    return blocks[0]


@pytest.mark.parametrize(
    ("guide", "heading"),
    [("wpf.md", "## 9.3.3. Adapter skeleton"), ("maui.md", "## 9.4.3. Adapter skeleton")],
)
def test_xaml_recipe_is_the_executed_adapter(guide: str, heading: str) -> None:
    adapter = XAML_ADAPTER.read_text(encoding="utf-8")
    namespace = "namespace VMx.Tests.Integration;\n\n"
    assert namespace in adapter
    assert _fence(guide, heading, "csharp") == adapter.replace(namespace, "")


def test_textual_recipe_is_the_executed_widget() -> None:
    assert _fence("textual.md", "## 9.5.3. Adapter skeleton", "python") == (
        TEXTUAL_WIDGET.read_text(encoding="utf-8")
    )


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
