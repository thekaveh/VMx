"""Execute the React release-notes shell step without remote mutations."""

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _job(name: str) -> str:
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    tail = workflow.split(f"\n  {name}:\n", 1)[1]
    return re.split(r"(?m)^  [a-z][a-z0-9-]*:\n", tail, maxsplit=1)[0]


def _run_notes(tmp_path: Path, changelog: str, version: str = "0.2.0"):
    source = tmp_path / "packages/react/CHANGELOG.md"
    source.parent.mkdir(parents=True)
    source.write_text(changelog)
    extractor = ROOT / "tools/extract-react-release-notes.awk"
    if extractor.exists():
        destination = tmp_path / "tools/extract-react-release-notes.awk"
        destination.parent.mkdir()
        destination.write_bytes(extractor.read_bytes())
    executable = tmp_path / "bin/gh"
    executable.parent.mkdir()
    executable.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$VMX_TEST_GH_ARGS"\n'
        'printf "%s\\n" "VMX_TEST_RELEASE_CREATED"\n'
    )

    executable.chmod(0o755)
    arguments = tmp_path / "gh-arguments.txt"
    notes = tmp_path / "react-release-notes.md"
    script = textwrap.dedent(_job("react-release-notes").split("        run: |\n", 1)[1])
    script = script.replace("/tmp/react-release-notes.md", '"$RUNNER_TEMP/react-release-notes.md"')
    environment = {
        "PATH": str(executable.parent) + os.pathsep + os.defpath,
        "RUNNER_TEMP": str(tmp_path),
        "VMX_TEST_GH_ARGS": str(arguments),
        "GITHUB_REF": f"refs/tags/react-v{version}",
        "GITHUB_REF_NAME": f"react-v{version}",
        "GITHUB_SHA": "a" * 40,
        "GH_TOKEN": "",
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
    )
    return (
        result,
        notes.read_text() if notes.exists() else "",
        (arguments.read_text().splitlines() if arguments.exists() else []),
    )


def _run_documented_notes_guard(tmp_path: Path, changelog: str):
    source = tmp_path / "packages/react/CHANGELOG.md"
    source.parent.mkdir(parents=True)
    source.write_text(changelog)
    extractor = tmp_path / "tools/extract-react-release-notes.awk"
    extractor.parent.mkdir()
    extractor.write_bytes((ROOT / "tools/extract-react-release-notes.awk").read_bytes())
    contributor = (ROOT / "docs/content/contributing-releases.md").read_text()
    section = contributor.split("### 11.5.3. Recover React Release Metadata", 1)[1]
    script = re.findall(r"```bash\n(.*?)\n```", section, flags=re.DOTALL)[0]
    script = (
        'version="0.2.0"\nnotes="$RUNNER_TEMP/react-recovery-notes.md"'
        + script.split('notes="$(mktemp)"', 1)[1]
    )
    script = script.replace(
        'git show "${tag_sha}:packages/react/CHANGELOG.md"',
        "cat packages/react/CHANGELOG.md",
    )
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={"PATH": os.defpath, "RUNNER_TEMP": str(tmp_path)},
        text=True,
        capture_output=True,
        timeout=15,
    )


CHANGELOG = (
    "# Changelog\n\n## [Unreleased]\n\n- Future.\n\n"
    "## [0.3.0] - 2026-09-24\n\n### Fixed\n\n- First.\n\n"
    "## [0.2.0] - 2026-08-24\n\n### Added\n\n- Middle.\n\n"
    "## [0.1.0] - 2026-07-24\n\n- Last.\n"
)


def test_release_notes_first_version(tmp_path: Path) -> None:
    result, notes, _ = _run_notes(tmp_path, CHANGELOG, "0.3.0")
    assert result.returncode == 0, result.stderr
    assert notes == "\n### Fixed\n\n- First.\n\n"


def test_release_notes_middle_version(tmp_path: Path) -> None:
    result, notes, _ = _run_notes(tmp_path, CHANGELOG)
    assert result.returncode == 0, result.stderr
    assert notes == "\n### Added\n\n- Middle.\n\n"


def test_release_notes_last_version(tmp_path: Path) -> None:
    result, notes, _ = _run_notes(tmp_path, CHANGELOG, "0.1.0")
    assert result.returncode == 0, result.stderr
    assert notes == "\n- Last.\n"


def test_release_notes_absent_version(tmp_path: Path) -> None:
    result, notes, arguments = _run_notes(tmp_path, CHANGELOG, "9.9.9")
    assert result.returncode != 0
    assert not notes
    assert not arguments


def test_release_notes_empty_section(tmp_path: Path) -> None:
    result, notes, arguments = _run_notes(tmp_path, "## [0.2.0]\n## [0.1.0]\n- Old.\n")
    assert result.returncode != 0
    assert not notes
    assert not arguments


def test_release_notes_whitespace_only_section(tmp_path: Path) -> None:
    result, notes, arguments = _run_notes(tmp_path, "## [0.2.0]\n\n \t\n## [0.1.0]\n- Old.\n")
    assert result.returncode != 0
    assert not notes.strip()
    assert not arguments


def test_release_notes_similarly_prefixed_versions(tmp_path: Path) -> None:
    fixture = (
        "## [0.1.0-rc.1]\n- RC.\n## [0.10.0]\n- Ten.\n## [0.1.0]\n- Exact.\n## [0.0.9]\n- Old.\n"
    )
    result, notes, _ = _run_notes(tmp_path, fixture, "0.1.0")
    assert result.returncode == 0, result.stderr
    assert notes == "- Exact.\n"


def test_release_notes_version_is_not_a_regex(tmp_path: Path) -> None:
    fixture = "## [0x1x0]\n- Wrong.\n## [0.1.0] - date\n- Exact.\n"
    result, notes, _ = _run_notes(tmp_path, fixture, "0.1.0")
    assert result.returncode == 0, result.stderr
    assert notes == "- Exact.\n"


def test_release_notes_unexpected_heading_content(tmp_path: Path) -> None:
    fixture = (
        "## [0.2.0]suffix\n- Wrong.\n## [0.2.0] - date\n### Fixed\n"
        "- Selected.\n## Unexpected heading\n- Must not bleed.\n## [0.1.0]\n- Old.\n"
    )
    result, notes, _ = _run_notes(tmp_path, fixture)
    assert result.returncode == 0, result.stderr
    assert notes == "### Fixed\n- Selected.\n"


def test_release_notes_empty_level_two_heading_ends_section(tmp_path: Path) -> None:
    result, notes, _ = _run_notes(tmp_path, "## [0.2.0]\n- Selected.\n##\n- Must not bleed.\n")
    assert result.returncode == 0, result.stderr
    assert notes == "- Selected.\n"


@pytest.mark.parametrize(
    ("changelog", "expected_returncode", "expected_stdout"),
    [
        ("## [0.1.0]\n- Other.\n", 1, ""),
        ("## [0.2.0]\n## [0.1.0]\n- Old.\n", 1, ""),
        ("## [0.2.0]\n\n \t\n", 1, ""),
        ("## [0.2.0]\n\n- Selected.\n", 0, "\n- Selected.\n"),
    ],
    ids=("missing", "empty", "whitespace-only", "valid"),
)
def test_documented_recovery_notes_guard(
    tmp_path: Path, changelog: str, expected_returncode: int, expected_stdout: str
) -> None:
    result = _run_documented_notes_guard(tmp_path, changelog)
    assert result.returncode == expected_returncode, result.stderr
    assert result.stdout == expected_stdout


def test_release_notes_are_printed_before_release_creation(tmp_path: Path) -> None:
    result, notes, arguments = _run_notes(tmp_path, CHANGELOG)
    assert result.returncode == 0, result.stderr
    assert result.stdout == notes + "VMX_TEST_RELEASE_CREATED\n"
    assert arguments == [
        "release",
        "create",
        "react-v0.2.0",
        "--title",
        "React adapter v0.2.0 (npm)",
        "--notes-file",
        str(tmp_path / "react-release-notes.md"),
        "--target",
        "a" * 40,
    ]


def test_real_adapter_changelog_extracts_current_package_version(tmp_path: Path) -> None:
    version = json.loads((ROOT / "packages/react/package.json").read_text())["version"]
    result, notes, arguments = _run_notes(
        tmp_path, (ROOT / "packages/react/CHANGELOG.md").read_text(), version
    )
    assert result.returncode == 0, result.stderr
    assert notes.strip()
    assert arguments[2] == f"react-v{version}"


def test_release_notes_remain_after_public_verification() -> None:
    assert "    needs: react-verify-published\n" in _job("react-release-notes")
    verification = _job("react-verify-published")
    assert "    needs: react\n" in verification
    assert 'react: ["18.3.1", "19.2.8"]' in verification
    assert "dist.attestations --json | grep -q" in verification
    assert "'provenance'" in verification
    assert (
        'npm install --ignore-scripts --no-audit --no-fund "@thekaveh/vmx-react@${version}" '
        '"react@${{ matrix.react }}" "react-dom@${{ matrix.react }}"' in verification
    )
    assert "mkdir /tmp/react-consumer" in verification
    assert "createVmxStore" in verification


def test_executable_release_regressions_run_on_ubuntu_ci() -> None:
    workflow = (ROOT / ".github/workflows/conformance.yml").read_text()
    assert "runs-on: ubuntu-latest" in workflow
    assert "-m pytest tools/tests/ -v" in workflow
