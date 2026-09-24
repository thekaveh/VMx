#!/usr/bin/env python3
"""Assert this interpreter's identity, then run Python argv with that executable."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def normalized(path: str) -> str:
    """Normalize directory aliases without following the executable symlink itself."""
    directory, filename = os.path.split(os.path.abspath(path))
    return os.path.normcase(os.path.join(os.path.realpath(directory), filename))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default=os.environ.get("UV_PYTHON"))
    context = parser.add_mutually_exclusive_group(required=True)
    context.add_argument("--venv")
    context.add_argument("--tool-context", action="store_true")
    parser.add_argument("--expected-executable")
    parser.add_argument("--capture-output", action="store_true")
    parser.add_argument("python_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    actual = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(
        f"Python identity: requested={args.expected_version} actual={actual} "
        f"sys.executable={sys.executable} sys.prefix={sys.prefix}",
        file=sys.stderr,
        flush=True,
    )
    if args.expected_version != actual:
        parser.exit(1, "Python version mismatch\n")
    if args.venv:
        if os.path.normcase(os.path.realpath(sys.prefix)) != os.path.normcase(
            os.path.realpath(args.venv)
        ):
            parser.exit(1, "Python prefix mismatch\n")
        entries = (
            ["Scripts/python.exe"]
            if os.name == "nt"
            else ["bin/python", "bin/python3", f"bin/python{actual}"]
        )
        if normalized(sys.executable) not in {
            normalized(os.path.join(args.venv, entry)) for entry in entries
        }:
            parser.exit(1, "Python executable mismatch for virtualenv\n")
    if args.expected_executable is not None and normalized(sys.executable) != normalized(
        args.expected_executable
    ):
        parser.exit(1, "Python executable mismatch against initial assertion\n")
    if args.capture_output:
        if "\n" in sys.executable or "\r" in sys.executable:
            parser.exit(1, "Python executable cannot contain newlines in a step output\n")
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"executable={sys.executable}\n")
    child_args = args.python_args
    if child_args and child_args[0] == "--":
        child_args = child_args[1:]
    if child_args:
        return subprocess.run([sys.executable, *child_args], check=False, timeout=1800).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
