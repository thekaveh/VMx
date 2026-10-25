//! A confirmation decorator awaits an asynchronous inner command (spec
//! `04-commands.md` §8.3.2, ADR-0145).
//!
//! Inner bodies block on channels the test releases, so every "not completed
//! yet" check is deterministic. Timeouts only guard against hangs.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use vmx::{
    AsyncRelayCommand, AsyncRelayCommandBuilder, AsyncValue, Command, CommandErrorStream,
    CommandExt, CompositeCommand, ConfirmationDecoratorCommand, ConfirmationExecution,
    RelayCommand, ValueSubscription, VmxError, VmxResult, NO_HOOK, NO_PREDICATE,
};

const BOUND: Duration = Duration::from_secs(10);

/// An `AsyncRelayCommand` whose body counts its runs, reports its start, and
/// returns the result the test releases it with. It also records whether the
/// body saw its cancellation token cancelled.
struct GatedInner {
    command: AsyncRelayCommand,
    runs: Arc<AtomicUsize>,
    cancelled_runs: Arc<AtomicUsize>,
    started: mpsc::Receiver<()>,
    release: mpsc::Sender<VmxResult<()>>,
}

impl GatedInner {
    fn new() -> Self {
        Self::built_from(AsyncRelayCommand::builder())
    }

    fn built_from(builder: AsyncRelayCommandBuilder) -> Self {
        let runs = Arc::new(AtomicUsize::new(0));
        let cancelled_runs = Arc::new(AtomicUsize::new(0));
        let (started_tx, started) = mpsc::channel();
        let (release, released) = mpsc::channel::<VmxResult<()>>();
        let released = Mutex::new(released);
        let command = builder
            .task({
                let (runs, cancelled_runs) = (runs.clone(), cancelled_runs.clone());
                move |token| {
                    runs.fetch_add(1, Ordering::SeqCst);
                    let _ = started_tx.send(());
                    let result = released
                        .lock()
                        .unwrap()
                        .recv_timeout(BOUND)
                        .expect("the test released the inner body");
                    if token.is_cancelled() {
                        cancelled_runs.fetch_add(1, Ordering::SeqCst);
                    }
                    result
                }
            })
            .build();
        Self {
            command,
            runs,
            cancelled_runs,
            started,
            release,
        }
    }

    fn await_start(&self) {
        self.started
            .recv_timeout(BOUND)
            .expect("the inner body started");
    }

    fn release(&self, result: VmxResult<()>) {
        self.release
            .send(result)
            .expect("the inner body is waiting for release");
    }

    fn runs(&self) -> usize {
        self.runs.load(Ordering::SeqCst)
    }
}

/// A hand-written asynchronous command that counts its synchronous `execute`
/// calls and its awaitable entry-point calls separately. Each entry-point
/// call returns a completion that the test settles.
#[derive(Clone, Default)]
struct ProbeCommand {
    execute_calls: Arc<AtomicUsize>,
    entry_calls: Arc<AtomicUsize>,
    completions: Arc<Mutex<Vec<AsyncValue<VmxResult<()>>>>>,
}

impl ProbeCommand {
    /// Returns `(execute calls, entry-point calls)`.
    fn calls(&self) -> (usize, usize) {
        (
            self.execute_calls.load(Ordering::SeqCst),
            self.entry_calls.load(Ordering::SeqCst),
        )
    }

    fn settle_latest(&self, result: VmxResult<()>) {
        let completion = self
            .completions
            .lock()
            .unwrap()
            .last()
            .cloned()
            .expect("the entry point was called");
        assert!(completion.resolve(result));
    }
}

impl Command for ProbeCommand {
    fn can_execute(&self) -> bool {
        true
    }

    fn execute(&self) {
        self.execute_calls.fetch_add(1, Ordering::SeqCst);
    }

    fn as_async(&self) -> Option<Box<dyn FnOnce() -> AsyncValue<VmxResult<()>> + Send>> {
        let probe = self.clone();
        Some(Box::new(move || {
            probe.entry_calls.fetch_add(1, Ordering::SeqCst);
            let completion = AsyncValue::pending();
            probe.completions.lock().unwrap().push(completion.clone());
            completion
        }))
    }
}

/// Joins an awaited execution, failing instead of hanging.
fn join_within(execution: ConfirmationExecution) -> std::thread::Result<()> {
    let (joined_tx, joined) = mpsc::channel();
    thread::spawn(move || {
        let _ = joined_tx.send(execution.join());
    });
    joined
        .recv_timeout(BOUND)
        .expect("the awaited execution completed")
}

/// Waits for an entry point's completion, failing instead of hanging.
fn settle_within(completion: AsyncValue<VmxResult<()>>) -> VmxResult<()> {
    let (settled_tx, settled) = mpsc::channel();
    thread::spawn(move || {
        let _ = settled_tx.send(completion.wait_result());
    });
    settled
        .recv_timeout(BOUND)
        .expect("the awaited entry point settled")
        .expect("the awaited entry point did not panic")
}

/// Records every failure published on an error stream.
struct ErrorLog {
    errors: Arc<Mutex<Vec<VmxError>>>,
    _subscription: ValueSubscription,
}

impl ErrorLog {
    fn of(stream: CommandErrorStream) -> Self {
        let errors = Arc::new(Mutex::new(Vec::new()));
        let observed = errors.clone();
        let subscription = stream.subscribe(move |error| observed.lock().unwrap().push(error));
        Self {
            errors,
            _subscription: subscription,
        }
    }

    fn entries(&self) -> Vec<VmxError> {
        self.errors.lock().unwrap().clone()
    }
}

/// Signals each eligibility change of an async command: one when an
/// execution is admitted and one after it has released admission.
fn eligibility_signal(command: &AsyncRelayCommand) -> (mpsc::Receiver<()>, vmx::Subscription) {
    let (changed_tx, changed) = mpsc::channel();
    let changed_tx = Mutex::new(changed_tx);
    let subscription = command.can_execute_changed().subscribe(move |_| {
        let _ = changed_tx.lock().unwrap().send(());
    });
    (changed, subscription)
}

fn failure() -> VmxError {
    VmxError::Other("save failed".to_string())
}

/// CMDD-014 — An awaited confirmation completes when its async inner operation
/// completes, not when it starts
#[test]
fn awaited_confirmation_completes_when_the_async_inner_operation_completes() {
    let inner = GatedInner::new();
    let decorator = inner.command.clone().confirm(|| AsyncValue::ready(true));

    let execution = decorator.execute_async();
    inner.await_start();

    assert!(
        !execution.is_finished(),
        "the awaiter completed while the inner body was blocked"
    );
    assert!(inner.command.is_executing());
    inner.release(Ok(()));
    join_within(execution).expect("the awaited execution succeeded");
    assert!(
        !inner.command.is_executing(),
        "the awaiter completed after the inner operation finished"
    );
    assert_eq!(inner.runs(), 1);
}

/// CMDD-014 — The awaited path invokes an async inner exactly once, through its
/// awaitable entry point and never through its synchronous execute
#[test]
fn awaited_confirmation_invokes_an_async_inner_once_through_its_entry_point() {
    let probe = ProbeCommand::default();
    let decision = AsyncValue::pending();
    let decorator = ConfirmationDecoratorCommand::new(probe.clone(), {
        let decision = decision.clone();
        move || decision.clone()
    });

    let execution = decorator.execute_async();
    assert_eq!(probe.calls(), (0, 0), "nothing runs before confirmation");
    decision.resolve(true);

    assert_eq!(probe.calls(), (0, 1));
    assert!(
        !execution.is_finished(),
        "the awaiter waits for the operation the entry point returned"
    );
    probe.settle_latest(Ok(()));
    join_within(execution).expect("the awaited execution succeeded");
    assert_eq!(probe.calls(), (0, 1));
}

/// CMDD-014 — An async inner shared as `Arc<dyn Command>` is still awaited
/// through its forwarded entry point
#[test]
fn an_async_inner_shared_behind_an_arc_is_still_awaited() {
    let inner = GatedInner::new();
    let shared: Arc<dyn Command> = Arc::new(inner.command.clone());
    assert!(shared.as_async().is_some(), "Arc forwards the entry point");
    let decorator = ConfirmationDecoratorCommand::new(shared, || AsyncValue::ready(true));

    let execution = decorator.execute_async();
    inner.await_start();

    assert!(!execution.is_finished());
    inner.release(Ok(()));
    join_within(execution).expect("the awaited execution succeeded");
    assert_eq!(inner.runs(), 1);
}

/// CMDD-014 — Only async commands and confirmation decorators expose an
/// awaitable entry point; every other command is synchronous
#[test]
fn only_async_commands_and_confirmations_expose_an_awaitable_entry_point() {
    let async_command = AsyncRelayCommand::new(|_token| Ok(()));
    let confirmed_relay = RelayCommand::noop().confirm(|| AsyncValue::ready(true));

    assert!(async_command.as_async().is_some());
    assert!(confirmed_relay.as_async().is_some());
    assert!(RelayCommand::noop().as_async().is_none());
    assert!(CompositeCommand::from_commands(vec![async_command.clone()])
        .as_async()
        .is_none());
    assert!(async_command
        .wrap_with(NO_PREDICATE, NO_HOOK, NO_HOOK)
        .as_async()
        .is_none());
}

/// CMDD-014 — A false confirmation completes the awaiter without invoking the
/// inner command
#[test]
fn awaited_false_confirmation_completes_without_invoking_the_inner() {
    let probe = ProbeCommand::default();
    let inner = GatedInner::new();
    let probe_decision = AsyncValue::pending();
    let inner_decision = AsyncValue::pending();
    let over_probe = ConfirmationDecoratorCommand::new(probe.clone(), {
        let decision = probe_decision.clone();
        move || decision.clone()
    });
    let over_inner = ConfirmationDecoratorCommand::new(inner.command.clone(), {
        let decision = inner_decision.clone();
        move || decision.clone()
    });

    let probe_execution = over_probe.execute_async();
    let inner_completion = over_inner.as_async().expect("entry point")();
    assert!(!probe_execution.is_finished());
    probe_decision.resolve(false);
    inner_decision.resolve(false);

    join_within(probe_execution).expect("a declined confirmation completes");
    assert_eq!(settle_within(inner_completion), Ok(()));
    assert_eq!(probe.calls(), (0, 0));
    assert_eq!(inner.runs(), 0);
    assert!(inner.started.try_recv().is_err());
}

/// CMDD-014 — A synchronous inner runs once through execute, and the awaiter
/// completes after that call returns
#[test]
fn awaited_confirmation_runs_a_sync_inner_once_through_execute() {
    let runs = Arc::new(AtomicUsize::new(0));
    let (entered_tx, entered) = mpsc::channel();
    let (release, released) = mpsc::channel::<()>();
    let inner = RelayCommand::new({
        let runs = runs.clone();
        move || {
            runs.fetch_add(1, Ordering::SeqCst);
            let _ = entered_tx.send(());
            released
                .recv_timeout(BOUND)
                .expect("the test released the synchronous inner");
        }
    });
    assert!(inner.as_async().is_none());
    let decision = AsyncValue::pending();
    let decorator = ConfirmationDecoratorCommand::new(inner, {
        let decision = decision.clone();
        move || decision.clone()
    });

    let execution = decorator.execute_async();
    // A synchronous inner runs on the thread that resolves the confirmation.
    let resolver = thread::spawn(move || decision.resolve(true));
    entered.recv_timeout(BOUND).expect("the inner started");

    assert!(
        !execution.is_finished(),
        "the awaiter completed while the synchronous inner was running"
    );
    release.send(()).unwrap();
    join_within(execution).expect("the awaited execution succeeded");
    resolver.join().unwrap();
    assert_eq!(runs.load(Ordering::SeqCst), 1);
}

/// CMDD-015 — An awaited async inner failure reaches only the awaiter,
/// unchanged
#[test]
fn awaited_inner_failure_reaches_only_the_awaiter() {
    let inner = GatedInner::new();
    let decorator = inner.command.clone().confirm(|| AsyncValue::ready(true));
    let decorator_errors = ErrorLog::of(decorator.error_stream());
    let inner_errors = ErrorLog::of(inner.command.error_stream());

    // `execute_async`: `join` returns the original `VmxError` as its payload.
    let execution = decorator.execute_async();
    inner.await_start();
    inner.release(Err(failure()));
    let payload = join_within(execution).expect_err("the failure reached the awaiter");
    let error = payload
        .downcast::<VmxError>()
        .expect("the payload is the original VmxError");
    assert_eq!(*error, failure());

    // The decorator's entry point returns the same failure as a `VmxResult`.
    let completion = decorator.as_async().expect("entry point")();
    inner.await_start();
    inner.release(Err(failure()));
    assert_eq!(settle_within(completion), Err(failure()));

    assert_eq!(inner.runs(), 2);
    assert!(decorator_errors.entries().is_empty());
    assert!(inner_errors.entries().is_empty());
}

/// CMDD-015 — A fire-and-forget async inner failure reaches only the inner's
/// error stream, exactly once
#[test]
fn fire_and_forget_inner_failure_reaches_only_the_inner_error_stream() {
    let inner = GatedInner::new();
    let decorator = inner.command.clone().confirm(|| AsyncValue::ready(true));
    let decorator_errors = ErrorLog::of(decorator.error_stream());
    let (inner_error_tx, inner_errors) = mpsc::channel();
    let inner_error_tx = Mutex::new(inner_error_tx);
    let _inner_errors = inner.command.error_stream().subscribe(move |error| {
        let _ = inner_error_tx.lock().unwrap().send(error);
    });
    let (changed, _changed) = eligibility_signal(&inner.command);

    decorator.execute();
    inner.await_start();
    changed.recv_timeout(BOUND).expect("admission");
    inner.release(Err(failure()));

    assert_eq!(
        inner_errors
            .recv_timeout(BOUND)
            .expect("the inner reported its failure"),
        failure()
    );
    changed
        .recv_timeout(BOUND)
        .expect("the inner execution finished");
    assert!(
        inner_errors.try_recv().is_err(),
        "the failure was reported once"
    );
    assert!(decorator_errors.entries().is_empty());
    assert_eq!(inner.runs(), 1);
}

/// Runs one fire-and-forget execution whose confirmation fails and returns the
/// decorator's errors, the inner's errors, and whether the inner admitted the
/// call. Admission is read synchronously: `AsyncRelayCommand` marks itself
/// executing before it spawns its body, so a call that reaches the inner is
/// visible when `execute` returns, whether or not the body has run yet.
fn fire_and_forget_with_failing_confirm<F>(confirm: F) -> (Vec<VmxError>, Vec<VmxError>, bool)
where
    F: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
{
    let inner = GatedInner::new();
    let decorator = ConfirmationDecoratorCommand::new(inner.command.clone(), confirm);
    let decorator_errors = ErrorLog::of(decorator.error_stream());
    let inner_errors = ErrorLog::of(inner.command.error_stream());

    decorator.execute();
    let admitted = inner.command.is_executing() || inner.runs() > 0;
    if admitted {
        // Let a wrongly admitted body finish instead of waiting out its bound.
        inner.await_start();
        inner.release(Ok(()));
    }

    (decorator_errors.entries(), inner_errors.entries(), admitted)
}

/// CMDD-015 — A failing confirmation on the fire-and-forget path reaches only
/// the decorator's error stream, once, and invokes no inner
#[test]
fn fire_and_forget_confirm_failure_reaches_only_the_decorator_error_stream() {
    // A Rust confirmation fails by panicking, either while producing the
    // `AsyncValue<bool>` or in the `map` that produces it (ADR-0138).
    let expected = vec![VmxError::Other(
        "command panicked: confirm failed".to_string(),
    )];
    let thrown =
        fire_and_forget_with_failing_confirm(|| -> AsyncValue<bool> { panic!("confirm failed") });
    let settled_panicked = fire_and_forget_with_failing_confirm(|| {
        AsyncValue::ready(()).map(|()| -> bool { panic!("confirm failed") })
    });

    for (decorator_errors, inner_errors, admitted) in [thrown, settled_panicked] {
        assert_eq!(decorator_errors, expected);
        assert!(inner_errors.is_empty());
        assert!(!admitted, "a failed confirmation invoked the inner");
    }
}

/// CMDD-016 — A busy async inner drops the confirmed call: its body runs no
/// second time and the awaiter completes
#[test]
fn busy_async_inner_drops_the_confirmed_call_and_the_awaiter_completes() {
    let inner = GatedInner::new();
    let decision = AsyncValue::pending();
    let decorator = ConfirmationDecoratorCommand::new(inner.command.clone(), {
        let decision = decision.clone();
        move || decision.clone()
    });

    // The decorator admits the call while the inner is idle, then the inner
    // becomes busy with its own call before the confirmation resolves.
    let execution = decorator.execute_async();
    let running = inner.command.execute_async();
    inner.await_start();
    decision.resolve(true);

    join_within(execution).expect("the dropped call completed the awaiter");
    assert!(
        inner.command.is_executing(),
        "the awaiter did not wait for the unrelated execution"
    );
    inner.release(Ok(()));
    running
        .join()
        .unwrap()
        .expect("the inner's own call succeeded");
    assert_eq!(inner.runs(), 1);
    assert!(
        inner.started.try_recv().is_err(),
        "the dropped call never ran the body"
    );
}

/// CMDD-016 — An inner already executing before the call disables the
/// decorator, so neither entry point invokes confirm
#[test]
fn inner_executing_before_the_call_disables_the_decorator_and_skips_confirm() {
    let inner = GatedInner::new();
    let confirms = Arc::new(AtomicUsize::new(0));
    let decorator = ConfirmationDecoratorCommand::new(inner.command.clone(), {
        let confirms = Arc::clone(&confirms);
        move || {
            confirms.fetch_add(1, Ordering::SeqCst);
            AsyncValue::ready(true)
        }
    });

    let running = inner.command.execute_async();
    inner.await_start();
    assert!(!decorator.can_execute());

    join_within(decorator.execute_async()).expect("the refused call completed the awaiter");
    decorator.execute();

    assert_eq!(confirms.load(Ordering::SeqCst), 0);
    inner.release(Ok(()));
    running
        .join()
        .unwrap()
        .expect("the inner's own call succeeded");
    assert_eq!(inner.runs(), 1);
}

/// An async command whose body reports its start and then waits for its
/// cancellation token.
fn cancellable_inner(throw_on_cancel: bool) -> (AsyncRelayCommand, mpsc::Receiver<()>) {
    let (started_tx, started) = mpsc::channel();
    let mut builder = AsyncRelayCommand::builder().task(move |token| {
        let _ = started_tx.send(());
        let deadline = Instant::now() + BOUND;
        while !token.is_cancelled() {
            if Instant::now() > deadline {
                return Err(VmxError::Other("never cancelled".to_string()));
            }
            thread::sleep(Duration::from_millis(1));
        }
        Err(VmxError::Cancelled)
    });
    if throw_on_cancel {
        builder = builder.throw_on_cancel();
    }
    (builder.build(), started)
}

/// CMDD-016 — Cancelling the inner ends an awaited decorator call with the
/// inner's own cancellation outcome, unchanged
#[test]
fn inner_cancellation_outcome_passes_through_the_awaiter_unchanged() {
    for throw_on_cancel in [false, true] {
        let (inner, started) = cancellable_inner(throw_on_cancel);
        let start = || started.recv_timeout(BOUND).expect("the inner body started");

        // The inner's own awaited outcome for the same cancellation.
        let direct = inner.execute_async();
        start();
        inner.cancel();
        let expected = direct.join().unwrap();
        assert_eq!(
            expected,
            if throw_on_cancel {
                Err(VmxError::Cancelled)
            } else {
                Ok(())
            }
        );

        let decorator = inner.clone().confirm(|| AsyncValue::ready(true));
        let execution = decorator.execute_async();
        start();
        assert!(!execution.is_finished());
        inner.cancel();
        match (join_within(execution), &expected) {
            (Ok(()), Ok(())) => {}
            (Err(payload), Err(error)) => assert_eq!(
                *payload
                    .downcast::<VmxError>()
                    .expect("the payload is the original VmxError"),
                *error
            ),
            (joined, _) => panic!(
                "throw_on_cancel = {throw_on_cancel}: expected {expected:?}, joined Ok = {}",
                joined.is_ok()
            ),
        }

        let completion = decorator.as_async().expect("entry point")();
        start();
        inner.cancel();
        assert_eq!(settle_within(completion), expected);
        assert!(!inner.is_executing());
        assert!(inner.can_execute());
    }
}

/// CMDD-017 — An outer confirmation awaits a nested confirmation and its async
/// inner operation, which runs once
#[test]
fn nested_confirmation_wrappers_are_awaited_end_to_end() {
    let inner = GatedInner::new();
    let nested_decision = AsyncValue::pending();
    let nested = ConfirmationDecoratorCommand::new(inner.command.clone(), {
        let decision = nested_decision.clone();
        move || decision.clone()
    });
    let outer = nested.clone().confirm(|| AsyncValue::ready(true));

    let execution = outer.execute_async();
    assert!(
        !execution.is_finished(),
        "the outer awaiter waits for the nested confirmation"
    );
    nested_decision.resolve(true);
    inner.await_start();
    assert!(
        !execution.is_finished(),
        "the outer awaiter waits for the inner operation"
    );
    inner.release(Ok(()));
    join_within(execution).expect("the nested execution succeeded");
    assert_eq!(inner.runs(), 1);

    // A failure of the innermost operation reaches the outer awaiter unchanged.
    let outer_errors = ErrorLog::of(outer.error_stream());
    let nested_errors = ErrorLog::of(nested.error_stream());
    let completion = outer.as_async().expect("entry point")();
    inner.await_start();
    inner.release(Err(failure()));
    assert_eq!(settle_within(completion), Err(failure()));
    assert_eq!(inner.runs(), 2);
    assert!(outer_errors.entries().is_empty());
    assert!(nested_errors.entries().is_empty());
}

/// CMDD-017 — Disposing the decorator while its async inner runs neither
/// cancels nor disposes the inner, and the awaiter completes when it does
#[test]
fn disposal_during_inner_execution_neither_cancels_nor_disposes_the_inner() {
    let inner = GatedInner::new();
    let inner_streams_completed = Arc::new(AtomicUsize::new(0));
    let _inner_errors = inner
        .command
        .error_stream()
        .subscribe_with_completion(|_| {}, {
            let completed = inner_streams_completed.clone();
            move || {
                completed.fetch_add(1, Ordering::SeqCst);
            }
        });
    let _inner_changes = inner
        .command
        .can_execute_changed()
        .subscribe_with_completion(|_| {}, {
            let completed = inner_streams_completed.clone();
            move || {
                completed.fetch_add(1, Ordering::SeqCst);
            }
        });
    let decorator = inner.command.clone().confirm(|| AsyncValue::ready(true));
    let decorator_completed = Arc::new(AtomicBool::new(false));
    let _decorator_errors = decorator.error_stream().subscribe_with_completion(|_| {}, {
        let completed = decorator_completed.clone();
        move || completed.store(true, Ordering::SeqCst)
    });

    let execution = decorator.execute_async();
    inner.await_start();
    decorator.dispose();

    assert!(
        decorator_completed.load(Ordering::SeqCst),
        "decorator disposed"
    );
    assert!(
        inner.command.is_executing(),
        "disposal did not end the inner operation"
    );
    assert!(
        !execution.is_finished(),
        "the awaiter waits for the inner operation"
    );
    inner.release(Ok(()));
    join_within(execution).expect("the awaiter completed with the inner operation");
    assert_eq!(
        inner.cancelled_runs.load(Ordering::SeqCst),
        0,
        "the inner was not cancelled"
    );
    assert!(inner.command.can_execute(), "the inner was not disposed");
    assert_eq!(inner_streams_completed.load(Ordering::SeqCst), 0);

    // The inner stays usable by its owner.
    let again = inner.command.execute_async();
    inner.await_start();
    inner.release(Ok(()));
    again.join().unwrap().expect("the inner still runs");
    assert_eq!(inner.runs(), 2);
}

/// CMDD-017 — Disposing the decorator while its confirmation is pending starts
/// no inner work when the confirmation then resolves true
#[test]
fn disposal_during_a_pending_confirmation_starts_no_inner_work() {
    let probe = ProbeCommand::default();
    let inner = GatedInner::new();
    let probe_decision = AsyncValue::pending();
    let inner_decision = AsyncValue::pending();
    let over_probe = ConfirmationDecoratorCommand::new(probe.clone(), {
        let decision = probe_decision.clone();
        move || decision.clone()
    });
    let over_inner = ConfirmationDecoratorCommand::new(inner.command.clone(), {
        let decision = inner_decision.clone();
        move || decision.clone()
    });

    let probe_execution = over_probe.execute_async();
    let inner_completion = over_inner.as_async().expect("entry point")();
    over_probe.dispose();
    over_inner.dispose();
    // Resolve on another thread after dispose() has returned.
    thread::spawn(move || {
        probe_decision.resolve(true);
        inner_decision.resolve(true);
    })
    .join()
    .unwrap();

    join_within(probe_execution).expect("the awaiter completed");
    assert_eq!(settle_within(inner_completion), Ok(()));
    assert_eq!(probe.calls(), (0, 0));
    assert_eq!(inner.runs(), 0);
    assert!(inner.started.try_recv().is_err());
    assert!(inner.command.can_execute(), "the inner stays usable");
}
