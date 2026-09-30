use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use vmx::{
    AsyncRelayCommand, AsyncValue, Command, CompositeCommand, ConfirmationDecoratorCommand,
    DecoratorCommand, Message, RelayCommand, VmxError,
};

fn recording_command(
    log: Arc<Mutex<Vec<&'static str>>>,
    label: &'static str,
    enabled: bool,
) -> RelayCommand {
    RelayCommand::new(move || log.lock().unwrap().push(label)).with_can_execute(move || enabled)
}

/// CMDD-001 — CompositeCommand.CanExecute is OR over inner commands
#[test]
fn composite_command_can_execute_is_or() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let disabled = recording_command(log.clone(), "disabled", false);
    let enabled = recording_command(log, "enabled", true);

    assert!(CompositeCommand::from_commands(vec![disabled, enabled]).can_execute());
}

/// CMDD-002 — CompositeCommand.Execute invokes only enabled inner commands
#[test]
fn composite_command_execute_invokes_only_enabled() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let a = recording_command(log.clone(), "a", true);
    let b = recording_command(log.clone(), "b", false);
    let c = recording_command(log.clone(), "c", true);
    let command = CompositeCommand::from_commands(vec![a, b, c]);

    command.execute();

    assert_eq!(*log.lock().unwrap(), vec!["a", "c"]);
}

/// CMDD-003 — CompositeCommand propagates inner CanExecuteChanged
#[test]
fn composite_command_propagates_inner_can_execute_changed() {
    let inner = RelayCommand::noop();
    let composite = CompositeCommand::from_commands(vec![inner.clone()]);
    let fired = Arc::new(AtomicUsize::new(0));
    let fired_clone = fired.clone();
    let _subscription = composite.can_execute_changed().subscribe(move |_| {
        fired_clone.fetch_add(1, Ordering::SeqCst);
    });

    inner.trigger_can_execute_changed();

    assert_eq!(fired.load(Ordering::SeqCst), 1);
}

/// CMDD-004 — DecoratorCommand.CanExecute is inner AND extra-predicate
#[test]
fn decorator_command_can_execute_is_inner_and_extra_predicate() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let inner = recording_command(log, "inner", true);
    let decorated = DecoratorCommand::new(inner, Some(|| false), None::<fn()>, None::<fn()>);

    assert!(!decorated.can_execute());
}

/// CMDD-005 — DecoratorCommand.Execute invokes pre, inner, post in order
#[test]
fn decorator_command_execute_invokes_pre_inner_post() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let inner = recording_command(log.clone(), "inner", true);
    let pre_log = log.clone();
    let post_log = log.clone();
    let decorated = DecoratorCommand::new(
        inner,
        None::<fn() -> bool>,
        Some(move || pre_log.lock().unwrap().push("pre")),
        Some(move || post_log.lock().unwrap().push("post")),
    );

    decorated.execute();

    assert_eq!(*log.lock().unwrap(), vec!["pre", "inner", "post"]);
}

/// CMDD-006 — DecoratorCommand.Execute is no-op when CanExecute is false
#[test]
fn decorator_command_execute_noop_when_disabled() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let inner = recording_command(log.clone(), "inner", true);
    let decorated = DecoratorCommand::new(
        inner,
        Some(|| false),
        Some({
            let log = log.clone();
            move || log.lock().unwrap().push("pre")
        }),
        Some({
            let log = log.clone();
            move || log.lock().unwrap().push("post")
        }),
    );

    decorated.execute();

    assert!(log.lock().unwrap().is_empty());
}

/// CMDD-007 — ConfirmationDecoratorCommand invokes inner only when confirmed
#[test]
fn confirmation_decorator_invokes_inner_only_when_confirmed() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let yes =
        ConfirmationDecoratorCommand::new(recording_command(log.clone(), "yes", true), || {
            AsyncValue::ready(true)
        });
    let no = ConfirmationDecoratorCommand::new(recording_command(log.clone(), "no", true), || {
        AsyncValue::ready(false)
    });

    yes.execute();
    no.execute();

    assert_eq!(*log.lock().unwrap(), vec!["yes"]);
}

#[test]
fn confirmation_decorator_awaits_pending_decision() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let decision = AsyncValue::pending();
    let pending_decision = decision.clone();
    let command = ConfirmationDecoratorCommand::new(
        recording_command(log.clone(), "confirmed", true),
        move || pending_decision.clone(),
    );

    let execution = command.execute_async();
    assert!(!execution.is_finished());
    assert!(log.lock().unwrap().is_empty());
    decision.resolve(true);
    assert!(execution.is_finished());
    execution.join().unwrap();

    assert_eq!(*log.lock().unwrap(), vec!["confirmed"]);
}

#[test]
fn pending_confirmation_uses_a_resolver_thread_continuation() {
    let execution_threads = Arc::new(Mutex::new(Vec::new()));
    let observed_threads = execution_threads.clone();
    let decision = AsyncValue::pending();
    let pending_decision = decision.clone();
    let command = ConfirmationDecoratorCommand::new(
        RelayCommand::new(move || {
            observed_threads
                .lock()
                .unwrap()
                .push(std::thread::current().id());
        }),
        move || pending_decision.clone(),
    );

    command.execute();
    assert_eq!(decision.pending_continuation_count(), 1);
    let resolving_thread = std::thread::current().id();
    decision.resolve(true);

    assert_eq!(*execution_threads.lock().unwrap(), vec![resolving_thread]);
}

#[test]
fn many_pending_confirmations_retain_one_continuation_each() {
    let decisions = (0..128).map(|_| AsyncValue::pending()).collect::<Vec<_>>();
    let command = ConfirmationDecoratorCommand::new(RelayCommand::noop(), {
        let decisions = Arc::new(Mutex::new(decisions.clone()));
        move || decisions.lock().unwrap().pop().unwrap()
    });

    for _ in 0..decisions.len() {
        command.execute();
    }

    assert!(decisions
        .iter()
        .all(|decision| decision.pending_continuation_count() == 1));
}

#[test]
fn confirmation_decorator_async_path_is_gated_before_confirming() {
    let confirms = Arc::new(AtomicUsize::new(0));
    let command = ConfirmationDecoratorCommand::new(
        recording_command(Arc::new(Mutex::new(Vec::new())), "disabled", false),
        {
            let confirms = confirms.clone();
            move || {
                confirms.fetch_add(1, Ordering::SeqCst);
                AsyncValue::ready(true)
            }
        },
    );

    command.execute_async().join().unwrap();

    assert_eq!(confirms.load(Ordering::SeqCst), 0);
}

#[test]
fn confirmation_decorator_async_path_propagates_inner_panic() {
    let command =
        ConfirmationDecoratorCommand::new(RelayCommand::new(|| panic!("inner boom")), || {
            AsyncValue::ready(true)
        });
    let errors = Arc::new(AtomicUsize::new(0));
    let errors_clone = errors.clone();
    let _subscription = command.errors().subscribe(move |_| {
        errors_clone.fetch_add(1, Ordering::SeqCst);
    });

    assert!(command.execute_async().join().is_err());
    assert_eq!(errors.load(Ordering::SeqCst), 0);
}

#[derive(Debug, PartialEq)]
struct ConfirmationPanicPayload(u32);

#[test]
fn confirmation_execution_join_preserves_the_original_panic_payload() {
    let command = ConfirmationDecoratorCommand::new(
        RelayCommand::new(|| std::panic::panic_any(ConfirmationPanicPayload(42))),
        || AsyncValue::ready(true),
    );

    let payload = command.execute_async().join().unwrap_err();
    let payload = payload
        .downcast::<ConfirmationPanicPayload>()
        .expect("join should retain the concrete panic payload");

    assert_eq!(*payload, ConfirmationPanicPayload(42));
}

/// CMDD-008 — ConfirmationDecoratorCommand.CanExecute delegates to inner
#[test]
fn confirmation_decorator_can_execute_delegates_to_inner() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let enabled =
        ConfirmationDecoratorCommand::new(recording_command(log.clone(), "x", true), || {
            AsyncValue::ready(true)
        });
    let disabled = ConfirmationDecoratorCommand::new(recording_command(log, "x", false), || {
        AsyncValue::ready(true)
    });

    assert!(enabled.can_execute());
    assert!(!disabled.can_execute());
}

/// CMDD-009 — Decorators compose (decorator of confirmation of relay)
#[test]
fn decorators_compose() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let relay = recording_command(log.clone(), "relay", true);
    let confirmation = ConfirmationDecoratorCommand::new(relay, || AsyncValue::ready(true));
    let decorated = DecoratorCommand::new(
        confirmation,
        None::<fn() -> bool>,
        None::<fn()>,
        None::<fn()>,
    );

    decorated.execute();

    assert_eq!(*log.lock().unwrap(), vec!["relay"]);
}

/// CMDD-010 — ConfirmationDecoratorCommand surfaces fire-and-forget errors on `errors`
#[test]
fn confirmation_decorator_surfaces_fire_and_forget_errors() {
    let throwing = RelayCommand::new(|| panic!("inner boom"));
    let confirming = ConfirmationDecoratorCommand::new(throwing, || AsyncValue::ready(true));
    let errors = Arc::new(AtomicUsize::new(0));
    let errors_clone = errors.clone();
    let _subscription = confirming.errors().subscribe(move |_| {
        errors_clone.fetch_add(1, Ordering::SeqCst);
    });

    confirming.execute();

    assert_eq!(errors.load(Ordering::SeqCst), 1);
}

#[test]
fn confirmation_decorator_isolates_confirm_panics_by_execution_mode() {
    let fire_and_forget =
        ConfirmationDecoratorCommand::new(RelayCommand::noop(), || panic!("confirm boom"));
    let errors = Arc::new(AtomicUsize::new(0));
    let observed = errors.clone();
    let _subscription = fire_and_forget.errors().subscribe(move |_| {
        observed.fetch_add(1, Ordering::SeqCst);
    });

    fire_and_forget.execute();

    assert_eq!(errors.load(Ordering::SeqCst), 1);

    let awaited =
        ConfirmationDecoratorCommand::new(RelayCommand::noop(), || panic!("awaited confirm boom"));
    assert!(awaited.execute_async().join().is_err());
}

#[test]
fn confirmation_decorator_disposal_stops_in_flight_and_late_emissions() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let decision = AsyncValue::pending();
    let pending_decision = decision.clone();
    let confirming = ConfirmationDecoratorCommand::new(
        recording_command(log.clone(), "confirmed", true),
        move || pending_decision.clone(),
    );
    let errors = confirming.errors();
    let deliveries = Arc::new(AtomicUsize::new(0));
    let deliveries_inner = deliveries.clone();
    let _subscription = errors.subscribe(move |_| {
        deliveries_inner.fetch_add(1, Ordering::SeqCst);
    });

    let execution = confirming.execute_async();
    confirming.dispose();
    confirming.dispose();
    decision.resolve(true);
    execution.join().unwrap();
    errors.send(vmx::Message::Custom {
        sender_id: 0,
        sender_name: "test".to_string(),
        name: "late".to_string(),
    });
    confirming.execute();

    assert!(log.lock().unwrap().is_empty());
    assert_eq!(deliveries.load(Ordering::SeqCst), 0);
}

#[test]
fn confirmation_error_value_precedes_disposal_completion() {
    let confirming =
        ConfirmationDecoratorCommand::new(RelayCommand::new(|| panic!("inner boom")), || {
            AsyncValue::ready(true)
        });
    let events = Arc::new(Mutex::new(Vec::new()));
    let values = events.clone();
    let completion = events.clone();
    let _subscription = confirming.errors().subscribe_with_completion(
        move |_| values.lock().unwrap().push("value"),
        move || completion.lock().unwrap().push("completion"),
    );

    confirming.execute();
    confirming.dispose();
    confirming.execute();

    assert_eq!(*events.lock().unwrap(), vec!["value", "completion"]);
}

/// CMD-008 — Confirm(delegate) is equivalent to explicit ConfirmationDecoratorCommand
#[test]
fn confirm_fluent_matches_explicit_confirmation_decorator() {
    let called = Arc::new(Mutex::new(0));
    let called_inner = called.clone();
    let command = RelayCommand::new(move || *called_inner.lock().unwrap() += 1);

    let confirmed = command.clone().confirm(|| AsyncValue::ready(true));
    let explicit = ConfirmationDecoratorCommand::new(command, || AsyncValue::ready(true));

    assert_eq!(confirmed.can_execute(), explicit.can_execute());
    confirmed.execute();
    explicit.execute();
    assert_eq!(*called.lock().unwrap(), 2);
}

/// CMD-009 — PrecedeWith(other) is equivalent to CompositeCommand(other, receiver)
#[test]
fn precede_with_runs_other_before_receiver() {
    let order = Arc::new(Mutex::new(Vec::new()));
    let left_order = order.clone();
    let right_order = order.clone();
    let receiver = RelayCommand::new(move || right_order.lock().unwrap().push("receiver"));
    let other = RelayCommand::new(move || left_order.lock().unwrap().push("other"));

    receiver.precede_with(other).execute();

    assert_eq!(*order.lock().unwrap(), vec!["other", "receiver"]);
}

/// CMD-010 — SucceedWith(other) is equivalent to CompositeCommand(receiver, other)
#[test]
fn succeed_with_runs_receiver_before_other() {
    let order = Arc::new(Mutex::new(Vec::new()));
    let receiver_order = order.clone();
    let other_order = order.clone();
    let receiver = RelayCommand::new(move || receiver_order.lock().unwrap().push("receiver"));
    let other = RelayCommand::new(move || other_order.lock().unwrap().push("other"));

    receiver.succeed_with(other).execute();

    assert_eq!(*order.lock().unwrap(), vec!["receiver", "other"]);
}

/// CMD-011 — WrapWith(predicate?, pre?, post?) is equivalent to explicit DecoratorCommand
#[test]
fn wrap_with_runs_pre_inner_post_with_predicate() {
    let order = Arc::new(Mutex::new(Vec::new()));
    let inner_order = order.clone();
    let pre_order = order.clone();
    let post_order = order.clone();
    let command = RelayCommand::new(move || inner_order.lock().unwrap().push("inner"));

    command
        .wrap_with(
            Some(|| true),
            Some(move || pre_order.lock().unwrap().push("pre")),
            Some(move || post_order.lock().unwrap().push("post")),
        )
        .execute();

    assert_eq!(*order.lock().unwrap(), vec!["pre", "inner", "post"]);
}

/// CMDD-011 — Disposed composite and decorator commands are inert
#[test]
fn disposed_composite_and_decorator_commands_are_inert() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let a = recording_command(log.clone(), "a", true);
    let composite =
        CompositeCommand::from_commands(vec![a.clone(), recording_command(log.clone(), "b", true)]);
    let composite_clone = composite.clone();
    composite.dispose();
    composite.dispose();

    assert!(
        !composite_clone.can_execute(),
        "clones share disposal state"
    );
    composite_clone.execute();

    let inner = recording_command(log.clone(), "inner", true);
    let (pre_log, post_log, predicate_log) = (log.clone(), log.clone(), log.clone());
    let decorator = DecoratorCommand::new(
        inner.clone(),
        Some(move || {
            predicate_log.lock().unwrap().push("predicate");
            true
        }),
        Some(move || pre_log.lock().unwrap().push("pre")),
        Some(move || post_log.lock().unwrap().push("post")),
    );
    let decorator_clone = decorator.clone();
    decorator.dispose();
    decorator.dispose();

    assert!(!decorator_clone.can_execute());
    decorator_clone.execute();
    assert!(log.lock().unwrap().is_empty());

    a.execute();
    inner.execute();
    assert_eq!(*log.lock().unwrap(), vec!["a", "inner"]);
}

/// Disposing a composite releases its child subscriptions and completes its
/// own change hub after one notification; the children's hubs stay open.
#[test]
fn composite_disposal_completes_only_its_own_change_hub() {
    let child = RelayCommand::noop();
    let composite = CompositeCommand::from_commands(vec![child.clone()]);
    let events = Arc::new(Mutex::new(Vec::new()));
    let (values, completions) = (events.clone(), events.clone());
    let _subscription = composite.can_execute_changed().subscribe_with_completion(
        move |_| values.lock().unwrap().push("value"),
        move || completions.lock().unwrap().push("completion"),
    );
    let child_events = Arc::new(AtomicUsize::new(0));
    let child_events_inner = child_events.clone();
    let _child_subscription = child.can_execute_changed().subscribe(move |_| {
        child_events_inner.fetch_add(1, Ordering::SeqCst);
    });

    composite.dispose();
    child.raise_can_execute_changed();

    assert_eq!(*events.lock().unwrap(), vec!["value", "completion"]);
    assert_eq!(child_events.load(Ordering::SeqCst), 1);
}

/// CMDD-012 — Disposed confirmation decorators are inert, including a pending confirmation
#[test]
fn disposed_confirmation_decorator_is_inert_including_pending_confirmations() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let confirms = Arc::new(AtomicUsize::new(0));
    let confirms_inner = confirms.clone();
    let disposed_first = ConfirmationDecoratorCommand::new(
        recording_command(log.clone(), "never", true),
        move || {
            confirms_inner.fetch_add(1, Ordering::SeqCst);
            AsyncValue::ready(true)
        },
    );
    disposed_first.dispose();
    assert!(!disposed_first.can_execute());
    disposed_first.execute();
    disposed_first.execute_async().join().unwrap();
    assert_eq!(confirms.load(Ordering::SeqCst), 0);

    // Rust confirmations are `AsyncValue<bool>`, which has no faulted state;
    // a panicking delegate is covered by CMDD-010.
    for confirmed in [true, false] {
        let inner = recording_command(log.clone(), "inner", true);
        let decision = AsyncValue::pending();
        let pending = decision.clone();
        let confirming = ConfirmationDecoratorCommand::new(inner.clone(), move || pending.clone());
        let deliveries = Arc::new(AtomicUsize::new(0));
        let deliveries_inner = deliveries.clone();
        let _subscription = confirming.errors().subscribe(move |_| {
            deliveries_inner.fetch_add(1, Ordering::SeqCst);
        });

        confirming.execute();
        confirming.clone().dispose();
        // Resolve on another thread after dispose() has returned.
        std::thread::spawn(move || {
            decision.resolve(confirmed);
        })
        .join()
        .unwrap();

        assert!(log.lock().unwrap().is_empty(), "confirmed = {confirmed}");
        assert_eq!(deliveries.load(Ordering::SeqCst), 0);
        inner.execute();
        assert_eq!(
            log.lock().unwrap().drain(..).collect::<Vec<_>>(),
            vec!["inner"]
        );
    }
}

/// CMDD-013 — Disposal during execution admits no later inner work
#[test]
fn disposal_during_execution_admits_no_later_inner_work() {
    // A composite whose first child disposes it runs no later child.
    let log = Arc::new(Mutex::new(Vec::new()));
    let holder: Arc<Mutex<Option<CompositeCommand>>> = Arc::new(Mutex::new(None));
    let first = RelayCommand::new({
        let (log, holder) = (log.clone(), holder.clone());
        move || {
            log.lock().unwrap().push("first");
            if let Some(composite) = holder.lock().unwrap().as_ref() {
                composite.dispose();
            }
        }
    });
    let composite = CompositeCommand::from_commands(vec![
        first,
        recording_command(log.clone(), "second", true),
    ]);
    *holder.lock().unwrap() = Some(composite.clone());
    composite.execute();
    assert_eq!(*log.lock().unwrap(), vec!["first"]);

    // A decorator disposed by its extra predicate runs neither hook nor inner.
    let log = Arc::new(Mutex::new(Vec::new()));
    let slot: Arc<Mutex<Option<DecoratorCommand<RelayCommand>>>> = Arc::new(Mutex::new(None));
    let decorator = DecoratorCommand::new(
        recording_command(log.clone(), "inner", true),
        Some({
            let slot = slot.clone();
            move || {
                if let Some(decorator) = slot.lock().unwrap().as_ref() {
                    decorator.dispose();
                }
                true
            }
        }),
        Some({
            let log = log.clone();
            move || log.lock().unwrap().push("pre")
        }),
        Some({
            let log = log.clone();
            move || log.lock().unwrap().push("post")
        }),
    );
    *slot.lock().unwrap() = Some(decorator.clone());
    decorator.execute();
    assert!(log.lock().unwrap().is_empty());

    // A decorator disposed by its pre-action skips the inner but runs post once.
    let log = Arc::new(Mutex::new(Vec::new()));
    let slot: Arc<Mutex<Option<DecoratorCommand<RelayCommand>>>> = Arc::new(Mutex::new(None));
    let decorator = DecoratorCommand::new(
        recording_command(log.clone(), "inner", true),
        None::<fn() -> bool>,
        Some({
            let (log, slot) = (log.clone(), slot.clone());
            move || {
                log.lock().unwrap().push("pre");
                if let Some(decorator) = slot.lock().unwrap().as_ref() {
                    decorator.dispose();
                }
            }
        }),
        Some({
            let log = log.clone();
            move || log.lock().unwrap().push("post")
        }),
    );
    *slot.lock().unwrap() = Some(decorator.clone());
    decorator.execute();
    decorator.execute();
    assert_eq!(*log.lock().unwrap(), vec!["pre", "post"]);
}

// ---------------------------------------------------------------------------
// AsyncRelayCommand participates in the base Command contract (#344): spec
// chapter 4 declares IAsyncCommand : ICommand; no new conformance ID. Waits use
// channels; the timeout is only a hang guard.
// ---------------------------------------------------------------------------

const SIGNAL_TIMEOUT: Duration = Duration::from_secs(10);

/// An async command whose body reports start, waits for release, then reports done.
struct GatedAsync {
    command: AsyncRelayCommand,
    started: mpsc::Receiver<()>,
    release: mpsc::Sender<()>,
    done: mpsc::Receiver<()>,
}

fn gated_async(result: fn() -> vmx::VmxResult<()>) -> GatedAsync {
    let (started_tx, started) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    let (done_tx, done) = mpsc::channel();
    let started_tx = Mutex::new(started_tx);
    let release_rx = Mutex::new(release_rx);
    let done_tx = Mutex::new(done_tx);
    let command = AsyncRelayCommand::new(move |_token| {
        started_tx.lock().unwrap().send(()).unwrap();
        release_rx
            .lock()
            .unwrap()
            .recv_timeout(SIGNAL_TIMEOUT)
            .unwrap();
        done_tx.lock().unwrap().send(()).unwrap();
        result()
    });
    GatedAsync {
        command,
        started,
        release,
        done,
    }
}

/// Signals every eligibility change; execution end is announced after the
/// admission epoch resets, so it is a deterministic "finished" marker.
fn eligibility_signal(command: &AsyncRelayCommand) -> (mpsc::Receiver<()>, vmx::Subscription) {
    let (tx, rx) = mpsc::channel();
    let tx = Mutex::new(tx);
    let subscription = command
        .can_execute_changed()
        .subscribe(move |_| tx.lock().unwrap().send(()).unwrap());
    (rx, subscription)
}

fn run_to_completion(command: &AsyncRelayCommand, dispatch: impl FnOnce()) {
    let (changed, _subscription) = eligibility_signal(command);
    dispatch();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap(); // admission
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap(); // completion
}

#[test]
fn async_relay_command_is_usable_as_dyn_command_and_in_wrappers() {
    let runs = Arc::new(AtomicUsize::new(0));
    let counted = {
        let runs = runs.clone();
        move || {
            let runs = runs.clone();
            AsyncRelayCommand::new(move |_token| {
                runs.fetch_add(1, Ordering::SeqCst);
                Ok(())
            })
        }
    };

    let as_dyn: Arc<dyn Command> = Arc::new(counted());
    assert!(as_dyn.can_execute());

    let inner = counted();
    let composite = CompositeCommand::new(vec![Arc::new(inner.clone()) as Arc<dyn Command>]);
    run_to_completion(&inner, || composite.execute());

    let inner = counted();
    let pre_post = Arc::new(Mutex::new(Vec::new()));
    let (pre_log, post_log) = (pre_post.clone(), pre_post.clone());
    let decorated = DecoratorCommand::new(
        inner.clone(),
        Some(|| true),
        Some(move || pre_log.lock().unwrap().push("pre")),
        Some(move || post_log.lock().unwrap().push("post")),
    );
    run_to_completion(&inner, || decorated.execute());
    assert_eq!(*pre_post.lock().unwrap(), vec!["pre", "post"]);

    let inner = counted();
    let confirmed = ConfirmationDecoratorCommand::new(inner.clone(), || AsyncValue::ready(true));
    run_to_completion(&inner, || confirmed.execute());

    assert_eq!(runs.load(Ordering::SeqCst), 3);
}

#[test]
fn trait_execute_returns_while_async_body_is_pending() {
    let gated = gated_async(|| Ok(()));
    let (changed, _subscription) = eligibility_signal(&gated.command);

    Command::execute(&gated.command);

    gated.started.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    assert!(
        gated.command.is_executing(),
        "execute returned while the body is pending"
    );
    gated.release.send(()).unwrap();
    gated.done.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    assert!(!gated.command.is_executing());
}

#[test]
fn trait_eligibility_matches_inherent_before_during_and_after_execution() {
    let gated = gated_async(|| Ok(()));
    let command = &gated.command;
    let as_trait: &dyn Command = command;
    let (changed, _subscription) = eligibility_signal(command);

    assert_eq!(
        as_trait.can_execute(),
        AsyncRelayCommand::can_execute(command)
    );
    assert!(as_trait.can_execute());
    // Same hub identity: a message sent on the inherent hub reaches a
    // subscriber of the trait hub.
    let (probe_tx, probe) = mpsc::channel();
    let probe_tx = Mutex::new(probe_tx);
    let _probe = as_trait.can_execute_changed().subscribe(move |message| {
        if let Message::Custom { name, .. } = message {
            if name == "identity-probe" {
                probe_tx.lock().unwrap().send(()).unwrap();
            }
        }
    });
    AsyncRelayCommand::can_execute_changed(command).send(Message::Custom {
        sender_id: 0,
        sender_name: "test".to_string(),
        name: "identity-probe".to_string(),
    });
    probe.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap(); // the probe itself

    as_trait.execute();
    gated.started.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    assert_eq!(
        as_trait.can_execute(),
        AsyncRelayCommand::can_execute(command)
    );
    assert!(!as_trait.can_execute());

    gated.release.send(()).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    assert_eq!(
        as_trait.can_execute(),
        AsyncRelayCommand::can_execute(command)
    );
    assert!(as_trait.can_execute());
}

#[test]
fn trait_execute_reports_a_fault_once_on_the_errors_hub() {
    let gated = gated_async(|| Err(VmxError::Other("boom".to_string())));
    let faults = Arc::new(AtomicUsize::new(0));
    let counted = faults.clone();
    let _faults = gated.command.errors().subscribe(move |_| {
        counted.fetch_add(1, Ordering::SeqCst);
    });
    let (changed, _subscription) = eligibility_signal(&gated.command);

    Command::execute(&gated.command);
    gated.started.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    gated.release.send(()).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap();

    assert_eq!(faults.load(Ordering::SeqCst), 1);
}

#[test]
fn trait_calls_on_a_clone_share_in_flight_state() {
    let gated = gated_async(|| Ok(()));
    let clone: Arc<dyn Command> = Arc::new(gated.command.clone());
    let (changed, _subscription) = eligibility_signal(&gated.command);

    clone.execute();
    gated.started.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    assert!(gated.command.is_executing());
    assert!(!clone.can_execute());
    clone.execute(); // rejected: the shared execution is still admitted

    gated.release.send(()).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    changed.recv_timeout(SIGNAL_TIMEOUT).unwrap();
    assert!(
        gated.started.try_recv().is_err(),
        "the second execute was not admitted"
    );
    assert!(clone.can_execute());
}
