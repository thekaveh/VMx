//! Drives the app through its key bindings and renders it with ratatui's
//! `TestBackend`, the way a user sees it.

use crossterm::event::KeyCode;
use notes_showcase::app::handle_key;
use notes_showcase::{views, WorkspaceVm};
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

#[test]
fn paging_moves_the_selection_so_delete_targets_a_visible_note() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");

    press(&workspace, "n");
    let screen_after_paging = screen(&workspace);
    assert!(
        screen_after_paging.contains("> Documentation refresh"),
        "{screen_after_paging}"
    );
    assert!(
        screen_after_paging.contains("Title: Documentation refresh"),
        "{screen_after_paging}"
    );

    press(&workspace, "d");
    let messages = workspace.notifications().messages();
    assert_eq!(messages, vec!["Delete note 'Documentation refresh'?"]);

    press(&workspace, "y");
    let screen_after_delete = screen(&workspace);
    assert!(
        !screen_after_delete.contains("Documentation refresh'?"),
        "{screen_after_delete}"
    );
    assert!(screen_after_delete.contains("> "), "{screen_after_delete}");
}

#[test]
fn a_search_that_hides_the_selection_moves_it_to_a_visible_note() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");

    press(&workspace, "n/");
    let screen = screen(&workspace);
    let selected = screen
        .lines()
        .find_map(|line| line.split("> ").nth(1))
        .map(|rest| rest.split('│').next().unwrap_or("").trim().to_string())
        .expect("a visible note is marked");
    assert_eq!(workspace.notes().current_title(), selected);
    assert!(workspace.notes().visible_titles().contains(&selected));
}
