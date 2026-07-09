use std::sync::{Arc, Mutex};

use vmx::{Command, ModeledCrudCommands};

/// COMP-019 — CreateNewCommand invokes create-new action
#[test]
fn create_new_command_invokes_action() {
    let calls = Arc::new(Mutex::new(0));
    let seen = calls.clone();
    let crud = ModeledCrudCommands::<i32>::new(
        || None,
        move || *seen.lock().unwrap() += 1,
        |_| {},
        |_| {},
    );

    crud.create_new_command().execute();

    assert_eq!(*calls.lock().unwrap(), 1);
}

/// COMP-020 — UpdateCurrentCommand invokes update with current VM
#[test]
fn update_current_command_invokes_update_with_current() {
    let current = Arc::new(Mutex::new(Some(7)));
    let updated = Arc::new(Mutex::new(Vec::new()));
    let source = current.clone();
    let seen = updated.clone();
    let crud = ModeledCrudCommands::new(
        move || *source.lock().unwrap(),
        || {},
        move |item| seen.lock().unwrap().push(item),
        |_| {},
    );

    crud.update_current_command().execute();

    assert_eq!(updated.lock().unwrap().clone(), vec![7]);
}

/// COMP-021 — UpdateCurrentCommand.CanExecute false when current is null
#[test]
fn update_current_command_can_execute_false_without_current() {
    let crud = ModeledCrudCommands::<i32>::new(|| None, || {}, |_| {}, |_| {});

    assert!(!crud.update_current_command().can_execute());
}

/// COMP-022 — DeleteCurrentCommand invokes delete with current VM
#[test]
fn delete_current_command_invokes_delete_with_current() {
    let deleted = Arc::new(Mutex::new(Vec::new()));
    let seen = deleted.clone();
    let crud = ModeledCrudCommands::new(
        || Some(3),
        || {},
        |_| {},
        move |item| seen.lock().unwrap().push(item),
    );

    crud.delete_current_command().execute();

    assert_eq!(deleted.lock().unwrap().clone(), vec![3]);
}

/// COMP-023 — DeleteCurrentCommand.CanExecute false when current is null
#[test]
fn delete_current_command_can_execute_false_without_current() {
    let crud = ModeledCrudCommands::<i32>::new(|| None, || {}, |_| {}, |_| {});

    assert!(!crud.delete_current_command().can_execute());
}

/// COMP-024 — DeleteCurrentCommand confirm gate
#[test]
fn delete_current_command_confirm_gate_blocks_and_allows_delete() {
    let deleted = Arc::new(Mutex::new(Vec::new()));
    let blocked_seen = deleted.clone();
    let blocked = ModeledCrudCommands::with_confirm_delete(
        || Some(1),
        || {},
        |_| {},
        move |item| blocked_seen.lock().unwrap().push(item),
        || false,
    );
    blocked.delete_current_command().execute();
    assert!(deleted.lock().unwrap().is_empty());

    let allowed_seen = deleted.clone();
    let allowed = ModeledCrudCommands::with_confirm_delete(
        || Some(2),
        || {},
        |_| {},
        move |item| allowed_seen.lock().unwrap().push(item),
        || true,
    );
    allowed.delete_current_command().execute();

    assert_eq!(deleted.lock().unwrap().clone(), vec![2]);
}
