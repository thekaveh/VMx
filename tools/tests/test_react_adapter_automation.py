"""Contracts for the official React adapter's CI and release wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_typescript_ci_covers_both_supported_react_majors() -> None:
    workflow = (ROOT / ".github/workflows/typescript.yml").read_text()
    assert 'react: "18.3.1"' in workflow
    assert 'react: "19.2.8"' in workflow
    assert 'react-dom-types: "18.3.7"' in workflow
    assert 'react-dom-types: "19.2.3"' in workflow
    assert '"@types/react-dom@${{ matrix.react-dom-types }}"' in workflow
    assert "python3 tools/check-react-package.py" in workflow
    assert "python3 tools/smoke-react-consumer.py" in workflow
    assert "needs: [build, runtime-floor, react, package, examples]" in workflow


def test_release_is_tag_driven_and_core_gated() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert '- "react-v*"' in workflow
    assert "if: startsWith(github.ref, 'refs/tags/react-v')" in workflow
    assert 'npm view "@thekaveh/vmx@${core_version}" version --json' in workflow
    assert "environment:\n      name: npm-react" in workflow
    assert "react-verify-published:" in workflow
    assert "react-release-notes:" in workflow


def test_automation_owns_and_monitors_adapter() -> None:
    assert "packages/react/**   @thekaveh" in (ROOT / ".github/CODEOWNERS").read_text()
    dependabot = (ROOT / ".github/dependabot.yml").read_text()
    security = (ROOT / ".github/workflows/security-audit.yml").read_text()
    assert "- /packages/react" in dependabot
    assert "- packages/react" in security


def test_release_checker_accepts_adapter_tag_namespace() -> None:
    checker = (ROOT / "tools/check-version-consistency.py").read_text()
    assert '"python", "typescript", "react", "rust", "swift"' in checker
    assert 'repo_root / "packages" / "react" / "CHANGELOG.md"' in checker
