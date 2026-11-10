"""Run every release job's notes extraction step with the shared extractor (#783)."""

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import check_version_consistency as cvc
import pytest

ROOT = Path(__file__).resolve().parents[2]
EXTRACTOR = ROOT / "tools/extract-release-notes.awk"

# flavor -> (step name, tag prefix, changelog path)
STEPS = {
    "python": ("Extract CHANGELOG section", "python", "langs/python/CHANGELOG.md"),
    "typescript": (
        "Extract TypeScript release notes",
        "typescript",
        "langs/typescript/CHANGELOG.md",
    ),
    "react": (
        "Extract adapter release notes and create GitHub Release",
        "react",
        "packages/react/CHANGELOG.md",
    ),
    "rust": ("Extract Rust release notes", "rust", "langs/rust/CHANGELOG.md"),
    "swift": ("Extract Swift release notes", "swift", "langs/swift/CHANGELOG.md"),
}

CHANGELOG = (
    "# Changelog\n\n## [Unreleased]\n\n- Future.\n\n"
    "## [0.1.30] - 2026-10-01\n\n- Thirty.\n\n"
    "## [0.1.4](https://example.test/compare/v0.1.3...v0.1.4) (2026-09-24)\n\n- Link form.\n\n"
    "## [0.1.3] — unreleased source version\n\n- Em dash.\n\n"
    "## [0.1.2] - 2026-08-24\n\n### Fixed\n\n- Dash.\n"
)


def _step_script(name: str) -> str:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    step = workflow.split(f"      - name: {name}\n", 1)[1]
    step = re.split(r"(?m)^(?:      - |  [A-Za-z0-9_-]+:$)", step, maxsplit=1)[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def _run_step(tmp_path: Path, flavor: str, changelog: str, version: str):
    name, prefix, path = STEPS[flavor]
    source = tmp_path / path
    source.parent.mkdir(parents=True)
    source.write_text(changelog, encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/extract-release-notes.awk").write_bytes(EXTRACTOR.read_bytes())
    gh = tmp_path / "bin/gh"
    gh.parent.mkdir()
    gh.write_text("#!/bin/sh\nexit 0\n")
    gh.chmod(0o755)
    output = tmp_path / "out"
    output.mkdir()
    script = _step_script(name).replace("/tmp/", f"{output}/")
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            "PATH": str(gh.parent) + os.pathsep + os.defpath,
            "GITHUB_REF": f"refs/tags/{prefix}-v{version}",
            "GITHUB_REF_NAME": f"{prefix}-v{version}",
            "GITHUB_SHA": "a" * 40,
            "GH_TOKEN": "",
        },
        text=True,
        capture_output=True,
        timeout=15,
    )
    notes = [path.read_text(encoding="utf-8") for path in output.glob("*.md")]
    return result, (notes[0] if notes else "")


def test_release_workflow_holds_no_inline_awk_program() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    awk_lines = [line for line in workflow.splitlines() if re.search(r"\bawk\b", line)]
    assert awk_lines
    for line in awk_lines:
        assert "-f tools/extract-release-notes.awk" in line, line


@pytest.mark.parametrize("flavor", sorted(STEPS))
@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.1.4", "\n- Link form.\n\n"),
        ("0.1.3", "\n- Em dash.\n\n"),
        ("0.1.2", "\n### Fixed\n\n- Dash.\n"),
    ],
)
def test_each_job_extracts_exactly_one_section(
    tmp_path: Path, flavor: str, version: str, expected: str
) -> None:
    result, notes = _run_step(tmp_path, flavor, CHANGELOG, version)
    assert result.returncode == 0, result.stderr
    assert notes == expected


@pytest.mark.parametrize("flavor", sorted(STEPS))
def test_each_job_rejects_a_version_that_only_shares_a_prefix(tmp_path: Path, flavor: str) -> None:
    only_longer = "# Changelog\n\n## [0.1.30] - 2026-10-01\n\n- Thirty.\n"
    result, notes = _run_step(tmp_path, flavor, only_longer, "0.1.3")
    assert result.returncode != 0
    assert "Thirty" not in notes


def _manifest_versions() -> dict[str, str]:
    manifests = cvc.collect_manifests(ROOT)
    react = json.loads((ROOT / "packages/react/package.json").read_text(encoding="utf-8"))
    return {
        "python": manifests["python"]["version"],
        "typescript": manifests["typescript"]["version"],
        "react": react["version"],
        "rust": manifests["rust"]["version"],
        "swift": manifests["swift"]["version"],
    }


@pytest.mark.parametrize("flavor", sorted(STEPS))
def test_extractor_finds_each_manifest_version_in_its_changelog(flavor: str) -> None:
    version = _manifest_versions()[flavor]
    result = subprocess.run(
        ["awk", "-v", f"v={version}", "-f", str(EXTRACTOR), str(ROOT / STEPS[flavor][2])],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), f"{flavor} {version}"


# #1381: a column-0 "##" line that CommonMark does not read as a heading. The
# extractor ends a section at each raw "##" line, so the gates reject the file.
BLOCK_INPUTS = {
    "fence-in-section": (
        "# Changelog\n\n## [Unreleased]\n\n## [0.2.0] - 2026-02-01\n\n- Before.\n\n"
        "```sh\n## run this first\nmake\n```\n\n- After.\n\n## [0.1.0] - 2026-01-01\n\n- Old.\n"
    ),
    "fenced-placeholder-in-unreleased": (
        "# Changelog\n\n## [Unreleased]\n\n```md\n## [0.2.0] - 2026-01-01\n\n- Placeholder.\n"
        "```\n\n## [0.2.0] - 2026-02-01\n\n- Real notes.\n"
    ),
    "html-block-in-section": (
        "# Changelog\n\n## [Unreleased]\n\n## [0.2.0] - 2026-02-01\n\n- Visible.\n\n"
        "<details>\n## Internal\n\n- Hidden.\n</details>\n"
    ),
}


def _gate_issues(tmp_path: Path, changelog: str) -> tuple[list[str], list[str]]:
    root = tmp_path / "gates"
    flavor = root / "langs/python/CHANGELOG.md"
    flavor.parent.mkdir(parents=True)
    flavor.write_text(changelog, encoding="utf-8")
    react = root / "packages/react"
    react.mkdir(parents=True)
    (react / "package.json").write_text('{"version": "0.2.0"}', encoding="utf-8")
    (react / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return (
        cvc.check_changelog_sections(root, {"python": {"version": "0.2.0"}}),
        cvc.check_react_changelog_section(root),
    )


@pytest.mark.parametrize("flavor", sorted(STEPS))
@pytest.mark.parametrize("changelog", BLOCK_INPUTS.values(), ids=BLOCK_INPUTS.keys())
def test_gates_reject_every_block_line_that_would_mislead_the_extractor(
    tmp_path: Path, flavor: str, changelog: str
) -> None:
    result, notes = _run_step(tmp_path, flavor, changelog, "0.2.0")
    # The step alone accepts the wrong notes: it fails only on blank output.
    assert result.returncode == 0, result.stderr
    assert notes.strip()
    source = tmp_path / "parsed.md"
    source.write_text(changelog, encoding="utf-8")
    _, parse_errors = cvc._parse_changelog_sections(source)
    flavor_issues, react_issues = _gate_issues(tmp_path, changelog)
    # So the gates reject the file, and no release of it reaches the step.
    assert any("is not a CHANGELOG heading" in issue for issue in parse_errors)
    assert any("is not a CHANGELOG heading" in issue for issue in flavor_issues)
    assert any("is not a CHANGELOG heading" in issue for issue in react_issues)


def test_gates_accept_a_fence_without_a_column_zero_heading_marker(tmp_path: Path) -> None:
    changelog = (
        "# Changelog\n\n## [Unreleased]\n\n## [0.2.0] - 2026-02-01\n\n"
        "```md\n  ## indented example\n#### deeper\n```\n\n<details>\n\n- Hidden.\n\n</details>\n"
    )
    assert _gate_issues(tmp_path, changelog) == ([], [])
