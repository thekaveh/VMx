"""Contract tests for the root documentation diagram generator."""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]

# The diagram functions write only the SVG and HTML files. `generate` renders a
# PNG with `rsvg-convert` only when the PNG does not record its current SVG, so
# none of these tests needs the docs toolchain.


def _load_generator() -> ModuleType:
    path = ROOT / "tools" / "generate-doc-diagrams.py"
    spec = importlib.util.spec_from_file_location("root_doc_diagrams", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_html_diagram_is_self_contained() -> None:
    generator = _load_generator()
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>probe</text></svg>'

    rendered = generator.html_doc("Title", "Subtitle", svg, [])

    assert svg in rendered
    assert "<object" not in rendered
    assert 'data="' not in rendered
    assert "@media (prefers-reduced-motion: reduce)" in rendered
    assert ".pulse-dot { animation: none; }" in rendered


def test_svg_has_accessible_title_and_description() -> None:
    generator = _load_generator()

    rendered = generator.svg_doc("System map", "Components and data flow", 200, 100, "")

    assert 'role="img"' in rendered
    assert 'aria-labelledby="diagram-title diagram-description"' in rendered
    assert '<title id="diagram-title">System map</title>' in rendered
    assert '<desc id="diagram-description">Components and data flow</desc>' in rendered


def test_neutral_arrow_labels_use_contrast_safe_text() -> None:
    generator = _load_generator()

    rendered = generator.arrow(0, 0, 100, 100, "edge")

    assert 'fill="#94a3b8"' in rendered


def test_root_diagram_facts_are_derived_from_canonical_sources() -> None:
    generator = _load_generator()
    conformance = (ROOT / "spec/12-conformance.md").read_text(encoding="utf-8")
    capabilities = (ROOT / "spec/14-capabilities.md").read_text(encoding="utf-8")
    parity = (ROOT / "examples/notes-showcase-parity.md").read_text(encoding="utf-8")

    ids = re.findall(r"^### ([A-Z]+-\d{3})\b", conformance, re.MULTILINE)
    capability_match = re.search(r"lists the (\d+) capability interfaces", capabilities)
    assert capability_match
    assert generator.FIXTURE_COUNT == len(list((ROOT / "spec/fixtures").glob("*.json")))
    assert generator.NOTES_FEATURE_COUNT == len(re.findall(r"^\| \d+\s+\|", parity, re.MULTILINE))
    assert generator.CAPABILITY_COUNT == int(capability_match.group(1))
    assert generator.LIBRARY_COUNT == sum(not item.startswith("THEME-") for item in ids)


def test_root_diagrams_render_derived_facts_without_hidden_literals(
    tmp_path: Path,
) -> None:
    generator = _load_generator()
    rendered: list[str] = []
    generator.FIXTURE_COUNT = 91
    generator.NOTES_FEATURE_COUNT = 92
    generator.CAPABILITY_COUNT = 93
    generator.LIBRARY_COUNT = 94
    generator.write_triplet = lambda *args: rendered.append(repr(args))

    generator.architecture(tmp_path)
    generator.class_diagram(tmp_path)
    generator.showcase_hierarchy(tmp_path)
    generator.showcase_components(tmp_path)

    output = "\n".join(rendered)
    for sentinel in (91, 92, 93, 94):
        assert str(sentinel) in output


def test_showcase_diagrams_describe_conceptual_parity_without_claiming_shared_storage(
    tmp_path: Path,
) -> None:
    generator = _load_generator()
    rendered: list[str] = []
    generator.write_triplet = lambda *args: rendered.append(repr(args))

    generator.showcase_hierarchy(tmp_path)
    generator.showcase_components(tmp_path)

    output = "\n".join(rendered)
    assert "flat parent-id navigation" in output
    assert "HierarchicalVM-equivalent" in output
    assert "app-owned current selection" in output
    assert "CompositeVM / list / array" in output
    assert "HierarchicalVM<NotebookModel" not in output
    assert "CompositeVM<NoteVM>" not in output


def test_html_footer_text_meets_wcag_aa_contrast() -> None:
    generator = _load_generator()
    rendered = generator.html_doc("Title", "Subtitle", "<svg/>", [])

    assert "footer { margin-top: 24px; text-align: center; color: #94a3b8;" in rendered

    def luminance(value: str) -> float:
        channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    foreground = luminance("#94a3b8")
    background = luminance("#020617")
    assert (foreground + 0.05) / (background + 0.05) >= 4.5


def test_class_diagram_names_real_message_types_and_capabilities(
    tmp_path: Path,
) -> None:
    generator = _load_generator()

    generator.class_diagram(tmp_path)

    rendered = (tmp_path / "assets" / "class-diagram.html").read_text(encoding="utf-8")
    assert "ConstructionStatusChangedMessage" in rendered
    assert "TreeStructureChangedMessage" in rendered
    assert "property-value projection helper" in rendered
    assert "search / filter / page" in rendered
    assert ">PropertyValueChanged<" not in rendered
    assert "filter / page / count" not in rendered


def test_class_diagram_separates_adjacent_edge_labels(tmp_path: Path) -> None:
    generator = _load_generator()
    generator.class_diagram(tmp_path)
    rendered = (tmp_path / "assets" / "class-diagram.svg").read_text(encoding="utf-8")

    label_y = {
        label: int(y)
        for y, label in re.findall(r'<text x="[^"]+" y="(\d+)"[^>]*>([^<]+)</text>', rendered)
        if label in {"AsyncResourceVM", "hub events"}
    }
    assert abs(label_y["AsyncResourceVM"] - label_y["hub events"]) >= 20


def test_showcase_hierarchy_has_no_notification_self_edge(tmp_path: Path) -> None:
    generator = _load_generator()
    generator.showcase_hierarchy(tmp_path)
    rendered = (tmp_path / "examples" / "assets" / "notes-showcase-vm-hierarchy.svg").read_text(
        encoding="utf-8"
    )

    assert "saved / post" in rendered
    assert "M1180,755 C1030,755 1030,755 880,755" not in rendered


def _architecture_body(tmp_path: Path) -> str:
    generator = _load_generator()
    captured: list[str] = []
    generator.write_triplet = lambda *args: captured.append(args[6])
    generator.architecture(tmp_path)
    return captured[0]


def _edge_points(body: str) -> list[list[tuple[int, int]]]:
    edges = []
    for d in re.findall(r'<path d="(M[^"]+)"', body):
        if " C" in d:
            numbers = [int(value) for value in re.findall(r"-?\d+", d)]
            edges.append([(numbers[0], numbers[1]), (numbers[-2], numbers[-1])])
        else:
            pairs = re.findall(r"(-?\d+),(-?\d+)", d)
            edges.append([(int(x), int(y)) for x, y in pairs])
    return edges


def test_architecture_edges_run_straight_with_one_labeled_flavor_trunk(tmp_path: Path) -> None:
    body = _architecture_body(tmp_path)

    for points in _edge_points(body):
        for (x1, y1), (x2, y2) in pairwise(points):
            assert x1 == x2 or y1 == y2, f"diagonal edge {(x1, y1)} -> {(x2, y2)}"
    assert body.count(">idiomatic APIs<") == 1


def test_architecture_portfolio_box_has_no_dead_space(tmp_path: Path) -> None:
    body = _architecture_body(tmp_path)
    title = re.search(r'<text x="\d+" y="(\d+)"[^>]*>Example Portfolio</text>', body)
    assert title is not None
    top = int(title.group(1)) - 32
    rect = re.search(rf'<rect x="\d+" y="{top}" width="\d+" height="(\d+)"', body)
    assert rect is not None
    last_baseline = top + 58 + 2 * 24

    assert top + int(rect.group(1)) - last_baseline <= 32


# --------------------------------------------------------------------------
# PNG freshness (#1477): a PNG records the digest of the SVG it came from.
# --------------------------------------------------------------------------


def _copy_committed_triplets(generator: ModuleType, destination: Path) -> None:
    for base in generator.TRIPLET_BASES:
        for suffix in (".svg", ".html", ".png"):
            target = destination / base.with_suffix(suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / base.with_suffix(suffix), target)


def _png_bytes(generator: ModuleType, root: Path) -> dict[Path, bytes]:
    return {
        base: (root / base.with_suffix(".png")).read_bytes() for base in generator.TRIPLET_BASES
    }


def _refuse_rsvg(monkeypatch: pytest.MonkeyPatch, generator: ModuleType) -> None:
    real_run = generator.subprocess.run

    def guarded_run(args: list[str], *rest: object, **kwargs: object) -> object:
        if args and args[0] == "rsvg-convert":
            raise AssertionError(f"unexpected rsvg-convert call: {args}")
        return real_run(args, *rest, **kwargs)

    monkeypatch.setattr(generator.subprocess, "run", guarded_run)


def test_generation_keeps_current_pngs_without_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = _load_generator()
    _copy_committed_triplets(generator, tmp_path)
    before = _png_bytes(generator, tmp_path)
    _refuse_rsvg(monkeypatch, generator)

    assert generator.generate(tmp_path) == []

    assert _png_bytes(generator, tmp_path) == before


def test_generation_renders_only_the_png_of_a_changed_svg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = _load_generator()
    _copy_committed_triplets(generator, tmp_path)
    before = _png_bytes(generator, tmp_path)
    changed = Path("assets/class-diagram")
    original_class_diagram = generator.class_diagram

    def changed_class_diagram(output_root: Path) -> None:
        original_class_diagram(output_root)
        svg = output_root / changed.with_suffix(".svg")
        svg.write_text(svg.read_text(encoding="utf-8") + "<!-- changed -->\n", encoding="utf-8")

    rendered: list[Path] = []

    def fake_render(svg_path: Path, png_path: Path) -> None:
        rendered.append(png_path)
        png_path.write_bytes(before[changed])

    monkeypatch.setattr(generator, "class_diagram", changed_class_diagram)
    monkeypatch.setattr(generator, "render_png", fake_render)

    reported = generator.generate(tmp_path)

    png = tmp_path / changed.with_suffix(".png")
    assert rendered == [png]
    assert reported == [png]
    svg = (tmp_path / changed.with_suffix(".svg")).read_bytes()
    assert generator.png_source_digest(png) == generator.svg_render_digest(svg)
    after = _png_bytes(generator, tmp_path)
    assert {base for base in before if after[base] != before[base]} == {changed}


def test_check_reports_a_png_rendered_from_an_older_svg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    generator = _load_generator()
    committed = tmp_path / "repo"
    _copy_committed_triplets(generator, committed)
    stale = Path("assets/class-diagram.png")
    generator.stamp_png(
        committed / stale, generator.svg_render_digest(b"<svg><!-- older --></svg>")
    )
    monkeypatch.setattr(generator, "ROOT", committed)
    _refuse_rsvg(monkeypatch, generator)

    assert generator.main(["--check"]) == 1

    output = capsys.readouterr().out
    assert output.splitlines() == [
        f"stale generated diagram: {stale}",
        "run: python tools/generate-doc-diagrams.py",
    ]


def test_check_passes_committed_triplets_and_reports_an_unstamped_png(tmp_path: Path) -> None:
    generator = _load_generator()
    candidate = tmp_path / "candidate"
    committed = tmp_path / "repo"
    generator.generate(candidate, render_pngs=False)
    _copy_committed_triplets(generator, committed)

    assert generator.check_generated(candidate, committed) == []

    unstamped = Path("examples/assets/notes-showcase-vm-hierarchy.png")
    data = (committed / unstamped).read_bytes()
    chunks = generator._png_chunks(data)
    rebuilt = generator._PNG_SIGNATURE + b"".join(
        generator._png_chunk(kind, body) for kind, body in chunks if kind != b"tEXt"
    )
    (committed / unstamped).write_bytes(rebuilt)
    assert generator.check_generated(candidate, committed) == [unstamped]


def test_stamp_keeps_the_png_valid_and_replaces_an_earlier_digest(tmp_path: Path) -> None:
    generator = _load_generator()
    png = tmp_path / "x.png"
    shutil.copyfile(ROOT / "assets/architecture.png", png)

    generator.stamp_png(png, "a" * 64)
    generator.stamp_png(png, "b" * 64)

    chunks = generator._png_chunks(png.read_bytes())
    assert chunks[0][0] == b"IHDR"
    assert chunks[-1][0] == b"IEND"
    stamps = [body for kind, body in chunks if kind == b"tEXt"]
    assert stamps == [generator.PNG_SOURCE_KEYWORD + b"\0" + b"b" * 64]
    assert generator.png_source_digest(png) == "b" * 64


def test_both_generators_record_the_same_digest() -> None:
    root = _load_generator()
    path = ROOT / "docs/assets/diagrams/generate_diagrams.py"
    spec = importlib.util.spec_from_file_location("site_doc_diagrams_digest", path)
    assert spec is not None
    assert spec.loader is not None
    site = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = site
    spec.loader.exec_module(site)

    assert site.PNG_SOURCE_KEYWORD == root.PNG_SOURCE_KEYWORD
    assert site.PNG_RENDER_RECIPE == root.PNG_RENDER_RECIPE
    assert site.svg_render_digest(b"<svg/>") == root.svg_render_digest(b"<svg/>")
