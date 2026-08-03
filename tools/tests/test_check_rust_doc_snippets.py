from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/check-rust-doc-snippets.py"
SPEC = importlib.util.spec_from_file_location("check_rust_doc_snippets", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_extracts_only_rust_fences() -> None:
    markdown = """```bash
cargo check
```
```rust
fn main() {}
```
"""

    assert MODULE.extract_rust_snippets(markdown) == ["fn main() {}\n"]


def test_rejects_non_standalone_rust_fragments() -> None:
    with pytest.raises(ValueError, match="snippets without fn main: 2"):
        MODULE.validate_standalone(["fn main() {}\n", "let value = 1;\n"])


def test_public_guide_snippets_are_standalone() -> None:
    snippets = MODULE.extract_rust_snippets(MODULE.GUIDE.read_text(encoding="utf-8"))

    MODULE.validate_standalone(snippets)
