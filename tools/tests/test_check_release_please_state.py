"""Tests for the release-please source/manifest preflight."""

import json
from pathlib import Path

import check_release_please_state as crps


def _write_state(root: Path, source: str, published: str) -> None:
    about = root / "langs" / "python" / "src" / "vmx" / "__about__.py"
    about.parent.mkdir(parents=True)
    about.write_text(
        f'__version__ = "{source}"  # x-release-please-version\n',
        encoding="utf-8",
    )
    (root / ".release-please-manifest.json").write_text(
        json.dumps({"langs/python": published}),
        encoding="utf-8",
    )


def test_matching_source_and_manifest_is_ready(tmp_path: Path) -> None:
    _write_state(tmp_path, "3.22.0", "3.22.0")

    result = crps.check_state(tmp_path)

    assert result.ready is True
    assert result.source_version == "3.22.0"
    assert result.published_version == "3.22.0"


def test_source_ahead_of_manifest_is_safely_blocked(tmp_path: Path) -> None:
    _write_state(tmp_path, "3.22.0", "3.1.0")

    result = crps.check_state(tmp_path)

    assert result.ready is False
    assert "bootstrap" in result.reason
    assert "downgrade" in result.reason


def test_github_output_records_boolean_and_versions(tmp_path: Path) -> None:
    _write_state(tmp_path, "3.22.0", "3.1.0")
    output = tmp_path / "github-output"

    exit_code = crps.main(["--root", str(tmp_path), "--github-output", str(output)])

    assert exit_code == 0
    assert output.read_text(encoding="utf-8").splitlines() == [
        "ready=false",
        "source-version=3.22.0",
        "published-version=3.1.0",
    ]


def test_release_workflow_gates_action_on_preflight() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github" / "workflows" / "release-please.yml").read_text(encoding="utf-8")

    assert "python3 tools/check-release-please-state.py" in workflow
    assert "id: release-state" in workflow
    assert "if: steps.release-state.outputs.ready == 'true'" in workflow
