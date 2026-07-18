use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::time::{Duration, Instant};
use vmx::{
    AsyncRelayCommand, CancellationToken, Command, Message, MessageHub, RelayCommand,
    RelayCommandOf, VmxError, VmxResult,
};

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

#[test]
fn command_predicate_panics_map_to_not_executable() {
    let relay = RelayCommand::noop().with_can_execute(|| panic!("relay predicate"));
    let parameterized =
        RelayCommandOf::<i32>::noop().with_can_execute(|_| panic!("parameterized predicate"));
    let asynchronous = AsyncRelayCommand::noop().with_can_execute(|| panic!("async predicate"));
    let decorated = RelayCommand::noop().wrap_with(
        Some(|| panic!("decorator predicate")),
        None::<fn()>,
        None::<fn()>,
    );

    assert!(!relay.can_execute());
    assert!(!parameterized.can_execute(&1));
    assert!(!asynchronous.can_execute());
    assert!(!decorated.can_execute());
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
        sender_name: "trigger".to_string(),
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

#[test]
fn async_relay_command_immediate_cancel_is_not_lost_during_admission() {
    const RUNS: usize = 4_096;
    const RUN_TIMEOUT: Duration = Duration::from_millis(250);
    for run_number in 0..RUNS {
        let observed_cancel = Arc::new(AtomicBool::new(false));
        let observed_cancel_clone = observed_cancel.clone();
        let command = AsyncRelayCommand::new(move |token| {
            let deadline = Instant::now() + RUN_TIMEOUT;
            while !token.is_cancelled() && Instant::now() < deadline {
                std::thread::yield_now();
            }
            observed_cancel_clone.store(token.is_cancelled(), Ordering::SeqCst);
            Ok(())
        });

        let (execution_sender, execution_receiver) = mpsc::channel();
        let executing_command = command.clone();
        let starter = std::thread::spawn(move || {
            execution_sender
                .send(executing_command.execute_async())
                .unwrap();
        });
        let observation_deadline = Instant::now() + RUN_TIMEOUT;
        while !command.is_executing() && Instant::now() < observation_deadline {
            std::thread::yield_now();
        }
        assert!(
            command.is_executing(),
            "execution was not observable while admitting run {run_number}"
        );
        command.cancel();
        let execution = execution_receiver
            .recv_timeout(RUN_TIMEOUT)
            .unwrap_or_else(|_| panic!("execution handle was not returned for run {run_number}"));
        starter.join().unwrap();
        execution.join().unwrap().unwrap();

        assert!(
            observed_cancel.load(Ordering::SeqCst),
            "cancel was lost while admitting run {run_number}"
        );
    }
}

#[test]
fn async_relay_command_builder_owns_predicate_and_additive_triggers() {
    let allowed = Arc::new(AtomicBool::new(false));
    let trigger = MessageHub::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let command = AsyncRelayCommand::builder()
        .task({
            let calls = calls.clone();
            move |_| {
                calls.fetch_add(1, Ordering::SeqCst);
                Ok(())
            }
        })
        .predicate({
            let allowed = allowed.clone();
            move || allowed.load(Ordering::SeqCst)
        })
        .trigger(trigger.clone())
        .build();
    let notifications = Arc::new(AtomicUsize::new(0));
    let observed = notifications.clone();
    let _subscription = command.can_execute_changed().subscribe(move |_| {
        observed.fetch_add(1, Ordering::SeqCst);
    });

    assert!(!command.can_execute());
    trigger.send(Message::Custom {
        sender_id: 1,
        sender_name: "trigger".to_string(),
        name: "predicate_changed".to_string(),
    });
    assert_eq!(notifications.load(Ordering::SeqCst), 1);
    allowed.store(true, Ordering::SeqCst);
    command.execute_async().join().unwrap().unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn async_relay_command_routes_fire_and_forget_faults_to_errors() {
    let command = AsyncRelayCommand::new(|_| Err(VmxError::Other("boom".into())));
    let errors = Arc::new(AtomicUsize::new(0));
    let observed = errors.clone();
    let _subscription = command.errors().subscribe(move |message| {
        if matches!(message, Message::Custom { name, .. } if name == "error") {
            observed.fetch_add(1, Ordering::SeqCst);
        }
    });

    command.execute();
    while command.is_executing() {
        std::thread::yield_now();
    }

    assert_eq!(errors.load(Ordering::SeqCst), 1);
}

#[test]
fn async_relay_command_supports_default_and_throwing_cancellation_modes() {
    fn cancellable(token: CancellationToken) -> VmxResult<()> {
        while !token.is_cancelled() {
            std::thread::yield_now();
        }
        Err(VmxError::Cancelled)
    }

    let default = AsyncRelayCommand::new(cancellable);
    let run = default.execute_async();
    while !default.is_executing() {
        std::thread::yield_now();
    }
    default.cancel();
    assert_eq!(run.join().unwrap(), Ok(()));

    let throwing = AsyncRelayCommand::builder()
        .task(cancellable)
        .throw_on_cancel()
        .build();
    let run = throwing.execute_async();
    while !throwing.is_executing() {
        std::thread::yield_now();
    }
    throwing.cancel();
    assert_eq!(run.join().unwrap(), Err(VmxError::Cancelled));

    let faulting = AsyncRelayCommand::new(|token| {
        while !token.is_cancelled() {
            std::thread::yield_now();
        }
        Err(VmxError::Other("fault after cancel".into()))
    });
    let run = faulting.execute_async();
    while !faulting.is_executing() {
        std::thread::yield_now();
    }
    faulting.cancel();
    assert_eq!(
        run.join().unwrap(),
        Err(VmxError::Other("fault after cancel".into()))
    );
}

#[test]
fn async_relay_command_admits_only_one_concurrent_execution() {
    const CALLERS: usize = 8;
    let predicate_barrier = Arc::new(Barrier::new(CALLERS));
    let calls = Arc::new(AtomicUsize::new(0));
    let release = Arc::new(AtomicBool::new(false));
    let command = AsyncRelayCommand::new({
        let calls = calls.clone();
        let release = release.clone();
        move |_| {
            calls.fetch_add(1, Ordering::SeqCst);
            while !release.load(Ordering::SeqCst) {
                std::thread::yield_now();
            }
            Ok(())
        }
    })
    .with_can_execute({
        let predicate_barrier = predicate_barrier.clone();
        move || {
            predicate_barrier.wait();
            true
        }
    });

    let callers = (0..CALLERS)
        .map(|_| {
            let command = command.clone();
            std::thread::spawn(move || command.execute_async())
        })
        .collect::<Vec<_>>();
    let runs = callers
        .into_iter()
        .map(|caller| caller.join().unwrap())
        .collect::<Vec<_>>();

    release.store(true, Ordering::SeqCst);
    for run in runs {
        run.join().unwrap().unwrap();
    }

    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn async_relay_command_clears_execution_state_after_action_panic() {
    let command = AsyncRelayCommand::new(|_| -> vmx::VmxResult<()> {
        panic!("action panic");
    });

    let result = command.execute_async().join();

    assert!(result.is_err());
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
