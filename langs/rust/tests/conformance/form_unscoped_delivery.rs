//! `FormVm` notifications delivered outside a publication scope (spec/20
//! §5.5, ADR-0176).
//!
//! - #1228: thread A delivers an admission notification, an update's
//!   eligibility change, or an `approve_errors` send. These open no scope, so
//!   thread B's `dispose()` does not wait. It marks the form disposed and
//!   returns, and the channels complete only after A's delivery returns.
//! - #1292: when threads A and C both deliver outside a scope, the deferred
//!   teardown runs on the thread whose delivery ends last.
//! - #1231: a validator registration revalidates as an update. It waits for
//!   another thread's publication scope and sends `errors_changed` in its own
//!   scope.
//!
//! Every wait is bounded by [`BOUND`], so a stall fails instead of hanging.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread::{self, JoinHandle, ThreadId};
use std::time::{Duration, Instant};

use vmx::{wait_registered_for_testing, Command, FormVm, Subscription, VmxError};

/// The hang guard of every wait in this file.
const BOUND: Duration = Duration::from_secs(10);

/// Joins `handle`, failing instead of hanging when it does not return by
/// `deadline`.
fn join_by<T>(handle: JoinHandle<T>, deadline: Instant, what: &str) -> T {
    while !handle.is_finished() {
        assert!(Instant::now() < deadline, "{what} did not return: deadlock");
        thread::sleep(Duration::from_millis(1));
    }
    handle.join().unwrap()
}

/// A form whose model is invalid below zero.
fn form(persister: fn(&i32) -> vmx::VmxResult<()>) -> FormVm<i32> {
    FormVm::builder()
        .initial(1)
        .persister(persister)
        .validator("value", |model: &i32| {
            (*model < 0).then(|| "negative".to_string())
        })
        .build()
        .unwrap()
}

/// Records when the form's `errors_changed` and `approve_errors` channels
/// complete.
struct Completion {
    errors_changed: Arc<AtomicBool>,
    approve_errors: Arc<AtomicBool>,
    _subscriptions: Vec<Subscription>,
}

impl Completion {
    fn watch(form: &FormVm<i32>) -> Self {
        let errors_changed = Arc::new(AtomicBool::new(false));
        let approve_errors = Arc::new(AtomicBool::new(false));
        let subscriptions = vec![
            form.errors_changed().subscribe_with_completion(|_| {}, {
                let completed = Arc::clone(&errors_changed);
                move || completed.store(true, Ordering::SeqCst)
            }),
            form.approve_errors().subscribe_with_completion(|_| {}, {
                let completed = Arc::clone(&approve_errors);
                move || completed.store(true, Ordering::SeqCst)
            }),
        ];
        Self {
            errors_changed,
            approve_errors,
            _subscriptions: subscriptions,
        }
    }

    fn any(&self) -> bool {
        self.errors_changed.load(Ordering::SeqCst) || self.approve_errors.load(Ordering::SeqCst)
    }

    fn all(&self) -> bool {
        self.errors_changed.load(Ordering::SeqCst) && self.approve_errors.load(Ordering::SeqCst)
    }
}

/// A blocking observer for thread A: it signals once it runs on A, then
/// waits, bounded, until the test releases it.
struct Block {
    a: Arc<Mutex<Option<ThreadId>>>,
    entered: Mutex<Option<mpsc::Sender<()>>>,
    release: Mutex<mpsc::Receiver<()>>,
    completed_on_return: Arc<Mutex<Option<bool>>>,
}

/// Runs `deliver` on thread A, where `observe` blocks the delivery that
/// the test targets, and disposes the form on thread B meanwhile.
///
/// Returns whether any channel had completed when B's `dispose()` returned
/// and when A's observer returned.
fn dispose_during(
    form: &FormVm<i32>,
    observe: impl FnOnce(Arc<dyn Fn() + Send + Sync>) -> Subscription,
    deliver: impl FnOnce(FormVm<i32>) + Send + 'static,
) -> (bool, bool, Completion) {
    let completion = Completion::watch(form);
    let (entered_tx, entered) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel::<()>();
    let block = Arc::new(Block {
        a: Arc::new(Mutex::new(None)),
        entered: Mutex::new(Some(entered_tx)),
        release: Mutex::new(release_rx),
        completed_on_return: Arc::new(Mutex::new(None)),
    });
    let observer: Arc<dyn Fn() + Send + Sync> = Arc::new({
        let block = Arc::clone(&block);
        let errors_changed = Arc::clone(&completion.errors_changed);
        let approve_errors = Arc::clone(&completion.approve_errors);
        move || {
            if *block.a.lock().unwrap() != Some(thread::current().id()) {
                return;
            }
            let Some(entered) = block.entered.lock().unwrap().take() else {
                return;
            };
            entered.send(()).unwrap();
            // A dropped sender also releases A.
            let _ = block.release.lock().unwrap().recv_timeout(BOUND);
            *block.completed_on_return.lock().unwrap() = Some(
                errors_changed.load(Ordering::SeqCst) || approve_errors.load(Ordering::SeqCst),
            );
        }
    });
    let _observation = observe(observer);

    let a = thread::spawn({
        let (form, a) = (form.clone(), Arc::clone(&block.a));
        move || {
            *a.lock().unwrap() = Some(thread::current().id());
            deliver(form);
        }
    });
    entered.recv_timeout(BOUND).expect("A's observer runs on A");
    let b = thread::spawn({
        let form = form.clone();
        move || form.dispose()
    });
    let deadline = Instant::now() + BOUND;
    join_by(b, deadline, "B's dispose()");
    let completed_at_dispose_return = completion.any();
    drop(release_tx);
    join_by(a, deadline, "A");
    let completed_at_observer_return = block
        .completed_on_return
        .lock()
        .unwrap()
        .expect("A's observer returned");
    (
        completed_at_dispose_return,
        completed_at_observer_return,
        completion,
    )
}

fn assert_deferred(outcome: (bool, bool, Completion), what: &str) {
    let (at_dispose_return, at_observer_return, completion) = outcome;
    assert!(
        !at_dispose_return,
        "{what}: B's dispose() completed a channel during A's delivery"
    );
    assert!(
        !at_observer_return,
        "{what}: a channel completed before A's observer returned"
    );
    assert!(
        completion.all(),
        "{what}: the channels complete after A's delivery returns"
    );
}

/// #1228 — B's `dispose()` during A's admission eligibility change defers its
/// teardown to A. A's approval then never reaches its persister.
#[test]
fn a_dispose_during_an_admission_notification_completes_the_channels_after_it() {
    let persisted = Arc::new(AtomicBool::new(false));
    let form = form(|_| Ok(()));
    let outcome = dispose_during(
        &form,
        |observer| {
            let form = form.clone();
            form.approve_command()
                .can_execute_changed()
                .subscribe(move |_| {
                    // The admission notification sees an approval in flight.
                    if !form.can_approve() {
                        observer();
                    }
                })
        },
        {
            let persisted = Arc::clone(&persisted);
            move |form| {
                assert_eq!(form.approve(), Ok(()));
                persisted.store(form.snapshot() != 1, Ordering::SeqCst);
            }
        },
    );
    assert_deferred(outcome, "admission");
    assert!(!persisted.load(Ordering::SeqCst));
}

/// #1228 — B's `dispose()` during the eligibility change of A's `set_model`,
/// after its update scope closed, defers its teardown to A.
#[test]
fn a_dispose_during_an_update_eligibility_change_completes_the_channels_after_it() {
    let form = form(|_| Ok(()));
    let outcome = dispose_during(
        &form,
        |observer| {
            form.approve_command()
                .can_execute_changed()
                .subscribe(move |_| observer())
        },
        |form| form.set_model(-1),
    );
    assert_deferred(outcome, "update eligibility change");
    assert_eq!(form.model(), -1, "A's update committed");
}

/// #1228 — B's `dispose()` during A's `approve_errors` send defers its
/// teardown to A, as in C# and Python.
#[test]
fn a_dispose_during_an_approve_errors_send_completes_the_channels_after_it() {
    let form = form(|_| Err(VmxError::Other("persist failed".to_string())));
    let outcome = dispose_during(
        &form,
        |observer| form.approve_errors().subscribe(move |_| observer()),
        |form| form.approve_command().execute(),
    );
    assert_deferred(outcome, "approve_errors");
}

/// #1228 — a disposal made by the delivering thread's own observer also
/// waits for that delivery, and the channels complete before the update
/// returns.
#[test]
fn a_dispose_from_an_update_eligibility_observer_completes_the_channels_when_it_returns() {
    let form = form(|_| Ok(()));
    let completion = Completion::watch(&form);
    let completed_in_observer = Arc::new(Mutex::new(None));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, completed_in_observer) = (form.clone(), Arc::clone(&completed_in_observer));
        let errors_changed = Arc::clone(&completion.errors_changed);
        move |_| {
            form.dispose();
            *completed_in_observer.lock().unwrap() = Some(errors_changed.load(Ordering::SeqCst));
        }
    });
    form.set_model(-1);
    assert_eq!(*completed_in_observer.lock().unwrap(), Some(false));
    assert!(completion.all(), "the update completes the channels");
}

/// One thread's blocking point in an observer: it signals once the observer
/// runs on that thread, then waits, bounded, until the test releases it.
struct Gate {
    thread: Mutex<Option<ThreadId>>,
    entered: Mutex<Option<mpsc::Sender<()>>>,
    release: Mutex<mpsc::Receiver<()>>,
}

impl Gate {
    fn new() -> (Arc<Self>, mpsc::Receiver<()>, mpsc::Sender<()>) {
        let (entered_tx, entered) = mpsc::channel();
        let (release, release_rx) = mpsc::channel();
        let gate = Arc::new(Self {
            thread: Mutex::new(None),
            entered: Mutex::new(Some(entered_tx)),
            release: Mutex::new(release_rx),
        });
        (gate, entered, release)
    }

    /// Blocks the first call on this gate's thread. Returns whether it did.
    fn pass(&self) -> bool {
        if *self.thread.lock().unwrap() != Some(thread::current().id()) {
            return false;
        }
        let Some(entered) = self.entered.lock().unwrap().take() else {
            return false;
        };
        entered.send(()).unwrap();
        // A dropped sender also releases the thread.
        let _ = self.release.lock().unwrap().recv_timeout(BOUND);
        true
    }
}

/// #1292 — thread A delivers an `approve_errors` send and thread C an
/// update's eligibility change, each outside a scope, and thread B's
/// `dispose()` defers its teardown. The teardown runs when no delivery
/// remains on any thread, on the thread that ends the last one: when A
/// returns first, no channel completes, and the channels complete on C when
/// C returns. (A hub delivers one message at a time, so the two deliveries
/// use two hubs.)
#[test]
fn a_deferred_teardown_runs_on_the_thread_that_ends_the_last_delivery() {
    let form = form(|_| Err(VmxError::Other("persist failed".to_string())));
    let completion = Completion::watch(&form);
    let completed_on = Arc::new(Mutex::new(None::<ThreadId>));
    let _completed_on = form.errors_changed().subscribe_with_completion(|_| {}, {
        let completed_on = Arc::clone(&completed_on);
        move || *completed_on.lock().unwrap() = Some(thread::current().id())
    });
    let (gate_a, entered_a, release_a) = Gate::new();
    let (gate_c, entered_c, release_c) = Gate::new();
    let completed_on_a_return = Arc::new(Mutex::new(None::<bool>));
    let _approve_errors = form.approve_errors().subscribe({
        let gate_a = Arc::clone(&gate_a);
        let completed_on_a_return = Arc::clone(&completed_on_a_return);
        let errors_changed = Arc::clone(&completion.errors_changed);
        let approve_errors = Arc::clone(&completion.approve_errors);
        move |_| {
            if gate_a.pass() {
                *completed_on_a_return.lock().unwrap() = Some(
                    errors_changed.load(Ordering::SeqCst) || approve_errors.load(Ordering::SeqCst),
                );
            }
        }
    });
    let _eligibility = form.approve_command().can_execute_changed().subscribe({
        let gate_c = Arc::clone(&gate_c);
        move |_| {
            gate_c.pass();
        }
    });

    let spawn_on = |gate: &Arc<Gate>, call: fn(&FormVm<i32>)| {
        let (form, gate) = (form.clone(), Arc::clone(gate));
        thread::spawn(move || {
            *gate.thread.lock().unwrap() = Some(thread::current().id());
            call(&form);
            thread::current().id()
        })
    };
    let a = spawn_on(&gate_a, |form| form.approve_command().execute());
    entered_a
        .recv_timeout(BOUND)
        .expect("A's observer runs on A");
    // The failed approval is no longer in flight, so C's update, which makes
    // the model invalid, changes the approval eligibility.
    let c = spawn_on(&gate_c, |form| form.set_model(-1));
    entered_c
        .recv_timeout(BOUND)
        .expect("C's observer runs on C");

    let deadline = Instant::now() + BOUND;
    let b = thread::spawn({
        let form = form.clone();
        move || form.dispose()
    });
    join_by(b, deadline, "B's dispose()");
    assert!(
        !completion.any(),
        "B's dispose() completed a channel during A's and C's deliveries"
    );

    drop(release_a);
    join_by(a, deadline, "A");
    assert_eq!(
        *completed_on_a_return.lock().unwrap(),
        Some(false),
        "a channel completed before A's observer returned"
    );
    assert!(
        !completion.any(),
        "a channel completed when A returned while C still delivers"
    );

    drop(release_c);
    let c_id = join_by(c, deadline, "C");
    assert!(completion.all(), "the channels complete when C returns");
    assert_eq!(
        *completed_on.lock().unwrap(),
        Some(c_id),
        "the teardown runs on C, the thread that ends the last delivery"
    );
    assert_eq!(form.model(), -1, "C's update committed");
}

/// #1231 — thread A holds a settlement scope in an approval subscriber.
/// Thread B registers a field validator. B's revalidation waits, recorded in
/// the wait-for graph, and B's `errors_changed` delivery comes after A's
/// subscriber returns.
#[test]
fn a_validator_registration_waits_for_another_threads_settlement_scope() {
    let form = form(|_| Ok(()));
    form.set_model(2);
    let log = Arc::new(Mutex::new(Vec::<&str>::new()));
    let a_slot = Arc::new(Mutex::new(None::<ThreadId>));
    let (entered_tx, entered) = mpsc::channel();
    let entered_tx = Mutex::new(Some(entered_tx));
    let (release_tx, release_rx) = mpsc::channel::<()>();
    let release_rx = Mutex::new(release_rx);
    let _approved = form.subscribe_approved({
        let (log, a_slot) = (Arc::clone(&log), Arc::clone(&a_slot));
        move |_| {
            if *a_slot.lock().unwrap() != Some(thread::current().id()) {
                return;
            }
            if let Some(entered) = entered_tx.lock().unwrap().take() {
                entered.send(()).unwrap();
            }
            let _ = release_rx.lock().unwrap().recv_timeout(BOUND);
            log.lock().unwrap().push("A's subscriber returns");
        }
    });
    let _errors = form.errors_changed().subscribe({
        let log = Arc::clone(&log);
        move |_| log.lock().unwrap().push("errors_changed")
    });

    let a = thread::spawn({
        let (form, a_slot) = (form.clone(), Arc::clone(&a_slot));
        move || {
            *a_slot.lock().unwrap() = Some(thread::current().id());
            form.approve()
        }
    });
    entered
        .recv_timeout(BOUND)
        .expect("A's subscriber runs on A");
    let (b_id_tx, b_id) = mpsc::channel();
    let b = thread::spawn({
        let form = form.clone();
        move || {
            b_id_tx.send(thread::current().id()).unwrap();
            form.with_field_validator("extra", |_: &i32| Some("required".to_string()));
        }
    });
    let b_id = b_id.recv_timeout(BOUND).expect("B runs");
    // Release A once B waits, or once B returned without waiting.
    let deadline = Instant::now() + BOUND;
    while !wait_registered_for_testing(b_id) && !b.is_finished() {
        assert!(Instant::now() < deadline, "B neither waited nor returned");
        thread::sleep(Duration::from_millis(1));
    }
    let b_waited = wait_registered_for_testing(b_id);
    drop(release_tx);
    assert_eq!(join_by(a, deadline, "A"), Ok(()));
    join_by(b, deadline, "B");

    assert!(b_waited, "B's revalidation records a wait-for edge");
    assert_eq!(
        *log.lock().unwrap(),
        vec!["A's subscriber returns", "errors_changed"],
        "B's errors_changed comes after A's settlement scope"
    );
    assert_eq!(form.field_error("extra").as_deref(), Some("required"));
    assert!(!form.can_approve());
}
