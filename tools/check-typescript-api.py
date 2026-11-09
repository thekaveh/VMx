#!/usr/bin/env python3
"""Compare the built declarations of ``@thekaveh/vmx`` with the recorded API snapshot.

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

Run it after ``npm run build`` in ``langs/typescript``::

    python3 ../../tools/check-typescript-api.py            # check
    python3 ../../tools/check-typescript-api.py --update   # rewrite baseline

Exit codes: 0 when the declarations match the snapshot, 1 on any difference
(the unified diff is printed), 2 when the build output is missing or
malformed.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "langs/typescript"
DEFAULT_DIST = PACKAGE_DIR / "dist"
DEFAULT_BASELINE = PACKAGE_DIR / "api/vmx.api.txt"
UPDATE_HINT = "npm run build && python3 ../../tools/check-typescript-api.py --update"

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


def entry_points(package_json: Path) -> set[str]:
    """Return the declaration stems (``index``, ``notifications``, ...) of the exports map."""
    import json

    manifest = json.loads(package_json.read_text(encoding="utf-8"))
    stems: set[str] = set()
    for conditions in manifest["exports"].values():
        # A plain string export, such as "./package.json", declares no types.
        types = conditions.get("import") if isinstance(conditions, dict) else None
        types = types.get("types") if isinstance(types, dict) else None
        if isinstance(types, str):
            stems.add(Path(types).name.removesuffix(".d.ts"))
    return stems


def render_api(dist: Path, entries: set[str]) -> str:
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
        "// Public declarations of @thekaveh/vmx: dist/*.d.ts without chunk hashes or comments.",
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
    parser.add_argument("--package-json", type=Path, default=PACKAGE_DIR / "package.json")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--update", action="store_true", help="rewrite the baseline")
    args = parser.parse_args(argv)
    try:
        current = render_api(args.dist, entry_points(args.package_json))
    except (ApiError, OSError, KeyError, ValueError) as error:
        print(f"ERROR: cannot render the TypeScript API: {error}", file=sys.stderr)
        return 2
    if args.update:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(current, encoding="utf-8")
        print(f"Updated {args.baseline}")
        return 0
    if not args.baseline.is_file():
        print(f"FAIL: missing API baseline {args.baseline}; run {UPDATE_HINT}", file=sys.stderr)
        return 1
    recorded = args.baseline.read_text(encoding="utf-8")
    if recorded == current:
        print(f"OK: the @thekaveh/vmx declarations match {args.baseline.name}")
        return 0
    sys.stdout.writelines(
        difflib.unified_diff(
            recorded.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"baseline/{args.baseline.name}",
            tofile="current",
        )
    )
    print(
        f"FAIL: the @thekaveh/vmx declarations differ from {args.baseline}. "
        f"For an intended change, run `{UPDATE_HINT}` in langs/typescript and commit "
        "the baseline; a removed or changed export needs a major version bump "
        "(CONTRIBUTING.md).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
