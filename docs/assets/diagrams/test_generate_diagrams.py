from __future__ import annotations

import importlib.util
import json
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

        self.assertEqual(facts.spec_version, (REPO_ROOT / "spec" / "VERSION").read_text(encoding="utf-8").strip())
        self.assertEqual(facts.spec_chapter_count, len(list((REPO_ROOT / "spec").glob("[0-9][0-9]-*.md"))))
        self.assertEqual(facts.adr_count, len(list((REPO_ROOT / "spec" / "ADRs").glob("[0-9][0-9][0-9][0-9]-*.md"))))
        self.assertEqual(facts.fixture_count, len(list((REPO_ROOT / "spec" / "fixtures").glob("*.json"))))
        self.assertEqual(facts.total_conformance_count, 286)
        self.assertEqual(facts.library_conformance_count, 281)
        self.assertEqual(facts.theme_conformance_count, 5)
        self.assertEqual(facts.capability_count, 22)
        self.assertEqual(facts.notes_feature_count, 19)
        self.assertEqual(facts.registry_ids, tuple(item["id"] for item in registry))

    def test_html_shell_uses_local_fonts_and_light_first_theme(self) -> None:
        html = self.generator.html_doc(
            self.generator.system_architecture(),
            "system-architecture.svg",
        )

        self.assertNotIn("fonts.googleapis.com", html)
        self.assertIn("color-scheme: light dark;", html)
        self.assertIn("@media (prefers-color-scheme: dark)", html)
        self.assertIn("background: var(--page-bg);", html)
        self.assertIn("Embedded SVG stays high-contrast for portability", html)


if __name__ == "__main__":
    unittest.main()
