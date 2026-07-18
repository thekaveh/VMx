"""Cross-cutting CI coverage contracts."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def test_every_workflow_change_triggers_the_pin_inventory() -> None:
    conformance = (WORKFLOWS / "conformance.yml").read_text(encoding="utf-8")

    assert conformance.count('- ".github/workflows/**"') == 2
    assert "python tools/check-workflow-pins.py" in conformance


def test_wpf_example_builds_on_windows_with_real_xaml_enabled() -> None:
    csharp = (WORKFLOWS / "csharp.yml").read_text(encoding="utf-8")

    assert "wpf-example:" in csharp
    assert "runs-on: windows-latest" in csharp
    assert "dotnet build examples/csharp/wpf/TodoApp/WpfTodoApp.csproj -c Release" in csharp


def test_react_showcase_runs_complete_static_and_production_gates() -> None:
    typescript = (WORKFLOWS / "typescript.yml").read_text(encoding="utf-8")
    prefix = "--prefix examples/typescript/react/notes-showcase"

    assert f"npm run typecheck {prefix}" in typescript
    assert f"npm run lint {prefix}" in typescript
    assert f"npm run build {prefix}" in typescript
