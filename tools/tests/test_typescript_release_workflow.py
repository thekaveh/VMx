"""Contract tests for TypeScript package and release workflows."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_typescript_ci_triggers_for_package_verification_tools() -> None:
    workflow = _workflow("typescript.yml")

    assert '- "tools/check-typescript-package.py"' in workflow
    assert '- "tools/smoke-npm-consumer.py"' in workflow


def test_typescript_ci_verifies_packed_consumers_on_node_20_and_22() -> None:
    workflow = _workflow("typescript.yml")

    assert "name: package (node${{ matrix.node-version }})" in workflow
    assert 'node-version: ["20", "22"]' in workflow
    assert "python3 tools/check-typescript-package.py" in workflow
    assert "python3 tools/smoke-npm-consumer.py" in workflow
    assert "--package-dir langs/typescript" in workflow
    assert "--version 3.21.0" in workflow


def test_contract_suite_triggers_on_typescript_and_release_workflow_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert '- ".github/workflows/typescript.yml"' in workflow
    assert '- ".github/workflows/release.yml"' in workflow
