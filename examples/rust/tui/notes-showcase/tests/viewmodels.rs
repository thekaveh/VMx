use notes_showcase::viewmodels::NoteFormVm;
use notes_showcase::{InMemoryNoteRepository, WorkspaceVm};
use pretty_assertions::assert_eq;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;
use vmx::{ConstructionStatus, NotificationType, VmNode};

const TIMEOUT: Duration = Duration::from_secs(5);

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
    assert_eq!(form.title_error(), Some("Title is required.".to_string()));
    form.save().expect("invalid direct save is a no-op");
    assert_eq!(
        repository.note("rust-parity").expect("original note").title,
        "Rust flavor parity"
    );

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
fn a_double_save_while_the_save_is_pending_persists_once() {
    let repository = InMemoryNoteRepository::seeded();
    let saved = Arc::new(Mutex::new(Vec::new()));
    let reentrant = Arc::new(Mutex::new(Vec::new()));
    let form_slot = Arc::new(Mutex::new(None::<NoteFormVm>));
    let (entered_tx, entered) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    let release_rx = Mutex::new(release_rx);
    repository.set_save_hook({
        let saved = Arc::clone(&saved);
        let reentrant = Arc::clone(&reentrant);
        let form_slot = Arc::clone(&form_slot);
        move |_, draft| {
            saved.lock().unwrap().push(draft.title.clone());
            // Saving again from inside the pending save does nothing.
            let form = form_slot.lock().unwrap().take();
            if let Some(form) = form {
                reentrant.lock().unwrap().push(form.save());
            }
            let _ = entered_tx.send(());
            release_rx
                .lock()
                .unwrap()
                .recv_timeout(TIMEOUT)
                .expect("the test releases the pending save");
        }
    });
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");
    let form = workspace.form();
    *form_slot.lock().unwrap() = Some(form.clone());
    form.set_title("Saved once");

    let (done, pending) = mpsc::channel();
    thread::spawn({
        let form = form.clone();
        move || {
            let _ = done.send(form.save());
        }
    });
    entered
        .recv_timeout(TIMEOUT)
        .expect("the first save is pending");
    form.save()
        .expect("a second save while one is pending is a no-op");
    release.send(()).unwrap();

    assert_eq!(
        pending
            .recv_timeout(TIMEOUT)
            .expect("the first save settles"),
        Ok(())
    );
    assert_eq!(*saved.lock().unwrap(), vec!["Saved once"]);
    assert_eq!(*reentrant.lock().unwrap(), vec![Ok(())]);
    assert_eq!(
        repository.note("rust-parity").expect("saved note").title,
        "Saved once"
    );
    assert!(!form.is_dirty());

    // Once the save settles, the next one persists.
    form.set_title("Saved twice");
    release.send(()).unwrap();
    form.save().expect("the next save persists");
    assert_eq!(*saved.lock().unwrap(), vec!["Saved once", "Saved twice"]);
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
fn global_search_refresh_after_the_last_page_keeps_results_without_duplicates() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");
    let search = workspace.global_search();
    let all = vec!["Rust flavor parity", "VMx inspector notes", "Theme polish"];

    search.set_query("vmx");
    search.refresh();
    search.load_more();
    search.refresh();

    assert_eq!(search.result_titles(), all);
    assert!(!search.can_load_more());
    search.load_more();
    assert_eq!(search.result_titles(), all);
}

#[test]
fn a_repeated_delete_request_keeps_one_resolvable_confirmation() {
    let repository = InMemoryNoteRepository::seeded();
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");

    workspace.request_delete_current();
    workspace.request_delete_current();
    assert_eq!(
        workspace.notifications().messages(),
        vec!["Delete note 'Rust flavor parity'?"]
    );

    workspace.reject_delete_current();
    assert!(workspace.notifications().messages().is_empty());
    assert!(repository.note("rust-parity").is_some());
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

#[test]
fn workspace_dispose_disposes_the_tree() {
    let workspace = WorkspaceVm::seeded().unwrap();
    let notifications = workspace.notifications();

    workspace.dispose().unwrap();

    assert_eq!(notifications.status(), ConstructionStatus::Disposed);
}

#[test]
fn notifications_over_the_cap_are_dismissed() {
    let workspace = WorkspaceVm::seeded().unwrap();
    let notifications = workspace.notifications();

    for index in 0..8 {
        notifications.post(NotificationType::Notification, format!("n{index}"));
    }

    let messages = notifications.messages();
    assert_eq!(messages.len(), 5);
    assert_eq!(messages.last().map(String::as_str), Some("n7"));
}
