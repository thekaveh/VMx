"""Repository security automation contracts."""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dependabot_covers_every_committed_dependency_ecosystem() -> None:
    config = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    sections = dict(
        re.findall(
            r"^  - package-ecosystem: (\S+)\n(.*?)(?=^  - package-ecosystem:|\Z)",
            config,
            flags=re.MULTILINE | re.DOTALL,
        )
    )
    expected_directories = {
        "github-actions": {"/"},
        "npm": {
            "/langs/typescript",
            "/examples/typescript/console/hello-vmx",
            "/examples/typescript/react/notes-showcase",
        },
        "cargo": {
            "/langs/rust",
            "/examples/rust/console/hello-vmx",
            "/examples/rust/tui/notes-showcase",
        },
        "uv": {
            "/langs/python",
            "/examples/python",
            "/examples/python/textual/inspector",
            "/examples/python/textual/notes_showcase",
        },
        "pip": {"/docs"},
        "nuget": {"/langs/csharp", "/examples/csharp"},
    }
    assert set(sections) == set(expected_directories)
    for ecosystem, expected in expected_directories.items():
        directories = set(re.findall(r"^      - (/\S*)$", sections[ecosystem], flags=re.MULTILINE))
        directory = re.search(r"^    directory: (/\S*)$", sections[ecosystem], re.MULTILINE)
        if directory is not None:
            directories.add(directory.group(1))
        assert directories == expected
        assert "target-branch: develop" in sections[ecosystem]
        if len(expected) > 1:
            assert "group-by: dependency-name" in sections[ecosystem]
    assert config.count("interval: weekly") == 6


def test_dependabot_preserves_python_bounds_and_defers_only_incompatible_js_majors() -> None:
    config = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    sections = dict(
        re.findall(
            r"^  - package-ecosystem: (\S+)\n(.*?)(?=^  - package-ecosystem:|\Z)",
            config,
            flags=re.MULTILINE | re.DOTALL,
        )
    )

    assert "versioning-strategy: lockfile-only" in sections["uv"]
    assert "dependency-name: typescript" not in sections["npm"]
    assert re.search(
        r'dependency-name: jsdom\n\s+versions: \[">=30\.0\.0"\]',
        sections["npm"],
    )


def test_typescript_projects_track_the_latest_peer_supported_compiler() -> None:
    manifests = (
        REPO_ROOT / "langs/typescript/package.json",
        REPO_ROOT / "examples/typescript/console/hello-vmx/package.json",
        REPO_ROOT / "examples/typescript/react/notes-showcase/package.json",
    )
    for manifest in manifests:
        assert '"typescript": "^6.0.3"' in manifest.read_text(encoding="utf-8")

    vite_types = REPO_ROOT / "examples/typescript/react/notes-showcase/src/vite-env.d.ts"
    assert vite_types.read_text(encoding="utf-8") == '/// <reference types="vite/client" />\n'

    tsconfig = (REPO_ROOT / "langs/typescript/tsconfig.json").read_text(encoding="utf-8")
    assert '"ignoreDeprecations": "6.0"' in tsconfig


def test_typescript_dependency_graph_is_validated_with_scoped_security_override() -> None:
    manifests = (
        REPO_ROOT / "langs/typescript/package.json",
        REPO_ROOT / "examples/typescript/console/hello-vmx/package.json",
        REPO_ROOT / "examples/typescript/react/notes-showcase/package.json",
    )
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest["scripts"]["check:deps"] == "npm ls --all --omit=optional"

    library_manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert library_manifest.get("overrides") == {"tsup": {"esbuild": "0.28.1"}}

    lock = json.loads(
        (REPO_ROOT / "langs/typescript/package-lock.json").read_text(encoding="utf-8")
    )
    assert lock["packages"]["node_modules/tsup"]["dependencies"]["esbuild"] == "^0.27.0"
    assert lock["packages"]["node_modules/esbuild"]["version"] == "0.28.1"
    for path in manifests[1:]:
        assert path.with_name(".npmrc").read_text(encoding="utf-8") == "install-links=true\n"

    typescript_ci = (REPO_ROOT / ".github/workflows/typescript.yml").read_text(encoding="utf-8")
    release_ci = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    security_ci = (REPO_ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")
    assert typescript_ci.count("npm run check:deps") >= 3
    assert "npm run check:deps" in release_ci
    assert 'npm ci --prefix "${{ matrix.project }}" --ignore-scripts' in security_ci
    assert 'npm run check:deps --prefix "${{ matrix.project }}"' in security_ci


def test_dependabot_defers_incompatible_nuget_updates() -> None:
    config = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    ledger = (REPO_ROOT / "docs/maintenance/2026-07-01-contract-ledger.md").read_text(
        encoding="utf-8"
    )
    nuget = config.split("  - package-ecosystem: nuget\n", maxsplit=1)[1]
    expected = {
        "coverlet.collector": "10.0.1",
        "coverlet.msbuild": "10.0.1",
        "FluentAssertions": ">=7.0.0",
        "Microsoft.Extensions.DependencyInjection": ">=9.0.0",
    }
    for dependency, version in expected.items():
        assert re.search(
            rf"dependency-name: {re.escape(dependency)}\n\s+versions: "
            rf'\["{re.escape(version)}"\]',
            nuget,
        )
    assert "FluentAssertions `7+` is a deliberate assertion-library migration" in ledger
    assert re.search(r"commercial-use\s+license decision", ledger)
    assert "88 C# test files" in ledger
    assert "DI implementation runtime `9+` is deferred" in ledger
    assert re.search(r"runtime-floor compatibility\s+evidence", ledger)


def test_dependabot_changes_run_the_automation_contracts() -> None:
    workflow = (REPO_ROOT / ".github/workflows/conformance.yml").read_text(encoding="utf-8")

    assert workflow.count('      - ".github/dependabot.yml"') == 1


def test_weekly_audit_covers_every_committed_lock_family() -> None:
    workflow = (REPO_ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")

    assert 'cron: "23 6 * * 1"' in workflow
    assert "  pull_request:" in workflow
    assert "  push:\n    branches: [main, develop]" in workflow
    pull_request = workflow.split("  pull_request:\n", maxsplit=1)[1].split(
        "  schedule:", maxsplit=1
    )[0]
    assert "    paths:" not in pull_request
    assert 'name: "required: security"' in workflow
    assert "--no-emit-local" in workflow
    assert workflow.count('"-warnaserror:NU1901;NU1902;NU1903;NU1904"') == 2
    assert "dotnet list" not in workflow
    for relative in (
        "langs/typescript",
        "examples/typescript/console/hello-vmx",
        "examples/typescript/react/notes-showcase",
        "langs/rust/Cargo.lock",
        "examples/rust/console/hello-vmx/Cargo.lock",
        "examples/rust/tui/notes-showcase/Cargo.lock",
        "langs/python",
        "examples/python",
        "examples/python/textual/inspector",
        "examples/python/textual/notes_showcase",
        "docs/requirements.txt",
        "langs/csharp/VMx.sln",
        "examples/csharp/Examples.sln",
    ):
        assert relative in workflow

    assert workflow.startswith("name: security-audit\n\npermissions:\n  contents: read\n")


def test_required_security_gate_scans_committed_secrets() -> None:
    workflow = (REPO_ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")
    policy = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "  secrets:\n    timeout-minutes: 10" in workflow
    assert "fetch-depth: 0" in workflow
    assert "gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e" in workflow
    assert 'GITLEAKS_VERSION: "8.30.1"' in workflow
    assert "needs: [secrets, codeql, npm, cargo, python, docs, nuget]" in workflow
    assert "currently has no secret-scanner\nallowlist entries" in policy
    assert "`.gitleaksignore`" in policy


def test_codeql_covers_every_implementation_language() -> None:
    workflow = (REPO_ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")

    codeql = workflow.split("  codeql:\n", maxsplit=1)[1].split("\n  npm:", maxsplit=1)[0]
    assert "      security-events: write" in codeql
    assert "      fail-fast: false" in codeql
    for language in ("csharp", "javascript-typescript", "python", "rust", "swift"):
        assert codeql.count(f"          - language: {language}\n") == 1
    assert "            build-mode: manual\n            runner: macos-15" in codeql
    assert codeql.count("            build-mode: none\n") == 4
    assert "swift build -c release --package-path langs/swift" in codeql
    assert "swift build -c release --package-path examples/swift/notes-showcase" in codeql
    assert "github/codeql-action/init@e4fba868fa4b1b91e1fdab776edc8cfbe6e9fb81" in codeql
    assert "github/codeql-action/analyze@e4fba868fa4b1b91e1fdab776edc8cfbe6e9fb81" in codeql


def test_release_workflow_defaults_to_read_only() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert workflow.startswith("name: release\n\npermissions:\n  contents: read\n")


def test_docs_workflows_do_not_bootstrap_mutable_pip() -> None:
    for name in ("docs.yml", "wiki.yml"):
        workflow = (REPO_ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "pip install --upgrade pip" not in workflow
