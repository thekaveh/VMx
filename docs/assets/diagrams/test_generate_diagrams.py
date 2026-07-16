from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = Path(__file__).resolve().parent / "generate_diagrams.py"


def load_generator_module():
    spec = importlib.util.spec_from_file_location("vmx_generate_diagrams", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load generator from {GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GenerateDiagramsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = load_generator_module()

    def test_load_source_facts_matches_repo_state(self) -> None:
        facts = self.generator.load_source_facts()
        registry = json.loads(
            (REPO_ROOT / "docs" / "assets" / "diagrams" / "diagram-registry.json").read_text(
                encoding="utf-8"
            )
        )
        conformance = (REPO_ROOT / "spec" / "12-conformance.md").read_text(encoding="utf-8")
        capability_spec = (REPO_ROOT / "spec" / "14-capabilities.md").read_text(encoding="utf-8")
        notes_parity = (REPO_ROOT / "examples" / "notes-showcase-parity.md").read_text(
            encoding="utf-8"
        )
        conformance_ids = re.findall(r"^### ([A-Z]+-\d{3})\b", conformance, re.MULTILINE)
        theme_count = sum(1 for item in conformance_ids if item.startswith("THEME-"))
        total_count = len(conformance_ids)
        capability_count = int(
            re.search(
                r"lists the (\d+) capability interfaces",
                capability_spec,
                re.MULTILINE,
            ).group(1)
        )
        notes_feature_count = len(re.findall(r"^\| \d+\s+\|", notes_parity, re.MULTILINE))

        self.assertEqual(
            facts.spec_version, (REPO_ROOT / "spec" / "VERSION").read_text(encoding="utf-8").strip()
        )
        self.assertEqual(
            facts.spec_chapter_count, len(list((REPO_ROOT / "spec").glob("[0-9][0-9]-*.md")))
        )
        self.assertEqual(
            facts.adr_count,
            len(list((REPO_ROOT / "spec" / "ADRs").glob("[0-9][0-9][0-9][0-9]-*.md"))),
        )
        self.assertEqual(
            facts.fixture_count, len(list((REPO_ROOT / "spec" / "fixtures").glob("*.json")))
        )
        self.assertEqual(facts.total_conformance_count, total_count)
        self.assertEqual(facts.library_conformance_count, total_count - theme_count)
        self.assertEqual(facts.theme_conformance_count, theme_count)
        self.assertEqual(facts.capability_count, capability_count)
        self.assertEqual(facts.notes_feature_count, notes_feature_count)
        self.assertEqual(facts.registry_ids, tuple(item["id"] for item in registry))

    def test_html_shell_uses_jetbrains_mono_and_dark_theme(self) -> None:
        html = self.generator.html_doc(
            self.generator.system_architecture(),
            "system-architecture.svg",
        )

        self.assertIn("fonts.googleapis.com", html)
        self.assertIn("JetBrains Mono", html)
        self.assertIn("color-scheme: dark;", html)
        self.assertNotIn("@media (prefers-color-scheme: dark)", html)
        self.assertIn("background: var(--page-bg);", html)
        self.assertNotIn("follow the labeled relationships between components", html)
        self.assertNotIn("Generated for", html)
        self.assertNotIn("Dark SVG source uses", html)
        self.assertIn("<svg", html)

    def test_every_diagram_box_text_stays_inside_bounds(self) -> None:
        for diagram in self.generator.build_diagrams().values():
            for box in diagram.boxes:
                text_runs = (
                    (box.title, box.title_size),
                    *((line, box.line_size) for line in box.lines),
                )
                for text, font_size in text_runs:
                    fitted_size = self.generator.fitted_font_size(
                        text,
                        font_size,
                        self.generator.box_text_width(box),
                    )
                    estimated_width = (
                        len(text) * fitted_size * self.generator.MONO_GLYPH_WIDTH_FACTOR
                    )
                    self.assertLessEqual(
                        estimated_width,
                        self.generator.box_text_width(box),
                        f"{diagram.title}: {box.title!r} text overflows: {text!r}",
                    )
                last_line_baseline = (
                    box.y + 54 + ((len(box.lines) - 1) * max(18, box.line_size + 6))
                )
                self.assertLessEqual(
                    last_line_baseline,
                    box.y + box.h - 2,
                    f"{diagram.title}: {box.title!r} body overflows vertically",
                )

    def test_class_lineage_routes_do_not_cross_boxes_or_overlap(self) -> None:
        diagram = self.generator.class_architecture()
        lineage = diagram.relationships[:5]
        seen_segments: set[tuple[tuple[int, int], tuple[int, int]]] = set()

        for relationship in lineage:
            for start, end in zip(relationship.points, relationship.points[1:], strict=False):
                segment = tuple(sorted((start, end)))
                self.assertNotIn(segment, seen_segments)
                seen_segments.add(segment)
                for box in diagram.boxes:
                    if start[0] == end[0]:
                        x = start[0]
                        low, high = sorted((start[1], end[1]))
                        crosses = box.x < x < box.x + box.w and max(low, box.y) < min(
                            high, box.y + box.h
                        )
                    else:
                        y = start[1]
                        low, high = sorted((start[0], end[0]))
                        crosses = box.y < y < box.y + box.h and max(low, box.x) < min(
                            high, box.x + box.w
                        )
                    self.assertFalse(
                        crosses,
                        f"{relationship.kind} segment {start}->{end} crosses {box.title}",
                    )

    def test_svg_output_is_dark_and_uses_architecture_palette(self) -> None:
        svg = self.generator.svg_doc(self.generator.system_architecture())

        self.assertIn('fill="#020617"', svg)
        self.assertIn('stroke="#1e293b"', svg)
        self.assertIn('stroke="#22d3ee"', svg)
        self.assertNotIn('fill="#f3f7fb"', svg)

    def test_class_architecture_uses_explicit_helper_boxes(self) -> None:
        diagram = self.generator.class_architecture()
        titles = {box.title for box in diagram.boxes}
        viewmodel_families = self.generator.viewmodel_families()
        capability_box = next(
            box for box in viewmodel_families.boxes if box.title == "Capability overlays"
        )

        self.assertIn("ComponentVM<M>", titles)
        self.assertIn("IComponentVM<M>", titles)
        self.assertIn("ICompositeVM<VM>", titles)
        self.assertIn("ICommand", titles)
        self.assertIn("IPageable", titles)
        self.assertIn("Confirm delegate", titles)
        self.assertIn(
            "PagedComposition and TokenPagedComposition are composition/paging "
            "primitives, not CompositeVM subclasses.",
            diagram.notes[0].lines[0],
        )
        self.assertIn(
            f"{self.generator.SOURCE_FACTS.capability_count} micro-interfaces",
            capability_box.lines,
        )

    def test_commands_map_includes_sync_and_async_command_contracts(self) -> None:
        diagram = self.generator.commands_capabilities()
        rendered_text = {text for box in diagram.boxes for text in (box.title, *box.lines)}

        self.assertIn("ICommand / ICommand<T>", rendered_text)
        self.assertIn("IAsyncCommand", rendered_text)
        self.assertIn("RelayCommand", rendered_text)
        self.assertIn("AsyncRelayCommand", rendered_text)


if __name__ == "__main__":
    unittest.main()
