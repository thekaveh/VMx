"""Contract tests for the root documentation diagram generator."""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]

# The triplet writer rasterizes each SVG to PNG via `rsvg-convert`. That binary
# is installed in the docs CI job (librsvg2-bin) but not in the conformance job,
# so tests that render a real triplet skip when it is unavailable.
_REQUIRES_RSVG = pytest.mark.skipif(
    shutil.which("rsvg-convert") is None,
    reason="requires rsvg-convert (docs CI job / local docs toolchain)",
)


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


def test_root_diagrams_render_derived_facts_without_hidden_literals(tmp_path: Path) -> None:
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


@_REQUIRES_RSVG
def test_class_diagram_names_real_message_types_and_capabilities(tmp_path: Path) -> None:
    generator = _load_generator()

    generator.class_diagram(tmp_path)

    rendered = (tmp_path / "assets" / "class-diagram.html").read_text(encoding="utf-8")
    assert "ConstructionStatusChangedMessage" in rendered
    assert "TreeStructureChangedMessage" in rendered
    assert "property-value projection helper" in rendered
    assert "search / filter / page" in rendered
    assert ">PropertyValueChanged<" not in rendered
    assert "filter / page / count" not in rendered


@_REQUIRES_RSVG
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


@_REQUIRES_RSVG
def test_showcase_hierarchy_has_no_notification_self_edge(tmp_path: Path) -> None:
    generator = _load_generator()
    generator.showcase_hierarchy(tmp_path)
    rendered = (tmp_path / "examples" / "assets" / "notes-showcase-vm-hierarchy.svg").read_text(
        encoding="utf-8"
    )

    assert "saved / post" in rendered
    assert "M1180,755 C1030,755 1030,755 880,755" not in rendered
