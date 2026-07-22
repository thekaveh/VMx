from __future__ import annotations

import re
import textwrap
from pathlib import Path

from scripts.docs import build_docs
from scripts.docs.check_docs import (
    _check_descendant_heading_numbers,
    check,
    check_canonical_links,
    check_generated_wiki_links,
    check_historical_audits,
    check_professional_markdown,
    check_raw_html_headings,
    check_self_containment,
)
from scripts.docs.links import find_links, is_forbidden
from scripts.docs.manifest import load_manifest
from scripts.docs.transforms import build_source_map, rewrite_for_surface

ROOT = Path(__file__).resolve().parents[2]


def test_descendant_heading_numbers_require_hierarchy_and_sequence() -> None:
    valid = """# 5.2. Page

## 5.2.1. First

### 5.2.1.1. Detail

## 5.2.2. Second
"""
    assert _check_descendant_heading_numbers(valid, "5.2", Path("page.md")) == []

    invalid = """# 5.2. Page

## 5.2.2. Skipped first section

#### 5.2.2.1.1. Missing H3 parent
"""
    findings = _check_descendant_heading_numbers(invalid, "5.2", Path("page.md"))
    assert any("expected heading number '5.2.1.'" in item.message for item in findings)
    assert any("skips its H3 parent" in item.message for item in findings)


def test_descendant_heading_numbers_ignore_fenced_code() -> None:
    markdown = """# 3.1. Page

## 3.1.1. Real

```markdown
## Not a real heading
```
"""
    assert _check_descendant_heading_numbers(markdown, "3.1", Path("page.md")) == []


def test_manifest_loads_all_canonical_pages() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    sources = {section.source for section in manifest.pages()}
    content = {path.relative_to(ROOT) for path in (ROOT / "docs/content").rglob("*.md")}
    assert content <= sources


def test_source_maps_preserve_site_paths_and_flatten_wiki() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    site_map = build_source_map(manifest, "site")
    wiki_map = build_source_map(manifest, "wiki")

    assert site_map[Path("docs/content/index.md")] == Path("index.md")
    assert site_map[Path("docs/content/architecture/system-architecture.md")] == Path(
        "architecture/system-architecture.md"
    )
    assert wiki_map[Path("docs/content/index.md")] == Path("Home.md")
    assert wiki_map[Path("docs/content/architecture/system-architecture.md")].name.endswith(
        "System-Architecture.md"
    )


def test_forbidden_link_matrix_keeps_surfaces_self_contained() -> None:
    assert is_forbidden("https://github.com/thekaveh/VMx/blob/main/README.md", "site")
    assert is_forbidden("https://thekaveh.github.io/VMx/quickstart/", "wiki")
    assert is_forbidden("https://github.com/thekaveh/VMx/wiki", "repo")
    assert not is_forbidden("https://example.com/VMx", "site")


def test_repo_self_containment_scans_current_facing_markdown(tmp_path: Path) -> None:
    example = tmp_path / "examples/example.md"
    example.parent.mkdir(parents=True)
    example.write_text(
        "[Published copy](https://thekaveh.github.io/VMx/examples/example/).\n",
        encoding="utf-8",
    )

    findings = check_self_containment(tmp_path)

    assert len(findings) == 1
    assert "examples/example.md" in findings[0].message


def test_canonical_link_check_rejects_missing_markdown_and_html_targets(tmp_path: Path) -> None:
    page = tmp_path / "docs/content/index.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        '[Missing](quickstart.md)\n<a href="missing/">Missing route</a>\n'
        '```python\nvalue = Model[str]("cancel")\n```\n',
        encoding="utf-8",
    )

    findings = check_canonical_links(tmp_path)

    assert len(findings) == 2
    assert all("target does not exist" in finding.message for finding in findings)


def test_canonical_link_check_rejects_missing_heading_fragment(tmp_path: Path) -> None:
    content = tmp_path / "docs/content"
    content.mkdir(parents=True)
    (content / "index.md").write_text(
        "[Precise section](target.md#missing-section)\n", encoding="utf-8"
    )
    (content / "target.md").write_text("# Target\n\n## 1. Existing Section\n", encoding="utf-8")

    findings = check_canonical_links(tmp_path)

    assert len(findings) == 1
    assert "heading fragment does not exist" in findings[0].message


def test_surface_rewrite_preserves_cross_page_and_local_fragments() -> None:
    source_map = {
        Path("docs/content/source.md"): Path("guide/source.md"),
        Path("docs/maintenance/ledger.md"): Path("maintenance/ledger.md"),
    }
    markdown = "[Ledger](../maintenance/ledger.md#precise-section) [Local](#local-section)"

    site = rewrite_for_surface(
        markdown,
        surface="site",
        current_source=Path("docs/content/source.md"),
        current_output=Path("guide/source.md"),
        source_map=source_map,
        repo_root=ROOT,
    )
    wiki = rewrite_for_surface(
        markdown,
        surface="wiki",
        current_source=Path("docs/content/source.md"),
        current_output=Path("Source.md"),
        source_map=source_map,
        repo_root=ROOT,
    )

    assert site == ("[Ledger](../maintenance/ledger.md#precise-section) [Local](#local-section)")
    assert wiki == "[[Ledger|ledger#precise-section]] [Local](#local-section)"


def test_generated_wiki_link_check_rejects_malformed_and_missing_targets(
    tmp_path: Path,
) -> None:
    wiki = tmp_path / "generated/wiki"
    wiki.mkdir(parents=True)
    (wiki / "Home.md").write_text(
        "[[Good|Existing]]\n[[Missing|Absent]]\n[Broken|Existing]]\n",
        encoding="utf-8",
    )
    (wiki / "Existing.md").write_text("# Existing\n", encoding="utf-8")

    findings = check_generated_wiki_links(tmp_path)

    assert len(findings) == 2
    assert any("malformed wiki link" in finding.message for finding in findings)
    assert any("wiki target does not exist: Absent" in finding.message for finding in findings)


def test_canonical_docs_reject_raw_html_heading_elements(tmp_path: Path) -> None:
    page = tmp_path / "docs/content/index.md"
    page.parent.mkdir(parents=True)
    page.write_text("# 1. Page\n\n<h3>Skipped heading</h3>\n", encoding="utf-8")

    findings = check_raw_html_headings(tmp_path)

    assert len(findings) == 1
    assert "raw HTML heading" in findings[0].message


def test_repo_surface_markdown_rejects_decorative_status_icons(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Supported: ✓\n", encoding="utf-8")

    findings = check_professional_markdown(tmp_path)

    assert len(findings) == 1
    assert "decorative status icon" in findings[0].message


def test_historical_audits_require_notice_and_index_entry(tmp_path: Path) -> None:
    audit = tmp_path / "docs/audit"
    audit.mkdir(parents=True)
    (audit / "README.md").write_text("# Audit archive\n", encoding="utf-8")
    (audit / "old-report.md").write_text("# Old report\n", encoding="utf-8")

    findings = check_historical_audits(tmp_path)

    assert len(findings) == 2
    assert any("historical audit notice is missing" in item.message for item in findings)
    assert any("not listed" in item.message for item in findings)


def test_wiki_rewrite_maps_relative_html_routes_to_manifest_pages() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "wiki")

    rewritten = rewrite_for_surface(
        '<a href="getting-started/">Quickstart</a>',
        surface="wiki",
        current_source=Path("docs/content/index.md"),
        current_output=Path("Home.md"),
        source_map=source_map,
    )

    assert 'href="3-1-Quickstart"' in rewritten


def test_markdown_link_scanner_does_not_cross_line_boundaries() -> None:
    markdown = "The interval is [0, count)\n\n[Composite](composite.md)\n"

    assert find_links(markdown) == [
        find_links("[Composite](composite.md)")[0],
    ]


def test_wiki_rewrite_preserves_link_after_unmatched_bracket() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "wiki")
    rewritten = rewrite_for_surface(
        "The interval is [0, count)\n\n"
        "[Composite Family](viewmodel-families/composite-family.md)\n",
        surface="wiki",
        current_source=Path("docs/content/primitives/builders-collections-tree-utilities.md"),
        current_output=Path("6-7-Builders-Collections-Tree-Utilities.md"),
        source_map=source_map,
    )

    assert "The interval is [0, count)" in rewritten
    assert "[[Composite Family|6-2-5-Composite-Family]]" in rewritten


def test_build_generates_self_contained_surfaces() -> None:
    build_docs.build(site=True, wiki=True, check=True, repo_root=ROOT)

    site_page = ROOT / "generated/site/flavors/csharp.md"
    wiki_page = ROOT / "generated/wiki/7-2-C.md"
    assert site_page.exists()
    assert wiki_page.exists()
    assert "github.com/thekaveh/VMx/blob/main" not in site_page.read_text(encoding="utf-8")
    assert "thekaveh.github.io/VMx" not in wiki_page.read_text(encoding="utf-8")
    assert (ROOT / "mkdocs.yml").read_text(encoding="utf-8").find("repo_url") == -1
    assert "generator: false" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    state_site = (ROOT / "generated/site/primitives/state-reactive-helpers.md").read_text(
        encoding="utf-8"
    )
    state_wiki = (ROOT / "generated/wiki/6-5-State-Reactive-Helpers.md").read_text(encoding="utf-8")
    form_site = (
        ROOT / "generated/site/primitives/viewmodel-families/specialized/form-vm.md"
    ).read_text(encoding="utf-8")
    releases_site = (ROOT / "generated/site/contributing-releases.md").read_text(encoding="utf-8")
    assert "#1236-expandablestate-is-missing-members" in state_site
    assert "#1236-expandablestate-is-missing-members" in state_wiki
    assert "#1244-formvm-direct-approve-gates-on-strictdirty" in form_site
    assert "CONTRIBUTING.md#" not in releases_site


def test_build_repo_root_is_fully_isolated(tmp_path: Path, monkeypatch) -> None:
    selected = tmp_path / "selected"
    other = tmp_path / "other"
    for root, marker, version in ((selected, "SELECTED", "9.9.9"), (other, "OTHER", "1.0.0")):
        (root / "docs/content").mkdir(parents=True)
        (root / "docs/content/index.md").write_text(
            f"# 1. {marker}\n\n[Details](details.md)\n", encoding="utf-8"
        )
        (root / "docs/content/details.md").write_text(
            f"# 2. {marker} details\n\n[Home](index.md)\n", encoding="utf-8"
        )
        (root / "docs/manifest.yaml").write_text(
            textwrap.dedent(
                """\
                surfaces: [repo, site, wiki]
                numbering: baked
                sections:
                  - id: home
                    number: "1"
                    title: Home
                    source: docs/content/index.md
                  - id: details
                    number: "2"
                    title: Details
                    source: docs/content/details.md
                """
            ),
            encoding="utf-8",
        )
        (root / "spec").mkdir()
        (root / "spec/VERSION").write_text(f"{version}\n", encoding="utf-8")

    monkeypatch.chdir(other)
    build_docs.build(site=True, wiki=True, check=True, repo_root=selected)

    assert "SELECTED" in (selected / "generated/site/index.md").read_text(encoding="utf-8")
    assert "OTHER" not in (selected / "generated/site/index.md").read_text(encoding="utf-8")
    assert "9.9.9" in (selected / "generated/wiki/_Footer.md").read_text(encoding="utf-8")
    assert "details.md" in (selected / "generated/site/index.md").read_text(encoding="utf-8")
    assert "[[Details|2-Details]]" in (selected / "generated/wiki/Home.md").read_text(
        encoding="utf-8"
    )


def test_docs_check_passes() -> None:
    assert check(ROOT) == []


def test_generated_wiki_has_sidebar_footer_and_diagram_assets() -> None:
    build_docs.build(site=True, wiki=True, check=True, repo_root=ROOT)
    assert (ROOT / "generated/wiki/_Sidebar.md").exists()
    footer = (ROOT / "generated/wiki/_Footer.md").read_text(encoding="utf-8")
    version = (ROOT / "spec/VERSION").read_text(encoding="utf-8").strip()
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert footer == f"VMx · Specification {version} · Apache-2.0 · thekaveh/VMx\n"
    assert (ROOT / "generated/wiki/assets/diagrams/system-architecture.png").exists()
    sidebar = (ROOT / "generated/wiki/_Sidebar.md").read_text(encoding="utf-8")
    assert re.search(r"\[\[5\.2\. System Architecture\|5-2-System-Architecture\]\]", sidebar)
