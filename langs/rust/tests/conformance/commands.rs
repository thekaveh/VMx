use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use vmx::{AsyncRelayCommand, Command, Message, MessageHub, RelayCommand, RelayCommandOf};

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

/// CMD-014 — imperative raise emits once without evaluating delegates
#[test]
fn imperative_raise_emits_once_without_evaluating_delegates() {
    let predicate_calls = Arc::new(AtomicUsize::new(0));
    let predicate_calls_clone = predicate_calls.clone();
    let task_calls = Arc::new(AtomicUsize::new(0));
    let task_calls_clone = task_calls.clone();
    let command = RelayCommand::new(move || {
        task_calls_clone.fetch_add(1, Ordering::SeqCst);
    })
    .with_can_execute(move || {
        predicate_calls_clone.fetch_add(1, Ordering::SeqCst);
        true
    });
    let fired = Arc::new(AtomicUsize::new(0));
    let fired_clone = fired.clone();
    let _subscription = command.can_execute_changed().subscribe(move |_| {
        fired_clone.fetch_add(1, Ordering::SeqCst);
    });

    command.raise_can_execute_changed();

    assert_eq!(fired.load(Ordering::SeqCst), 1);
    assert_eq!(predicate_calls.load(Ordering::SeqCst), 0);
    assert_eq!(task_calls.load(Ordering::SeqCst), 0);
}

/// CMD-015 — repeated imperative and trigger notifications are additive
#[test]
fn repeated_imperative_and_trigger_notifications_are_additive() {
    let trigger = MessageHub::new();
    let command = RelayCommand::builder().trigger(trigger.clone()).build();
    let fired = Arc::new(AtomicUsize::new(0));
    let fired_clone = fired.clone();
    let _subscription = command.can_execute_changed().subscribe(move |_| {
        fired_clone.fetch_add(1, Ordering::SeqCst);
    });

    command.raise_can_execute_changed();
    command.raise_can_execute_changed();
    trigger.send(Message::Custom {
        sender_id: 0,
        name: "trigger".to_string(),
    });

    assert_eq!(fired.load(Ordering::SeqCst), 3);
}

/// CMD-016 — imperative raise after disposal is a no-op
#[test]
fn imperative_raise_after_disposal_is_noop() {
    let relay = RelayCommand::noop();
    let parameterized = RelayCommandOf::<i32>::noop();
    let async_command = AsyncRelayCommand::noop();
    relay.dispose();
    parameterized.dispose();
    async_command.dispose();
    let fired = Arc::new(AtomicUsize::new(0));
    let subscriptions = [
        relay.can_execute_changed(),
        parameterized.can_execute_changed(),
        async_command.can_execute_changed(),
    ]
    .into_iter()
    .map(|hub| {
        let fired = fired.clone();
        hub.subscribe(move |_| {
            fired.fetch_add(1, Ordering::SeqCst);
        })
    })
    .collect::<Vec<_>>();

    relay.raise_can_execute_changed();
    parameterized.raise_can_execute_changed();
    async_command.raise_can_execute_changed();

    assert_eq!(fired.load(Ordering::SeqCst), 0);
    drop(subscriptions);
}

/// CMD-017 — parameterized imperative raise emits exactly once
#[test]
fn parameterized_imperative_raise_emits_once() {
    let command = RelayCommandOf::<i32>::noop();
    let fired = Arc::new(AtomicUsize::new(0));
    let fired_clone = fired.clone();
    let _subscription = command.can_execute_changed().subscribe(move |_| {
        fired_clone.fetch_add(1, Ordering::SeqCst);
    });

    command.raise_can_execute_changed();

    assert_eq!(fired.load(Ordering::SeqCst), 1);
}

/// CMD-018 — async imperative raise while idle emits exactly once
#[test]
fn async_imperative_raise_while_idle_emits_once() {
    let command = AsyncRelayCommand::noop();
    let fired = Arc::new(AtomicUsize::new(0));
    let fired_clone = fired.clone();
    let _subscription = command.can_execute_changed().subscribe(move |_| {
        fired_clone.fetch_add(1, Ordering::SeqCst);
    });

    command.raise_can_execute_changed();

    assert_eq!(fired.load(Ordering::SeqCst), 1);
}

/// CMD-019 — async imperative raise while in flight is additive with state flips
#[test]
fn async_imperative_raise_while_in_flight_is_additive() {
    let release = Arc::new(AtomicBool::new(false));
    let release_clone = release.clone();
    let command = AsyncRelayCommand::new(move |_| {
        while !release_clone.load(Ordering::SeqCst) {
            std::thread::yield_now();
        }
        Ok(())
    });
    let fired = Arc::new(AtomicUsize::new(0));
    let fired_clone = fired.clone();
    let _subscription = command.can_execute_changed().subscribe(move |_| {
        fired_clone.fetch_add(1, Ordering::SeqCst);
    });

    let run = command.execute_async();
    while !command.is_executing() {
        std::thread::yield_now();
    }
    assert_eq!(fired.load(Ordering::SeqCst), 1);
    command.raise_can_execute_changed();
    assert_eq!(fired.load(Ordering::SeqCst), 2);
    release.store(true, Ordering::SeqCst);
    run.join().unwrap().unwrap();

    assert_eq!(fired.load(Ordering::SeqCst), 3);
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
