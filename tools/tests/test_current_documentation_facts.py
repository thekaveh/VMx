"""Keep current-facing repository inventories derived from their sources."""

from __future__ import annotations

import json
import re
import subprocess
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
    assert f"(0001..{last})" in readme
    assert f"(0001-{last})" in spec_readme


def test_current_lifecycle_docs_match_the_normative_catalog_range() -> None:
    catalog = (ROOT / "spec/12-conformance.md").read_text(encoding="utf-8")
    highest = max(int(value) for value in re.findall(r"^### LIFE-(\d{3})\b", catalog, re.MULTILINE))
    expected = f"LIFE-001..{highest:03d}"
    paths = (
        *(ROOT / "docs/content/getting-started").glob("*.md"),
        ROOT / "langs/swift/README.md",
        ROOT / "langs/csharp/tests/VMx.Conformance.Tests/LifecycleConformanceTests.cs",
        ROOT / "langs/python/tests/conformance/test_lifecycle.py",
        ROOT / "langs/swift/Tests/VMxTests/LifecycleTests.swift",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if "LIFE-001" in text:
            assert expected in text, path


def test_root_readme_preserves_complete_3_22_source_ranges() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    en = "\N{EN DASH}"

    assert (
        f"| 3.22.x | 3.22.0{en}3.22.1 | 3.22.0{en}3.22.1 | 3.23.0{en}3.23.1 "
        f"| 3.22.0{en}3.23.0  | 0.25.0{en}0.26.0 |"
    ) in readme


def test_rust_threading_claim_has_paired_dispatch_and_real_thr_002() -> None:
    spec = (ROOT / "spec/11-threading.md").read_text(encoding="utf-8")
    runtime = (ROOT / "langs/rust/src/runtime.rs").read_text(encoding="utf-8")
    component = (ROOT / "langs/rust/src/components.rs").read_text(encoding="utf-8")
    tests = (ROOT / "langs/rust/tests/conformance/threading.rs").read_text(encoding="utf-8")
    crate_readme = (ROOT / "langs/rust/README.md").read_text(encoding="utf-8")

    assert "| Rust" in spec and "DefaultDispatcher" in spec
    assert "fn dispatch_background" in runtime
    assert "pub struct DefaultDispatcher" in runtime
    assert "pub fn background" in component
    assert ".background(true)" in tests
    assert "drain_background" in tests
    assert "DefaultDispatcher" in crate_readme
    assert ".background(true)" in crate_readme
    assert "background_errors()" in crate_readme
    assert "reconstruct remains a synchronous atomic" in crate_readme
    assert "rejected background or foreground scheduling" in crate_readme
    assert "on_construct" in component and "on_destruct" in component
    assert "any VM" not in (ROOT / "spec/10-builders.md").read_text(encoding="utf-8")


def test_adr_metadata_links_resolve() -> None:
    adr_dir = ROOT / "spec/ADRs"
    for adr in adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"):
        text = adr.read_text(encoding="utf-8")
        metadata = "\n".join(
            line
            for line in text.splitlines()
            if line.startswith(("**Extends:**", "**Related:**", "**Supersedes:**"))
        )
        for target in re.findall(r"\[[^\]]+\]\(([^)#]+\.md)\)", metadata):
            assert (adr.parent / target).is_file(), f"{adr}: missing {target}"


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


def test_contract_ledger_matches_python_reactivex_locks() -> None:
    ledger = (ROOT / "docs/maintenance/2026-07-01-contract-ledger.md").read_text(encoding="utf-8")
    lock_paths = (
        ROOT / "langs/python/uv.lock",
        ROOT / "examples/python/uv.lock",
        ROOT / "examples/python/textual/inspector/uv.lock",
        ROOT / "examples/python/textual/notes_showcase/uv.lock",
    )
    versions = set()
    for path in lock_paths:
        lock = path.read_text(encoding="utf-8")
        match = re.search(r'\[\[package\]\]\nname = "reactivex"\nversion = "([^"]+)"', lock)
        assert match, f"{path}: missing reactivex package"
        versions.add(match.group(1))

    assert versions == {"5.1.0"}
    assert "committed locks resolve stable `5.1.0`" in ledger


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
    assert "TypeScript is `6.0.3`" in ledger
    assert "TypeScript 7 remains outside that public contract" in ledger
    assert "jsdom `30.0.0` drops Node 20" in ledger
    for engine_range in ("^22.22.2", "^24.15.0", ">=26.0.0"):
        assert engine_range in ledger
    assert "`webidl.util.markAsUncloneable`" in ledger
    assert (
        "Python branch CI builds, validates, and fresh-installs both the wheel and sdist." in ledger
    )
    assert "npm `11.18.0`" in ledger
    assert "npm `11.5.1`" not in ledger


def test_release_runbooks_match_pinned_tooling_and_manifest_versions() -> None:
    typescript = (ROOT / "langs/typescript/RELEASING.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "npm 11.18.0" in typescript
    assert "npm@11.18.0" in workflow

    csharp = (ROOT / "langs/csharp/RELEASING.md").read_text(encoding="utf-8")
    assert "core_version=$(awk" in csharp
    assert 'core_tag="csharp-v${core_version}"' in csharp
    assert "csharp-v3.22.0" not in csharp
    assert "VMx >= 3.20.0" not in csharp

    snippet = re.search(
        r"Read the release candidates.*?```bash\n(.*?)\n```",
        csharp,
        re.DOTALL,
    )
    assert snippet
    result = subprocess.run(
        [
            "bash",
            "-c",
            snippet.group(1) + '\nprintf "%s\\n%s\\n%s\\n" "$core_version" '
            '"$notifications_version" "$di_version"\n',
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    expected = [
        re.search(r"<Version>([^<]+)</Version>", path.read_text(encoding="utf-8")).group(1)
        for path in (
            ROOT / "langs/csharp/src/VMx/VMx.csproj",
            ROOT / "langs/csharp/src/VMx.Notifications/VMx.Notifications.csproj",
            ROOT
            / "langs/csharp/src/VMx.Extensions.DependencyInjection"
            / "VMx.Extensions.DependencyInjection.csproj",
        )
    ]
    assert result.stdout.splitlines() == expected


def test_current_docs_match_library_conformance_catalog() -> None:
    catalog = (ROOT / "spec/12-conformance.md").read_text(encoding="utf-8")
    library_count = len(set(re.findall(r"^### (?!THEME-)[A-Z]+-[0-9]{3}\b", catalog, re.MULTILINE)))
    assert library_count

    overview = (ROOT / "spec/00-overview.md").read_text(encoding="utf-8")
    rust_parity = (ROOT / "docs/maintenance/2026-07-16-rust-capability-parity.md").read_text(
        encoding="utf-8"
    )
    assert f"{library_count} library IDs" in overview
    assert f"all {library_count} library IDs" in rust_parity


def test_current_rust_docs_match_cargo_package_version() -> None:
    cargo = (ROOT / "langs/rust/Cargo.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"$', cargo, re.MULTILINE)
    assert version

    for path in (
        ROOT / "README.md",
        ROOT / "langs/rust/README.md",
        ROOT / "docs/content/getting-started/rust.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert f"v{version.group(1)}" in text
        assert "v0.25.1" not in text


def test_swift_conformance_ledger_counts_each_library_id_once() -> None:
    ledger = (ROOT / "compatibility-matrix.md").read_text(encoding="utf-8")
    start = ledger.index("+50 leaf-area")
    end = ledger.index("DISC-009", start)
    increments = [int(value) for value in re.findall(r"\+(\d+)", ledger[start:end])]
    assert 44 + sum(increments) == 403
    assert ledger[start:end].count("COMP-038..041") == 1


def test_swift_readme_summarizes_current_conformance_without_history_ledger() -> None:
    catalog = (ROOT / "spec/12-conformance.md").read_text(encoding="utf-8")
    library_count = len(set(re.findall(r"^### (?!THEME-)[A-Z]+-[0-9]{3}\b", catalog, re.MULTILINE)))
    theme_count = len(set(re.findall(r"^### THEME-[0-9]{3}\b", catalog, re.MULTILINE)))
    readme = (ROOT / "langs/swift/README.md").read_text(encoding="utf-8")
    status = readme.split("## 1. Status", maxsplit=1)[1].split("## 2. Install", maxsplit=1)[0]

    assert f"all **{library_count} of {library_count}** library conformance IDs" in status
    assert f"**{library_count + theme_count} total**" in status
    assert "+50 leaf-area" not in status


def test_python_release_guidance_is_stable_semver_only() -> None:
    runbook = (ROOT / "langs/python/RELEASING.md").read_text(encoding="utf-8")

    assert "Stable SemVer releases only" in runbook
    assert "PEP 440 segments are supported" not in runbook
    assert "A 404 there is visible to every consumer" in runbook
    assert "A 405 there is visible to every consumer" not in runbook


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
    assert "no handle object is returned or needed" not in catalogue
    assert "batchUpdate(): BatchUpdateHandle" in catalogue


def test_rust_parity_ledger_does_not_reopen_resolved_surface_work() -> None:
    ledger = (ROOT / "docs/maintenance/2026-07-16-rust-capability-parity.md").read_text(
        encoding="utf-8"
    )

    assert "four of the five built-in commands" not in ledger
    assert "does not implement the\n`Expandable` / `Collapsible`" not in ledger
    assert "full forwarding-component delegation" in ledger


def test_current_guidance_does_not_reference_superseded_task_briefs_or_scraper_behavior() -> None:
    swift_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "langs/swift").rglob("*.swift"))
    )
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert re.search(r"Task[- ]?[0-9]+", swift_sources, re.IGNORECASE) is None
    assert "a commented-out stub also matches" not in agents


def test_current_forwarding_docs_cover_nested_rust_override_surface() -> None:
    rust_source = (ROOT / "langs/rust/src/forwarding.rs").read_text(encoding="utf-8")
    canonical = (
        ROOT / "docs/content/primitives/viewmodel-families/forwarding-wrapper-family.md"
    ).read_text(encoding="utf-8")

    assert "ADR-0028" not in rust_source.split("use super::", maxsplit=1)[0]
    for member in (
        "ForwardingComponentVm::new",
        "ForwardingComponentVm::wrap",
        "with_hint_override",
    ):
        assert member in canonical
