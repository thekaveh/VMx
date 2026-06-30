"""Unit tests for tools/check-conformance-coverage.py.

The script is imported under the module name `check_conformance_coverage` (the
hyphen in the filename would prevent direct import; conftest.py pre-loads it
under the underscore alias via importlib so plain imports work in tests).
"""

import textwrap
from pathlib import Path

import check_conformance_coverage as ccc


def test_parse_catalog_extracts_ids(tmp_path: Path) -> None:
    catalog = tmp_path / "12-conformance.md"
    catalog.write_text(
        textwrap.dedent(
            """\
            # 12 — Conformance test catalog

            ## Lifecycle (`LIFE-NNN`)

            ### LIFE-001 — construct transitions through Constructing
            ...

            ### LIFE-002 — destruct transitions through Destructing
            ...

            ## Commands (`CMD-NNN`)

            ### CMD-001 — execute invokes task
            ...
            """
        ),
        encoding="utf-8",
    )

    ids = ccc.parse_catalog_ids(catalog)

    assert ids == {"LIFE-001", "LIFE-002", "CMD-001"}


def test_parse_catalog_ignores_prefix_table(tmp_path: Path) -> None:
    """The 'Identifier prefixes' table mentions LIFE-NNN as a literal label,
    not as a test ID. Make sure the parser does not pick those up."""
    catalog = tmp_path / "12-conformance.md"
    catalog.write_text(
        textwrap.dedent(
            """\
            ## Identifier prefixes

            | Prefix | Area |
            |---|---|
            | LIFE-NNN | Lifecycle |
            | CMD-NNN | Commands |

            ### LIFE-001 — first real test
            """
        ),
        encoding="utf-8",
    )

    ids = ccc.parse_catalog_ids(catalog)

    assert ids == {"LIFE-001"}


def test_scrape_python_tests_finds_marks(tmp_path: Path) -> None:
    test_file = tmp_path / "test_lifecycle.py"
    test_file.write_text(
        textwrap.dedent(
            """\
            import pytest

            @pytest.mark.conformance("LIFE-001")
            def test_construct_transitions():
                pass

            @pytest.mark.conformance("LIFE-002")
            async def test_destruct_transitions():
                pass

            @pytest.mark.conformance(
                "LIFE-003"
            )
            def test_multiline_decorator():
                pass

            @pytest.mark.conformance("LIFE-004", reason="documented gap")
            def test_with_kwargs():
                pass

            @pytest.mark.conformance(  "LIFE-005"  )
            def test_extra_whitespace():
                pass

            def test_unrelated_helper():
                pass
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_python_conformance_ids(tmp_path)

    assert found == {"LIFE-001", "LIFE-002", "LIFE-003", "LIFE-004", "LIFE-005"}


def test_scrape_csharp_tests_finds_traits(tmp_path: Path) -> None:
    test_file = tmp_path / "LifecycleTests.cs"
    test_file.write_text(
        textwrap.dedent(
            """\
            using Xunit;

            public class LifecycleTests
            {
                [Fact, Trait("Conformance", "LIFE-001")]
                public void Construct_Transitions() { }

                [Fact]
                [Trait("Conformance", "LIFE-002")]
                public void Destruct_Transitions() { }

                [Fact, Trait("Conformance", "LIFE-003")]
                [Trait("Category", "Fast")]
                public void Combined_With_Other_Traits() { }

                public void UnrelatedHelper() { }

                // This must NOT match — Trait outside brackets is not an attribute
                public Trait fake = new Trait("Conformance", "LIFE-999");
            }
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_csharp_conformance_ids(tmp_path)

    assert "LIFE-001" in found
    assert "LIFE-002" in found
    assert "LIFE-003" in found
    assert "LIFE-999" not in found


def test_scrape_typescript_tests_finds_describe_ids(tmp_path: Path) -> None:
    test_file = tmp_path / "lifecycle.test.ts"
    test_file.write_text(
        textwrap.dedent(
            """\
            import { describe, it, expect } from "vitest";

            describe("LIFE-001", () => {
              it("construct transitions", () => {});
            });

            describe("LIFE-002", () => {
              it("destruct transitions", () => {});
            });

            // Not a conformance ID — should be ignored
            describe("some helper", () => {});
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_typescript_conformance_ids(tmp_path)

    assert found == {"LIFE-001", "LIFE-002"}


def test_report_gaps_empty_when_complete() -> None:
    catalog = {"LIFE-001", "LIFE-002"}
    language_coverage = {"python": {"LIFE-001", "LIFE-002"}}

    gaps = ccc.compute_gaps(catalog, language_coverage)

    assert gaps == {}


def test_report_gaps_lists_missing_ids_per_language() -> None:
    catalog = {"LIFE-001", "LIFE-002", "CMD-001"}
    language_coverage = {
        "python": {"LIFE-001"},
        "csharp": {"LIFE-001", "LIFE-002", "CMD-001"},
    }

    gaps = ccc.compute_gaps(catalog, language_coverage)

    assert gaps == {"python": {"LIFE-002", "CMD-001"}}


# ─── dormant subset plumbing (retained per ADR-0065 as an extension point) ─────
# No flavor currently sets a manifest, so these unit tests give the subset
# branch of compute_gaps + load_subset_manifest direct regression coverage.


def test_load_subset_manifest_parses_ids(tmp_path: Path) -> None:
    manifest = tmp_path / "subset.txt"
    manifest.write_text(
        "# a comment\nLIFE-001\n\n  LIFE-002  \n# another\nCMD-001\n",
        encoding="utf-8",
    )

    assert ccc.load_subset_manifest(manifest) == {"LIFE-001", "LIFE-002", "CMD-001"}


def test_compute_gaps_subset_branch_passes_on_exact_match() -> None:
    catalog = {"LIFE-001", "LIFE-002"}
    coverage = {"demo": {"LIFE-001", "LIFE-002"}}
    subsets = {"demo": {"LIFE-001", "LIFE-002"}}

    assert ccc.compute_gaps(catalog, coverage, subsets) == {}


def test_compute_gaps_subset_branch_flags_bogus_unlisted_untested() -> None:
    catalog = {"LIFE-001", "LIFE-002", "CMD-001"}
    # found has: LIFE-001 (listed, ok), CMD-001 (in catalog but NOT in manifest →
    # unlisted), TYPO-999 (not in catalog → bogus). Manifest also lists LIFE-002
    # which has no marker → untested.
    coverage = {"demo": {"LIFE-001", "CMD-001", "TYPO-999"}}
    subsets = {"demo": {"LIFE-001", "LIFE-002"}}

    gaps = ccc.compute_gaps(catalog, coverage, subsets)

    assert gaps == {"demo": {"TYPO-999", "CMD-001", "LIFE-002"}}


def test_main_returns_zero_when_active_dirs_are_empty_and_no_require(
    tmp_path: Path,
) -> None:
    """Empty conformance directories report 0/N covered but do not fail.
    The strict check is opt-in via the --require flag (covered separately)."""
    catalog = tmp_path / "spec" / "12-conformance.md"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("### LIFE-001 — sample\n", encoding="utf-8")

    (tmp_path / "langs" / "python" / "tests" / "conformance").mkdir(parents=True)
    (tmp_path / "langs" / "csharp" / "tests" / "VMx.Conformance.Tests").mkdir(parents=True)

    rc = ccc.main(["--repo-root", str(tmp_path)])

    assert rc == 0


def test_main_returns_nonzero_when_required_lang_has_gaps(tmp_path: Path) -> None:
    catalog = tmp_path / "spec" / "12-conformance.md"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("### LIFE-001 — sample\n### LIFE-002 — sample\n", encoding="utf-8")

    py_dir = tmp_path / "langs" / "python" / "tests" / "conformance"
    py_dir.mkdir(parents=True)
    (py_dir / "test_x.py").write_text(
        '@pytest.mark.conformance("LIFE-001")\ndef test_one(): pass\n',
        encoding="utf-8",
    )

    rc = ccc.main(["--repo-root", str(tmp_path), "--require", "python"])

    assert rc == 1


def test_main_returns_2_when_required_lang_has_no_directory(tmp_path: Path) -> None:
    """A required language whose tests/conformance directory is missing must fail
    with rc=2; reporting it as 'no coverage' silently would be a gate hole."""
    catalog = tmp_path / "spec" / "12-conformance.md"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("### LIFE-001 — sample\n", encoding="utf-8")

    # Note: do NOT create langs/csharp/tests/VMx.Conformance.Tests/
    rc = ccc.main(["--repo-root", str(tmp_path), "--require", "csharp"])

    assert rc == 2


def test_render_report_no_coverage_dirs() -> None:
    report = ccc.render_report({"LIFE-001"}, {}, {})
    assert "No language conformance directories found." in report


def test_render_report_shows_missing_ids() -> None:
    report = ccc.render_report(
        {"LIFE-001", "LIFE-002"},
        {"python": {"LIFE-001"}},
        {"python": {"LIFE-002"}},
    )
    assert "MISSING (1): LIFE-002" in report


def test_render_report_full_coverage_has_no_missing_line() -> None:
    report = ccc.render_report({"LIFE-001"}, {"python": {"LIFE-001"}}, {})
    assert "MISSING" not in report
    assert "1/1 covered" in report


def test_main_returns_2_when_catalog_missing(tmp_path: Path) -> None:
    """If spec/12-conformance.md is absent, the tool exits with rc=2 and a
    clear error message rather than silently reporting 0 IDs."""
    rc = ccc.main(["--repo-root", str(tmp_path)])
    assert rc == 2


def test_render_report_flags_orphan_ids() -> None:
    """Orphan IDs are detected entirely inside render_report — no compute_gaps involvement."""
    catalog = {"LIFE-001"}
    coverage = {"python": {"LIFE-001", "LIFE-999"}}  # LIFE-999 is in tests but not catalog
    report = ccc.render_report(catalog, coverage, gaps={})
    assert "ORPHAN (1): LIFE-999" in report
    assert "1/1 covered" in report


# ─── VMX-029: comment-filtering hardening ─────────────────────────────────────


def test_scrape_python_ignores_commented_out_marker(tmp_path: Path) -> None:
    """A Python marker preceded by # on the same line must not count as coverage (VMX-029)."""
    test_file = tmp_path / "test_lifecycle.py"
    test_file.write_text(
        textwrap.dedent(
            """\
            import pytest

            # @pytest.mark.conformance("XXX-001")
            # def test_placeholder(): pass

            @pytest.mark.conformance("XXX-002")
            def test_real(): pass
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_python_conformance_ids(tmp_path)

    assert "XXX-001" not in found, "commented-out Python marker must be ignored"
    assert "XXX-002" in found, "genuine Python marker must still be counted"


def test_scrape_typescript_ignores_line_commented_marker(tmp_path: Path) -> None:
    """A TS describe() preceded by // on the same line must not count as coverage (VMX-029)."""
    test_file = tmp_path / "lifecycle.test.ts"
    test_file.write_text(
        textwrap.dedent(
            """\
            import { describe, it } from "vitest";

            // describe("XXX-001", () => { it("placeholder", () => {}); });

            describe("XXX-002", () => {
              it("real", () => {});
            });
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_typescript_conformance_ids(tmp_path)

    assert "XXX-001" not in found, "line-commented TS describe must be ignored"
    assert "XXX-002" in found, "genuine TS describe must still be counted"


def test_scrape_csharp_ignores_block_commented_marker(tmp_path: Path) -> None:
    """A C# Trait inside /* ... */ must not count as coverage (VMX-029)."""
    test_file = tmp_path / "LifecycleTests.cs"
    test_file.write_text(
        textwrap.dedent(
            """\
            using Xunit;

            public class LifecycleTests
            {
                /*
                [Fact, Trait("Conformance", "XXX-001")]
                public void Placeholder() { }
                */

                [Fact, Trait("Conformance", "XXX-002")]
                public void RealTest() { }
            }
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_csharp_conformance_ids(tmp_path)

    assert "XXX-001" not in found, "block-commented C# trait must be ignored"
    assert "XXX-002" in found, "genuine C# trait must still be counted"


def test_scrape_csharp_ignores_line_commented_marker(tmp_path: Path) -> None:
    """A C# Trait on a line starting with // must not count as coverage (VMX-029)."""
    test_file = tmp_path / "LifecycleTests.cs"
    test_file.write_text(
        textwrap.dedent(
            """\
            using Xunit;

            public class LifecycleTests
            {
                // [Fact, Trait("Conformance", "XXX-001")]
                // public void Placeholder() { }

                [Fact, Trait("Conformance", "XXX-002")]
                public void RealTest() { }
            }
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_csharp_conformance_ids(tmp_path)

    assert "XXX-001" not in found, "line-commented C# trait must be ignored"
    assert "XXX-002" in found, "genuine C# trait must still be counted"


# ─── Swift conformance scraper (full-catalog parity) ──────────────────────────
#
# Swift reached full library parity in Phase 3 Inc 6; the subset manifest was
# retired in Inc 7 (VMX-031's two-way subset match → full-catalog enforcement,
# identical to csharp/python/typescript). Swift now passes only when every
# catalog ID has a `/// XXX-NNN —` marker.

# Minimal catalog for the Swift scraper tests.
_SWIFT_CATALOG_TEXT = "### LIFE-001 — sample\n### LIFE-002 — sample\n"

# A Swift test file whose markers cover the full catalog above.
_SWIFT_GOOD_TEST = (
    "/// LIFE-001 — construct transitions\n"
    "func testLife001() {}\n"
    "/// LIFE-002 — destruct transitions\n"
    "func testLife002() {}\n"
)


def _make_swift_fixture(
    tmp_path: Path,
    catalog_text: str,
    test_content: str,
) -> None:
    """Helper: write catalog + swift test into tmp_path (no manifest — Swift is
    enforced against the full catalog like the other flavors)."""
    catalog = tmp_path / "spec" / "12-conformance.md"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(catalog_text, encoding="utf-8")

    swift_dir = tmp_path / "langs" / "swift" / "Tests" / "VMxTests"
    swift_dir.mkdir(parents=True)
    (swift_dir / "LifecycleTests.swift").write_text(test_content, encoding="utf-8")


def test_swift_full_catalog_coverage_passes(tmp_path: Path) -> None:
    """Swift markers covering every catalog ID pass (full-parity, no manifest)."""
    _make_swift_fixture(tmp_path, _SWIFT_CATALOG_TEXT, _SWIFT_GOOD_TEST)

    rc = ccc.main(["--repo-root", str(tmp_path), "--require", "swift"])

    assert rc == 0


def test_swift_ignores_vmx_finding_reference(tmp_path: Path) -> None:
    """A `/// VMX-002 — ...` audit finding-id reference must NOT be scraped as a
    conformance marker (it is not a catalog id and would otherwise read as a
    spurious ORPHAN)."""
    test_with_finding_ref = (
        "/// VMX-002 regression — background construct vs dispose race\n"
        "func testVmx002Regression() {}\n"
        "/// LIFE-001 — construct transitions\n"
        "func testLife001() {}\n"
        "/// LIFE-002 — destruct transitions\n"
        "func testLife002() {}\n"
    )
    _make_swift_fixture(tmp_path, _SWIFT_CATALOG_TEXT, test_with_finding_ref)

    rc = ccc.main(["--repo-root", str(tmp_path), "--require", "swift"])

    assert rc == 0, "VMX-NNN finding references must be ignored, not scraped"


def test_swift_missing_catalog_id_fails(tmp_path: Path) -> None:
    """A catalog ID with no Swift test marker must fail under full-catalog
    enforcement (the same MISSING gate as csharp/python/typescript)."""
    test_only_life001 = "/// LIFE-001 — construct transitions\nfunc testLife001() {}\n"
    _make_swift_fixture(tmp_path, _SWIFT_CATALOG_TEXT, test_only_life001)

    rc = ccc.main(["--repo-root", str(tmp_path), "--require", "swift"])

    assert rc == 1


def test_swift_orphan_id_is_informational(tmp_path: Path) -> None:
    """A Swift marker not in the catalog is an informational ORPHAN, NOT a hard
    failure — matching the full-parity flavors (compute_gaps only flags
    ``catalog - found``). Full catalog coverage + an extra marker still passes."""
    test_with_orphan = (
        "/// LIFE-001 — construct transitions\n"
        "func testLife001() {}\n"
        "/// LIFE-002 — destruct transitions\n"
        "func testLife002() {}\n"
        "/// FUTURE-999 — an id not yet in this catalog\n"
        "func testFuture999() {}\n"
    )
    _make_swift_fixture(tmp_path, _SWIFT_CATALOG_TEXT, test_with_orphan)

    rc = ccc.main(["--repo-root", str(tmp_path), "--require", "swift"])

    assert rc == 0, "orphan markers are informational for full-parity flavors"
