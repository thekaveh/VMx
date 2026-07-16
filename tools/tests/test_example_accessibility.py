"""Source-level accessibility contracts for native flagship views."""

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
