"""Keep the SwiftUI integration recipe identical to the code Swift CI compiles."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE = REPO_ROOT / "docs" / "content" / "integration" / "swiftui.md"
COMPILED = REPO_ROOT / "langs" / "swift" / "Tests" / "VMxTests" / "SwiftUIRecipeTests.swift"
IMPORTS = "import Combine\nimport SwiftUI\nimport VMx\n\n"


def _compiled_region() -> str:
    text = COMPILED.read_text(encoding="utf-8")
    match = re.search(r"// BEGIN swiftui-recipe\n(.*?)// END swiftui-recipe\n", text, re.S)
    assert match is not None, "SwiftUIRecipeTests.swift lost its recipe markers"
    return match.group(1)


def _guide_snippet() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    section = text.split("## 9.12.3. Adapter and view", 1)[1].split("\n## ", 1)[0]
    match = re.search(r"```swift\n(.*?)```", section, re.S)
    assert match is not None, "the SwiftUI guide lost its adapter snippet"
    return match.group(1)


def test_swiftui_guide_snippet_matches_the_compiled_recipe() -> None:
    assert _guide_snippet() == IMPORTS + _compiled_region()


def test_swiftui_guide_does_not_regress_to_disposing_on_disappear() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    assert "try? adapter.vm.construct" not in text
    assert "selectCommand.execute()" not in text
    assert ".onDisappear { adapter.vm.dispose() }" not in text
