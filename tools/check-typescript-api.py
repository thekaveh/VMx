#!/usr/bin/env python3
"""Compare the built declarations of an npm package with its recorded API snapshot.

``npm run build`` (tsup) writes one ``.d.ts`` per package entry point and
shared declaration chunks named ``<name>-<hash>.d.ts``. The hash changes
whenever chunk content changes, so the tool removes it from file names and
from the relative imports that name a chunk. The snapshot is the
concatenation of every normalized ESM declaration file, in name order. The
CommonJS ``.d.cts`` files must normalize to the same text.

Normalization also removes comments (``/** ... */`` doc comments, block
comments and ``//`` line comments), so a change to a doc comment alone does not
change the snapshot. Everything else in the declarations is part of the
snapshot, including the ``private constructor()`` and ``#private`` markers that
TypeScript emits.

Run it after ``npm run build`` in the package directory. The defaults check
``@thekaveh/vmx`` in ``langs/typescript``; the React adapter
``@thekaveh/vmx-react`` in ``packages/react`` passes its own paths::

    python3 ../../tools/check-typescript-api.py            # check @thekaveh/vmx
    python3 ../../tools/check-typescript-api.py --update   # rewrite its baseline
    python3 ../../tools/check-typescript-api.py --dist dist --package-json package.json \
        --baseline api/vmx-react.api.txt                   # check the adapter

Exit codes: 0 when the declarations match the snapshot, 1 on any difference
(the unified diff is printed), 2 when the build output is missing or
malformed.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "langs/typescript"
DEFAULT_DIST = PACKAGE_DIR / "dist"
DEFAULT_PACKAGE_JSON = PACKAGE_DIR / "package.json"
DEFAULT_BASELINE = PACKAGE_DIR / "api/vmx.api.txt"

# tsup/rollup chunk names end in an eight-character URL-safe hash.
_CHUNK_FILE = re.compile(r"^(?P<base>.+)-(?P<hash>[A-Za-z0-9_-]{8})\.d\.c?ts$")
_CHUNK_IMPORT = re.compile(r"""(['"]\./[^'"]+?)-[A-Za-z0-9_-]{8}(\.c?js['"])""")


class ApiError(Exception):
    """The build output cannot be rendered into a snapshot."""


def _normalized_name(path: Path, entries: set[str]) -> str:
    suffix = ".d.cts" if path.name.endswith(".d.cts") else ".d.ts"
    stem = path.name[: -len(suffix)]
    if stem in entries:
        return f"{stem}.d.ts"
    match = _CHUNK_FILE.match(path.name)
    if match is None:
        raise ApiError(f"{path.name} is neither an entry point nor a hashed chunk")
    return f"{match.group('base')}.d.ts"


# Marks the place of a removed comment on each line that the comment touched.
_COMMENT_MARK = "\x00"


def _strip_comments(text: str) -> str:
    """Remove ``/* */`` and ``//`` comments outside string literals.

    A line that held only a comment is dropped; a line that held a comment and
    code keeps the code. Original blank lines stay.
    """
    out: list[str] = []
    index, length, quote = 0, len(text), ""
    while index < length:
        char = text[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
        elif char in "'\"`":
            quote = char
            out.append(char)
            index += 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ApiError("unterminated block comment in the declarations")
            out.append(_COMMENT_MARK)
            out.append(f"\n{_COMMENT_MARK}" * text.count("\n", index, end))
            index = end + 2
        elif text.startswith("//", index):
            end = text.find("\n", index)
            out.append(_COMMENT_MARK)
            index = length if end < 0 else end
        else:
            out.append(char)
            index += 1
    lines: list[str] = []
    for line in "".join(out).split("\n"):
        if _COMMENT_MARK in line:
            line = line.replace(_COMMENT_MARK, "")
            if not line.strip():
                continue
        lines.append(line)
    return "\n".join(lines)


def _normalized_text(text: str) -> str:
    text = _strip_comments(text.replace("\r\n", "\n"))
    text = _CHUNK_IMPORT.sub(r"\1\2", text)
    text = text.replace(".cjs'", ".js'").replace('.cjs"', '.js"')
    return "\n".join(line.rstrip() for line in text.strip("\n").split("\n")) + "\n"


def _collect(dist: Path, pattern: str, entries: set[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(dist.glob(pattern)):
        name = _normalized_name(path, entries)
        if name in files:
            raise ApiError(f"two declaration files normalize to {name}")
        files[name] = _normalized_text(path.read_text(encoding="utf-8"))
    return files


def package_identity(package_json: Path) -> tuple[str, str]:
    """Return the ``name`` and ``version`` fields of the package manifest."""
    manifest = json.loads(package_json.read_text(encoding="utf-8"))
    for field in ("name", "version"):
        if not isinstance(manifest.get(field), str):
            raise ApiError(f"{package_json} has no string {field} field")
    return manifest["name"], manifest["version"]


def bump_rule(version: str) -> str:
    """Return the version bump that a removed or changed export needs (CONTRIBUTING.md)."""
    if version.partition(".")[0] == "0":
        return "a minor version bump while the version is 0.x"
    return "a major version bump"


def update_hint(package_json: Path, dist: Path, baseline: Path) -> str:
    """Return the command that rewrites the baseline, run in the package directory.

    A path that differs from the core defaults is named, so the command repeats
    the check that CI runs for the package.
    """
    options = [
        f"{flag} {os.path.relpath(path, package_json.parent)}"
        for flag, path, default in (
            ("--dist", dist, DEFAULT_DIST),
            ("--package-json", package_json, DEFAULT_PACKAGE_JSON),
            ("--baseline", baseline, DEFAULT_BASELINE),
        )
        if path != default
    ]
    return " ".join(
        ["npm run build &&", "python3 ../../tools/check-typescript-api.py", *options, "--update"]
    )


def _display(path: Path) -> str:
    """Return a path relative to the repository root, or the path as given outside it."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def entry_points(package_json: Path) -> set[str]:
    """Return the declaration stems (``index``, ``notifications``, ...) of the exports map."""
    manifest = json.loads(package_json.read_text(encoding="utf-8"))
    stems: set[str] = set()
    for conditions in manifest["exports"].values():
        # A plain string export, such as "./package.json", declares no types.
        types = conditions.get("import") if isinstance(conditions, dict) else None
        types = types.get("types") if isinstance(types, dict) else None
        if isinstance(types, str):
            stems.add(Path(types).name.removesuffix(".d.ts"))
    return stems


def render_api(dist: Path, entries: set[str], package_name: str) -> str:
    esm = _collect(dist, "*.d.ts", entries)
    cjs = _collect(dist, "*.d.cts", entries)
    missing = sorted(f"{stem}.d.ts" for stem in entries if f"{stem}.d.ts" not in esm)
    if missing:
        raise ApiError(f"missing entry declarations {missing} in {dist}; run npm run build")
    if esm != cjs:
        differing = sorted(
            name for name in esm.keys() | cjs.keys() if esm.get(name) != cjs.get(name)
        )
        raise ApiError(f"ESM and CommonJS declarations differ: {differing}")
    parts = [
        f"// Public declarations of {package_name}: dist/*.d.ts without chunk hashes or comments.",
        "// Generated by tools/check-typescript-api.py; do not edit by hand.",
    ]
    for name, text in esm.items():
        parts.append("")
        parts.append(f"// ==== {name} ====")
        parts.append(text.rstrip("\n"))
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--package-json", type=Path, default=DEFAULT_PACKAGE_JSON)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--update", action="store_true", help="rewrite the baseline")
    args = parser.parse_args(argv)
    dist, package_json, baseline = (
        path.resolve() for path in (args.dist, args.package_json, args.baseline)
    )
    try:
        name, version = package_identity(package_json)
        current = render_api(dist, entry_points(package_json), name)
    except (ApiError, OSError, KeyError, ValueError) as error:
        print(f"ERROR: cannot render the TypeScript API: {error}", file=sys.stderr)
        return 2
    hint = update_hint(package_json, dist, baseline)
    where = _display(package_json.parent)
    if args.update:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(current, encoding="utf-8")
        print(f"Updated {baseline}")
        return 0
    if not baseline.is_file():
        print(f"FAIL: missing API baseline {baseline}; run {hint} in {where}", file=sys.stderr)
        return 1
    recorded = baseline.read_text(encoding="utf-8")
    if recorded == current:
        print(f"OK: the {name} declarations match {baseline.name}")
        return 0
    sys.stdout.writelines(
        difflib.unified_diff(
            recorded.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"baseline/{baseline.name}",
            tofile="current",
        )
    )
    print(
        f"FAIL: the {name} declarations differ from {baseline}. "
        f"For an intended change, run `{hint}` in {where} and commit "
        f"the baseline; a removed or changed export needs {bump_rule(version)} "
        "(CONTRIBUTING.md).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
