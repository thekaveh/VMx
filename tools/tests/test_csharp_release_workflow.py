"""Contract tests for C# package and release workflows."""

import re
from pathlib import Path

from .workflow_jobs import push_path_patterns, run_commands, workflow_job

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
    assert command in "\n".join(run_commands(release))


def test_csharp_restore_enforces_low_severity_transitive_auditing() -> None:
    props = (REPO_ROOT / "langs/csharp/Directory.Build.props").read_text(encoding="utf-8")

    assert "<NuGetAudit>true</NuGetAudit>" in props
    assert "<NuGetAuditMode>all</NuGetAuditMode>" in props
    assert "<NuGetAuditLevel>low</NuGetAuditLevel>" in props


def test_conformance_runs_on_every_push_including_csharp_release_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert push_path_patterns(workflow) is None, "conformance.yml runs on every push (#1836)"


_CSHARP_RELEASE_JOBS = (
    "csharp-build",
    "csharp-publish",
    "csharp-verify-published",
    "csharp-release-notes",
)


def _csharp_release_jobs() -> str:
    """The C# release jobs in workflow order, each under its own key."""
    workflow = _workflow("release.yml")
    return "".join(f"{name}:\n{workflow_job(workflow, name)}" for name in _CSHARP_RELEASE_JOBS)


def test_release_builds_and_validates_before_protected_authentication() -> None:
    jobs = _csharp_release_jobs()
    commands = "\n".join(run_commands(jobs))

    assert "csharp-build:" in jobs
    assert "dotnet restore langs/csharp/VMx.sln --locked-mode" in commands
    assert "dotnet format langs/csharp/VMx.sln --verify-no-changes" in commands
    assert "python3 tools/check-nuget-package.py" in commands
    assert "python3 tools/smoke-nuget-consumer.py" in commands
    assert re.search(r"actions/upload-artifact@[0-9a-f]{40}\b", jobs)
    assert jobs.index("csharp-build:") < jobs.index("csharp-publish:")


def test_release_tags_select_one_explicit_csharp_package_namespace() -> None:
    workflow = _workflow("release.yml")
    jobs = _csharp_release_jobs()

    assert '- "csharp-v*"' in workflow
    assert '- "csharp-notifications-v*"' in workflow
    assert '- "csharp-dependency-injection-v*"' in workflow
    assert "python3 tools/select-csharp-release.py" in "\n".join(run_commands(jobs))
    assert "project_version == version" not in jobs


def test_release_uses_protected_nuget_oidc_without_long_lived_key() -> None:
    jobs = _csharp_release_jobs()

    assert "environment:\n      name: nuget-csharp" in jobs
    assert "id-token: write" in jobs
    assert re.search(r"NuGet/login@[0-9a-f]{40}\b", jobs)
    assert "user: ${{ secrets.NUGET_USER }}" in jobs
    assert "secrets.NUGET_API_KEY" not in jobs
    assert "--skip-duplicate" not in jobs
    assert "NUGET_API_KEY: ${{ steps.login.outputs.NUGET_API_KEY }}" in jobs
    assert '--api-key "$NUGET_API_KEY"' in "\n".join(run_commands(jobs))
    assert '--api-key "${{ steps.login.outputs.NUGET_API_KEY }}"' not in jobs


def test_release_verifies_public_frameworks_before_release_notes() -> None:
    jobs = _csharp_release_jobs()

    assert "csharp-verify-published:" in jobs
    assert 'framework: ["net8.0", "netstandard2.0"]' in jobs
    commands = "\n".join(run_commands(jobs))
    assert "--poll-timeout 900" in commands
    assert "--timeout 1200" in commands
    assert "csharp-verify-published:\n    timeout-minutes: 25" in jobs
    assert "csharp-release-notes:" in jobs
    assert "needs: csharp-verify-published" in jobs
    assert "tools/render-csharp-release-notes.py" in commands
    assert "gh release create" in "\n".join(run_commands(jobs))
