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
    assert "--project-root langs/csharp/src" in workflow
    assert "--package VMx=3.20.0" not in workflow
    assert '--framework "${{ matrix.framework }}"' in workflow


def test_csharp_ci_and_release_cover_current_dotnet_lts() -> None:
    ci = _workflow("csharp.yml")
    release = _csharp_release_jobs()
    unit_project = (REPO_ROOT / "langs/csharp/tests/VMx.Tests/VMx.Tests.csproj").read_text()
    conformance_project = (
        REPO_ROOT / "langs/csharp/tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj"
    ).read_text()

    assert "10.0.x" in ci
    assert "10.0.x" in release
    assert "net8.0;net9.0;net10.0" in unit_project
    assert "net8.0;net9.0;net10.0" in conformance_project


def test_csharp_ci_and_release_audit_transitive_dependencies() -> None:
    ci = _workflow("csharp.yml")
    release = _csharp_release_jobs()
    command = "dotnet list langs/csharp/VMx.sln package --vulnerable --include-transitive"

    assert command in ci
    assert command in release


def test_csharp_restore_enforces_low_severity_transitive_auditing() -> None:
    props = (REPO_ROOT / "langs/csharp/Directory.Build.props").read_text(encoding="utf-8")

    assert "<NuGetAudit>true</NuGetAudit>" in props
    assert "<NuGetAuditMode>all</NuGetAuditMode>" in props
    assert "<NuGetAuditLevel>low</NuGetAuditLevel>" in props


def test_conformance_triggers_on_csharp_and_release_workflow_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert workflow.count('- ".github/workflows/**"') == 1


def _csharp_release_jobs() -> str:
    workflow = _workflow("release.yml")
    body = workflow.split("\n  csharp-build:\n", maxsplit=1)[1].split(
        "\n  python-test:\n", maxsplit=1
    )[0]
    return f"csharp-build:\n{body}"


def test_release_builds_and_validates_before_protected_authentication() -> None:
    jobs = _csharp_release_jobs()

    assert "csharp-build:" in jobs
    assert "dotnet restore langs/csharp/VMx.sln --locked-mode" in jobs
    assert "dotnet format langs/csharp/VMx.sln --verify-no-changes" in jobs
    assert "python3 tools/check-nuget-package.py" in jobs
    assert "python3 tools/smoke-nuget-consumer.py" in jobs
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in jobs
    assert jobs.index("csharp-build:") < jobs.index("csharp-publish:")


def test_release_tags_select_one_explicit_csharp_package_namespace() -> None:
    workflow = _workflow("release.yml")
    jobs = _csharp_release_jobs()

    assert '- "csharp-v*"' in workflow
    assert '- "csharp-notifications-v*"' in workflow
    assert '- "csharp-dependency-injection-v*"' in workflow
    assert "python3 tools/select-csharp-release.py" in jobs
    assert "project_version == version" not in jobs


def test_release_uses_protected_nuget_oidc_without_long_lived_key() -> None:
    jobs = _csharp_release_jobs()

    assert "environment:\n      name: nuget-csharp" in jobs
    assert "id-token: write" in jobs
    assert "NuGet/login@8d196754b4036150537f80ac539e15c2f1028841" in jobs
    assert "user: ${{ secrets.NUGET_USER }}" in jobs
    assert "NUGET_API_KEY" not in jobs.replace("steps.login.outputs.NUGET_API_KEY", "")
    assert "--skip-duplicate" not in jobs


def test_release_verifies_public_frameworks_before_release_notes() -> None:
    jobs = _csharp_release_jobs()

    assert "csharp-verify-published:" in jobs
    assert 'framework: ["net8.0", "netstandard2.0"]' in jobs
    assert "--poll-timeout 900" in jobs
    assert "csharp-release-notes:" in jobs
    assert "needs: csharp-verify-published" in jobs
    assert "tools/render-csharp-release-notes.py" in jobs
    assert "gh release create" in jobs
