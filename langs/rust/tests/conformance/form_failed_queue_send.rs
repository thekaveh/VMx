//! A failed send of the outermost `FormVm` update's queue stops the later
//! sends and releases each nested approval that has not started (spec/20 §5.4
//! rule 7, ADR-0216, #1415).
//!
//! The Rust hub isolates subscriber panics, so only an internal panic fails a
//! send. These tests use the debug-build drain limit: a hub subscriber that
//! sends again on each message makes the drain panic after 10 000 deliveries.

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use vmx::{Command, FormVm, Message, MessageHub, Subscription};

type Model = &'static str;

/// Lets a callback registered at build time reach the form built from it.
#[derive(Clone, Default)]
struct Slot(Arc<OnceLock<FormVm<Model>>>);

impl Slot {
    fn form(&self) -> FormVm<Model> {
        self.0.get().expect("the form is built").clone()
    }
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

fn custom(name: &str) -> Message {
    Message::Custom {
        sender_id: 0,
        sender_name: "test".into(),
        name: name.into(),
    }
}

/// What one run observed.
struct Run {
    form: FormVm<Model>,
    persisted: Arc<AtomicUsize>,
    eligibility_changes: Arc<AtomicUsize>,
    /// The `"model"` messages the form's hub delivered.
    model_messages: Arc<Mutex<Vec<Model>>>,
    _subscriptions: Vec<Subscription>,
}

/// Builds a form whose validator, on the first `"a"`, starts a nested
/// approval through `approve`, then assigns `"b"` and `"c"`. The form's hub
/// subscriber records each `"model"` message and, on the first one, sends
/// again on each message until the drain limit panics.
fn run(approve: impl Fn(&FormVm<Model>) + Send + Sync + 'static) -> Run {
    let slot = Slot::default();
    let persisted = Arc::new(AtomicUsize::new(0));
    let nested = once({
        let slot = slot.clone();
        move || {
            let form = slot.form();
            approve(&form);
            form.set_model("b");
            form.set_model("c");
        }
    });
    let hub = MessageHub::new();
    let form = FormVm::builder()
        .initial("i")
        .hub(hub.clone())
        .persister({
            let persisted = persisted.clone();
            move |_: &Model| {
                persisted.fetch_add(1, Ordering::SeqCst);
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
    assert!(slot.0.set(form.clone()).is_ok());
    let eligibility_changes = Arc::new(AtomicUsize::new(0));
    let model_messages = Arc::new(Mutex::new(Vec::new()));
    let changes = form.approve_command().can_execute_changed().subscribe({
        let eligibility_changes = eligibility_changes.clone();
        move |_| {
            eligibility_changes.fetch_add(1, Ordering::SeqCst);
        }
    });
    let spinning = Arc::new(AtomicBool::new(false));
    let spinner = hub.subscribe({
        let (form, hub, model_messages) = (form.clone(), hub.clone(), model_messages.clone());
        move |message| {
            if let Message::PropertyChanged(change) = message {
                if change.property_name == "model" {
                    model_messages.lock().unwrap().push(form.model());
                    spinning.store(true, Ordering::SeqCst);
                }
            }
            if spinning.load(Ordering::SeqCst) {
                hub.send(custom("spin"));
            }
        }
    });
    Run {
        form,
        persisted,
        eligibility_changes,
        model_messages,
        _subscriptions: vec![changes, spinner],
    }
}

fn assert_released(run: &Run, outcome: std::thread::Result<()>) {
    assert!(outcome.is_err(), "the failed send propagates");
    // One model message went out, after both nested commits. Its send
    // failed, so the second one was never sent.
    assert_eq!(*run.model_messages.lock().unwrap(), ["c"]);
    assert_eq!(
        run.persisted.load(Ordering::SeqCst),
        0,
        "the released approval called its persister"
    );
    // The admission change and the release change.
    assert_eq!(run.eligibility_changes.load(Ordering::SeqCst), 2);
    assert!(run.form.can_approve(), "the released approval is in flight");
    assert_eq!(run.form.model(), "c");
}

/// FORM-044 — a failed send stops the later sends and releases a nested approve() without calling its persister
#[test]
fn a_failed_send_releases_a_nested_approval_without_its_persister() {
    let run = run(|form| assert_eq!(form.approve(), Ok(())));

    let outcome = catch_unwind(AssertUnwindSafe(|| run.form.set_model("a")));

    assert_released(&run, outcome);
}

/// FORM-044 — a failed send releases an approval the approve command started, and approve_errors stays silent
#[test]
fn a_failed_send_releases_a_nested_command_approval_silently() {
    let run = run(|form| form.approve_command().execute());
    let errors = Arc::new(AtomicUsize::new(0));
    let _errors = run.form.approve_errors().subscribe({
        let errors = errors.clone();
        move |_| {
            errors.fetch_add(1, Ordering::SeqCst);
        }
    });

    let outcome = catch_unwind(AssertUnwindSafe(|| run.form.set_model("a")));

    assert_released(&run, outcome);
    assert_eq!(errors.load(Ordering::SeqCst), 0);
}

/// FORM-044 — the form stays usable after a failed send
#[test]
fn the_form_approves_again_after_a_failed_send() {
    let run = run(|form| assert_eq!(form.approve(), Ok(())));
    let outcome = catch_unwind(AssertUnwindSafe(|| run.form.set_model("a")));
    assert!(outcome.is_err());

    assert_eq!(run.form.approve(), Ok(()));

    assert_eq!(run.persisted.load(Ordering::SeqCst), 1);
    assert_eq!(run.form.snapshot(), "c");
}
