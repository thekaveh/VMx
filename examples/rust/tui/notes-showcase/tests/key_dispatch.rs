//! Drives the app through its key bindings and renders it with ratatui's
//! `TestBackend`, the way a user sees it.

use crossterm::event::KeyCode;
use notes_showcase::app::handle_key;
use notes_showcase::{views, InMemoryNoteRepository, WorkspaceVm};
use ratatui::{backend::TestBackend, Terminal};

fn press(workspace: &WorkspaceVm, keys: &str) {
    for key in keys.chars() {
        assert!(handle_key(workspace, KeyCode::Char(key)));
    }
}

fn screen(workspace: &WorkspaceVm) -> String {
    let mut terminal = Terminal::new(TestBackend::new(140, 24)).expect("test terminal");
    terminal
        .draw(|frame| views::render(frame, workspace))
        .expect("frame renders");
    let buffer = terminal.backend().buffer();
    let width = buffer.area.width as usize;
    buffer
        .content()
        .chunks(width)
        .map(|row| row.iter().map(|cell| cell.symbol()).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn deleting_every_note_leaves_an_empty_editor_that_saves_nothing() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");

    press(&workspace, "dydydydy");

    let screen = screen(&workspace);
    assert!(screen.contains("0 of 0"), "{screen}");
    assert!(!screen.contains("Title: Theme polish"), "{screen}");
    assert!(screen.contains("No note selected"), "{screen}");
    let form = workspace.form();
    assert!(!form.has_note());
    assert_eq!(form.title(), "");
    form.set_title("Ghost edit");
    assert_eq!(form.save(), Ok(()));
}

fn marked_rows(workspace: &WorkspaceVm) -> Vec<String> {
    workspace
        .notes()
        .visible_rows()
        .into_iter()
        .filter(|(_, selected)| *selected)
        .map(|(title, _)| title)
        .collect()
}

#[test]
fn paging_keeps_the_selection_and_j_selects_a_note_on_the_page() {
    let repository = InMemoryNoteRepository::seeded();
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");

    press(&workspace, "n");
    let screen_after_paging = screen(&workspace);
    assert!(
        screen_after_paging.contains("Title: Rust flavor parity"),
        "{screen_after_paging}"
    );
    assert!(marked_rows(&workspace).is_empty());

    press(&workspace, "j");
    let screen_after_j = screen(&workspace);
    assert!(
        screen_after_j.contains("> Documentation refresh"),
        "{screen_after_j}"
    );
    assert!(
        screen_after_j.contains("Title: Documentation refresh"),
        "{screen_after_j}"
    );

    press(&workspace, "d");
    let messages = workspace.notifications().messages();
    assert_eq!(messages, vec!["Delete note 'Documentation refresh'?"]);

    press(&workspace, "y");
    assert!(repository.note("docs-refresh").is_none());
    assert!(repository.note("rust-parity").is_some());
}

#[test]
fn a_search_that_hides_the_selection_keeps_it() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");

    press(&workspace, "j/");
    let screen_after_search = screen(&workspace);
    assert!(
        screen_after_search.contains("Title: Release channels"),
        "{screen_after_search}"
    );
    assert!(marked_rows(&workspace).is_empty());

    press(&workspace, "x");
    let screen_after_clear = screen(&workspace);
    assert!(
        screen_after_clear.contains("> Release channels"),
        "{screen_after_clear}"
    );
    assert!(
        screen_after_clear.contains("Title: Release channels"),
        "{screen_after_clear}"
    );
}

#[test]
fn j_and_k_stop_at_the_ends_of_the_page() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");

    press(&workspace, "k");
    assert_eq!(marked_rows(&workspace), vec!["Rust flavor parity"]);
    press(&workspace, "jj");
    assert_eq!(marked_rows(&workspace), vec!["Release channels"]);
    press(&workspace, "kk");
    assert_eq!(marked_rows(&workspace), vec!["Rust flavor parity"]);
}
