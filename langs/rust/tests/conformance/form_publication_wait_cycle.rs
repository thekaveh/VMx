//! A `FormVm` call that waits for another thread's publication scope records
//! its wait in the one wait-for graph (spec/20 §5.5, ADR-0176, #1170, #1160).
//!
//! Thread X publishes a form notification, and a sink on X sends on hub `H`.
//! Thread Y drains `H`, and its subscriber calls the form. Y's form wait and
//! X's hub send wait for each other. Each test runs both arrival orders:
//!
//! - X's send records its wait first. Y's form wait would close the cycle, so
//!   it is refused. Y's `set_model`, `revert` or validator revalidation joins
//!   X's queue and replays on X when X's publication ends. Y's `dispose()` marks the form disposed, and
//!   X runs the teardown when its publication ends.
//! - Y's form wait comes first. X's send would close the cycle, so it enqueues
//!   for Y's drain (ADR-0119). Y proceeds when X's scope closes, and its drain
//!   then delivers X's message.
//!
//! The threads are ordered by observed wait registrations, not by sleeps.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread::{self, JoinHandle, ThreadId};
use std::time::{Duration, Instant};

use vmx::{wait_registered_for_testing, Command, FormVm, Message, MessageHub, VmxResult};

/// The hang guard of every wait in this file.
const BOUND: Duration = Duration::from_secs(10);

/// The invalid model that makes X's update change the error map.
const BAD: i32 = -1;
/// The model that Y's `set_model` assigns.
const Y_MODEL: i32 = 42;

/// Where X's sink runs.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Sink {
    /// X's `set_model(BAD)` delivers `errors_changed`.
    UpdateErrorsChanged,
    /// X's approval delivers `OnApproved`.
    OnApproved,
    /// X's `OnApproved` subscriber calls `set_model`; the form's hub is `H`,
    /// so the nested update's `"model"` message is X's send.
    OnApprovedSetsModel,
    /// X's approval resets the model to `BAD` and delivers `errors_changed`.
    ResetErrorsChanged,
    /// X's approval delivers its settlement eligibility change.
    Settlement,
}

/// What Y's `H` subscriber does to the form.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Call {
    /// Reads `is_dirty()` (the control: it never waits).
    ReadIsDirty,
    SetModel,
    Revert,
    Dispose,
    /// Approves the form again. A refused admission is admitted, and a
    /// refused settlement commits at once in a second scope.
    Approve,
    /// Registers a field validator. Its revalidation waits like `set_model`,
    /// and a refused one joins X's queue (#1231).
    RegisterValidator,
}

/// Which wait the test lets record first.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Order {
    /// X's hub send waits first; Y's form wait is refused.
    SendFirst,
    /// Y's form wait comes first; X's send is refused.
    FormWaitFirst,
}

/// A thread id that a test publishes once the thread runs.
#[derive(Clone, Default)]
struct Slot(Arc<Mutex<Option<ThreadId>>>);

impl Slot {
    fn set(&self) {
        *self.0.lock().unwrap() = Some(thread::current().id());
    }

    fn get(&self) -> Option<ThreadId> {
        *self.0.lock().unwrap()
    }
}

/// Polls `condition` until it holds or the bound passes. Returns whether it
/// held, so a sink or subscriber never panics inside the library.
fn eventually(condition: impl Fn() -> bool) -> bool {
    let deadline = Instant::now() + BOUND;
    while !condition() {
        if Instant::now() >= deadline {
            return false;
        }
        thread::sleep(Duration::from_millis(1));
    }
    true
}

/// Joins `handle`, failing instead of hanging when it does not return by
/// `deadline`.
fn join_by<T>(handle: JoinHandle<T>, deadline: Instant, what: &str) -> T {
    while !handle.is_finished() {
        assert!(Instant::now() < deadline, "{what} did not return: deadlock");
        thread::sleep(Duration::from_millis(1));
    }
    handle.join().unwrap()
}

fn custom(name: &str) -> Message {
    Message::Custom {
        sender_id: 0,
        sender_name: "test".into(),
        name: name.into(),
    }
}

fn named(message: &Message, expected: &str) -> bool {
    matches!(message, Message::Custom { name, .. } if name == expected)
}

/// What one run observed.
#[derive(Debug)]
struct Outcome {
    x_result: VmxResult<()>,
    /// The model Y read right after its call returned.
    y_read_after_call: i32,
    /// Whether Y saw its validator's error right after its call returned,
    /// and whether the form has it at the end of the run.
    y_saw_extra_error: bool,
    extra_error_at_end: bool,
    /// Whether the arrival order was the one the test asked for.
    ordered: bool,
    /// The non-`go` messages each `H` subscriber received.
    y_subscriber_messages: Vec<String>,
    counting_subscriber_messages: Vec<String>,
    /// Whether the form's `errors_changed` stream had completed when Y's
    /// call returned, and at the end of the run.
    completed_at_y_return: bool,
    completed_at_end: bool,
    /// Whether the approval subscription was still active at the end.
    approval_subscription_active: bool,
    model: i32,
    snapshot: i32,
    is_disposed: bool,
    /// The persister calls, and Y's approve result.
    persisted: usize,
    y_approve: Option<VmxResult<()>>,
}

fn label(message: &Message) -> String {
    match message {
        Message::Custom { name, .. } => name.clone(),
        Message::PropertyChanged(changed) => format!("property:{}", changed.property_name),
        other => format!("{other:?}"),
    }
}

/// Runs one #1170 row in one arrival order.
fn run(sink: Sink, call: Call, order: Order) -> Outcome {
    let h = MessageHub::new();
    let persisted = Arc::new(AtomicUsize::new(0));
    let form_hub = if sink == Sink::OnApprovedSetsModel {
        h.clone()
    } else {
        MessageHub::new()
    };
    let mut builder = FormVm::builder()
        .initial(1)
        .persister({
            let persisted = Arc::clone(&persisted);
            move |_: &i32| {
                persisted.fetch_add(1, Ordering::SeqCst);
                Ok(())
            }
        })
        .hub(form_hub)
        .validator("value", |model: &i32| {
            (*model < 0).then(|| "negative".to_string())
        });
    if sink == Sink::ResetErrorsChanged {
        builder = builder.reset_on_approved(|_| Ok(BAD));
    }
    let form = builder.build().unwrap();
    if sink != Sink::UpdateErrorsChanged {
        // The approvals approve a dirty form.
        form.set_model(2);
    }

    let x_slot = Slot::default();
    let y_slot = Slot::default();
    let ordered = Arc::new(AtomicBool::new(false));
    let (y_draining_tx, y_draining) = mpsc::channel::<()>();
    let (release_y, release_y_rx) = mpsc::channel::<()>();
    let release_y = Mutex::new(Some(release_y));
    let fired = Arc::new(AtomicBool::new(false));

    // X's sink: release Y, then send on H once, on X only.
    let x_sink = {
        let (h, x_slot, y_slot, ordered, fired) = (
            h.clone(),
            x_slot.clone(),
            y_slot.clone(),
            Arc::clone(&ordered),
            Arc::clone(&fired),
        );
        let form = form.clone();
        move || {
            if x_slot.get() != Some(thread::current().id()) || fired.swap(true, Ordering::SeqCst) {
                return;
            }
            drop(release_y.lock().unwrap().take());
            if order == Order::FormWaitFirst && call != Call::ReadIsDirty {
                let y = y_slot.get();
                ordered.store(
                    eventually(|| y.is_some_and(wait_registered_for_testing)),
                    Ordering::SeqCst,
                );
            }
            if sink == Sink::OnApprovedSetsModel {
                form.set_model(3);
            } else {
                h.send(custom("x"));
            }
        }
    };
    let x_sink = Arc::new(x_sink);
    let mut keep = Vec::new();
    let mut keep_approval = None;
    match sink {
        Sink::UpdateErrorsChanged | Sink::ResetErrorsChanged => {
            let x_sink = Arc::clone(&x_sink);
            keep.push(form.errors_changed().subscribe(move |_| x_sink()));
        }
        Sink::OnApproved | Sink::OnApprovedSetsModel => {
            let x_sink = Arc::clone(&x_sink);
            keep_approval = Some(form.subscribe_approved(move |_| x_sink()));
        }
        Sink::Settlement => {
            let x_sink = Arc::clone(&x_sink);
            let form = form.clone();
            // The admission notification sees an approval in flight.
            keep.push(
                form.approve_command()
                    .can_execute_changed()
                    .subscribe(move |_| {
                        if form.can_approve() {
                            x_sink();
                        }
                    }),
            );
        }
    }
    let approval_subscription = keep_approval.unwrap_or_else(|| form.subscribe_approved(|_| {}));
    let completed = Arc::new(AtomicBool::new(false));
    keep.push(form.errors_changed().subscribe_with_completion(|_| {}, {
        let completed = Arc::clone(&completed);
        move || completed.store(true, Ordering::SeqCst)
    }));

    // Y's subscriber: hold the drain until X's sink runs, then call the form.
    let y_messages = Arc::new(Mutex::new(Vec::new()));
    let y_read = Arc::new(Mutex::new(None));
    let y_saw_extra_error = Arc::new(AtomicBool::new(false));
    let y_approve = Arc::new(Mutex::new(None));
    let completed_at_y_return = Arc::new(AtomicBool::new(false));
    let release_y_rx = Mutex::new(release_y_rx);
    let _y_subscriber = h.subscribe({
        let (form, x_slot, ordered) = (form.clone(), x_slot.clone(), Arc::clone(&ordered));
        let (y_messages, y_read, y_approve) = (
            Arc::clone(&y_messages),
            Arc::clone(&y_read),
            Arc::clone(&y_approve),
        );
        let (completed, completed_at_y_return) =
            (Arc::clone(&completed), Arc::clone(&completed_at_y_return));
        let y_saw_extra_error = Arc::clone(&y_saw_extra_error);
        move |message| {
            if !named(message, "go") {
                y_messages.lock().unwrap().push(label(message));
                return;
            }
            y_draining_tx.send(()).unwrap();
            // A dropped sender also releases Y.
            let _ = release_y_rx.lock().unwrap().recv_timeout(BOUND);
            if order == Order::SendFirst && call != Call::ReadIsDirty {
                let x = x_slot.get();
                ordered.store(
                    eventually(|| x.is_some_and(wait_registered_for_testing)),
                    Ordering::SeqCst,
                );
            }
            match call {
                Call::ReadIsDirty => {
                    let _ = form.is_dirty();
                    ordered.store(true, Ordering::SeqCst);
                }
                Call::SetModel => form.set_model(Y_MODEL),
                Call::Revert => form.revert(),
                Call::Dispose => form.dispose(),
                Call::Approve => *y_approve.lock().unwrap() = Some(form.approve()),
                Call::RegisterValidator => {
                    form.with_field_validator("extra", |_: &i32| Some("required".to_string()));
                }
            }
            *y_read.lock().unwrap() = Some(form.model());
            y_saw_extra_error.store(form.field_error("extra").is_some(), Ordering::SeqCst);
            completed_at_y_return.store(completed.load(Ordering::SeqCst), Ordering::SeqCst);
        }
    });
    let counting = Arc::new(Mutex::new(Vec::new()));
    let _counting_subscriber = h.subscribe({
        let counting = Arc::clone(&counting);
        move |message| {
            if !named(message, "go") {
                counting.lock().unwrap().push(label(message));
            }
        }
    });

    let y = thread::spawn({
        let (h, y_slot) = (h.clone(), y_slot.clone());
        move || {
            y_slot.set();
            h.send(custom("go"));
        }
    });
    y_draining.recv_timeout(BOUND).expect("Y holds the drain");
    let x = thread::spawn({
        let (form, x_slot) = (form.clone(), x_slot.clone());
        move || {
            x_slot.set();
            if sink == Sink::UpdateErrorsChanged {
                form.set_model(BAD);
                Ok(())
            } else {
                form.approve()
            }
        }
    });
    let deadline = Instant::now() + BOUND;
    let x_result = join_by(x, deadline, "X");
    join_by(y, deadline, "Y");

    let y_read_after_call = y_read.lock().unwrap().expect("Y called the form");
    let y_subscriber_messages = y_messages.lock().unwrap().clone();
    let counting_subscriber_messages = counting.lock().unwrap().clone();
    let outcome = Outcome {
        x_result,
        y_read_after_call,
        y_saw_extra_error: y_saw_extra_error.load(Ordering::SeqCst),
        extra_error_at_end: form.field_error("extra").is_some(),
        ordered: ordered.load(Ordering::SeqCst),
        y_subscriber_messages,
        counting_subscriber_messages,
        completed_at_y_return: completed_at_y_return.load(Ordering::SeqCst),
        completed_at_end: completed.load(Ordering::SeqCst),
        approval_subscription_active: approval_subscription.is_active(),
        model: form.model(),
        snapshot: form.snapshot(),
        is_disposed: !form.deny_command().can_execute(),
        persisted: persisted.load(Ordering::SeqCst),
        y_approve: y_approve.lock().unwrap().take(),
    };
    drop(keep);
    outcome
}

/// The messages X sends on `H` in a row, each of which every `H` subscriber
/// receives exactly once.
fn x_messages(sink: Sink, call: Call) -> Vec<String> {
    if sink != Sink::OnApprovedSetsModel {
        return vec!["x".to_string()];
    }
    let mut messages = vec!["property:model".to_string()];
    if call == Call::SetModel {
        // Y's own edit publishes one more model message, on Y or on X.
        messages.push("property:model".to_string());
    }
    messages
}

/// Runs a row in both arrival orders and checks that no call is lost.
fn check_row(sink: Sink, call: Call) {
    for order in [Order::SendFirst, Order::FormWaitFirst] {
        let outcome = run(sink, call, order);
        let context = format!("{sink:?} / {call:?} / {order:?}: {outcome:?}");
        assert!(outcome.ordered, "the waits arrived as ordered: {context}");
        assert_eq!(outcome.x_result, Ok(()), "{context}");
        let expected = x_messages(sink, call);
        assert_eq!(outcome.y_subscriber_messages, expected, "{context}");
        assert_eq!(outcome.counting_subscriber_messages, expected, "{context}");
        let refused = order == Order::SendFirst;
        match call {
            Call::ReadIsDirty => {}
            Call::SetModel => {
                assert_eq!(outcome.model, Y_MODEL, "Y's edit is not lost: {context}");
                assert_eq!(
                    outcome.y_read_after_call == Y_MODEL,
                    !refused,
                    "a refused edit returns before it takes effect: {context}"
                );
            }
            Call::Revert => {
                assert_eq!(
                    outcome.model, outcome.snapshot,
                    "Y's revert is not lost: {context}"
                );
            }
            Call::Dispose => {
                assert!(outcome.is_disposed, "{context}");
                assert!(
                    outcome.completed_at_end,
                    "errors_changed completes: {context}"
                );
                assert!(
                    !outcome.approval_subscription_active,
                    "the approval subscription ends: {context}"
                );
                if refused {
                    assert!(
                        !outcome.completed_at_y_return,
                        "a refused dispose leaves the teardown to X: {context}"
                    );
                } else if sink != Sink::UpdateErrorsChanged {
                    assert!(
                        outcome.completed_at_y_return,
                        "a dispose after X's settlement tears down at once: {context}"
                    );
                }
                // After an update scope, X may still deliver its eligibility
                // change and "model" message. A dispose then leaves the
                // teardown to X's delivery (#1228), so Y may return first.
            }
            Call::Approve => {
                assert_eq!(outcome.y_approve, Some(Ok(())), "{context}");
                assert_eq!(outcome.persisted, 2, "Y's approval persists: {context}");
                assert_eq!(outcome.snapshot, 2, "{context}");
            }
            Call::RegisterValidator => {
                assert!(
                    outcome.extra_error_at_end,
                    "Y's revalidation is not lost: {context}"
                );
                assert_eq!(
                    outcome.y_saw_extra_error, !refused,
                    "a refused revalidation returns before it takes effect: {context}"
                );
            }
        }
    }
}

/// #1170 — X's update `errors_changed` sink sends on `H` while Y drains it.
#[test]
fn an_update_errors_changed_sink_and_a_hub_drainer_calling_the_form_finish() {
    for call in [
        Call::ReadIsDirty,
        Call::SetModel,
        Call::Revert,
        Call::Dispose,
        Call::RegisterValidator,
    ] {
        check_row(Sink::UpdateErrorsChanged, call);
    }
}

/// #1170 — X's `OnApproved` sink sends on `H` while Y drains it. When Y's
/// approval closes the cycle, its admission and its settlement do not wait,
/// and two threads hold publication scopes (spec/20 §5.5).
#[test]
fn an_approved_sink_and_a_hub_drainer_calling_the_form_finish() {
    for call in [
        Call::ReadIsDirty,
        Call::SetModel,
        Call::Revert,
        Call::Dispose,
        Call::Approve,
        Call::RegisterValidator,
    ] {
        check_row(Sink::OnApproved, call);
    }
}

/// #1170 — X's `OnApproved` subscriber calls `set_model` on a form whose hub
/// is `H`, so the nested update sends its `"model"` message while the
/// settlement scope is still open.
#[test]
fn an_approved_sink_edit_on_a_form_published_to_the_drained_hub_finishes() {
    for call in [Call::ReadIsDirty, Call::SetModel] {
        check_row(Sink::OnApprovedSetsModel, call);
    }
}

/// #1170 — the `errors_changed` sink of X's approval reset sends on `H`.
#[test]
fn a_reset_errors_changed_sink_and_a_hub_drainer_calling_the_form_finish() {
    for call in [Call::ReadIsDirty, Call::SetModel] {
        check_row(Sink::ResetErrorsChanged, call);
    }
}

/// #1170 — X's settlement eligibility-change sink sends on `H`.
#[test]
fn a_settlement_sink_and_a_hub_drainer_calling_the_form_finish() {
    for call in [Call::ReadIsDirty, Call::SetModel] {
        check_row(Sink::Settlement, call);
    }
}

/// spec/20 §5.5 — a refused update replays on the publisher. Its replay
/// panic propagates from the publisher's update after the last replay.
#[test]
fn a_refused_update_that_panics_at_replay_reaches_the_publishers_update() {
    let h = MessageHub::new();
    let armed = Arc::new(AtomicBool::new(false));
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .validator("value", {
            let armed = Arc::clone(&armed);
            move |model: &i32| {
                // The second preparation of Y's edit, its replay on X, panics.
                if *model == Y_MODEL && armed.swap(false, Ordering::SeqCst) {
                    panic!("replayed validator panic");
                }
                (*model < 0).then(|| "negative".to_string())
            }
        })
        .build()
        .unwrap();
    let x_slot = Slot::default();
    let (y_draining_tx, y_draining) = mpsc::channel::<()>();
    let (release_y, release_y_rx) = mpsc::channel::<()>();
    let release_y = Mutex::new(Some(release_y));
    let _x_sink = form.errors_changed().subscribe({
        let (h, x_slot) = (h.clone(), x_slot.clone());
        move |_| {
            if x_slot.get() == Some(thread::current().id()) {
                drop(release_y.lock().unwrap().take());
                h.send(custom("x"));
            }
        }
    });
    let release_y_rx = Mutex::new(release_y_rx);
    let deliveries = Arc::new(AtomicUsize::new(0));
    let _y_subscriber = h.subscribe({
        let (form, x_slot, armed, deliveries) = (
            form.clone(),
            x_slot.clone(),
            Arc::clone(&armed),
            Arc::clone(&deliveries),
        );
        move |message| {
            if !named(message, "go") {
                deliveries.fetch_add(1, Ordering::SeqCst);
                return;
            }
            y_draining_tx.send(()).unwrap();
            let _ = release_y_rx.lock().unwrap().recv_timeout(BOUND);
            let x = x_slot.get();
            eventually(|| x.is_some_and(wait_registered_for_testing));
            form.set_model(Y_MODEL);
            armed.store(true, Ordering::SeqCst);
        }
    });
    let y = thread::spawn({
        let h = h.clone();
        move || h.send(custom("go"))
    });
    y_draining.recv_timeout(BOUND).expect("Y holds the drain");
    let x = thread::spawn({
        let (form, x_slot) = (form.clone(), x_slot.clone());
        move || {
            x_slot.set();
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| form.set_model(BAD)))
        }
    });
    let deadline = Instant::now() + BOUND;
    let x_outcome = join_by(x, deadline, "X");
    join_by(y, deadline, "Y");

    assert!(x_outcome.is_err(), "the replay panic reaches X's set_model");
    assert_eq!(form.model(), BAD, "X's own update stands");
    assert_eq!(deliveries.load(Ordering::SeqCst), 1);
    form.set_model(5);
    assert_eq!(form.model(), 5, "the form stays usable");
}
