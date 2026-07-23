"""Targeted layout contracts for generated documentation diagrams."""

from __future__ import annotations

import importlib.util
import sys
from itertools import pairwise
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


def _on_perimeter(point, box) -> bool:
    x, y = point
    horizontal = box.x <= x <= box.x + box.w and y in {box.y, box.y + box.h}
    vertical = box.y <= y <= box.y + box.h and x in {box.x, box.x + box.w}
    return horizontal or vertical


def _segment_enters_box(start, end, box) -> bool:
    """Return whether a segment enters the strict interior of an axis-aligned box."""
    if _on_perimeter(start, box) or _on_perimeter(end, box):
        return False
    intervals = []
    for first, second, low, high in (
        (start[0], end[0], box.x, box.x + box.w),
        (start[1], end[1], box.y, box.y + box.h),
    ):
        delta = second - first
        if delta == 0:
            if not low < first < high:
                return False
            intervals.append((0.0, 1.0))
        else:
            bounds = sorted(((low - first) / delta, (high - first) / delta))
            intervals.append((max(0.0, bounds[0]), min(1.0, bounds[1])))
    return max(interval[0] for interval in intervals) < min(interval[1] for interval in intervals)


def test_all_diagram_routes_avoid_unrelated_boxes() -> None:
    generator = _generator()
    for diagram_id, diagram in generator.build_diagrams().items():
        routes = [line.points for line in diagram.lines]
        routes.extend(relationship.points for relationship in diagram.relationships)
        for route in routes:
            for start, end in pairwise(route):
                for box in diagram.boxes:
                    assert not _segment_enters_box(start, end, box), (
                        f"{diagram_id}: route {start}->{end} crosses {box.title}"
                    )
