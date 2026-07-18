"""Keep current-facing repository inventories derived from their sources."""

from __future__ import annotations

import json
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


def test_showcase_docs_match_current_react_and_swift_sources() -> None:
    package = json.loads(
        (ROOT / "examples/typescript/react/notes-showcase/package.json").read_text(encoding="utf-8")
    )
    react_major = package["dependencies"]["react"].lstrip("^").split(".", maxsplit=1)[0]
    parity = (ROOT / "examples/notes-showcase-parity.md").read_text(encoding="utf-8")
    assert f"React {react_major} + Vite" in parity

    swift_root = ROOT / "examples/swift/notes-showcase"
    swift_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(swift_root.rglob("*.swift"))
    )
    assert re.search(r"task-[0-9]+-brief\.md", swift_sources, re.IGNORECASE) is None
    assert "BindableDerived sidecars are not implemented in Swift yet" not in swift_sources


def test_python_release_notes_recovery_respects_immutable_tag_contents() -> None:
    runbook = (ROOT / "langs/python/RELEASING.md").read_text(encoding="utf-8")

    assert "re-run that job alone from the Actions UI after fixing the CHANGELOG" not in runbook
    assert re.search(r"immutable\s+tag commit", runbook)


def test_cross_flavor_catalogue_contains_only_current_numbered_entries() -> None:
    catalogue = (ROOT / "spec/ADRs/0009-cross-flavor-divergence-catalogue.md").read_text(
        encoding="utf-8"
    )

    assert re.search(r"^### (?!\d+\.\d+\s)", catalogue, re.MULTILINE) is None
    assert "legacy alias still ships in v2.0.0" not in catalogue
    assert "does **not** conform `CompositeVM` or `GroupVM` to `Sequence`" not in catalogue
    assert "model-set-after-dispose is\n  **unspecified**" not in catalogue


def test_rust_parity_ledger_does_not_reopen_resolved_surface_work() -> None:
    ledger = (ROOT / "docs/maintenance/2026-07-16-rust-capability-parity.md").read_text(
        encoding="utf-8"
    )

    assert "four of the five built-in commands" not in ledger
    assert "does not implement the\n`Expandable` / `Collapsible`" not in ledger
    assert "full forwarding-component delegation" in ledger
