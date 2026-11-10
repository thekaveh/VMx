"""Contracts for the official React adapter's CI and release wiring."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _job(workflow: str, name: str) -> str:
    return workflow.split(f"\n  {name}:\n", 1)[1].split("\n\n  ", 1)[0]


def test_typescript_ci_covers_both_supported_react_majors_on_every_node_line() -> None:
    # #1334: each React major runs on each Node line of the core build job and
    # installs with npm ci from its own tracked lockfile.
    workflow = (ROOT / ".github/workflows/typescript.yml").read_text()
    react = _job(workflow, "react")
    assert 'react: ["18", "19"]' in react
    assert 'node-version: ["20", "22", "24", "26"]' in react
    assert 'node-version: ["20", "22", "24", "26"]' in _job(workflow, "build")
    assert "name: react adapter (React ${{ matrix.react }} / node${{ matrix.node-version }})" in (
        react
    )
    assert "node-version: ${{ matrix.node-version }}" in react
    assert "npm install" not in react
    assert "--package-lock=false" not in react
    copy = react.index(
        "cp packages/react-18-deps/package.json packages/react-18-deps/package-lock.json"
        " packages/react/"
    )
    install = react.index("npm ci --prefix packages/react\n")
    audit = react.index("npm audit --prefix packages/react --package-lock-only")
    assert "if: matrix.react == '18'" in react[:copy]
    assert copy < install < audit
    assert "python3 tools/check-react-package.py" in react
    assert "python3 tools/smoke-react-consumer.py" in react
    assert (
        "needs: [build, runtime-floor, react, react-runtime-floor, package, examples]" in workflow
    )


def test_react_adapter_entry_points_load_at_the_node_runtime_floor() -> None:
    workflow = (ROOT / ".github/workflows/typescript.yml").read_text()
    floor = _job(workflow, "react-runtime-floor")
    assert 'react: ["18", "19"]' in floor
    assert 'node-version: "20.5.0"' in floor
    assert "npm install" not in floor
    assert 'run: node packages/react/scripts/check-runtime-floor.mjs "${{ matrix.react }}"' in floor
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
    examples = workflow.split("  examples:\n", 1)[1].split("  required:\n", 1)[0]
    build = examples.index("- name: Install React adapter deps + build dist")
    install = examples.index("- name: notes-showcase install")
    test = examples.index(
        "npm test --prefix examples/typescript/react/notes-showcase --ignore-scripts"
    )
    assert build < install < test


def test_release_is_tag_driven_and_core_gated() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert '- "react-v*"' in workflow
    assert (
        "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/react-v')" in workflow
    )
    react = workflow.split("\n  react-build:\n", 1)[1].split("\n  react-publish:\n", 1)[0]
    assert 'peerDependencies?.["@thekaveh/vmx"]' in react
    assert 'npm view "@thekaveh/vmx@${core_range}" version --json' in react
    assert "langs/typescript/package.json" not in react
    assert "environment:\n      name: npm-react" in workflow
    assert "react-verify-published:" in workflow
    assert "react-release-notes:" in workflow


def test_release_audit_is_production_only_and_ci_audits_everything() -> None:
    release = (ROOT / ".github/workflows/release.yml").read_text()
    react = release.split("\n  react-build:\n", 1)[1].split("\n  react-publish:\n", 1)[0]
    ci = (ROOT / ".github/workflows/typescript.yml").read_text()
    full = "npm audit --prefix packages/react --package-lock-only --audit-level=low"
    assert (
        "npm audit --prefix packages/react --package-lock-only --omit=dev --audit-level=low"
        in react
    )
    assert full not in react
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
