"""Keep the SwiftUI integration recipe tied to the code Swift CI compiles and runs.

The guide's fences carry ``checked-snippet`` markers naming regions of
SwiftUIRecipeTests.swift; ``make docs-check`` (scripts/docs/check_docs.py) fails
when a fence differs. These tests keep the markers in place.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE = REPO_ROOT / "docs" / "content" / "integration" / "swiftui.md"
COMPILED = "langs/swift/Tests/VMxTests/SwiftUIRecipeTests.swift"


def _section(heading: str) -> str:
    text = GUIDE.read_text(encoding="utf-8")
    assert heading in text, f"the SwiftUI guide lost its '{heading}' section"
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_swiftui_guide_snippets_are_checked_against_the_compiled_recipe() -> None:
    for heading, region in (
        ("## 9.12.3. Adapter and view", "swiftui-recipe"),
        ("## 9.12.4. Lifecycle is throwing", "swiftui-throwing-lifecycle"),
    ):
        marker = f"<!-- checked-snippet: {COMPILED}#{region} -->\n\n```swift\n"
        assert marker in _section(heading), f"the guide lost the {region} marker"


def test_the_compiled_recipe_uses_the_public_api_only() -> None:
    assert "@testable import" not in (REPO_ROOT / COMPILED).read_text(encoding="utf-8")


def test_swiftui_guide_does_not_regress_to_disposing_on_disappear() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    assert "try? adapter.vm.construct" not in text
    assert "selectCommand.execute()" not in text
    assert ".onDisappear { adapter.vm.dispose() }" not in text
