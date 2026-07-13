"""Contract tests for C# package and release workflows."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_csharp_ci_triggers_for_package_verification_tools() -> None:
    workflow = _workflow("csharp.yml")

    assert '- "tools/check-nuget-package.py"' in workflow
    assert '- "tools/smoke-nuget-consumer.py"' in workflow


def test_csharp_ci_packs_and_verifies_both_consumer_frameworks() -> None:
    workflow = _workflow("csharp.yml")

    assert "name: package (${{ matrix.framework }})" in workflow
    assert 'framework: ["net8.0", "netstandard2.0"]' in workflow
    assert "dotnet pack" in workflow
    assert "python3 tools/check-nuget-package.py" in workflow
    assert "python3 tools/smoke-nuget-consumer.py" in workflow
    assert "--package VMx=3.20.0" in workflow
    assert "--package VMx.Notifications=1.2.0" in workflow
    assert "--package VMx.Extensions.DependencyInjection=2.1.1" in workflow
    assert '--framework "${{ matrix.framework }}"' in workflow


def test_conformance_triggers_on_csharp_and_release_workflow_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert workflow.count('- ".github/workflows/csharp.yml"') == 2
    assert workflow.count('- ".github/workflows/release.yml"') == 2
