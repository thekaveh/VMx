"""Contract tests for the root documentation diagram generator."""

from __future__ import annotations

import importlib.util
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
