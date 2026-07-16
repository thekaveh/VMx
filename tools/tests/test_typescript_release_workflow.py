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
    assert 'require("./langs/typescript/package.json").version' in workflow
    assert '--version "$package_version"' in workflow
    assert "--version 3.21.0" not in workflow


def test_contract_suite_triggers_on_typescript_and_release_workflow_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert '- ".github/workflows/typescript.yml"' in workflow
    assert '- ".github/workflows/release.yml"' in workflow


def _typescript_release_jobs() -> str:
    workflow = _workflow("release.yml")
    return workflow.split("\n  typescript:\n", maxsplit=1)[1].split("\n  swift:\n", maxsplit=1)[0]


def test_release_uses_trusted_publishing_node_and_npm_floors_without_cache() -> None:
    jobs = _typescript_release_jobs()

    assert 'node-version: "24"' in jobs
    assert "npm install --global npm@11.5.1" in jobs
    assert "id-token: write" in jobs
    assert "environment:\n      name: npm-typescript" in jobs
    assert "cache: npm" not in jobs


def test_release_runs_every_gate_before_publish() -> None:
    jobs = _typescript_release_jobs()
    required = [
        "npm run sync-fixtures",
        "npm run typecheck",
        "npm run typecheck:tests",
        "npm run lint",
        "npm run build",
        "npm test",
        "npm audit --package-lock-only --audit-level=low",
        "python3 tools/check-typescript-package.py",
        "python3 tools/smoke-npm-consumer.py",
    ]
    publish_index = jobs.index("name: Publish initial package with bootstrap token")

    assert all(jobs.index(command) < publish_index for command in required)
    assert "--package-dir langs/typescript" in jobs


def test_release_has_mutually_exclusive_bootstrap_and_oidc_publish_steps() -> None:
    jobs = _typescript_release_jobs()

    assert "if: steps.npm-auth.outputs.bootstrap == 'true'" in jobs
    assert "NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}" in jobs
    assert "npm publish --access public --provenance" in jobs
    assert "name: Publish with npm trusted publishing" in jobs
    assert "if: steps.npm-auth.outputs.bootstrap != 'true'" in jobs
    assert "npm publish --access public" in jobs


def test_release_polls_public_package_and_provenance_on_node_20_and_22() -> None:
    jobs = _typescript_release_jobs()

    assert "typescript-verify-published:" in jobs
    assert 'node-version: ["20", "22"]' in jobs
    assert "--poll-timeout 600" in jobs
    assert "dist.attestations" in jobs
    assert "predicateType" in jobs
    assert "for attempt in {1..60}" in jobs
    assert "sleep 10" in jobs


def test_release_notes_follow_public_verification() -> None:
    jobs = _typescript_release_jobs()

    verify_index = jobs.index("typescript-verify-published:")
    notes_index = jobs.index("typescript-release-notes:")
    create_index = jobs.index("gh release create", notes_index)

    assert verify_index < notes_index < create_index
    assert "needs: typescript-verify-published" in jobs
    assert "langs/typescript/CHANGELOG.md" in jobs
    assert "--notes-file /tmp/typescript-release-notes.md" in jobs
