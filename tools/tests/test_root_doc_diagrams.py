"""Contract tests for the root documentation diagram generator."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


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


def test_neutral_arrow_labels_use_contrast_safe_text() -> None:
    generator = _load_generator()

    rendered = generator.arrow(0, 0, 100, 100, "edge")

    assert 'fill="#94a3b8"' in rendered


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
