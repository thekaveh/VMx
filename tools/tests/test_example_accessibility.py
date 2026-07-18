"""Source-level accessibility contracts for flagship views."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_avalonia_global_search_names_input_and_results() -> None:
    view = (
        REPO_ROOT / "examples/csharp/avalonia/NotesShowcase/Views/GlobalSearchView.axaml"
    ).read_text(encoding="utf-8")

    assert 'AutomationProperties.Name="Search all notes"' in view
    assert 'AutomationProperties.Name="Global search results"' in view


def test_swift_notebook_rows_expose_selected_trait() -> None:
    view = (
        REPO_ROOT
        / "examples/swift/notes-showcase/Sources/NotesShowcase/Views/NotebooksTreeView.swift"
    ).read_text(encoding="utf-8")

    assert ".accessibilityLabel(nb.notebookName)" in view
    assert ".accessibilityAddTraits(isSelected ? [.isSelected] : [])" in view


def test_react_notifications_are_a_polite_live_status_region() -> None:
    view = (
        REPO_ROOT
        / "examples/typescript/react/notes-showcase/src/views/components/Notifications.tsx"
    ).read_text(encoding="utf-8")

    assert 'role="status"' in view
    assert 'aria-live="polite"' in view
    assert 'aria-atomic="false"' in view


def test_react_composite_widgets_have_semantic_keyboard_regressions_in_ci() -> None:
    test = (
        REPO_ROOT
        / "examples/typescript/react/notes-showcase/tests"
        / "views/components/CompositeKeyboardAccessibility.test.tsx"
    ).read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github/workflows/examples-contract-checks.yml").read_text(
        encoding="utf-8"
    )

    for key in ("ArrowDown", "ArrowUp", "Home", "End", "ArrowRight", "ArrowLeft"):
        assert key in test
    assert "axe.run" in test
    assert "React semantic and keyboard accessibility" in workflow
    assert "npm test --prefix examples/typescript/react/notes-showcase" in workflow
