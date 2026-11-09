//! Nested `FormVm` updates notify at the outermost update (spec/20 §5.4,
//! ADR-0180, #1173).
//!
//! A call from a preparation callback of `set_model` or `revert`, or from an
//! `errors_changed` subscriber that the outermost update delivers, is nested.
//! It returns before its notifications. The outermost update sends them
//! before it returns: error maps first, in commit order, then the others. A
//! nested approval persists after that. Queued notifications are dropped once
//! the form is disposed, and a disposal before the persister starts prevents
//! the persister call. Every wait is bounded, so a regression fails instead
//! of hanging.

use std::panic::{catch_unwind, panic_any, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex, OnceLock};
use std::thread::{self, JoinHandle, ThreadId};
use std::time::{Duration, Instant};

use vmx::{
    wait_registered_for_testing, ApprovalSubscription, Command, FormVm, FormVmBuilder, Message,
    MessageHub, Subscription, VmxError,
};

/// How long a test waits for work that must not happen.
const SETTLE: Duration = Duration::from_millis(50);

/// The hang guard of every cross-thread wait.
const BOUND: Duration = Duration::from_secs(10);

type Model = &'static str;

/// An ordered event log shared by the form's callbacks and observers.
#[derive(Clone, Default)]
struct Log(Arc<Mutex<Vec<String>>>);

impl Log {
    fn push(&self, event: impl Into<String>) {
        self.0.lock().unwrap().push(event.into());
    }

    fn take(&self) -> Vec<String> {
        std::mem::take(&mut *self.0.lock().unwrap())
    }
}

/// Lets a callback registered at build time reach the form built from it.
#[derive(Clone, Default)]
struct Slot(Arc<OnceLock<FormVm<Model>>>);

impl Slot {
    fn form(&self) -> FormVm<Model> {
        self.0.get().expect("the form is built").clone()
    }

    fn fill(&self, form: &FormVm<Model>) {
        assert!(self.0.set(form.clone()).is_ok());
    }
}

/// Logs each `errors_changed`, eligibility change, `FormReverted`, and model
/// message. `errors_changed` carries no map, so it logs the error map read
/// when the notification arrives.
fn observe(form: &FormVm<Model>, log: &Log) -> Vec<Subscription> {
    let errors = form.errors_changed().subscribe({
        let (form, log) = (form.clone(), log.clone());
        move |_| log.push(format!("errors {:?}", form.error_map()))
    });
    let command = form.approve_command().can_execute_changed().subscribe({
        let log = log.clone();
        move |_| log.push("can_execute")
    });
    let hub = form.hub().subscribe({
        let log = log.clone();
        move |message| match message {
            Message::PropertyChanged(change) if change.property_name == "model" => {
                log.push("model")
            }
            Message::FormReverted(_) => log.push("reverted"),
            _ => {}
        }
    });
    vec![errors, command, hub]
}

/// A non-strict form with a private hub whose validator rejects `rejected`
/// and runs `hook` on each validated model.
fn builder(
    initial: Model,
    rejected: Model,
    hook: impl Fn(&Model) + Send + Sync + 'static,
) -> FormVmBuilder<Model> {
    FormVm::builder()
        .initial(initial)
        .persister(|_| Ok(()))
        .hub(MessageHub::new())
        .validator("value", move |model: &Model| {
            hook(model);
            (*model == rejected).then(|| format!("rejects {model}"))
        })
}

/// Runs `nested` only the first time it is called.
fn once(nested: impl Fn() + Send + Sync + 'static) -> impl Fn() + Send + Sync + 'static {
    let armed = AtomicBool::new(true);
    move || {
        if armed.swap(false, Ordering::SeqCst) {
            nested();
        }
    }
}

fn error_map(model: Model) -> String {
    format!("errors {{\"value\": \"rejects {model}\"}}")
}

/// FORM-041 — a set_model nested in a validator returns before its notifications
#[test]
fn a_nested_assignment_from_a_validator_notifies_after_it_returns() {
    let (slot, log) = (Slot::default(), Log::default());
    let nested = once({
        let (slot, log) = (slot.clone(), log.clone());
        move || {
            slot.form().set_model("b");
            log.push("nested returned");
        }
    });
    let form = builder("i", "b", move |model| {
        if *model == "a" {
            nested();
        }
    })
    .build()
    .unwrap();
    slot.fill(&form);
    let _observers = observe(&form, &log);

    form.set_model("a");
    log.push("outer returned");

    assert_eq!(
        log.take(),
        [
            "nested returned".to_string(),
            error_map("b"),
            "can_execute".to_string(),
            "model".to_string(),
            "outer returned".to_string(),
        ]
    );
    assert_eq!(form.model(), "b");
    assert_eq!(form.field_error("value").as_deref(), Some("rejects b"));
}

/// FORM-041 — a deny nested in a validator returns before its notifications
#[test]
fn a_nested_deny_from_a_validator_notifies_after_it_returns() {
    let (slot, log) = (Slot::default(), Log::default());
    let nested = once({
        let (slot, log) = (slot.clone(), log.clone());
        move || {
            slot.form().deny_command().execute();
            log.push("nested returned");
        }
    });
    let form = builder("i", "x", move |model| {
        if *model == "a" {
            nested();
        }
    })
    .build()
    .unwrap();
    slot.fill(&form);
    form.set_model("x");
    assert!(form.is_dirty() && !form.is_valid());
    let _observers = observe(&form, &log);

    form.set_model("a");
    log.push("outer returned");

    assert_eq!(
        log.take(),
        [
            "nested returned",
            "errors {}",
            "reverted",
            "model",
            "can_execute",
            "outer returned",
        ]
    );
    assert_eq!(form.model(), form.snapshot());
    assert!(form.is_valid());
}

/// FORM-041 — an update from an errors_changed subscriber notifies after the outer update's error map, in commit order
#[test]
fn an_update_from_an_errors_changed_subscriber_notifies_in_commit_order() {
    let log = Log::default();
    let form = builder("i", "a", |_| {}).build().unwrap();
    let nested = once({
        let (form, log) = (form.clone(), log.clone());
        move || {
            form.set_model("c");
            log.push("nested returned");
        }
    });
    let _observers = observe(&form, &log);
    let _nested = form.errors_changed().subscribe(move |_| nested());

    form.set_model("a");
    log.push("outer returned");

    assert_eq!(
        log.take(),
        [
            error_map("a"),
            "nested returned".to_string(),
            "errors {}".to_string(),
            "can_execute".to_string(),
            "model".to_string(),
            "can_execute".to_string(),
            "model".to_string(),
            "outer returned".to_string(),
        ]
    );
    assert_eq!(form.model(), "c");
    assert!(form.is_valid());
}

/// FORM-041 — a nested approve() returns Ok once admitted and persists after the outer update's notifications
#[test]
fn a_nested_approval_persists_after_the_outer_notifications() {
    let (slot, log) = (Slot::default(), Log::default());
    let nested = once({
        let (slot, log) = (slot.clone(), log.clone());
        move || {
            assert_eq!(slot.form().approve(), Ok(()));
            log.push("nested returned");
        }
    });
    let form = FormVm::builder()
        .initial("i")
        .hub(MessageHub::new())
        .persister({
            let log = log.clone();
            move |model: &Model| {
                log.push(format!("persist {model}"));
                Ok(())
            }
        })
        .validator("value", move |model: &Model| {
            if *model == "a" {
                nested();
            }
            None
        })
        .build()
        .unwrap();
    slot.fill(&form);
    form.set_model("e");
    let _observers = observe(&form, &log);
    let _approved: ApprovalSubscription = form.subscribe_approved({
        let log = log.clone();
        move |model| log.push(format!("approved {model}"))
    });

    form.set_model("a");
    log.push("outer returned");

    // The admission change and the outer model message come first. The
    // approval then persists the model it captured, and races the outer
    // assignment as an edit during persistence (spec/20 §5.3).
    assert_eq!(
        log.take(),
        [
            "nested returned",
            "can_execute",
            "model",
            "persist e",
            "can_execute",
            "approved e",
            "outer returned",
        ]
    );
    assert_eq!(form.model(), "a");
    assert_eq!(form.snapshot(), "e");
    assert!(form.is_dirty());
}

/// FORM-041 — a nested approval routes a persister failure to approve_errors
#[test]
fn a_nested_approval_routes_its_failure_to_approve_errors() {
    let (slot, log) = (Slot::default(), Log::default());
    let nested = once({
        let (slot, log) = (slot.clone(), log.clone());
        move || {
            assert_eq!(slot.form().approve(), Ok(()));
            log.push("nested returned");
        }
    });
    let form = FormVm::builder()
        .initial("i")
        .hub(MessageHub::new())
        .persister(|_: &Model| Err(VmxError::Other("rejected".to_string())))
        .validator("value", move |model: &Model| {
            if *model == "a" {
                nested();
            }
            None
        })
        .build()
        .unwrap();
    slot.fill(&form);
    let _observers = observe(&form, &log);
    let _errors = form.approve_errors().subscribe({
        let log = log.clone();
        move |_| log.push("approve error")
    });

    form.set_model("a");
    log.push("outer returned");

    assert_eq!(
        log.take(),
        [
            "nested returned",
            "can_execute",
            "model",
            "can_execute",
            "approve error",
            "outer returned",
        ]
    );
    assert_eq!(form.snapshot(), "i");
    assert!(form.can_approve());
}

/// A panic planted in a persister.
#[derive(Debug, PartialEq)]
struct Planted;

/// FORM-041 — a nested approval's persister panic resumes from the outermost update after its notifications
#[test]
fn a_nested_approval_panic_resumes_from_the_outermost_update() {
    let (slot, log) = (Slot::default(), Log::default());
    let nested = once({
        let (slot, log) = (slot.clone(), log.clone());
        move || {
            assert_eq!(slot.form().approve(), Ok(()));
            log.push("nested returned");
        }
    });
    let form = FormVm::builder()
        .initial("i")
        .hub(MessageHub::new())
        .persister(|_: &Model| -> vmx::VmxResult<()> { panic_any(Planted) })
        .validator("value", move |model: &Model| {
            if *model == "a" {
                nested();
            }
            None
        })
        .build()
        .unwrap();
    slot.fill(&form);
    let _observers = observe(&form, &log);

    let payload = catch_unwind(AssertUnwindSafe(|| form.set_model("a")))
        .expect_err("the persister panic resumes from set_model");

    assert_eq!(payload.downcast_ref::<Planted>(), Some(&Planted));
    assert_eq!(
        log.take(),
        ["nested returned", "can_execute", "model", "can_execute"]
    );
    assert_eq!(form.model(), "a");
    assert!(
        form.can_approve(),
        "the failed settlement cleared the flight"
    );
}

/// Counts every notification of a form and its persister calls.
#[derive(Clone, Default)]
struct Counters {
    persists: Arc<AtomicUsize>,
    notifications: Arc<AtomicUsize>,
    /// The notification count after a `dispose()` from a callback returned.
    /// The commands' own disposal change is part of `dispose()` (spec/04).
    disposed_at: Arc<OnceLock<usize>>,
}

impl Counters {
    fn builder(&self, hook: impl Fn(&Model) + Send + Sync + 'static) -> FormVmBuilder<Model> {
        let persists = Arc::clone(&self.persists);
        FormVm::builder()
            .initial("i")
            .hub(MessageHub::new())
            .persister(move |_: &Model| {
                persists.fetch_add(1, Ordering::SeqCst);
                Ok(())
            })
            .validator("value", move |model: &Model| {
                hook(model);
                (*model == "b").then(|| "rejects b".to_string())
            })
    }

    fn observe(&self, form: &FormVm<Model>) -> (Vec<Subscription>, ApprovalSubscription) {
        let count = |counter: &Arc<AtomicUsize>| {
            let counter = Arc::clone(counter);
            move |_: &Message| {
                counter.fetch_add(1, Ordering::SeqCst);
            }
        };
        let subscriptions = vec![
            form.errors_changed().subscribe(count(&self.notifications)),
            form.approve_command()
                .can_execute_changed()
                .subscribe(count(&self.notifications)),
            form.hub().subscribe(count(&self.notifications)),
            form.approve_errors().subscribe(count(&self.notifications)),
        ];
        let approved = form.subscribe_approved({
            let counter = Arc::clone(&self.notifications);
            move |_| {
                counter.fetch_add(1, Ordering::SeqCst);
            }
        });
        (subscriptions, approved)
    }

    fn persists(&self) -> usize {
        self.persists.load(Ordering::SeqCst)
    }

    fn notifications(&self) -> usize {
        self.notifications.load(Ordering::SeqCst)
    }

    /// Disposes `form` from a callback. Nothing was sent before, and the
    /// count after it is the baseline for the rest of the test.
    fn dispose(&self, form: &FormVm<Model>) {
        assert_eq!(self.notifications(), 0, "a nested call sent nothing");
        form.dispose();
        assert!(self.disposed_at.set(self.notifications()).is_ok());
    }

    /// Asserts that nothing was sent after the disposal from a callback.
    fn assert_quiet_since_disposal(&self) {
        let disposed_at = *self
            .disposed_at
            .get()
            .expect("the callback disposed the form");
        assert_eq!(
            self.notifications(),
            disposed_at,
            "no queued notification was sent"
        );
    }
}

/// FORM-042 — a nested approval followed by dispose() never calls the persister
#[test]
fn disposal_after_a_nested_approval_prevents_the_persister_call() {
    let (slot, counters) = (Slot::default(), Counters::default());
    let nested = once({
        let (slot, counters) = (slot.clone(), counters.clone());
        move || {
            let form = slot.form();
            form.approve_command().execute();
            counters.dispose(&form);
        }
    });
    let form = counters
        .builder(move |model| {
            if *model == "trigger" {
                nested();
            }
        })
        .build()
        .unwrap();
    slot.fill(&form);
    let _observers = counters.observe(&form);

    form.set_model("trigger");
    thread::sleep(SETTLE);

    assert_eq!(counters.persists(), 0);
    counters.assert_quiet_since_disposal();
}

/// FORM-042 — dispose() after a nested set_model drops its queued notifications
#[test]
fn disposal_after_a_nested_assignment_drops_its_notifications() {
    let (slot, counters) = (Slot::default(), Counters::default());
    let nested = once({
        let (slot, counters) = (slot.clone(), counters.clone());
        move || {
            let form = slot.form();
            form.set_model("b");
            counters.dispose(&form);
        }
    });
    let form = counters
        .builder(move |model| {
            if *model == "a" {
                nested();
            }
        })
        .build()
        .unwrap();
    slot.fill(&form);
    let _observers = counters.observe(&form);

    form.set_model("a");

    counters.assert_quiet_since_disposal();
    assert_eq!(form.model(), "b");
}

/// FORM-042 — dispose() after the approve command returns keeps the persister call count
#[test]
fn disposal_after_the_approve_command_keeps_the_persister_count() {
    let counters = Counters::default();
    let form = counters.builder(|_| {}).build().unwrap();
    let _observers = counters.observe(&form);

    form.approve_command().execute();
    let persisted = counters.persists();
    form.dispose();
    thread::sleep(SETTLE);

    // The command path calls the persister before execute() returns.
    assert_eq!(persisted, 1);
    assert_eq!(counters.persists(), persisted);
}

/// Polls `condition` until it holds or [`BOUND`] passes, and reports whether
/// it held, so a callback never panics inside the library.
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

/// FORM-041 — a nested call never waits for another thread's publication scope and takes the refused-wait result
///
/// Thread X delivers its update's `errors_changed` in a scope, and its sink
/// sends on hub `H`, which thread Y drains. Y's `H` subscriber calls
/// `set_model`, whose wait for X's scope would close a wait-for cycle, so it
/// is refused and prepares at once (spec/20 §5.5). Its validator calls
/// `set_model` again. That nested call does not commit while X holds its
/// scope: it joins X's queue and replays when X's publication ends.
#[test]
fn a_nested_call_takes_the_refused_wait_result_while_another_thread_holds_a_scope() {
    const OUTER: i32 = 42;
    const NESTED: i32 = 43;
    let h = MessageHub::new();
    let x_id = Arc::new(OnceLock::new());
    let y_id = Arc::new(OnceLock::<ThreadId>::new());
    let read_after_nested = Arc::new(Mutex::new(None));
    let slot = Arc::new(OnceLock::<FormVm<i32>>::new());
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .hub(MessageHub::new())
        .validator("value", {
            let (slot, y_id) = (Arc::clone(&slot), Arc::clone(&y_id));
            let read_after_nested = Arc::clone(&read_after_nested);
            move |model: &i32| {
                if *model == OUTER && y_id.get() == Some(&thread::current().id()) {
                    let form = slot.get().expect("the form is built");
                    form.set_model(NESTED);
                    *read_after_nested.lock().unwrap() = Some(form.model());
                }
                (*model < 0).then(|| "negative".to_string())
            }
        })
        .build()
        .unwrap();
    assert!(slot.set(form.clone()).is_ok());

    let (release_y, release_y_rx) = mpsc::channel::<()>();
    let release_y = Mutex::new(Some(release_y));
    let _x_sink = form.errors_changed().subscribe({
        let (h, x_id) = (h.clone(), Arc::clone(&x_id));
        move |_| {
            if x_id.get() == Some(&thread::current().id()) {
                drop(release_y.lock().unwrap().take());
                // Y drains H, so this send waits for Y.
                h.send(custom("x"));
            }
        }
    });
    let ordered = Arc::new(AtomicBool::new(false));
    let (y_draining_tx, y_draining) = mpsc::channel::<()>();
    let release_y_rx = Mutex::new(release_y_rx);
    let _y_subscriber = h.subscribe({
        let (form, x_id, ordered) = (form.clone(), Arc::clone(&x_id), Arc::clone(&ordered));
        move |message| {
            if !matches!(message, Message::Custom { name, .. } if name == "go") {
                return;
            }
            y_draining_tx.send(()).unwrap();
            let _ = release_y_rx.lock().unwrap().recv_timeout(BOUND);
            let x = x_id.get().copied();
            ordered.store(
                eventually(|| x.is_some_and(wait_registered_for_testing)),
                Ordering::SeqCst,
            );
            form.set_model(OUTER);
        }
    });

    let y = thread::spawn({
        let (h, y_id) = (h.clone(), Arc::clone(&y_id));
        move || {
            y_id.set(thread::current().id()).unwrap();
            h.send(custom("go"));
        }
    });
    y_draining.recv_timeout(BOUND).expect("Y holds the drain");
    let x = thread::spawn({
        let (form, x_id) = (form.clone(), Arc::clone(&x_id));
        move || {
            x_id.set(thread::current().id()).unwrap();
            form.set_model(-1);
        }
    });
    let deadline = Instant::now() + BOUND;
    join_by(x, deadline, "X");
    join_by(y, deadline, "Y");

    assert!(ordered.load(Ordering::SeqCst), "X's send waited first");
    let read = read_after_nested
        .lock()
        .unwrap()
        .expect("Y's validator ran");
    assert_ne!(
        read, NESTED,
        "the nested call returned before it took effect"
    );
    // The nested call made the refused outer call stale, and it replayed on
    // X after X's publication ended.
    assert_eq!(form.model(), NESTED);
    assert!(form.is_valid());
}
