"""Unit tests for the workflow job and live-command reader."""

import pytest

from .workflow_jobs import run_commands, workflow_job

WORKFLOW = """\
name: demo
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: langs/demo
    steps:
      # - run: npm run retired
      - name: Lint
        run: npm run lint

      - run: echo "npm run quoted"
      - run: echo "$HASH  file.tar.gz" | sha256sum --check --strict
      - name: Build
        run: |
          # npm run commented
          npm run typecheck
          printf '%s\\n' "npm run printed"
          npm run build
      - run: >-
          npm run test
          --prefix examples/demo
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: npm publish
"""


def test_workflow_job_returns_the_whole_job_across_blank_lines() -> None:
    job = workflow_job(WORKFLOW, "build")

    assert "npm run lint" in job
    assert "npm run build" in job
    assert "npm publish" not in job
    assert "npm run retired" not in job


def test_workflow_job_names_the_missing_job_and_the_jobs_present() -> None:
    with pytest.raises(AssertionError) as raised:
        workflow_job(WORKFLOW, "deploy")

    message = str(raised.value)
    assert "'deploy'" in message
    assert "'build'" in message
    assert "'publish'" in message


def test_run_commands_returns_each_live_run_value_of_the_job() -> None:
    commands = run_commands(workflow_job(WORKFLOW, "build"))

    assert commands == [
        "npm run lint",
        "sha256sum --check --strict",
        "npm run typecheck\nnpm run build",
        "npm run test --prefix examples/demo",
    ]


def test_run_commands_drops_commented_out_and_echoed_commands() -> None:
    commands = "\n".join(run_commands(workflow_job(WORKFLOW, "build")))

    assert "retired" not in commands
    assert "commented" not in commands
    assert "quoted" not in commands
    assert "printed" not in commands
    assert "HASH" not in commands


CHAINED = r"""
      - run: echo building && node tools/y.py
      - run: printf 'done\n' || npm run lint
      - run: echo "npm run quoted && node tools/z.py"
      - run: echo "$(node tools/w.py)"
"""


def test_run_commands_keeps_a_command_chained_after_an_echo() -> None:
    # A quoted message drops only its own segment: a command chained after it,
    # with && || ; or |, runs, so its inputs are reads. A quote-only line is dropped.
    assert run_commands(CHAINED) == [
        "node tools/y.py",
        "npm run lint",
        'echo "$(node tools/w.py)"',
    ]


def test_run_commands_reads_a_list_item_run_key_and_skips_a_mapping_run_key() -> None:
    assert run_commands(workflow_job(WORKFLOW, "publish")) == ["npm publish"]
    defaults = "  build:\n    defaults:\n      run:\n        working-directory: x\n"
    assert run_commands(defaults) == []
