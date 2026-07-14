"""Tests for the workflow-pin and contract-ledger consistency checker."""

from pathlib import Path

import check_workflow_pins as cwp


def test_collect_workflow_actions_rejects_mutable_refs(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "steps:\n  - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )

    actions, issues = cwp.collect_workflow_actions(tmp_path)

    assert actions == {"actions/checkout@v4"}
    assert len(issues) == 1
    assert "40-character commit" in issues[0]


def test_check_ledger_requires_every_remote_action(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    action = "actions/checkout@" + "a" * 40
    (workflows / "ci.yml").write_text(
        f"steps:\n  - uses: {action} # v7.0.0\n  - uses: ./local-action\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")

    assert cwp.check_ledger(tmp_path, ledger) == [f"undocumented workflow action: {action}"]

    ledger.write_text(
        f"| Action | Pin |\n| --- | --- |\n| `{action}` | current |\n",
        encoding="utf-8",
    )
    assert cwp.check_ledger(tmp_path, ledger) == []
