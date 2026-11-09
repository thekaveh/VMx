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


def test_check_ledger_requires_every_remote_action_by_name(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    action = "actions/checkout@" + "a" * 40
    (workflows / "ci.yml").write_text(
        f"steps:\n  - uses: {action} # v7.0.0\n  - uses: ./local-action\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")

    assert cwp.check_ledger(tmp_path, ledger) == ["undocumented workflow action: actions/checkout"]

    ledger.write_text("| Action |\n| --- |\n| `actions/checkout` |\n", encoding="utf-8")
    assert cwp.check_ledger(tmp_path, ledger) == []


def test_a_new_sha_in_every_workflow_needs_no_ledger_edit(tmp_path: Path) -> None:
    # #1363: a Dependabot SHA update changes only the workflows.
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    ledger = tmp_path / "ledger.md"
    ledger.write_text("`astral-sh/setup-uv`\n", encoding="utf-8")
    for sha in ("a" * 40, "b" * 40):
        for name in ("ci.yml", "release.yml"):
            (workflows / name).write_text(
                f"steps:\n  - uses: astral-sh/setup-uv@{sha} # v10\n", encoding="utf-8"
            )
        assert cwp.check_ledger(tmp_path, ledger) == []


def test_check_ledger_rejects_two_shas_for_one_action(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        f"steps:\n  - uses: astral-sh/setup-uv@{'a' * 40}\n", encoding="utf-8"
    )
    (workflows / "release.yml").write_text(
        f"steps:\n  - uses: astral-sh/setup-uv@{'b' * 40}\n", encoding="utf-8"
    )
    ledger = tmp_path / "ledger.md"
    ledger.write_text("`astral-sh/setup-uv`\n", encoding="utf-8")

    assert cwp.check_ledger(tmp_path, ledger) == [
        f"workflow action uses more than one ref: astral-sh/setup-uv ({'a' * 40}, {'b' * 40})"
    ]


def test_check_ledger_rejects_a_sha_copied_into_the_ledger(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    current = "googleapis/release-please-action@" + "a" * 40
    (workflows / "release.yml").write_text(f"steps:\n  - uses: {current}\n", encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text(f"`googleapis/release-please-action`\n`{current}`\n", encoding="utf-8")

    assert cwp.check_ledger(tmp_path, ledger) == [
        f"ledger repeats a workflow pin: {current}; name the action only"
    ]
