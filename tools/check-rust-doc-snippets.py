#!/usr/bin/env python3
"""Compile every Rust fence in the public Rust getting-started guide."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/content/getting-started/rust.md"
CRATE = ROOT / "langs/rust"
RUST_FENCE = re.compile(r"^```rust\s*$\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)


def extract_rust_snippets(markdown: str) -> list[str]:
    """Return Rust fenced blocks in document order."""

    return [match.group(1).strip() + "\n" for match in RUST_FENCE.finditer(markdown)]


def validate_standalone(snippets: list[str]) -> None:
    """Reject fragments that cannot be pasted into a binary source file."""

    if not snippets:
        raise ValueError("the Rust getting-started guide contains no Rust snippets")
    missing_main = [
        str(index) for index, snippet in enumerate(snippets, start=1) if "fn main" not in snippet
    ]
    if missing_main:
        raise ValueError(f"Rust snippets without fn main: {', '.join(missing_main)}")


def main() -> int:
    snippets = extract_rust_snippets(GUIDE.read_text(encoding="utf-8"))
    validate_standalone(snippets)

    with tempfile.TemporaryDirectory(prefix="vmx-rust-docs-") as temp_dir:
        project = Path(temp_dir)
        source = project / "src/main.rs"
        source.parent.mkdir()
        crate_path = str(CRATE).replace("\\", "\\\\")
        (project / "Cargo.toml").write_text(
            "[package]\n"
            'name = "vmx-rust-doc-snippets"\n'
            'version = "0.0.0"\n'
            'edition = "2021"\n\n'
            "[dependencies]\n"
            f'vmx = {{ package = "vmx-rs", path = "{crate_path}" }}\n',
            encoding="utf-8",
        )

        for index, snippet in enumerate(snippets, start=1):
            source.write_text(snippet, encoding="utf-8")
            result = subprocess.run(
                ["cargo", "check", "--quiet", "--offline"],
                cwd=project,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if result.returncode:
                print(f"Rust documentation snippet {index} failed to compile:")
                print(result.stderr)
                return result.returncode

    print(f"Compiled {len(snippets)} standalone Rust documentation snippets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
