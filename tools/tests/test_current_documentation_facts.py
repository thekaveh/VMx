"""Keep current-facing repository inventories derived from their sources."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_current_docs_match_adr_inventory() -> None:
    adrs = sorted((ROOT / "spec/ADRs").glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert adrs
    count = len(adrs)
    last = adrs[-1].name[:4]

    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    spec_readme = (ROOT / "spec/README.md").read_text(encoding="utf-8")

    assert f"{count} ADRs" in agents
    assert readme.count(f"{count} ADRs") >= 2
    assert f"(0001-{last})" in spec_readme


def test_contract_ledger_matches_current_rust_package() -> None:
    cargo = (ROOT / "langs/rust/Cargo.toml").read_text(encoding="utf-8")
    cargo_lock = (ROOT / "langs/rust/Cargo.lock").read_text(encoding="utf-8")
    rust_source = (ROOT / "langs/rust/src/lib.rs").read_text(encoding="utf-8")
    ledger = (ROOT / "docs/maintenance/2026-07-01-contract-ledger.md").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"$', cargo, re.MULTILINE)
    msrv = re.search(r'^rust-version = "([^"]+)"$', cargo, re.MULTILINE)
    min_spec = re.search(r'MIN_SPEC_VERSION: &str = "([^"]+)"', rust_source)
    assert version and msrv and min_spec

    expected = (
        f"`vmx-rs` is `{version.group(1)}`, implements spec "
        f"`{min_spec.group(1)}`, and has MSRV Rust `{msrv.group(1)}`"
    )
    assert expected in ledger
    serde_json = re.search(r'\[\[package\]\]\nname = "serde_json"\nversion = "([^"]+)"', cargo_lock)
    assert serde_json
    assert f"locked to `{serde_json.group(1)}`" in ledger
    assert re.search(r"\d+ headless tests", ledger) is None
    assert re.search(r"ESLint; \d+ tests", ledger) is None


def test_contract_ledger_matches_docs_and_dom_tooling() -> None:
    requirements = (ROOT / "docs/requirements.txt").read_text(encoding="utf-8")
    ledger = (ROOT / "docs/maintenance/2026-07-01-contract-ledger.md").read_text(encoding="utf-8")
    for package, label in (("mkdocs-material", "MkDocs Material"), ("ruff", "Ruff")):
        version = re.search(rf"^{re.escape(package)}==([^ ]+)", requirements, re.MULTILINE)
        assert version
        assert f"{label} is `{version.group(1)}`" in ledger

    typescript_package = (ROOT / "langs/typescript/package.json").read_text(encoding="utf-8")
    react_package = (ROOT / "examples/typescript/react/notes-showcase/package.json").read_text(
        encoding="utf-8"
    )
    assert '"jsdom": "^29.1.1"' in typescript_package
    assert '"jsdom": "^29.1.1"' in react_package
    assert "jsdom `29.1.1`" in ledger
