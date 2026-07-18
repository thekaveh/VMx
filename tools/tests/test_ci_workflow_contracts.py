"""Cross-cutting CI coverage contracts."""

import json
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


def test_spec_discipline_enforces_develop_first_gitflow() -> None:
    workflow = (WORKFLOWS / "spec-discipline.yml").read_text(encoding="utf-8")

    assert "Enforce develop-first gitflow" in workflow
    assert "BASE_REF: ${{ github.event.pull_request.base.ref }}" in workflow
    assert "HEAD_REF: ${{ github.event.pull_request.head.ref }}" in workflow
    assert "HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name }}" in workflow
    assert 'if [ "$BASE_REF" = "develop" ]; then' in workflow
    assert (
        'if [ "$HEAD_REPO" = "$GITHUB_REPOSITORY" ] && [ "$HEAD_REF" = "develop" ]; then'
        in workflow
    )
    assert "release-please--branches--main--components--python" in workflow
    assert "git diff --name-status" in workflow
    assert "git ls-tree" in workflow
    for path in (
        ".release-please-manifest.json",
        "compatibility-matrix.md",
        "langs/python/CHANGELOG.md",
        "langs/python/src/vmx/__about__.py",
    ):
        assert path in workflow


def test_python_release_updates_the_compatibility_matrix() -> None:
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    extra_files = config["packages"]["langs/python"]["extra-files"]
    assert {"type": "generic", "path": "/compatibility-matrix.md"} in extra_files

    matrix = (REPO_ROOT / "compatibility-matrix.md").read_text(encoding="utf-8")
    header = next(line for line in matrix.splitlines() if line.startswith("| spec"))
    assert header.index("python") < header.index("csharp")
    current = next(line for line in matrix.splitlines() if line.startswith("| 3.22.x"))
    assert "x-release-please-version" in current
