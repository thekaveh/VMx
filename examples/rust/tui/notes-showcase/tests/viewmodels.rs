use notes_showcase::models::note_matches;
use notes_showcase::viewmodels::{NoteFormVm, NotificationEntry};
use notes_showcase::{InMemoryNoteRepository, NoteModel, NotebookModel, WorkspaceVm};
use pretty_assertions::assert_eq;
use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::thread;
use std::time::Duration;
use vmx::{
    Command, ConstructionStatus, NotificationReaction, NotificationType, VirtualTimeScheduler,
    VmNode,
};

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
fn global_search_load_more_continues_the_term_of_the_loaded_pages() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");
    let search = workspace.global_search();

    search.set_query("vmx");
    search.refresh();
    search.set_query("in");
    search.load_more();

    assert_eq!(
        search.result_titles(),
        vec!["Rust flavor parity", "VMx inspector notes", "Theme polish"]
    );
}

#[test]
fn global_search_refresh_for_another_term_replaces_the_loaded_pages() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");
    let search = workspace.global_search();

    search.set_query("in");
    search.refresh();
    search.load_more();
    assert_eq!(search.result_titles().len(), 4);

    // The first `and` page equals the head of the `in` results by note, but
    // not by term, so the refresh replaces the pages and their cursor.
    search.set_query("and");
    search.refresh();
    assert_eq!(
        search.result_titles(),
        vec!["Release channels", "Documentation refresh"]
    );
    assert!(search.can_load_more());

    search.load_more();
    assert_eq!(
        search.result_titles(),
        vec![
            "Release channels",
            "Documentation refresh",
            "VMx inspector notes"
        ]
    );
    assert!(!search.can_load_more());
}

/// Asserts that every result matches `term` and that no title repeats.
fn assert_results_match_once(titles: &[String], repository: &InMemoryNoteRepository, term: &str) {
    let notes = repository.notes();
    for title in titles {
        let note = notes
            .iter()
            .find(|note| &note.title == title)
            .expect("each result is a repository note");
        assert!(
            note_matches(note, term),
            "{title:?} does not match {term:?}: {titles:?}"
        );
    }
    let mut unique = titles.to_vec();
    unique.sort();
    unique.dedup();
    assert_eq!(unique.len(), titles.len(), "a title repeats: {titles:?}");
}

#[test]
fn global_search_load_more_does_nothing_while_a_refresh_runs() {
    let repository = InMemoryNoteRepository::seeded();
    let (entered_tx, entered) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    let release_rx = Mutex::new(release_rx);
    repository.set_search_hook(move |term, offset| {
        // Hold the first `in` page fetch until the test releases it.
        if term == "in" && offset == 0 {
            let _ = entered_tx.send(());
            release_rx
                .lock()
                .unwrap()
                .recv_timeout(TIMEOUT)
                .expect("the test releases the refresh");
        }
    });
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");
    let search = workspace.global_search();
    search.set_query("vmx");
    search.refresh();
    search.set_query("in");

    let (done, refreshed) = mpsc::channel();
    thread::spawn({
        let search = search.clone();
        move || {
            search.refresh();
            let _ = done.send(());
        }
    });
    entered
        .recv_timeout(TIMEOUT)
        .expect("the refresh fetches the first page");
    assert!(!search.can_load_more());
    search.load_more();
    release.send(()).unwrap();
    refreshed
        .recv_timeout(TIMEOUT)
        .expect("the refresh settles");

    let titles = search.result_titles();
    assert_eq!(titles, vec!["Release channels", "Documentation refresh"]);
    assert_results_match_once(&titles, &repository, "in");
    assert!(search.can_load_more());
}

/// Runs `refresh()` and `load_more()` together on two threads after the
/// first `vmx` page loads and the query becomes `term`.
fn race_refresh_and_load_more(term: &'static str, hold_first_page: bool, run: usize) {
    let repository = InMemoryNoteRepository::seeded();
    if hold_first_page {
        // A short first-page fetch gives a racing load time to start during
        // the refresh and discard it.
        repository.set_search_hook(move |searched, offset| {
            if searched == term && offset == 0 {
                thread::sleep(Duration::from_micros(200));
            }
        });
    }
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");
    let search = workspace.global_search();
    search.set_query("vmx");
    search.refresh();
    search.set_query(term);

    let start = Arc::new(Barrier::new(2));
    let (done, settled) = mpsc::channel();
    for refresh in [true, false] {
        let search = search.clone();
        let start = Arc::clone(&start);
        let done = done.clone();
        thread::spawn(move || {
            start.wait();
            if refresh {
                search.refresh();
            } else {
                search.load_more();
            }
            let _ = done.send(());
        });
    }
    for _ in 0..2 {
        settled
            .recv_timeout(TIMEOUT)
            .unwrap_or_else(|_| panic!("{term} run {run}: refresh and load more settle"));
    }

    let titles = search.result_titles();
    assert!(!titles.is_empty(), "{term} run {run}: no results");
    assert_results_match_once(&titles, &repository, term);
    workspace.dispose().expect("workspace disposes");
}

#[test]
fn global_search_racing_refresh_and_load_more_keep_one_term() {
    const RUNS: usize = 300;
    for run in 0..RUNS {
        // A load that starts during the refresh discards it, so the search
        // runs again.
        race_refresh_and_load_more("in", true, run);
        // `theme` has one page. A load admitted before the refresh commits
        // that terminal page fetches nothing (#1161), so page one is not
        // appended twice.
        race_refresh_and_load_more("theme", false, run);
    }
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
fn a_notification_expires_after_its_lifespan() {
    let scheduler = VirtualTimeScheduler::new();
    let workspace =
        WorkspaceVm::with_scheduler(InMemoryNoteRepository::seeded(), scheduler.clone())
            .expect("workspace builds");
    let notifications = workspace.notifications();
    notifications.post(NotificationType::Notification, "saved");

    scheduler.advance_by(Duration::from_secs(59));
    assert_eq!(notifications.messages(), vec!["saved"]);

    scheduler.advance_by(Duration::from_secs(1));
    assert!(notifications.messages().is_empty());
}

#[test]
fn a_delete_confirmation_stays_pending_past_its_lifespan() {
    let scheduler = VirtualTimeScheduler::new();
    let repository = InMemoryNoteRepository::seeded();
    let workspace = WorkspaceVm::with_scheduler(repository.clone(), scheduler.clone())
        .expect("workspace builds");

    workspace.request_delete_current();
    scheduler.advance_by(Duration::from_secs(600));
    assert_eq!(
        workspace.notifications().messages(),
        vec!["Delete note 'Rust flavor parity'?"]
    );

    workspace.approve_delete_current();
    assert!(repository.note("rust-parity").is_none());
}

#[test]
fn a_delete_confirmation_dropped_over_the_cap_deletes_nothing_and_frees_the_slot() {
    let repository = InMemoryNoteRepository::seeded();
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");
    let notifications = workspace.notifications();

    workspace.request_delete_current();
    let NotificationEntry::Confirmation(confirmation) = notifications.visible()[0].clone() else {
        panic!("a delete request posts a confirmation");
    };
    for index in 0..5 {
        notifications.post(NotificationType::Notification, format!("n{index}"));
    }
    assert_eq!(confirmation.reaction(), NotificationReaction::Reject);

    workspace.approve_delete_current();
    assert!(repository.note("rust-parity").is_some());

    workspace.request_delete_current();
    assert!(notifications
        .messages()
        .contains(&"Delete note 'Rust flavor parity'?".to_string()));
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

/// A disposed notification entry has an inert dismiss command.
fn is_disposed(vm: &NotificationEntry) -> bool {
    !vm.dismiss_command().can_execute()
}

#[test]
fn a_resolved_notification_entry_is_disposed() {
    let workspace = WorkspaceVm::seeded().unwrap();
    let notifications = workspace.notifications();
    let id = notifications.post(NotificationType::Notification, "saved");
    let entry = notifications.visible()[0].clone();

    notifications.resolve(id, NotificationReaction::Approve);

    assert!(notifications.visible().is_empty());
    assert!(is_disposed(&entry));
}

#[test]
fn a_notification_dropped_over_the_cap_is_dismissed_and_disposed() {
    let workspace = WorkspaceVm::seeded().unwrap();
    let notifications = workspace.notifications();
    notifications.post(NotificationType::Notification, "oldest");
    let oldest = notifications.visible()[0].clone();

    for index in 0..5 {
        notifications.post(NotificationType::Notification, format!("n{index}"));
    }

    assert!(oldest.is_resolved());
    assert!(is_disposed(&oldest));
    assert!(notifications.visible().iter().all(|vm| !is_disposed(vm)));
}

#[test]
fn workspace_dispose_disposes_the_remaining_notification_entries() {
    let workspace = WorkspaceVm::seeded().unwrap();
    let notifications = workspace.notifications();
    notifications.post(NotificationType::Notification, "first");
    notifications.post(NotificationType::Confirmation, "second");
    let entries = notifications.visible();

    workspace.dispose().unwrap();

    assert_eq!(entries.len(), 2);
    assert!(entries.iter().all(is_disposed));
    assert!(notifications.visible().is_empty());
}

#[test]
fn switching_notebooks_starts_on_the_first_page() {
    let note = |id: &str, notebook: &str| NoteModel {
        id: id.to_string(),
        notebook_id: notebook.to_string(),
        title: id.to_string(),
        body: String::new(),
        tags: Vec::new(),
        starred: false,
    };
    let repository = InMemoryNoteRepository::new(
        vec![
            NotebookModel {
                id: "a".to_string(),
                title: "A".to_string(),
            },
            NotebookModel {
                id: "b".to_string(),
                title: "B".to_string(),
            },
        ],
        vec![
            note("a1", "a"),
            note("a2", "a"),
            note("a3", "a"),
            note("b1", "b"),
            note("b2", "b"),
            note("b3", "b"),
        ],
    );
    let workspace = WorkspaceVm::new(repository).expect("workspace builds");
    let notes = workspace.notes();
    notes.set_notebook("a");
    notes.next_page();
    assert!(notes.page_summary().starts_with("3-"));

    notes.set_notebook("b");

    assert!(
        notes.page_summary().starts_with("1-"),
        "{}",
        notes.page_summary()
    );
}

#[test]
fn a_saved_note_updates_its_row_search_delete_prompt_and_later_loads() {
    let repository = InMemoryNoteRepository::seeded();
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");
    let form = workspace.form();

    form.set_title("Rust VMx showcase");
    form.save().expect("valid draft persists");

    // The list row and local search see the saved title.
    assert_eq!(
        workspace.notes().visible_titles(),
        vec!["Rust VMx showcase", "Release channels"]
    );
    workspace.set_search_term("showcase");
    assert_eq!(
        workspace.notes().visible_titles(),
        vec!["Rust VMx showcase"]
    );
    workspace.set_search_term("");

    // Selecting another note and back reloads the editor from the saved row.
    workspace
        .select_note("release-channels")
        .expect("note selects");
    workspace.select_note("rust-parity").expect("note selects");
    assert_eq!(form.title(), "Rust VMx showcase");

    // The delete prompt names the saved title.
    workspace.request_delete_current();
    assert_eq!(
        workspace.notifications().messages(),
        vec!["Delete note 'Rust VMx showcase'?"]
    );
    workspace.reject_delete_current();

    // A later save keeps the saved title instead of writing the old one back.
    form.set_body("Edited later.");
    form.save().expect("later save persists");
    let saved = repository.note("rust-parity").expect("saved note");
    assert_eq!(saved.title, "Rust VMx showcase");
    assert_eq!(saved.body, "Edited later.");
}

#[test]
fn paging_searching_or_switching_notebooks_cancels_a_pending_delete() {
    type Change = fn(&WorkspaceVm);
    let changes: [(&str, Change); 4] = [
        ("next page", |workspace| workspace.next_page()),
        ("previous page", |workspace| workspace.previous_page()),
        ("search", |workspace| workspace.set_search_term("docs")),
        ("notebook", |workspace| {
            workspace.select_notebook("engineering").unwrap()
        }),
    ];
    for (name, change) in changes {
        let repository = InMemoryNoteRepository::seeded();
        let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");

        workspace.request_delete_current();
        change(&workspace);
        assert!(
            workspace.notifications().messages().is_empty(),
            "{name}: the delete prompt is still pending"
        );
        workspace.approve_delete_current();
        assert!(
            repository.note("rust-parity").is_some(),
            "{name}: `y` deleted a note that left the screen"
        );
    }
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

// ADR-0201 §2.1: a search or a page change never changes the current note,
// and the editor keeps its draft while the note is hidden.
#[test]
fn a_search_that_hides_the_current_note_keeps_it_and_its_draft() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");
    let form = workspace.form();
    workspace
        .select_note("release-channels")
        .expect("note selects");
    form.set_title("Release draft");

    workspace.set_search_term("docs");
    let current = workspace.notes().current_note().expect("a current note");
    assert_eq!(current.id, "release-channels");
    assert_eq!(form.title(), "Release draft");
    assert!(form.is_dirty());
    assert!(marked_rows(&workspace).is_empty());

    workspace.set_search_term("");
    let current = workspace.notes().current_note().expect("a current note");
    assert_eq!(current.id, "release-channels");
    assert_eq!(form.title(), "Release draft");
    assert!(form.is_dirty());
    assert_eq!(marked_rows(&workspace), vec!["Release channels"]);
}

#[test]
fn a_page_change_keeps_the_current_note_and_its_draft() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");
    let form = workspace.form();
    form.set_title("Parity draft");

    workspace.next_page();
    let current = workspace.notes().current_note().expect("a current note");
    assert_eq!(current.id, "rust-parity");
    assert_eq!(form.title(), "Parity draft");
    assert!(marked_rows(&workspace).is_empty());

    workspace.previous_page();
    assert_eq!(form.title(), "Parity draft");
    assert_eq!(marked_rows(&workspace), vec!["Rust flavor parity"]);
}

// ADR-0201 §2.2: selecting another note discards the unsaved draft with no
// prompt, and the repository keeps the stored values.
#[test]
fn selecting_another_note_discards_the_unsaved_draft() {
    let repository = InMemoryNoteRepository::seeded();
    let workspace = WorkspaceVm::new(repository.clone()).expect("workspace builds");
    let form = workspace.form();
    workspace.select_note("rust-parity").expect("note selects");
    form.set_title("Unsaved draft");
    assert!(form.is_dirty());

    workspace
        .select_note("release-channels")
        .expect("note selects");
    assert_eq!(form.title(), "Release channels");
    assert!(!form.is_dirty());

    workspace.select_note("rust-parity").expect("note selects");
    assert_eq!(form.title(), "Rust flavor parity");
    assert!(!form.is_dirty());
    assert_eq!(
        repository.note("rust-parity").expect("stored note").title,
        "Rust flavor parity"
    );
}

#[test]
fn select_next_and_previous_note_stay_on_the_visible_page() {
    let workspace = WorkspaceVm::seeded().expect("workspace builds");
    let form = workspace.form();
    form.set_title("Parity draft");

    // At the first row, the previous-note step keeps the selection and draft.
    workspace.select_previous_note();
    assert_eq!(marked_rows(&workspace), vec!["Rust flavor parity"]);
    assert_eq!(form.title(), "Parity draft");

    workspace.select_next_note();
    assert_eq!(marked_rows(&workspace), vec!["Release channels"]);
    assert_eq!(form.title(), "Release channels");

    // At the last row, the next-note step keeps the selection.
    workspace.select_next_note();
    assert_eq!(marked_rows(&workspace), vec!["Release channels"]);

    workspace.select_previous_note();
    assert_eq!(marked_rows(&workspace), vec!["Rust flavor parity"]);
    assert_eq!(form.title(), "Rust flavor parity");

    // When the current note is not on the page, both steps select the first
    // visible note.
    workspace.next_page();
    workspace.select_previous_note();
    assert_eq!(marked_rows(&workspace), vec!["Documentation refresh"]);
    assert_eq!(form.title(), "Documentation refresh");
    workspace.previous_page();
    workspace.select_next_note();
    assert_eq!(marked_rows(&workspace), vec!["Rust flavor parity"]);

    // With an empty page, both steps keep the selection.
    workspace.set_search_term("no such note");
    workspace.select_next_note();
    workspace.select_previous_note();
    let current = workspace.notes().current_note().expect("a current note");
    assert_eq!(current.id, "rust-parity");
}
