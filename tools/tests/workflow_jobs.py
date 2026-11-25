"""Read the jobs and live commands of a GitHub Actions workflow.

Standard library only: the tools environment has no YAML parser, so these
readers work on the workflow text. A job is the text under one two-space job
key of `jobs:`. A live command is the value of a `run:` key, with comment lines
removed. A shell segment that only quotes output with `echo` or `printf` is
removed too, but a segment chained after it (`echo x && node tools/y.py`, or
`echo x | node tools/y.py`) still runs its command, so that command stays live.
"""

import re

_JOB_HEADER = re.compile(r"(?m)^  ([A-Za-z0-9_-]+):\n")
_COMMENT_LINE = re.compile(r"(?m)^\s*#.*\n")
_RUN_KEY = re.compile(r"^(?P<lead>\s*(?:-\s+)?)run:(?:[ \t]+(?P<value>.*?))?\s*$")
_BLOCK_HEADER = re.compile(r"(?P<style>[|>])[-+0-9]*")
_QUOTING_WORDS = frozenset({"echo", "printf"})
_PUSH_BLOCK = re.compile(r"(?ms)^  push:\n(.*?)(?=^\S|^  \S|\Z)")
_PUSH_PATH = re.compile(r'^      - "([^"]+)"$', re.M)


def workflow_jobs(text: str) -> dict[str, str]:
    """Map each job name of a workflow to its text, comment lines removed."""
    body = _COMMENT_LINE.sub("", text.split("\njobs:\n", maxsplit=1)[1])
    parts = _JOB_HEADER.split(body)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def push_path_patterns(text: str) -> list[str] | None:
    """Return the `on.push.paths` patterns of a workflow, or None when it has no push
    path filter. A workflow without the filter runs on every push to its branches."""
    block = _PUSH_BLOCK.search(text)
    if block is None or not re.search(r"(?m)^    paths:$", block.group(1)):
        return None
    return _PUSH_PATH.findall(block.group(1))


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
    """The part of one line that runs, or None when the line only quotes output.

    The line is split at its unquoted `&&`, `||`, `;` and `|` operators. A segment
    that starts with `echo` or `printf` only quotes a message and is dropped; any
    other segment runs. A line with a command substitution (`$(` or a backtick)
    runs its inner command, so it is kept whole.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "$(" in stripped or "`" in stripped:
        return line.rstrip()
    segments = _chain_segments(stripped)
    live = [segment for segment in segments if segment.split()[0] not in _QUOTING_WORDS]
    if len(live) == len(segments):
        return line.rstrip()
    return " && ".join(live) if live else None


def _chain_segments(text: str) -> list[str]:
    """Split a shell line at its unquoted `&&`, `||`, `;` and `|` operators.

    A backslash escapes the next character outside single quotes, and an operator
    inside quotes is text, so `echo "a && b"` is one segment.
    """
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote != "'" and char == "\\" and index + 1 < len(text):
            current.append(text[index : index + 2])
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif text.startswith(("&&", "||"), index):
            segments.append("".join(current))
            current = []
            index += 2
            continue
        elif char in ";|":
            segments.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()]
