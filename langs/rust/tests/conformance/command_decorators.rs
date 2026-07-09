use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use vmx::{
    Command, CompositeCommand, ConfirmationDecoratorCommand, DecoratorCommand, RelayCommand,
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
        ConfirmationDecoratorCommand::new(recording_command(log.clone(), "yes", true), || true);
    let no =
        ConfirmationDecoratorCommand::new(recording_command(log.clone(), "no", true), || false);

    yes.execute();
    no.execute();

    assert_eq!(*log.lock().unwrap(), vec!["yes"]);
}

/// CMDD-008 — ConfirmationDecoratorCommand.CanExecute delegates to inner
#[test]
fn confirmation_decorator_can_execute_delegates_to_inner() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let enabled =
        ConfirmationDecoratorCommand::new(recording_command(log.clone(), "x", true), || true);
    let disabled = ConfirmationDecoratorCommand::new(recording_command(log, "x", false), || true);

    assert!(enabled.can_execute());
    assert!(!disabled.can_execute());
}

/// CMDD-009 — Decorators compose (decorator of confirmation of relay)
#[test]
fn decorators_compose() {
    let log = Arc::new(Mutex::new(Vec::new()));
    let relay = recording_command(log.clone(), "relay", true);
    let confirmation = ConfirmationDecoratorCommand::new(relay, || true);
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
    let confirming = ConfirmationDecoratorCommand::new(throwing, || true);
    let errors = Arc::new(AtomicUsize::new(0));
    let errors_clone = errors.clone();
    let _subscription = confirming.errors().subscribe(move |_| {
        errors_clone.fetch_add(1, Ordering::SeqCst);
    });

    confirming.execute();

    assert_eq!(errors.load(Ordering::SeqCst), 1);
}
