"""Read the jobs and live commands of a GitHub Actions workflow.

Standard library only: the tools environment has no YAML parser, so these
readers work on the workflow text. A job is the text under one two-space job
key of `jobs:`. A live command is the value of a `run:` key, with comment lines
and lines that only quote a command with `echo` or `printf` removed. A pipe
after such a quote still runs its command, so that command stays live.
"""

import re

_JOB_HEADER = re.compile(r"(?m)^  ([A-Za-z0-9_-]+):\n")
_COMMENT_LINE = re.compile(r"(?m)^\s*#.*\n")
_RUN_KEY = re.compile(r"^(?P<lead>\s*(?:-\s+)?)run:(?:[ \t]+(?P<value>.*?))?\s*$")
_BLOCK_HEADER = re.compile(r"(?P<style>[|>])[-+0-9]*")
_QUOTING_WORDS = frozenset({"echo", "printf"})


def workflow_jobs(text: str) -> dict[str, str]:
    """Map each job name of a workflow to its text, comment lines removed."""
    body = _COMMENT_LINE.sub("", text.split("\njobs:\n", maxsplit=1)[1])
    parts = _JOB_HEADER.split(body)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def workflow_job(workflow: str, name: str) -> str:
    """Return the text of one job, or fail and name the job and the jobs present."""
    jobs = workflow_jobs(workflow)
    if name not in jobs:
        raise AssertionError(f"workflow has no job {name!r}; jobs: {sorted(jobs)}")
    return jobs[name]


def run_commands(job: str) -> list[str]:
    """Return the live `run:` value of each step in a job or any workflow text.

    A literal value (`|`) keeps its live lines, joined by newlines. A folded
    value (`>`) joins its live lines with spaces. A mapping key `run:` with no
    value, such as a `defaults:` block, is not a command.
    """
    lines = job.splitlines()
    commands: list[str] = []
    index = 0
    while index < len(lines):
        match = _RUN_KEY.match(lines[index])
        index += 1
        if match is None:
            continue
        column = len(match.group("lead"))
        value = match.group("value") or ""
        header = _BLOCK_HEADER.fullmatch(value)
        if header is None:
            command = _live_inline_value(value)
            if command is not None:
                commands.append(command)
            continue
        block: list[str] = []
        while index < len(lines) and (not lines[index].strip() or _indent(lines[index]) > column):
            block.append(lines[index])
            index += 1
        live = _live_block_lines(block)
        if not live:
            continue
        if header.group("style") == ">":
            commands.append(" ".join(line.strip() for line in live))
        else:
            commands.append("\n".join(live))
    return commands


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _live_inline_value(value: str) -> str | None:
    """The live text of an inline value. A `#` after whitespace starts a YAML comment
    only in a plain scalar, not in a quoted one."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return _live_text(value[1:-1])
    return _live_text(re.sub(r"\s+#.*$", "", value).strip())


def _live_block_lines(block: list[str]) -> list[str]:
    """The live lines of a block scalar, dedented to their common indentation."""
    content = [line for line in block if line.strip()]
    if not content:
        return []
    indent = min(_indent(line) for line in content)
    lines = (_live_text(line[indent:].rstrip()) for line in block)
    return [line for line in lines if line is not None]


def _live_text(line: str) -> str | None:
    """The part of one line that runs, or None when the line only quotes a command."""
    stripped = line.strip()
    words = stripped.split()
    if not words or stripped.startswith("#"):
        return None
    if words[0] not in _QUOTING_WORDS:
        return line.rstrip()
    _, separator, piped = stripped.partition(" | ")
    if not separator or not piped.strip():
        return None
    return piped.strip()
