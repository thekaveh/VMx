use notes_showcase::{InMemoryNoteRepository, WorkspaceVm};
use pretty_assertions::assert_eq;

#[test]
fn workspace_bootstraps_default_selection_and_vm_owned_sections() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");

    assert_eq!(workspace.notebooks().current_title(), "Product");
    assert_eq!(
        workspace.notes().visible_titles(),
        vec!["Rust flavor parity", "Release channels"]
    );
    assert_eq!(workspace.notes().page_summary(), "1-2 of 4");
    assert_eq!(workspace.form().title(), "Rust flavor parity");
    assert_eq!(workspace.editor().mode(), "edit");
}

#[test]
fn notes_search_filtering_and_paging_are_owned_by_notes_vm() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");
    let notes = workspace.notes();

    notes.set_search_term("docs");
    assert_eq!(notes.visible_titles(), vec!["Documentation refresh"]);
    assert_eq!(notes.page_summary(), "1-1 of 1");

    notes.set_search_term("");
    assert_eq!(
        notes.visible_titles(),
        vec!["Rust flavor parity", "Release channels"]
    );
    notes.next_page();
    assert_eq!(
        notes.visible_titles(),
        vec!["Documentation refresh", "Theme polish"]
    );
    assert_eq!(notes.page_summary(), "3-4 of 4");
}

#[test]
fn form_validation_save_and_revert_use_form_vm_contracts() {
    let repository = InMemoryNoteRepository::seeded();
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");
    let form = workspace.form();

    form.set_title("");
    assert!(!form.is_valid());
    assert_eq!(form.title_error(), Some("Title is required".to_string()));
    assert!(form.save().is_err());

    form.set_title("Rust VMx showcase");
    form.set_body("A terminal app with a pure VMx view model layer.");
    assert!(form.is_valid());
    assert!(form.is_dirty());
    form.save().expect("valid draft persists");
    assert!(!form.is_dirty());
    assert_eq!(
        repository.note("rust-parity").expect("saved note").title,
        "Rust VMx showcase"
    );

    form.set_title("Unsaved title");
    assert!(form.is_dirty());
    form.revert();
    assert_eq!(form.title(), "Rust VMx showcase");
    assert!(!form.is_dirty());
}

#[test]
fn global_search_uses_token_paging_and_can_load_more_results() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");
    let search = workspace.global_search();

    search.set_query("vmx");
    search.refresh();
    assert_eq!(
        search.result_titles(),
        vec!["Rust flavor parity", "VMx inspector notes"]
    );
    assert!(search.can_load_more());

    search.load_more();
    assert_eq!(
        search.result_titles(),
        vec!["Rust flavor parity", "VMx inspector notes", "Theme polish"]
    );
    assert!(!search.can_load_more());
}

#[test]
fn editor_mode_and_delete_confirmation_are_vm_commands() {
    let repository = InMemoryNoteRepository::seeded();
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");

    workspace.editor().show_preview();
    assert_eq!(workspace.editor().mode(), "preview");
    workspace.editor().show_edit();
    assert_eq!(workspace.editor().mode(), "edit");
    workspace.editor().toggle();
    assert_eq!(workspace.editor().mode(), "preview");

    workspace.request_delete_current();
    assert_eq!(
        workspace.notifications().messages(),
        vec!["Delete note 'Rust flavor parity'?"]
    );
    workspace.reject_delete_current();
    assert!(repository.note("rust-parity").is_some());

    workspace.request_delete_current();
    workspace.approve_delete_current();
    assert!(repository.note("rust-parity").is_none());
    assert_eq!(
        workspace.notifications().messages(),
        vec!["Deleted 'Rust flavor parity'"]
    );
}
