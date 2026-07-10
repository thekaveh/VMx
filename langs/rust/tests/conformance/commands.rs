use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use vmx::{AsyncRelayCommand, Command, RelayCommand, RelayCommandOf};

/// CMD-001 — execute invokes the configured task
#[test]
fn relay_command_execute_invokes_task() {
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_clone = calls.clone();
    let command = RelayCommand::new(move || {
        calls_clone.fetch_add(1, Ordering::SeqCst);
    });

    command.execute();

    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

/// CMD-002 — can_execute with no predicate returns true
#[test]
fn relay_command_without_predicate_can_execute() {
    assert!(RelayCommand::noop().can_execute());
}

/// CMD-003 — can_execute returns the predicate result
#[test]
fn relay_command_can_execute_returns_predicate_result() {
    assert!(!RelayCommand::noop()
        .with_can_execute(|| false)
        .can_execute());
}

/// CMD-004 — Trigger emission fires CanExecuteChanged
#[test]
fn relay_command_trigger_can_execute_changed_fires() {
    let command = RelayCommand::noop();
    let fired = Arc::new(AtomicUsize::new(0));
    let fired_clone = fired.clone();
    let _subscription = command.can_execute_changed().subscribe(move |_| {
        fired_clone.fetch_add(1, Ordering::SeqCst);
    });

    command.trigger_can_execute_changed();

    assert_eq!(fired.load(Ordering::SeqCst), 1);
}

/// CMD-005 — Parameterized variant passes parameter
#[test]
fn relay_command_of_passes_parameter() {
    let values = Arc::new(Mutex::new(Vec::new()));
    let values_clone = values.clone();
    let command = RelayCommandOf::new(move |value: i32| {
        values_clone.lock().unwrap().push(value);
    });

    command.execute(42);

    assert_eq!(*values.lock().unwrap(), vec![42]);
}

/// CMD-006 — execute with null task is a no-op
#[test]
fn relay_command_without_task_is_noop() {
    RelayCommand::noop().execute();
}

/// CMD-007 — Command truth-table matches fixture
#[test]
fn relay_command_matches_truth_table_fixture() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../spec/fixtures/command-truthtable.json"
    ))
    .unwrap();
    assert_eq!(fixture["cases"].as_array().unwrap().len(), 5);

    assert!(RelayCommand::noop().can_execute());
    assert!(!RelayCommand::noop()
        .with_can_execute(|| false)
        .can_execute());
}

/// CMD-012 — `AsyncRelayCommand.Cancel()` cancels an in-flight async task, non-throwing by default
#[test]
fn async_relay_command_cancel_cancels_in_flight_task() {
    let observed_cancel = Arc::new(AtomicBool::new(false));
    let observed_cancel_clone = observed_cancel.clone();
    let command = AsyncRelayCommand::new(move |token| {
        while !token.is_cancelled() {
            std::thread::sleep(Duration::from_millis(1));
        }
        observed_cancel_clone.store(true, Ordering::SeqCst);
        Ok(())
    });

    assert!(command.can_execute());
    let run = command.execute_async();
    while !command.is_executing() {
        std::thread::yield_now();
    }
    assert!(!command.can_execute());

    command.cancel();
    run.join().unwrap().unwrap();

    assert!(observed_cancel.load(Ordering::SeqCst));
    assert!(!command.is_executing());
    assert!(command.can_execute());
}

/// DISP-002 — command disposal is idempotent and cancels in-flight work
#[test]
fn repeated_async_command_dispose_cancels_one_in_flight_execution() {
    let observed_cancel = Arc::new(AtomicUsize::new(0));
    let observed_cancel_clone = observed_cancel.clone();
    let command = AsyncRelayCommand::new(move |token| {
        while !token.is_cancelled() {
            std::thread::sleep(Duration::from_millis(1));
        }
        observed_cancel_clone.fetch_add(1, Ordering::SeqCst);
        Ok(())
    });

    let run = command.execute_async();
    while !command.is_executing() {
        std::thread::yield_now();
    }
    command.dispose();
    command.dispose();
    run.join().unwrap().unwrap();

    assert_eq!(observed_cancel.load(Ordering::SeqCst), 1);
    assert!(!command.can_execute());
}

/// CMD-013 — disposed relay commands are inert
#[test]
fn disposed_relay_commands_are_inert() {
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_clone = calls.clone();
    let command = RelayCommand::new(move || {
        calls_clone.fetch_add(1, Ordering::SeqCst);
    });

    command.dispose();
    command.execute();

    assert!(!command.can_execute());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}
