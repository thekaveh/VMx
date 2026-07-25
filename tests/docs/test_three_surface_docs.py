from __future__ import annotations

import html
import re
import textwrap
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest
from scripts.docs import build_docs
from scripts.docs.check_docs import (
    _check_descendant_heading_numbers,
    check,
    check_canonical_links,
    check_generated_html_links,
    check_generated_wiki_links,
    check_historical_audits,
    check_professional_markdown,
    check_raw_html_headings,
    check_self_containment,
)
from scripts.docs.links import find_html_link_attributes, find_links, is_forbidden
from scripts.docs.manifest import load_manifest
from scripts.docs.transforms import build_source_map, rewrite_for_surface

ROOT = Path(__file__).resolve().parents[2]


class _StartTagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attributes: list[list[tuple[str, str | None]]] = []

    def handle_starttag(
        self,
        _tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.attributes.append(attrs)


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


def test_canonical_links_reject_site_style_directory_fallback(tmp_path: Path) -> None:
    content = tmp_path / "docs/content"
    content.mkdir(parents=True)
    (content / "guide.md").write_text("# 1. Guide\n", encoding="utf-8")
    (content / "index.md").write_text("[Guide](guide/)\n", encoding="utf-8")

    findings = check_canonical_links(tmp_path)

    assert [finding.message for finding in findings] == [
        "docs/content/index.md: target does not exist: guide/"
    ]


def test_canonical_link_check_rejects_missing_markdown_and_html_targets(
    tmp_path: Path,
) -> None:
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


def test_canonical_link_check_accepts_case_and_quote_variants_for_html_attributes(
    tmp_path: Path,
) -> None:
    page = tmp_path / "docs/content/index.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "<A HREF='missing.md'>Missing</A>\n"
        "<img SRC='missing.png'>\n"
        "<a href=also-missing.md>Missing</a>\n",
        encoding="utf-8",
    )

    findings = check_canonical_links(tmp_path)

    assert len(findings) == 3
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


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (
            "docs/content/installation.md",
            "index.md?mode=full#home",
            "../?mode=full#home",
        ),
        (
            "docs/content/architecture/system-architecture.md",
            "index.md#map",
            "../#map",
        ),
        ("docs/content/architecture/index.md", "index.md#map", "#map"),
        (
            "docs/content/installation.md",
            "getting-started/index.md",
            "../getting-started/",
        ),
        (
            "docs/content/architecture/system-architecture.md",
            "../getting-started/index.md",
            "../../getting-started/",
        ),
    ],
)
def test_site_rewrite_maps_index_html_links_to_directory_routes(
    source: str,
    target: str,
    expected: str,
) -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "site")
    current_source = Path(source)

    rewritten = rewrite_for_surface(
        f"<a href='{target}'>Target</a>",
        surface="site",
        current_source=current_source,
        current_output=source_map[current_source],
        source_map=source_map,
        repo_root=ROOT,
    )

    assert rewritten == f"<a href='{expected}'>Target</a>"


def test_site_rewrite_maps_same_directory_html_markdown_link_to_sibling_route() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    site_map = build_source_map(manifest, "site")
    wiki_map = build_source_map(manifest, "wiki")
    link = '<a href="notes-workspace-vm-layer.md">VM layer</a>'
    source = Path("docs/content/examples/notes-workspace.md")

    site = rewrite_for_surface(
        link,
        surface="site",
        current_source=source,
        current_output=site_map[source],
        source_map=site_map,
        repo_root=ROOT,
    )
    wiki = rewrite_for_surface(
        link,
        surface="wiki",
        current_source=source,
        current_output=wiki_map[source],
        source_map=wiki_map,
        repo_root=ROOT,
    )

    assert site == '<a href="../notes-workspace-vm-layer/">VM layer</a>'
    assert wiki == '<a href="8-4-VM-Layer-Map">VM layer</a>'


def test_html_rewrite_accepts_case_and_quote_variants() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "site")
    source = Path("docs/content/examples/notes-workspace.md")

    rewritten = rewrite_for_surface(
        "<A HREF='notes-workspace-vm-layer.md#details'>VM layer</A>",
        surface="site",
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )

    assert rewritten == "<A HREF='../notes-workspace-vm-layer/#details'>VM layer</A>"


def test_html_rewrite_supports_unquoted_attributes_and_preserves_code_and_comments() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "site")
    source = Path("docs/content/examples/notes-workspace.md")
    markdown = (
        "<a href=notes-workspace-vm-layer.md>Actual</a>\n\n"
        '`<a href="notes-workspace-vm-layer.md">inline</a>`\n\n'
        '```html\n<a href="notes-workspace-vm-layer.md">fenced</a>\n```\n\n'
        '    <a href="notes-workspace-vm-layer.md">indented</a>\n\n'
        '<!-- <a href="notes-workspace-vm-layer.md">commented</a> -->\n'
    )

    rewritten = rewrite_for_surface(
        markdown,
        surface="site",
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )

    assert rewritten.startswith('<a href="../notes-workspace-vm-layer/">Actual</a>')
    assert '`<a href="notes-workspace-vm-layer.md">inline</a>`' in rewritten
    assert '```html\n<a href="notes-workspace-vm-layer.md">fenced</a>\n```' in rewritten
    assert '    <a href="notes-workspace-vm-layer.md">indented</a>' in rewritten
    assert '<!-- <a href="notes-workspace-vm-layer.md">commented</a> -->' in rewritten


def test_markdown_rewrite_preserves_links_and_generic_calls_inside_commonmark_code() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "wiki")
    source = Path("docs/content/flavors/python.md")
    markdown = (
        "[Quickstart](../getting-started/index.md)\n\n"
        "```python\n"
        "ServicedObservableCollection[Note](hub)\n"
        "```\n\n"
        "- ~~~~swift\n"
        '  ModalVM[str]("cancel")\n'
        "  ~~~~\n\n"
        '<a title="[Attribute](../installation.md)" '
        'href="../getting-started/index.md">HTML</a>\n'
    )

    rewritten = rewrite_for_surface(
        markdown,
        surface="wiki",
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )

    assert "ServicedObservableCollection[Note](hub)" in rewritten
    assert 'ModalVM[str]("cancel")' in rewritten
    assert 'title="[Attribute](../installation.md)"' in rewritten
    assert 'href="3-1-Quickstart"' in rewritten
    assert "[[Quickstart|3-1-Quickstart]]" in rewritten


@pytest.mark.parametrize(
    ("quote", "encoded", "expected"),
    [
        (
            '"',
            "notes-workspace-vm-layer.md?x=1&amp;y=&quot;two&quot;#details",
            "../notes-workspace-vm-layer/?x=1&amp;y=&quot;two&quot;#details",
        ),
        (
            "'",
            "notes-workspace-vm-layer.md?x=&#39;two&#39;&amp;y=1#details",
            "../notes-workspace-vm-layer/?x=&#x27;two&#x27;&amp;y=1#details",
        ),
    ],
)
def test_html_rewrite_escapes_decoded_attribute_delimiters(
    quote: str,
    encoded: str,
    expected: str,
) -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "site")
    source = Path("docs/content/examples/notes-workspace.md")

    rewritten = rewrite_for_surface(
        f"<a href={quote}{encoded}{quote}>Target</a>",
        surface="site",
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )

    attributes = find_html_link_attributes(rewritten)
    assert len(attributes) == 1
    assert attributes[0].target == expected


@pytest.mark.parametrize("entity", ["&#32;", "&#9;", "&#10;", "&#61;", "&#96;"])
def test_html_rewrite_quotes_unquoted_attributes_after_entity_decoding(
    entity: str,
) -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "site")
    source = Path("docs/content/examples/notes-workspace.md")
    target = f"notes-workspace-vm-layer.md?x{entity}tail"

    rewritten = rewrite_for_surface(
        f"<a href={target}>Target</a>",
        surface="site",
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )
    parser = _StartTagCollector()
    parser.feed(rewritten)

    assert len(parser.attributes) == 1
    assert parser.attributes[0] == [
        ("href", f"../notes-workspace-vm-layer/?x{html.unescape(entity)}tail")
    ]


def test_html_attribute_scanner_ignores_non_html_contexts() -> None:
    markdown = (
        "<a href=actual.md>Actual</a>\n"
        '<a title="`code`" href="backtick-attribute.md">Backtick</a>\n'
        '<a data-x="``code``" href="multi-backtick-attribute.md">Multi</a>\n'
        r'\<a href="escaped-tag.md">Escaped tag</a>'
        "\n"
        r'\\<a href="even-backslash-tag.md">Even tag</a>'
        "\n"
        "`<a href='inline.md'>Inline</a>`\n"
        "```\n<img src='fenced.png'>\n```\n"
        "- ```html\n"
        "  <a href='list-fenced.md'>List fenced</a>\n"
        "  ```\n"
        "> ```html\n"
        "> <a href='quoted-fenced.md'>Quoted fenced</a>\n"
        "> ```\n"
        "````\n"
        "<a href='long-fenced.md'>Long fenced</a>\n"
        "    ```\n"
        "<a href='still-fenced.md'>Still fenced</a>\n"
        "````\n"
        "    <a href='indented.md'>Indented</a>\n"
        "<!-- <a href='commented.md'>Commented</a> -->\n"
        "<script>const example = \"<a href='script-text.md'>Text</a>\";</script>\n"
        "<pre><a href='pre-text.md'>Text</a></pre>\n"
    )

    attributes = find_html_link_attributes(markdown)

    assert [(attribute.attribute.lower(), attribute.target) for attribute in attributes] == [
        ("href", "actual.md"),
        ("href", "backtick-attribute.md"),
        ("href", "multi-backtick-attribute.md"),
        ("href", "even-backslash-tag.md"),
        ("href", "pre-text.md"),
    ]


def test_self_containment_checks_raw_html_attributes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "<A HREF='https://github.com/thekaveh/VMx/wiki'>Wiki</A>\n",
        encoding="utf-8",
    )

    findings = check_self_containment(tmp_path)

    assert len(findings) == 1
    assert "forbidden repo-surface link" in findings[0].message


def test_self_containment_ignores_html_like_code_and_comments(tmp_path: Path) -> None:
    forbidden = "https://github.com/thekaveh/VMx/wiki"
    (tmp_path / "README.md").write_text(
        f"`<a href='{forbidden}'>Inline</a>`\n"
        f"```\n<img src='{forbidden}'>\n```\n"
        f"    <a href='{forbidden}'>Indented</a>\n"
        f"<!-- <a href='{forbidden}'>Commented</a> -->\n",
        encoding="utf-8",
    )

    assert check_self_containment(tmp_path) == []


def test_generated_html_link_check_validates_routes_assets_and_fragments(
    tmp_path: Path,
) -> None:
    site = tmp_path / "generated/site"
    wiki = tmp_path / "generated/wiki"
    (site / "guide").mkdir(parents=True)
    (site / "assets").mkdir()
    wiki.mkdir(parents=True)
    (site / "guide/source.md").write_text(
        "<a href='../target/#existing'>Good</a>\n"
        "<a HREF='../target/#missing'>Bad fragment</a>\n"
        "<a href='../absent/'>Bad route</a>\n"
        "<img SRC='../../assets/one.svg'>\n",
        encoding="utf-8",
    )
    (site / "guide/target.md").write_text("# Target\n\n## Existing\n", encoding="utf-8")
    (site / "assets/one.svg").write_text("<svg></svg>\n", encoding="utf-8")
    (wiki / "Source.md").write_text(
        "<a href='Target#existing'>Good</a>\n"
        "<a HREF='Target#missing'>Bad fragment</a>\n"
        "<a href='../../README.md'>Traversal</a>\n"
        "<a href='/etc/hosts'>Absolute</a>\n",
        encoding="utf-8",
    )
    (wiki / "Target.md").write_text("# Target\n\n## Existing\n", encoding="utf-8")

    findings = check_generated_html_links(tmp_path)

    assert len(findings) == 5
    assert sum("heading fragment does not exist" in item.message for item in findings) == 2
    assert sum("target does not exist" in item.message for item in findings) == 3


def test_generated_site_links_honor_deployment_base_and_decode_paths(
    tmp_path: Path,
) -> None:
    site = tmp_path / "generated/site"
    site.mkdir(parents=True)
    (tmp_path / "mkdocs.yml").write_text(
        "site_url: https://example.test/VMx/\n",
        encoding="utf-8",
    )
    (site / "index.md").write_text(
        "# Home\n\n"
        "<a href='/VMx/#home'>Base root</a>\n"
        "<a href='/VMx/installation/#install'>Base-prefixed</a>\n"
        "<a href='/installation/'>Outside base</a>\n"
        "<a href='getting%2Dstarted/?mode=full#start'>Encoded</a>\n"
        "<a href='/VMx/%2e%2e/secret/'>Traversal</a>\n"
        "<a href='/VMx/%00/'>NUL</a>\n"
        "<a href='/VMx/%1f/'>Control</a>\n",
        encoding="utf-8",
    )
    (site / "installation.md").write_text("# Install\n\n## Install\n", encoding="utf-8")
    (site / "getting-started.md").write_text(
        "# Getting started\n\n## Start\n",
        encoding="utf-8",
    )

    findings = check_generated_html_links(tmp_path)

    assert len(findings) == 4
    assert all("target does not exist" in item.message for item in findings)
    assert any("/installation/" in item.message for item in findings)
    assert any("%2e%2e" in item.message for item in findings)
    assert any("%00" in item.message for item in findings)
    assert any("%1f" in item.message for item in findings)


def test_markdown_link_scanner_does_not_cross_line_boundaries() -> None:
    markdown = "The interval is [0, count)\n\n[Composite](composite.md)\n"

    assert find_links(markdown) == [
        find_links("[Composite](composite.md)")[0],
    ]


def test_markdown_link_scanner_handles_large_unmatched_bracket_input_linearly() -> None:
    started = time.monotonic()

    assert find_links("[" * 10_000) == []

    assert time.monotonic() - started < 1.0


def test_markdown_link_scanner_bounds_nested_candidate_validation() -> None:
    markdown = "[" * 1_600 + "x" + "](guide.md)" * 1_600
    started = time.monotonic()

    links = find_links(markdown)

    assert links
    assert links[0].target == "guide.md"
    assert time.monotonic() - started < 3.0


def test_markdown_link_scanner_bounds_unclosed_angle_recovery() -> None:
    markdown = "[bad](<x " * 2_000 + "[Docs](guide.md)"
    started = time.monotonic()

    links = find_links(markdown)

    assert links[-1].target == "guide.md"
    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize(
    "markdown",
    [
        "Prose (said 'hello\n\n[Docs](guide.md)",
        'Prose (said "hello\n\n[Docs](guide.md)',
        "Prose (<tag\n\n[Docs](guide.md)",
        "[bad]( 'unterminated\n\n[Docs](guide.md)",
        '[bad]( "unterminated\n\n[Docs](guide.md)',
        "[bad]( <unterminated\n\n[Docs](guide.md)",
        "[bad]( 'unterminated\n[Docs](guide.md)",
        '[bad]( "unterminated\n[Docs](guide.md)',
        "[bad]( <unterminated\n[Docs](guide.md)",
        "[bad](foo 'unclosed [Docs](guide.md)",
        '[bad](foo "unclosed [Docs](guide.md)',
        "[bad](<unclosed [Docs](guide.md)",
    ],
)
def test_markdown_link_scanner_ignores_unmatched_prose_parentheses(
    markdown: str,
) -> None:
    assert [link.target for link in find_links(markdown)] == ["guide.md"]


@pytest.mark.parametrize(
    ("markdown", "label", "target"),
    [
        ("[Docs](<guide path.md>)", "Docs", "guide path.md"),
        ("[Docs](guide(and)more.md)", "Docs", "guide(and)more.md"),
        (r"[Docs](guide\)name.md)", "Docs", "guide)name.md"),
        ("[Docs](guide.md 'title')", "Docs", "guide.md"),
        ("[Docs](guide.md (title))", "Docs", "guide.md"),
        ('[Docs](guide.md "line one\nline two")', "Docs", "guide.md"),
        ('[Docs](guide.md "literal [Other](other.md) text")', "Docs", "guide.md"),
        ("[Docs](it's.md)", "Docs", "it's.md"),
        ('[Docs](say"hi.md)', "Docs", 'say"hi.md'),
        ("[Docs](foo'bar(baz).md)", "Docs", "foo'bar(baz).md"),
        ("[a [nested] label](guide.md)", "a [nested] label", "guide.md"),
    ],
)
def test_markdown_link_scanner_supports_commonmark_destination_and_label_forms(
    markdown: str,
    label: str,
    target: str,
) -> None:
    links = find_links(markdown)
    assert [(link.label, link.target) for link in links] == [(label, target)]


def test_site_markdown_rewrite_preserves_commonmark_link_title() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "site")
    source = Path("docs/content/examples/notes-workspace.md")

    rewritten = rewrite_for_surface(
        "[VM [layer]]("
        "https://github.com/thekaveh/VMx/blob/main/"
        "docs/content/examples/notes-workspace-vm-layer.md 'Open details')",
        surface="site",
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )

    assert rewritten == "[VM [layer]](examples/notes-workspace-vm-layer.md 'Open details')"


@pytest.mark.parametrize("markdown", ["[Top]()", '[Top](<> "home")'])
@pytest.mark.parametrize("surface", ["site", "wiki"])
def test_surface_rewrite_preserves_empty_markdown_destinations(
    markdown: str,
    surface: str,
) -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, surface)
    source = Path("docs/content/index.md")

    assert (
        rewrite_for_surface(
            markdown,
            surface=surface,
            current_source=source,
            current_output=source_map[source],
            source_map=source_map,
            repo_root=ROOT,
        )
        == markdown
    )


@pytest.mark.parametrize("quote", ['"', "'"])
def test_wiki_markdown_rewrite_preserves_link_titles(quote: str) -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "wiki")
    source = Path("docs/content/flavors/python.md")

    rewritten = rewrite_for_surface(
        f"[Quickstart](../getting-started/index.md {quote}details{quote})",
        surface="wiki",
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )

    assert rewritten == f"[Quickstart](3-1-Quickstart {quote}details{quote})"


def test_wiki_markdown_rewrite_uses_markdown_for_nested_labels() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source_map = build_source_map(manifest, "wiki")
    source = Path("docs/content/examples/notes-workspace.md")

    rewritten = rewrite_for_surface(
        "[VM [layer]](notes-workspace-vm-layer.md)",
        surface="wiki",
        current_source=source,
        current_output=source_map[source],
        source_map=source_map,
        repo_root=ROOT,
    )

    assert rewritten == "[VM [layer]](8-4-VM-Layer-Map)"


def test_surface_rewrite_preserves_inline_code_link_labels() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    markdown = (
        "[`docs/maintenance/2026-07-16-rust-capability-parity.md`]"
        "(../../../docs/maintenance/2026-07-16-rust-capability-parity.md)"
    )
    source = Path("docs/content/getting-started/rust.md")

    for surface in ("site", "wiki"):
        source_map = build_source_map(manifest, surface)
        rewritten = rewrite_for_surface(
            markdown,
            surface=surface,
            current_source=source,
            current_output=source_map[source],
            source_map=source_map,
            repo_root=ROOT,
        )
        assert "`docs/maintenance/2026-07-16-rust-capability-parity.md`" in rewritten
        assert "[                                                       ]" not in rewritten


def test_surface_rewrite_preserves_inline_code_label_when_link_is_stripped() -> None:
    manifest = load_manifest(ROOT / "docs/manifest.yaml", ROOT)
    source = Path("docs/content/integration/wpf.md")
    markdown = "[`examples/csharp/wpf/TodoApp/`](../../../examples/csharp/wpf/TodoApp/)"

    for surface in ("site", "wiki"):
        source_map = build_source_map(manifest, surface)
        assert (
            rewrite_for_surface(
                markdown,
                surface=surface,
                current_source=source,
                current_output=source_map[source],
                source_map=source_map,
                repo_root=ROOT,
            )
            == "`examples/csharp/wpf/TodoApp/`"
        )


def test_generated_surfaces_reject_whitespace_only_link_labels(tmp_path: Path) -> None:
    site = tmp_path / "generated/site"
    wiki = tmp_path / "generated/wiki"
    site.mkdir(parents=True)
    wiki.mkdir(parents=True)
    (site / "page.md").write_text("[   ](target.md)\n", encoding="utf-8")
    (wiki / "Page.md").write_text("[[   |Target]]\n", encoding="utf-8")
    (wiki / "Target.md").write_text("# Target\n", encoding="utf-8")

    site_findings = check_self_containment(tmp_path)
    wiki_findings = check_generated_wiki_links(tmp_path)

    assert any("whitespace-only label" in finding.message for finding in site_findings)
    assert any("whitespace-only label" in finding.message for finding in wiki_findings)


@pytest.mark.parametrize(
    "empty_label",
    ["   ", "&nbsp;", "` `", "<span> </span>"],
)
def test_generated_surfaces_reject_visually_empty_link_labels(
    tmp_path: Path,
    empty_label: str,
) -> None:
    site = tmp_path / "generated/site"
    site.mkdir(parents=True)
    (site / "page.md").write_text(f"[{empty_label}](target.md)\n", encoding="utf-8")

    findings = check_self_containment(tmp_path)

    assert any("whitespace-only label" in finding.message for finding in findings)


def test_generated_surface_accepts_html_image_alt_link_label(tmp_path: Path) -> None:
    site = tmp_path / "generated/site"
    site.mkdir(parents=True)
    (site / "page.md").write_text(
        '[<img src="icon.png" alt="Guide">](guide.md)\n',
        encoding="utf-8",
    )

    assert not any(
        "whitespace-only label" in finding.message for finding in check_self_containment(tmp_path)
    )


def test_generated_surface_rejects_zero_width_only_link_label(tmp_path: Path) -> None:
    site = tmp_path / "generated/site"
    site.mkdir(parents=True)
    (site / "page.md").write_text("[\u200b](guide.md)\n", encoding="utf-8")

    assert any(
        "whitespace-only label" in finding.message for finding in check_self_containment(tmp_path)
    )


def test_commonmark_autolinks_participate_in_self_containment(tmp_path: Path) -> None:
    site = tmp_path / "generated/site"
    site.mkdir(parents=True)
    (site / "page.md").write_text(
        "<https://github.com/thekaveh/VMx/wiki>\n"
        "<maintainer@example.com>\n"
        "`<https://github.com/thekaveh/VMx/wiki>`\n"
        r"\<https://github.com/thekaveh/VMx/wiki>"
        "\n",
        encoding="utf-8",
    )

    links = find_links((site / "page.md").read_text(encoding="utf-8"))
    findings = check_self_containment(tmp_path)

    assert [link.target for link in links] == [
        "https://github.com/thekaveh/VMx/wiki",
        "mailto:maintainer@example.com",
    ]
    assert len(findings) == 1
    assert "forbidden site link" in findings[0].message


@pytest.mark.parametrize(
    "markdown",
    [
        "Text `` [Docs](guide.md) ``` tail",
        "Text ` [Docs](guide.md) `` tail",
        "Text `` [Docs](guide.md) ` tail",
        "Text ``` [Docs](guide.md) `` tail",
        "x <!--> [Docs](guide.md)",
        "x <!---> [Docs](guide.md)",
        "x <!-- unclosed [Docs](guide.md)",
        r"\[Docs](guide.md)",
        r"\![Docs](guide.md)",
        r"!\[Docs](guide.md)",
        r"\\[Docs](guide.md)",
        r"\` [Docs](guide.md) `",
        r"\`` [Docs](guide.md) ``",
        r"\` [Docs](guide.md) \`",
        r"\<!-- [Docs](guide.md) -->",
        r"\<script>[Docs](guide.md)</script>",
        "`foo <!-- ` [Docs](guide.md) -->",
    ],
)
def test_markdown_link_scanner_keeps_links_after_mismatched_inline_constructs(
    markdown: str,
) -> None:
    expected = [] if markdown.startswith((r"\[", r"!\[")) else ["guide.md"]
    assert [link.target for link in find_links(markdown)] == expected


@pytest.mark.parametrize(
    "markdown",
    [
        "Text `` [Docs](guide.md) `` tail",
        r"\\` [Docs](guide.md) `",
        r"\\<!-- [Docs](guide.md) -->",
        r"\\<script>[Docs](guide.md)</script>",
        "x <!-- closed [Docs](guide.md) --> tail",
        '<span title="[Docs](guide.md)">tail</span>',
    ],
)
def test_markdown_link_scanner_masks_real_code_comments_and_html_attributes(
    markdown: str,
) -> None:
    assert find_links(markdown) == []


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
    python_site = (ROOT / "generated/site/flavors/python.md").read_text(encoding="utf-8")
    python_wiki = (ROOT / "generated/wiki/7-3-Python.md").read_text(encoding="utf-8")
    modal_site = (
        ROOT / "generated/site/primitives/viewmodel-families/specialized/modal-vm.md"
    ).read_text(encoding="utf-8")
    modal_wiki = (ROOT / "generated/wiki/6-2-8-6-ModalVM.md").read_text(encoding="utf-8")
    assert "#1236-expandablestate-is-missing-members" in state_site
    assert "#1236-expandablestate-is-missing-members" in state_wiki
    assert "#1244-formvm-direct-approve-gates-on-strictdirty" in form_site
    assert "CONTRIBUTING.md#" not in releases_site
    assert "ServicedObservableCollection[Note](hub)" in python_site
    assert "ServicedObservableCollection[Note](hub)" in python_wiki
    assert 'ModalVM[str]("cancel")' in modal_site
    assert 'ModalVM[str]("cancel")' in modal_wiki


def test_build_repo_root_is_fully_isolated(tmp_path: Path, monkeypatch) -> None:
    selected = tmp_path / "selected"
    other = tmp_path / "other"
    for root, marker, version in (
        (selected, "SELECTED", "9.9.9"),
        (other, "OTHER", "1.0.0"),
    ):
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
