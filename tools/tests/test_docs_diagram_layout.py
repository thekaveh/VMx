"""Targeted layout contracts for generated documentation diagrams."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _generator():
    path = Path(__file__).resolve().parents[2] / "docs/assets/diagrams/generate_diagrams.py"
    spec = importlib.util.spec_from_file_location("docs_diagram_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_examples_vm_layer_side_edge_labels_stay_above_child_boxes() -> None:
    diagram = _generator().examples_vm_layer()
    labels = {
        line.label: line.label_xy
        for line in diagram.lines
        if line.label
        in {
            "current notebook -> bindTo()",
            "current note",
            "focusedVM capabilities",
        }
    }

    assert set(labels) == {
        "current notebook -> bindTo()",
        "current note",
        "focusedVM capabilities",
    }
    assert all(position is not None and position[1] < 340 for position in labels.values())


def test_neutral_edge_labels_use_contrast_safe_text() -> None:
    generator = _generator()
    line = generator.Polyline(((0, 0), (10, 10)), label="edge", label_xy=(5, 5))

    rendered = generator.draw_polyline_label(line)

    assert 'fill="#94a3b8"' in rendered
