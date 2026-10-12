//! `FormVm` model updates are failure-atomic (spec/20 §5.4, ADR-0144, #337).
//!
//! `set_model` and deny prepare before they commit. A validator, `PartialEq`,
//! or snapshotter that panics unwinds to the caller with the form unchanged
//! and nothing published. Updates are serialized across threads; a callback
//! that re-enters from the preparing thread and disposes the form or commits
//! another update makes the preparation it interrupted stale. Planted panics
//! carry a [`Planted`] payload, so an assertion failure is never mistaken for
//! one. As elsewhere in this suite, the test harness captures the panic
//! messages they print. Cross-thread waits are bounded, so a regression fails
//! instead of hanging.

use std::collections::BTreeMap;
use std::fmt;
use std::panic::{catch_unwind, panic_any, resume_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use vmx::{Command, FormVm, FormVmBuilder, Message, MessageHub, Subscription};

const TIMEOUT: Duration = Duration::from_secs(5);

/// How long a thread that should be blocked is given to make progress.
const BLOCKED: Duration = Duration::from_millis(150);

/// The value a planted callback fails on.
const MARKED: i32 = 13;

/// A planted failure, named after the callback that raised it.
#[derive(Debug, PartialEq)]
struct Planted(&'static str);

fn plant(site: &'static str) -> ! {
    panic_any(Planted(site))
}

/// Runs `update`, which must unwind with the panic planted at `site`.
fn assert_unwinds_from(site: &'static str, update: impl FnOnce()) {
    let payload = catch_unwind(AssertUnwindSafe(update))
        .expect_err("the planted panic propagates to the caller");
    match payload.downcast::<Planted>() {
        Ok(planted) => assert_eq!(*planted, Planted(site)),
        Err(other) => resume_unwind(other),
    }
}

/// Records, in order, every notification a model update can publish:
/// `errors`, `can_execute`, `reverted`, and `model <value read at publication>`.
struct Trace {
    events: Arc<Mutex<Vec<String>>>,
    _subscriptions: Vec<Subscription>,
}

impl Trace {
    fn observe<M>(form: &FormVm<M>) -> Self
    where
        M: Clone + PartialEq + Send + fmt::Debug + 'static,
    {
        let events = Arc::new(Mutex::new(Vec::new()));
        let push = |event: &'static str| {
            let events = Arc::clone(&events);
            move |_: &Message| events.lock().unwrap().push(event.to_string())
        };
        let errors = form.errors_changed().subscribe(push("errors"));
        let command = form
            .approve_command()
            .can_execute_changed()
            .subscribe(push("can_execute"));
        let hub = form.hub().subscribe({
            let events = Arc::clone(&events);
            let form = form.clone();
            move |message| match message {
                Message::PropertyChanged(change) if change.property_name == "model" => events
                    .lock()
                    .unwrap()
                    .push(format!("model {:?}", form.model())),
                Message::FormReverted(_) => events.lock().unwrap().push("reverted".to_string()),
                _ => {}
            }
        });
        Self {
            events,
            _subscriptions: vec![errors, command, hub],
        }
    }

    /// Returns a callback that appends `event` to this trace.
    fn marker(&self, event: &'static str) -> impl Fn() + Send + Sync + 'static {
        let events = Arc::clone(&self.events);
        move || events.lock().unwrap().push(event.to_string())
    }

    /// Returns and clears the events recorded so far.
    fn take(&self) -> Vec<String> {
        std::mem::take(&mut *self.events.lock().unwrap())
    }

    fn assert_quiet(&self) {
        assert_eq!(self.take(), Vec::<String>::new(), "nothing was published");
    }
}

/// Everything a model update may change, read through the public surface.
#[derive(Debug, PartialEq)]
struct FormState<V> {
    model: V,
    snapshot: V,
    errors: BTreeMap<String, String>,
    dirty: bool,
    valid: bool,
    can_approve: bool,
}

fn state_with<M, V>(form: &FormVm<M>, value: impl Fn(&M) -> V) -> FormState<V>
where
    M: Clone + PartialEq + Send + 'static,
{
    FormState {
        model: value(&form.model()),
        snapshot: value(&form.snapshot()),
        errors: form.error_map(),
        dirty: form.is_dirty(),
        valid: form.is_valid(),
        can_approve: form.approve_command().can_execute(),
    }
}

fn state(form: &FormVm<i32>) -> FormState<i32> {
    state_with(form, |model| *model)
}

fn errors(entries: &[(&str, &str)]) -> BTreeMap<String, String> {
    entries
        .iter()
        .map(|(field, error)| (field.to_string(), error.to_string()))
        .collect()
}

fn negative(model: &i32) -> Option<String> {
    (*model < 0).then(|| "negative".to_string())
}

fn builder<M: Clone + PartialEq + Send + 'static>(initial: M) -> FormVmBuilder<M> {
    FormVm::builder()
        .initial(initial)
        .persister(|_| Ok(()))
        .hub(MessageHub::new())
}

/// Lets a callback registered at build time reach the form built from it.
struct Slot<M: Clone + PartialEq + Send + 'static>(Arc<Mutex<Option<FormVm<M>>>>);

impl<M: Clone + PartialEq + Send + 'static> Clone for Slot<M> {
    fn clone(&self) -> Self {
        Self(Arc::clone(&self.0))
    }
}

impl<M: Clone + PartialEq + Send + 'static> Slot<M> {
    fn new() -> Self {
        Self(Arc::new(Mutex::new(None)))
    }

    fn fill(&self, form: &FormVm<M>) {
        *self.0.lock().unwrap() = Some(form.clone());
    }

    fn form(&self) -> FormVm<M> {
        self.0.lock().unwrap().clone().expect("the form is built")
    }
}

type EqHook = Arc<dyn Fn(i32, i32) + Send + Sync>;

/// A model whose `PartialEq` first runs a hook with both values, so a test
/// can make equality panic or read the form.
#[derive(Clone)]
struct Hooked {
    value: i32,
    on_eq: EqHook,
}

impl PartialEq for Hooked {
    fn eq(&self, other: &Self) -> bool {
        (self.on_eq)(self.value, other.value);
        self.value == other.value
    }
}

impl fmt::Debug for Hooked {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.value)
    }
}

/// Returns a constructor for models that share `on_eq`.
fn hooked(on_eq: impl Fn(i32, i32) + Send + Sync + 'static) -> impl Fn(i32) -> Hooked {
    let on_eq: EqHook = Arc::new(on_eq);
    move |value| Hooked {
        value,
        on_eq: Arc::clone(&on_eq),
    }
}

/// Holds a callback at a rendezvous until the test releases it.
#[derive(Clone)]
struct Gate(Arc<GateChannels>);

struct GateChannels {
    arrived: (Sender<()>, Mutex<Receiver<()>>),
    release: (Sender<()>, Mutex<Receiver<()>>),
}

impl Gate {
    fn new() -> Self {
        let (arrived, arrivals) = mpsc::channel();
        let (release, releases) = mpsc::channel();
        Self(Arc::new(GateChannels {
            arrived: (arrived, Mutex::new(arrivals)),
            release: (release, Mutex::new(releases)),
        }))
    }

    /// Called by the held callback: reports arrival, then waits for release.
    fn pass(&self) {
        self.0.arrived.0.send(()).unwrap();
        self.0
            .release
            .1
            .lock()
            .unwrap()
            .recv_timeout(TIMEOUT)
            .expect("the test released the callback");
    }

    fn arrived(&self) {
        self.0
            .arrived
            .1
            .lock()
            .unwrap()
            .recv_timeout(TIMEOUT)
            .expect("the callback reached the gate");
    }

    fn release(&self) {
        self.0.release.0.send(()).unwrap();
    }
}

fn on_worker<T: Send + 'static>(work: impl FnOnce() -> T + Send + 'static) -> Receiver<T> {
    let (done, result) = mpsc::channel();
    thread::spawn(move || {
        let _ = done.send(work());
    });
    result
}

fn finished<T>(result: &Receiver<T>) -> T {
    result.recv_timeout(TIMEOUT).expect("the worker finished")
}

fn assert_blocked<T: fmt::Debug>(result: &Receiver<T>) {
    assert_eq!(
        result.recv_timeout(BLOCKED).unwrap_err(),
        RecvTimeoutError::Timeout,
        "the worker waits for the update in progress"
    );
}

/// FORM-035 — a panicking field validator leaves the form unchanged, on its first run and after earlier runs
#[test]
fn a_panicking_field_validator_leaves_the_form_unchanged() {
    let runs = Arc::new(AtomicUsize::new(0));
    let form = builder(1)
        .strict(true)
        .validator("value", {
            let runs = Arc::clone(&runs);
            move |model: &i32| {
                runs.fetch_add(1, Ordering::SeqCst);
                if *model == MARKED {
                    plant("field validator");
                }
                negative(model)
            }
        })
        .build()
        .unwrap();
    let trace = Trace::observe(&form);
    assert_eq!(runs.load(Ordering::SeqCst), 1, "construction validated");

    // The validator's first run after construction.
    let pristine = state(&form);
    assert_unwinds_from("field validator", || form.set_model(MARKED));
    assert_eq!(runs.load(Ordering::SeqCst), 2);
    assert_eq!(state(&form), pristine);
    trace.assert_quiet();

    // After earlier successful runs: from an invalid form ...
    form.set_model(-1);
    assert_eq!(trace.take(), ["errors", "model -1"]);
    let invalid = state(&form);
    assert_unwinds_from("field validator", || form.set_model(MARKED));
    assert_eq!(state(&form), invalid);
    trace.assert_quiet();

    // ... and from a valid, dirty one that can approve.
    form.set_model(2);
    assert_eq!(trace.take(), ["errors", "can_execute", "model 2"]);
    let valid = state(&form);
    assert!(valid.can_approve);
    assert_unwinds_from("field validator", || form.set_model(MARKED));
    assert_eq!(state(&form), valid);
    trace.assert_quiet();
    assert_eq!(runs.load(Ordering::SeqCst), 6);

    // A candidate the validator accepts settles and publishes (FORM-030).
    form.set_model(-5);
    assert_eq!(trace.take(), ["errors", "can_execute", "model -5"]);
    assert_eq!(
        state(&form),
        FormState {
            model: -5,
            snapshot: 1,
            errors: errors(&[("value", "negative")]),
            dirty: true,
            valid: false,
            can_approve: false,
        }
    );
}

/// FORM-036 — a panicking model validator leaves the form unchanged
#[test]
fn a_panicking_model_validator_leaves_the_form_unchanged() {
    let form = builder(1)
        .validator("value", negative)
        .model_validator(|model: &i32| {
            if *model == -MARKED {
                plant("model validator");
            }
            BTreeMap::new()
        })
        .build()
        .unwrap();
    let trace = Trace::observe(&form);
    form.set_model(2);
    assert_eq!(trace.take(), ["model 2"]);
    let before = state(&form);

    // The field validator has already reported the candidate as negative
    // when the model validator panics.
    assert_unwinds_from("model validator", || form.set_model(-MARKED));
    assert_eq!(state(&form), before);
    trace.assert_quiet();

    form.set_model(-2);
    assert_eq!(trace.take(), ["errors", "can_execute", "model -2"]);
    assert_eq!(
        state(&form),
        FormState {
            model: -2,
            snapshot: 1,
            errors: errors(&[("value", "negative")]),
            dirty: true,
            valid: false,
            can_approve: false,
        }
    );
}

/// FORM-036 — a panicking `PartialEq` leaves the form unchanged, against the live model or the snapshot
#[test]
fn a_panicking_equality_leaves_the_form_unchanged() {
    let model = hooked(|left, right| {
        if left == MARKED || right == MARKED {
            plant("equality with the live model");
        }
        if matches!((left, right), (3, 1) | (1, 3)) {
            plant("equality with the snapshot");
        }
    });
    let form = builder(model(1))
        .strict(true)
        .validator("value", |model: &Hooked| {
            (model.value % 2 == 0).then(|| "even".to_string())
        })
        .build()
        .unwrap();
    let value = |model: &Hooked| model.value;
    let trace = Trace::observe(&form);
    form.set_model(model(2));
    assert_eq!(trace.take(), ["errors", "model 2"]);
    let before = state_with(&form, value);

    // The candidate is compared with the live model first.
    assert_unwinds_from("equality with the live model", || {
        form.set_model(model(MARKED))
    });
    assert_eq!(state_with(&form, value), before);
    trace.assert_quiet();

    // The validators accept 3 and would clear the error; then the strict
    // dirty comparison with the snapshot panics.
    assert_unwinds_from("equality with the snapshot", || form.set_model(model(3)));
    assert_eq!(state_with(&form, value), before);
    trace.assert_quiet();

    form.set_model(model(5));
    assert_eq!(trace.take(), ["errors", "can_execute", "model 5"]);
    assert_eq!(
        state_with(&form, value),
        FormState {
            model: 5,
            snapshot: 1,
            errors: BTreeMap::new(),
            dirty: true,
            valid: true,
            can_approve: true,
        }
    );
}

/// FORM-036 — deny whose validator panics on the snapshot value keeps the edit and publishes nothing
#[test]
fn deny_with_a_panicking_validator_keeps_the_edit() {
    let armed = Arc::new(AtomicBool::new(false));
    let form = builder(1)
        .validator("value", {
            let armed = Arc::clone(&armed);
            move |model: &i32| {
                if *model == 1 && armed.load(Ordering::SeqCst) {
                    plant("validator");
                }
                negative(model)
            }
        })
        .build()
        .unwrap();
    let trace = Trace::observe(&form);
    form.set_model(-2);
    assert_eq!(trace.take(), ["errors", "can_execute", "model -2"]);
    let edited = state(&form);
    armed.store(true, Ordering::SeqCst);

    assert_unwinds_from("validator", || form.deny_command().execute());
    assert_eq!(state(&form), edited);
    trace.assert_quiet();
    assert_unwinds_from("validator", || form.revert());
    assert_eq!(state(&form), edited);
    trace.assert_quiet();

    armed.store(false, Ordering::SeqCst);
    form.deny_command().execute();
    assert_eq!(
        trace.take(),
        ["errors", "reverted", "model 1", "can_execute"]
    );
    assert_eq!(
        state(&form),
        FormState {
            model: 1,
            snapshot: 1,
            errors: BTreeMap::new(),
            dirty: false,
            valid: true,
            can_approve: true,
        }
    );
}

/// FORM-036 — deny whose snapshotter panics keeps the edit and publishes nothing
#[test]
fn deny_with_a_panicking_snapshotter_keeps_the_edit() {
    let armed = Arc::new(AtomicBool::new(false));
    let copies = Arc::new(AtomicUsize::new(0));
    let form = builder(1)
        .snapshotter({
            let armed = Arc::clone(&armed);
            let copies = Arc::clone(&copies);
            move |model: &i32| {
                copies.fetch_add(1, Ordering::SeqCst);
                if armed.load(Ordering::SeqCst) {
                    plant("snapshotter");
                }
                *model
            }
        })
        .validator("value", negative)
        .build()
        .unwrap();
    let trace = Trace::observe(&form);
    form.set_model(-2);
    assert_eq!(trace.take(), ["errors", "can_execute", "model -2"]);
    let edited = state(&form);
    copies.store(0, Ordering::SeqCst);
    armed.store(true, Ordering::SeqCst);

    assert_unwinds_from("snapshotter", || form.deny_command().execute());
    assert_eq!(copies.load(Ordering::SeqCst), 1);
    assert_eq!(state(&form), edited);
    trace.assert_quiet();

    armed.store(false, Ordering::SeqCst);
    form.deny_command().execute();
    assert_eq!(copies.load(Ordering::SeqCst), 2);
    assert_eq!(
        trace.take(),
        ["errors", "reverted", "model 1", "can_execute"]
    );
    assert_eq!(form.model(), 1);
    assert!(!form.is_dirty() && form.is_valid());
}

/// FORM-037 — a set_model nested in a validator wins over the assignment it interrupted
#[test]
fn a_nested_assignment_from_a_validator_wins() {
    let slot = Slot::new();
    let armed = Arc::new(AtomicBool::new(true));
    let form = builder(1)
        .validator("value", {
            let slot = slot.clone();
            let armed = Arc::clone(&armed);
            move |model: &i32| {
                if *model == 10 && armed.swap(false, Ordering::SeqCst) {
                    slot.form().set_model(20);
                }
                (*model > 15).then(|| "too large".to_string())
            }
        })
        .build()
        .unwrap();
    slot.fill(&form);
    let trace = Trace::observe(&form);

    form.set_model(10);

    // Only the nested assignment commits and publishes; the outer one,
    // whose validators finished after that commit, publishes nothing.
    assert_eq!(trace.take(), ["errors", "can_execute", "model 20"]);
    assert_eq!(
        state(&form),
        FormState {
            model: 20,
            snapshot: 1,
            errors: errors(&[("value", "too large")]),
            dirty: true,
            valid: false,
            can_approve: false,
        }
    );

    form.set_model(10);
    assert_eq!(trace.take(), ["errors", "can_execute", "model 10"]);
    assert_eq!(form.model(), 10);
    assert!(form.is_valid());
}

/// FORM-037 — a deny, approval, or reset committed from a validator also wins over the interrupted assignment
#[test]
fn a_deny_or_approval_committed_from_a_validator_wins() {
    for case in ["deny", "approve", "reset"] {
        let slot = Slot::new();
        let armed = Arc::new(AtomicBool::new(false));
        let persisted = Arc::new(Mutex::new(Vec::new()));
        let mut builder = FormVm::builder()
            .initial(1)
            .hub(MessageHub::new())
            .persister({
                let persisted = Arc::clone(&persisted);
                move |model: &i32| {
                    persisted.lock().unwrap().push(*model);
                    Ok(())
                }
            })
            .validator("value", {
                let slot = slot.clone();
                let armed = Arc::clone(&armed);
                move |model: &i32| {
                    if *model == 10 && armed.swap(false, Ordering::SeqCst) {
                        let form = slot.form();
                        if case == "deny" {
                            form.deny_command().execute();
                        } else {
                            assert_eq!(form.approve(), Ok(()));
                        }
                    }
                    None
                }
            });
        if case == "reset" {
            builder = builder.reset_on_approved(|model| Ok(model * 100));
        }
        let form = builder.build().unwrap();
        slot.fill(&form);
        let trace = Trace::observe(&form);
        form.set_model(2);
        assert_eq!(trace.take(), ["model 2"], "{case}");
        armed.store(true, Ordering::SeqCst);

        form.set_model(10);

        let (events, model, persists): (&[&str], i32, &[i32]) = match case {
            "deny" => (&["reverted", "model 1"], 1, &[]),
            // Admission and settlement each raise one change (FORM-032).
            "approve" => (&["can_execute", "can_execute"], 2, &[2]),
            _ => (&["can_execute", "can_execute"], 200, &[2]),
        };
        assert_eq!(trace.take(), events, "{case}");
        assert_eq!(form.model(), model, "{case}");
        assert_eq!(form.snapshot(), model, "{case}");
        assert!(!form.is_dirty(), "{case}");
        assert_eq!(*persisted.lock().unwrap(), persists, "{case}");

        form.set_model(10);
        assert_eq!(trace.take(), ["model 10"], "{case}");
        assert_eq!(form.model(), 10, "{case}");
    }
}

/// FORM-038 — a validator that disposes the form during set_model commits nothing and leaves it inert
#[test]
fn disposal_from_a_validator_during_set_model_commits_nothing() {
    let persisted = Arc::new(AtomicUsize::new(0));
    let form = FormVm::builder()
        .initial(1)
        .hub(MessageHub::new())
        .persister({
            let persisted = Arc::clone(&persisted);
            move |_: &i32| {
                persisted.fetch_add(1, Ordering::SeqCst);
                Ok(())
            }
        })
        .build()
        .unwrap();
    let trace = Trace::observe(&form);
    form.with_field_validator("value", {
        let form = form.clone();
        let disposed = trace.marker("disposed");
        move |model: &i32| {
            if *model == MARKED {
                form.dispose();
                disposed();
            }
            negative(model)
        }
    });
    form.set_model(2);
    assert_eq!(trace.take(), ["model 2"]);

    form.set_model(MARKED);

    let events = trace.take();
    assert_eq!(events.last().map(String::as_str), Some("disposed"));
    assert!(
        !events
            .iter()
            .any(|event| event.starts_with("model") || event == "errors"),
        "the abandoned assignment published nothing: {events:?}"
    );
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 1);
    assert!(form.error_map().is_empty());

    // The disposed form is inert (FORM-014).
    form.set_model(-3);
    assert_eq!(form.approve(), Ok(()));
    form.approve_command().execute();
    form.deny_command().execute();
    assert_eq!(persisted.load(Ordering::SeqCst), 0);
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 1);
    assert!(form.error_map().is_empty());
    assert!(!form.can_approve());
    trace.assert_quiet();
}

/// FORM-038 — a validator that disposes the form while deny prepares leaves the model unreverted
#[test]
fn disposal_from_a_validator_during_deny_commits_nothing() {
    let form = builder(1).build().unwrap();
    let trace = Trace::observe(&form);
    let armed = Arc::new(AtomicBool::new(false));
    form.with_field_validator("value", {
        let form = form.clone();
        let armed = Arc::clone(&armed);
        let disposed = trace.marker("disposed");
        move |model: &i32| {
            if *model == 1 && armed.load(Ordering::SeqCst) {
                form.dispose();
                disposed();
            }
            negative(model)
        }
    });
    form.set_model(-2);
    assert_eq!(trace.take(), ["errors", "can_execute", "model -2"]);
    armed.store(true, Ordering::SeqCst);

    form.deny_command().execute();

    let events = trace.take();
    assert_eq!(events.last().map(String::as_str), Some("disposed"));
    assert!(
        !events.iter().any(|event| {
            event.starts_with("model") || event == "errors" || event == "reverted"
        }),
        "the abandoned revert published nothing: {events:?}"
    );
    assert_eq!(form.model(), -2);
    assert_eq!(form.snapshot(), 1);
    assert_eq!(form.error_map(), errors(&[("value", "negative")]));

    // The disposed form is inert (FORM-014).
    form.deny_command().execute();
    form.revert();
    form.set_model(5);
    assert_eq!(form.model(), -2);
    assert!(!form.can_approve());
    trace.assert_quiet();
}

// spec/20 §5.4: construction runs the same preparation, so a panicking
// validator fails construction and produces no form.
#[test]
fn a_panicking_validator_fails_construction() {
    assert_unwinds_from("field validator", || {
        let _ = builder(MARKED)
            .validator("value", |model: &i32| {
                if *model == MARKED {
                    plant("field validator");
                }
                None
            })
            .build();
    });
    assert_unwinds_from("model validator", || {
        let _ = builder(MARKED)
            .model_validator(|model: &i32| {
                if *model == MARKED {
                    plant("model validator");
                }
                BTreeMap::new()
            })
            .build();
    });
}

// spec/20 §5.4: preparation changes nothing, so a callback that reads the
// form sees the state from before the update, and it can read the form from
// the preparing thread without a deadlock. Run on a worker so a regression
// fails instead of hanging.
#[test]
fn callbacks_read_the_unchanged_form_during_preparation() {
    let slot = Slot::new();
    let seen = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(false));
    let read_form = {
        let slot = slot.clone();
        let seen = Arc::clone(&seen);
        let armed = Arc::clone(&armed);
        move |site: &str| {
            if !armed.load(Ordering::SeqCst) {
                return;
            }
            let form: FormVm<Hooked> = slot.form();
            seen.lock().unwrap().push(format!(
                "{site}: model {:?} snapshot {:?} errors {:?} dirty {} can_approve {}",
                form.model(),
                form.snapshot(),
                form.error_map(),
                form.is_dirty(),
                form.can_approve(),
            ));
        }
    };
    let model = hooked({
        let read_form = read_form.clone();
        move |left, right| {
            // Only the comparison of the live model 1 with the candidate 2.
            if (left, right) == (1, 2) {
                read_form("equality");
            }
        }
    });
    let form = builder(model(1))
        .strict(true)
        .validator("value", move |candidate: &Hooked| {
            read_form(&format!("validator of {candidate:?}"));
            (candidate.value < 0).then(|| "negative".to_string())
        })
        .build()
        .unwrap();
    slot.fill(&form);
    armed.store(true, Ordering::SeqCst);

    let updated = on_worker({
        let form = form.clone();
        let next = model(2);
        move || {
            form.set_model(next);
            form.revert();
        }
    });
    finished(&updated);

    assert_eq!(
        *seen.lock().unwrap(),
        [
            "equality: model 1 snapshot 1 errors {} dirty false can_approve false",
            "validator of 2: model 1 snapshot 1 errors {} dirty false can_approve false",
            "validator of 1: model 2 snapshot 1 errors {} dirty true can_approve true",
        ]
    );
    assert_eq!(form.model().value, 1);
    assert!(!form.is_dirty());
}

/// A form whose persister and whose validator of 3 can each be held at a gate.
struct HeldForm {
    form: FormVm<i32>,
    persist: Gate,
    hold_persist: Arc<AtomicBool>,
    validate: Gate,
    hold_validate: Arc<AtomicBool>,
    snapshotted: Mutex<Receiver<i32>>,
    approved: Arc<Mutex<Vec<i32>>>,
    _approved: vmx::ApprovalSubscription,
}

impl HeldForm {
    fn new() -> Self {
        let persist = Gate::new();
        let hold_persist = Arc::new(AtomicBool::new(false));
        let validate = Gate::new();
        let hold_validate = Arc::new(AtomicBool::new(false));
        let (snapshot_tx, snapshotted) = mpsc::channel();
        let snapshot_tx = Mutex::new(snapshot_tx);
        let form = FormVm::builder()
            .initial(1)
            .hub(MessageHub::new())
            .persister({
                let persist = persist.clone();
                let hold_persist = Arc::clone(&hold_persist);
                move |_: &i32| {
                    if hold_persist.swap(false, Ordering::SeqCst) {
                        persist.pass();
                    }
                    Ok(())
                }
            })
            .snapshotter(move |model: &i32| {
                let _ = snapshot_tx.lock().unwrap().send(*model);
                *model
            })
            .validator("value", {
                let validate = validate.clone();
                let hold_validate = Arc::clone(&hold_validate);
                move |model: &i32| {
                    if *model == 3 && hold_validate.swap(false, Ordering::SeqCst) {
                        validate.pass();
                    }
                    negative(model)
                }
            })
            .build()
            .unwrap();
        let approved = Arc::new(Mutex::new(Vec::new()));
        let subscription = form.subscribe_approved({
            let approved = Arc::clone(&approved);
            move |model| approved.lock().unwrap().push(model)
        });
        let held = Self {
            form,
            persist,
            hold_persist,
            validate,
            hold_validate,
            snapshotted: Mutex::new(snapshotted),
            approved,
            _approved: subscription,
        };
        held.form.set_model(2);
        while held.snapshotted.lock().unwrap().try_recv().is_ok() {}
        held
    }

    /// Starts `set_model(3)` on a worker and returns once its validator is
    /// held, with the update lock taken.
    fn edit_held_in_validator(&self) -> Receiver<()> {
        self.hold_validate.store(true, Ordering::SeqCst);
        let edit = on_worker({
            let form = self.form.clone();
            move || form.set_model(3)
        });
        self.validate.arrived();
        edit
    }

    fn snapshotted(&self) -> i32 {
        self.snapshotted
            .lock()
            .unwrap()
            .recv_timeout(TIMEOUT)
            .expect("the approval snapshotted its captured model")
    }
}

// spec/20 §5.4: updates are serialized. An approval commit waits for an edit
// another thread is preparing, and both complete: the edit is installed, not
// dropped as stale, and the snapshot advances to the captured model. The
// persister runs with edits unblocked (§5.3).
#[test]
fn an_approval_commit_waits_for_an_edit_preparing_on_another_thread() {
    let held = HeldForm::new();
    let trace = Trace::observe(&held.form);

    held.hold_persist.store(true, Ordering::SeqCst);
    let approval = on_worker({
        let form = held.form.clone();
        move || form.approve()
    });
    held.persist.arrived();
    // The edit takes the update lock while the approval persists.
    let edit = held.edit_held_in_validator();
    held.persist.release();
    assert_eq!(held.snapshotted(), 2);

    // The approval has prepared its snapshot and waits to commit it.
    assert_blocked(&approval);
    assert_eq!(held.form.snapshot(), 1);
    assert_eq!(held.form.model(), 2);

    held.validate.release();
    finished(&edit);
    assert_eq!(finished(&approval), Ok(()));

    assert_eq!(held.form.model(), 3);
    assert_eq!(held.form.snapshot(), 2);
    assert!(held.form.is_dirty());
    assert_eq!(*held.approved.lock().unwrap(), [2]);
    let mut events = trace.take();
    events.sort();
    assert_eq!(events, ["can_execute", "can_execute", "model 3"]);
}

// spec/20 §5.4: another thread's set_model waits for an edit in preparation,
// and each edit commits and publishes in turn.
#[test]
fn an_edit_on_another_thread_waits_for_an_edit_in_preparation() {
    let held = HeldForm::new();
    let trace = Trace::observe(&held.form);
    let first = held.edit_held_in_validator();

    let second = on_worker({
        let form = held.form.clone();
        move || form.set_model(-4)
    });
    assert_blocked(&second);
    assert_eq!(held.form.model(), 2);

    held.validate.release();
    finished(&first);
    finished(&second);

    assert_eq!(held.form.model(), -4);
    assert_eq!(held.form.error_map(), errors(&[("value", "negative")]));
    let events = trace.take();
    assert_eq!(
        events
            .iter()
            .filter(|event| event.starts_with("model"))
            .count(),
        2,
        "each edit published its model message: {events:?}"
    );
}

// spec/20 §5.4 and chapter 02 §7: disposal on another thread waits for an
// edit in preparation, which completes normally.
#[test]
fn disposal_on_another_thread_waits_for_an_edit_in_preparation() {
    let held = HeldForm::new();
    let edit = held.edit_held_in_validator();

    let disposal = on_worker({
        let form = held.form.clone();
        move || form.dispose()
    });
    assert_blocked(&disposal);
    assert!(held.form.can_approve());

    held.validate.release();
    finished(&edit);
    finished(&disposal);

    assert_eq!(held.form.model(), 3);
    assert!(!held.form.can_approve());
    held.form.set_model(4);
    assert_eq!(held.form.model(), 3);
}
