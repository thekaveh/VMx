"""Cross-cutting CI coverage contracts."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def test_every_workflow_change_triggers_the_pin_inventory() -> None:
    conformance = (WORKFLOWS / "conformance.yml").read_text(encoding="utf-8")

    assert conformance.count('- ".github/workflows/**"') == 1
    assert "python tools/check-workflow-pins.py" in conformance


def test_protected_branch_checks_are_always_present_and_aggregate_every_job() -> None:
    required = {
        "conformance.yml": ("required: conformance", None),
        "csharp.yml": ("required: csharp", "needs: [build, package, examples, wpf-example]"),
        "python.yml": (
            "required: python",
            "needs: [build, examples, small-examples, inspector]",
        ),
        "rust.yml": ("required: rust", "needs: [audit, build, examples, package]"),
        "swift.yml": ("required: swift", "needs: [build, platforms, examples]"),
        "typescript.yml": ("required: typescript", "needs: [build, package, examples]"),
        "docs.yml": ("required: docs", "needs: [build]"),
        "examples-contract-checks.yml": ("required: examples", None),
        "security-audit.yml": (
            "required: security",
            "needs: [npm, cargo, python, docs, nuget]",
        ),
        "spec-discipline.yml": ("required: spec discipline", None),
    }

    for filename, (context, needs) in required.items():
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        pull_request = workflow.split("  pull_request:\n", maxsplit=1)[1].split(
            "\njobs:", maxsplit=1
        )[0]
        assert "    paths:" not in pull_request, f"{filename} can skip its required check"
        assert f'name: "{context}"' in workflow
        if needs is not None:
            assert needs in workflow
            assert "    if: always()" in workflow
            assert "RESULTS: ${{ toJSON(needs) }}" in workflow


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
