"""Contracts for the official React adapter's CI and release wiring."""

import json
from pathlib import Path

from .workflow_jobs import run_commands, workflow_job

ROOT = Path(__file__).resolve().parents[2]


def test_typescript_ci_covers_both_supported_react_majors_on_every_node_line() -> None:
    # #1334: each React major runs on each Node line of the core build job and
    # installs with npm ci from its own tracked lockfile.
    workflow = (ROOT / ".github/workflows/typescript.yml").read_text()
    react = workflow_job(workflow, "react")
    commands = "\n".join(run_commands(react)) + "\n"
    assert 'react: ["18", "19"]' in react
    assert 'node-version: ["20", "22", "24", "26"]' in react
    assert 'node-version: ["20", "22", "24", "26"]' in workflow_job(workflow, "build")
    assert "name: react adapter (React ${{ matrix.react }} / node${{ matrix.node-version }})" in (
        react
    )
    assert "node-version: ${{ matrix.node-version }}" in react
    assert "npm install" not in react
    assert "--package-lock=false" not in react
    copy_command = (
        "cp packages/react-18-deps/package.json packages/react-18-deps/package-lock.json"
        " packages/react/"
    )
    copy = commands.index(copy_command)
    install = commands.index("npm ci --prefix packages/react\n")
    audit = commands.index("npm audit --prefix packages/react --package-lock-only")
    assert "if: matrix.react == '18'" in react[: react.index(copy_command)]
    assert copy < install < audit
    assert "python3 tools/check-react-package.py" in commands
    assert "python3 tools/smoke-react-consumer.py" in commands
    assert (
        "needs: [build, runtime-floor, react, react-runtime-floor, package, examples]" in workflow
    )


def test_react_adapter_entry_points_load_at_the_node_runtime_floor() -> None:
    workflow = (ROOT / ".github/workflows/typescript.yml").read_text()
    floor = workflow_job(workflow, "react-runtime-floor")
    commands = "\n".join(run_commands(floor))
    assert 'react: ["18", "19"]' in floor
    assert 'node-version: "20.5.0"' in floor
    assert "npm install" not in floor
    assert 'node packages/react/scripts/check-runtime-floor.mjs "${{ matrix.react }}"' in commands
    assert "npm run build --prefix packages/react" in commands
    assert floor.index("npm run build --prefix packages/react") < floor.index('"20.5.0"')
    script = (ROOT / "packages/react/scripts/check-runtime-floor.mjs").read_text()
    assert 'from "../dist/index.js"' in script
    assert 'require("../dist/index.cjs")' in script
    package = json.loads((ROOT / "packages/react/package.json").read_text())
    assert package["engines"]["node"] == ">=20.5.0"


_REACT_PACKAGES = ("react", "react-dom", "@types/react", "@types/react-dom")


def test_react_18_tree_matches_the_adapter_manifest_except_its_react_ranges() -> None:
    adapter = json.loads((ROOT / "packages/react/package.json").read_text())
    react18 = json.loads((ROOT / "packages/react-18-deps/package.json").read_text())
    lock = json.loads((ROOT / "packages/react-18-deps/package-lock.json").read_text())
    adapter_lock = json.loads((ROOT / "packages/react/package-lock.json").read_text())

    for name in _REACT_PACKAGES:
        assert react18["devDependencies"][name].startswith("^18."), name
        assert lock["packages"][f"node_modules/{name}"]["version"].startswith("18."), name
        assert adapter_lock["packages"][f"node_modules/{name}"]["version"].startswith("19."), name

    def comparable(manifest: dict) -> dict:
        rest = {key: value for key, value in manifest.items() if key != "version"}
        dev = manifest["devDependencies"]
        rest["devDependencies"] = {k: v for k, v in dev.items() if k not in _REACT_PACKAGES}
        return rest

    assert comparable(react18) == comparable(adapter)
    assert (ROOT / "packages/react-18-deps/.npmrc").read_bytes() == (
        ROOT / "packages/react/.npmrc"
    ).read_bytes()
    core = "node_modules/@thekaveh/vmx"
    assert lock["packages"][core] == adapter_lock["packages"][core]


def test_showcase_job_builds_adapter_before_suppressing_lifecycle_scripts() -> None:
    workflow = (ROOT / ".github/workflows/typescript.yml").read_text()
    examples = workflow_job(workflow, "examples")
    test_command = "npm test --prefix examples/typescript/react/notes-showcase --ignore-scripts"
    build = examples.index("- name: Install React adapter deps + build dist")
    install = examples.index("- name: notes-showcase install")
    assert test_command in "\n".join(run_commands(examples))
    test = examples.index(test_command)
    assert build < install < test


def test_release_is_tag_driven_and_core_gated() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert '- "react-v*"' in workflow
    assert (
        "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/react-v')" in workflow
    )
    react = workflow_job(workflow, "react-build")
    commands = "\n".join(run_commands(react))
    assert 'peerDependencies?.["@thekaveh/vmx"]' in commands
    assert 'npm view "@thekaveh/vmx@${core_range}" version --json' in commands
    assert "langs/typescript/package.json" not in react
    assert "environment:\n      name: npm-react" in workflow
    assert "react-verify-published:" in workflow
    assert "react-release-notes:" in workflow


def test_release_audit_is_production_only_and_ci_audits_everything() -> None:
    release = (ROOT / ".github/workflows/release.yml").read_text()
    ci = (ROOT / ".github/workflows/typescript.yml").read_text()
    commands = "\n".join(run_commands(workflow_job(release, "react-build")))
    full = "npm audit --prefix packages/react --package-lock-only --audit-level=low"
    assert (
        "npm audit --prefix packages/react --package-lock-only --omit=dev --audit-level=low"
        in commands
    )
    assert full not in commands
    assert full in ci


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
