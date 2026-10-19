//! `FormVm` admits one approval at a time (spec/20 §5.3, ADR-0143, #327).
//!
//! A gated persister holds an admitted approval in flight on a worker thread
//! while the test approves again from the persister, a command observer, or
//! another thread. Every wait is bounded, so a regression fails instead of
//! hanging.

use std::collections::VecDeque;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use vmx::{
    ApprovalSubscription, Command, FormVm, FormVmBuilder, Message, MessageHub, Subscription,
    VmxError, VmxResult,
};

const TIMEOUT: Duration = Duration::from_secs(5);

type Reentry = Box<dyn FnOnce() + Send>;
type GateSide = (Sender<i32>, Receiver<VmxResult<()>>);

/// A persister that records every model it receives.
///
/// An armed gate makes the next call report its model and wait until the test
/// releases it with an outcome. A queued reentry runs inside the next call,
/// before it waits. An unarmed call returns the next queued outcome, or
/// `Ok(())`.
#[derive(Clone, Default)]
struct GatedPersister {
    calls: Arc<Mutex<Vec<i32>>>,
    gate: Arc<Mutex<Option<GateSide>>>,
    reentry: Arc<Mutex<Option<Reentry>>>,
    outcomes: Arc<Mutex<VecDeque<VmxResult<()>>>>,
}

impl GatedPersister {
    fn persist(&self, model: &i32) -> VmxResult<()> {
        self.calls.lock().unwrap().push(*model);
        let gate = self.gate.lock().unwrap().take();
        let reentry = self.reentry.lock().unwrap().take();
        if let Some(reentry) = reentry {
            reentry();
        }
        match gate {
            Some((entered, release)) => {
                let _ = entered.send(*model);
                release
                    .recv_timeout(TIMEOUT)
                    .unwrap_or_else(|_| Err(failure("the persister gate timed out")))
            }
            None => self.outcomes.lock().unwrap().pop_front().unwrap_or(Ok(())),
        }
    }

    fn builder(&self) -> FormVmBuilder<i32> {
        let persister = self.clone();
        FormVm::builder()
            .persister(move |model: &i32| persister.persist(model))
            .hub(MessageHub::new())
    }

    fn form(&self, initial: i32) -> FormVm<i32> {
        self.builder().initial(initial).build().unwrap()
    }

    fn arm(&self) -> Gate {
        let (entered_tx, entered) = mpsc::channel();
        let (release, release_rx) = mpsc::channel();
        *self.gate.lock().unwrap() = Some((entered_tx, release_rx));
        Gate { entered, release }
    }

    fn reenter(&self, reentry: impl FnOnce() + Send + 'static) {
        *self.reentry.lock().unwrap() = Some(Box::new(reentry));
    }

    fn fail_next(&self, message: &str) {
        self.outcomes
            .lock()
            .unwrap()
            .push_back(Err(failure(message)));
    }

    fn calls(&self) -> Vec<i32> {
        self.calls.lock().unwrap().clone()
    }
}

struct Gate {
    entered: Receiver<i32>,
    release: Sender<VmxResult<()>>,
}

impl Gate {
    fn entered(&self) -> i32 {
        self.entered
            .recv_timeout(TIMEOUT)
            .expect("the admitted approval reached the persister")
    }

    fn release(&self, outcome: VmxResult<()>) {
        self.release
            .send(outcome)
            .expect("the persister waits for its outcome");
    }
}

fn failure(message: &str) -> VmxError {
    VmxError::Other(message.to_string())
}

fn approve_on_worker(form: &FormVm<i32>) -> Receiver<VmxResult<()>> {
    let form = form.clone();
    let (done, result) = mpsc::channel();
    thread::spawn(move || {
        let _ = done.send(form.approve());
    });
    result
}

fn execute_on_worker(form: &FormVm<i32>) -> Receiver<VmxResult<()>> {
    let form = form.clone();
    let (done, result) = mpsc::channel();
    thread::spawn(move || {
        form.approve_command().execute();
        let _ = done.send(Ok(()));
    });
    result
}

fn settled(result: &Receiver<VmxResult<()>>) -> VmxResult<()> {
    result
        .recv_timeout(TIMEOUT)
        .expect("the approval settled in time")
}

fn counter(hub: &MessageHub) -> (Arc<AtomicUsize>, Subscription) {
    let count = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&count);
    let subscription = hub.subscribe(move |_| {
        observed.fetch_add(1, Ordering::SeqCst);
    });
    (count, subscription)
}

fn approvals(form: &FormVm<i32>) -> (Arc<Mutex<Vec<i32>>>, ApprovalSubscription) {
    let approved = Arc::new(Mutex::new(Vec::new()));
    let observed = Arc::clone(&approved);
    let subscription = form.subscribe_approved(move |model| observed.lock().unwrap().push(model));
    (approved, subscription)
}

fn error_names(messages: &[Message]) -> Vec<String> {
    messages
        .iter()
        .map(|message| match message {
            Message::Custom { name, .. } => name.clone(),
            other => panic!("unexpected approve error message {other:?}"),
        })
        .collect()
}

/// FORM-031 — a second approval during an in-flight approval is refused
#[test]
fn a_second_approval_during_an_in_flight_approval_is_refused() {
    let persister = GatedPersister::default();
    let form = persister.form(1);
    let (approved, _approved) = approvals(&form);
    let approve_errors = form.approve_errors().record(64);
    let errors_changed = form.errors_changed().record(64);
    let hub = form.hub().record(64);
    let refused = Arc::new(Mutex::new(Vec::new()));
    // The admission notification reaches this handler first; it approves once.
    let handler_armed = Arc::new(AtomicBool::new(true));
    let _handler = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        let refused = Arc::clone(&refused);
        let handler_armed = Arc::clone(&handler_armed);
        move |_| {
            if handler_armed.swap(false, Ordering::SeqCst) {
                refused.lock().unwrap().push(("handler", form.approve()));
            }
        }
    });
    persister.reenter({
        let form = form.clone();
        let refused = Arc::clone(&refused);
        move || {
            refused.lock().unwrap().push(("persister", form.approve()));
            form.approve_command().execute();
        }
    });
    form.set_model(2);
    let hub_messages = hub.len();
    let gate = persister.arm();

    let first = approve_on_worker(&form);
    assert_eq!(gate.entered(), 2);
    // Another thread approves through both entry points.
    assert_eq!(form.approve(), Ok(()));
    form.approve_command().execute();

    assert_eq!(persister.calls(), vec![2]);
    assert_eq!(
        *refused.lock().unwrap(),
        vec![("handler", Ok(())), ("persister", Ok(()))]
    );
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 1);
    assert!(form.is_dirty());
    assert!(form.error_map().is_empty());
    assert!(approved.lock().unwrap().is_empty());
    assert!(approve_errors.is_empty());
    assert!(errors_changed.is_empty());
    assert_eq!(hub.len(), hub_messages);

    gate.release(Ok(()));
    assert_eq!(settled(&first), Ok(()));
    assert_eq!(form.snapshot(), 2);
    assert!(!form.is_dirty());
    assert_eq!(*approved.lock().unwrap(), vec![2]);

    form.set_model(3);
    assert_eq!(form.approve(), Ok(()));
    assert_eq!(persister.calls(), vec![2, 3]);
    assert_eq!(form.snapshot(), 3);
    assert_eq!(*approved.lock().unwrap(), vec![2, 3]);
    assert!(approve_errors.is_empty());
}

/// FORM-031 — an admission observer that disposes the form prevents the persister call
#[test]
fn an_admission_observer_that_disposes_the_form_prevents_the_persister_call() {
    let persister = GatedPersister::default();
    let form = persister.form(1);
    let (approved, _approved) = approvals(&form);
    let approve_errors = form.approve_errors().record(64);
    let _handler = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        move |_| form.dispose()
    });
    form.set_model(2);

    assert_eq!(form.approve(), Ok(()));

    assert!(persister.calls().is_empty());
    assert!(approved.lock().unwrap().is_empty());
    assert!(approve_errors.is_empty());
    assert_eq!(form.snapshot(), 1);
}

/// FORM-031 — an approval admitted through the command refuses the other entry point
#[test]
fn an_approval_admitted_through_the_command_refuses_every_other_approval() {
    let persister = GatedPersister::default();
    let form = persister.form(1);
    let (approved, _approved) = approvals(&form);
    let approve_errors = form.approve_errors().record(64);
    let reentrant = Arc::new(Mutex::new(Vec::new()));
    persister.reenter({
        let form = form.clone();
        let reentrant = Arc::clone(&reentrant);
        move || {
            reentrant.lock().unwrap().push(form.approve());
            form.approve_command().execute();
        }
    });
    form.set_model(2);
    let gate = persister.arm();

    let first = execute_on_worker(&form);
    assert_eq!(gate.entered(), 2);
    assert!(!form.approve_command().can_execute());
    assert_eq!(form.approve(), Ok(()));
    form.approve_command().execute();
    assert_eq!(persister.calls(), vec![2]);
    assert_eq!(*reentrant.lock().unwrap(), vec![Ok(())]);

    gate.release(Err(failure("persist failed")));
    settled(&first).unwrap();

    // The one failure is routed once, to the command's error channel.
    assert_eq!(
        error_names(&approve_errors.messages()),
        vec!["persist failed"]
    );
    assert_eq!(persister.calls(), vec![2]);
    assert!(approved.lock().unwrap().is_empty());
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 1);
    assert!(form.approve_command().can_execute());
}

/// FORM-032 — the approve command is disabled while an approval is in flight
#[test]
fn the_approve_command_is_disabled_while_an_approval_is_in_flight() {
    let persister = GatedPersister::default();
    let form = persister.builder().initial(1).strict(true).build().unwrap();
    let command = form.approve_command();
    let (changes, _changes) = counter(&command.can_execute_changed());
    let approve_errors = form.approve_errors().record(64);
    let at_persist = Arc::new(Mutex::new(Vec::new()));
    let record_at_persist = || {
        let changes = Arc::clone(&changes);
        let at_persist = Arc::clone(&at_persist);
        move || {
            at_persist
                .lock()
                .unwrap()
                .push(changes.load(Ordering::SeqCst))
        }
    };
    form.set_model(2);
    assert!(command.can_execute());

    // Success: the strict form becomes clean.
    let before = changes.load(Ordering::SeqCst);
    let gate = persister.arm();
    persister.reenter(record_at_persist());
    let approval = approve_on_worker(&form);
    gate.entered();
    assert_eq!(*at_persist.lock().unwrap(), vec![before + 1]);
    assert!(!command.can_execute());
    assert!(!form.can_approve());
    gate.release(Ok(()));
    assert_eq!(settled(&approval), Ok(()));
    // One settlement change also announces the strict transition.
    assert_eq!(changes.load(Ordering::SeqCst), before + 2);
    assert!(!command.can_execute());
    assert!(form.is_valid() && !form.is_dirty());

    // Failure through the command path: valid and dirty again afterwards.
    form.set_model(3);
    assert!(command.can_execute());
    let before = changes.load(Ordering::SeqCst);
    let gate = persister.arm();
    persister.reenter(record_at_persist());
    let approval = execute_on_worker(&form);
    gate.entered();
    assert_eq!(at_persist.lock().unwrap()[1], before + 1);
    assert!(!command.can_execute());
    gate.release(Err(failure("persist failed")));
    settled(&approval).unwrap();
    assert_eq!(changes.load(Ordering::SeqCst), before + 2);
    assert!(command.can_execute());
    assert_eq!(
        error_names(&approve_errors.messages()),
        vec!["persist failed"]
    );
}

/// FORM-032 — a failed or invalidating reset settles with exactly one change
#[test]
fn reset_outcomes_settle_with_exactly_one_command_change() {
    // The reset fails after a successful persist.
    let persister = GatedPersister::default();
    let form = persister
        .builder()
        .initial(1)
        .reset_on_approved(|_| Err(failure("reset failed")))
        .build()
        .unwrap();
    let command = form.approve_command();
    let (changes, _changes) = counter(&command.can_execute_changed());
    form.set_model(2);
    let before = changes.load(Ordering::SeqCst);
    let gate = persister.arm();
    let approval = approve_on_worker(&form);
    gate.entered();
    assert_eq!(changes.load(Ordering::SeqCst), before + 1);
    assert!(!command.can_execute());
    gate.release(Ok(()));
    assert_eq!(settled(&approval), Err(failure("reset failed")));
    assert_eq!(changes.load(Ordering::SeqCst), before + 2);
    assert!(command.can_execute());
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 1);

    // The reset succeeds with an invalid model: only the validity gate holds.
    let persister = GatedPersister::default();
    let form = persister
        .builder()
        .initial(1)
        .validator("value", |model| {
            (*model == 0).then(|| "required".to_string())
        })
        .reset_on_approved(|_| Ok(0))
        .build()
        .unwrap();
    let command = form.approve_command();
    let (changes, _changes) = counter(&command.can_execute_changed());
    let (errors_changed, _errors_changed) = counter(&form.errors_changed());
    form.set_model(2);
    let before = changes.load(Ordering::SeqCst);
    let gate = persister.arm();
    let approval = approve_on_worker(&form);
    gate.entered();
    assert_eq!(changes.load(Ordering::SeqCst), before + 1);
    gate.release(Ok(()));
    assert_eq!(settled(&approval), Ok(()));
    assert_eq!(changes.load(Ordering::SeqCst), before + 2);
    assert_eq!(errors_changed.load(Ordering::SeqCst), 1);
    assert!(!form.is_valid());
    assert!(!command.can_execute());
}

// Rust-specific exit path (ADR-0143): a panicking persister or reset settles
// like a failure, clearing the in-flight mark and raising one change, and then
// resumes on the caller, direct or command.
#[test]
fn a_panicking_persister_or_reset_settles_before_the_panic_resumes() {
    for (reset_panics, through_command) in [(false, false), (true, true)] {
        let armed = Arc::new(AtomicBool::new(true));
        let calls = Arc::new(AtomicUsize::new(0));
        let mut builder = FormVm::builder().initial(1).persister({
            let armed = Arc::clone(&armed);
            let calls = Arc::clone(&calls);
            move |_: &i32| {
                calls.fetch_add(1, Ordering::SeqCst);
                if !reset_panics && armed.swap(false, Ordering::SeqCst) {
                    panic!("persister panicked");
                }
                Ok(())
            }
        });
        if reset_panics {
            let armed = Arc::clone(&armed);
            builder = builder.reset_on_approved(move |model| {
                if armed.swap(false, Ordering::SeqCst) {
                    panic!("reset panicked");
                }
                Ok(*model)
            });
        }
        let form = builder.build().unwrap();
        let command = form.approve_command();
        let (changes, _changes) = counter(&command.can_execute_changed());
        let approve_errors = form.approve_errors().record(64);
        form.set_model(2);
        let before = changes.load(Ordering::SeqCst);

        let panicked = catch_unwind(AssertUnwindSafe(|| {
            if through_command {
                command.execute();
            } else {
                let _ = form.approve();
            }
        }));

        assert!(panicked.is_err(), "the panic resumes on the caller");
        assert_eq!(changes.load(Ordering::SeqCst), before + 2);
        assert!(command.can_execute());
        assert!(approve_errors.is_empty());
        assert_eq!(form.snapshot(), 1);
        assert_eq!(form.model(), 2);
        assert_eq!(form.approve(), Ok(()));
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        assert_eq!(form.snapshot(), 2);
    }
}

/// FORM-033 — an approval subscriber may approve again after settlement
#[test]
fn an_approval_subscriber_is_admitted_and_captures_the_settled_model() {
    let persister = GatedPersister::default();
    let form = persister
        .builder()
        .initial(1)
        .reset_on_approved(|model| Ok(model + 100))
        .build()
        .unwrap();
    let observed = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(true));
    let _subscriber = form.subscribe_approved({
        let form = form.clone();
        let observed = Arc::clone(&observed);
        let armed = Arc::clone(&armed);
        move |approved| {
            if armed.swap(false, Ordering::SeqCst) {
                let can_execute = form.approve_command().can_execute();
                let model = form.model();
                let retried = form.approve();
                observed
                    .lock()
                    .unwrap()
                    .push((approved, can_execute, model, retried));
            }
        }
    });
    form.set_model(2);

    assert_eq!(form.approve(), Ok(()));

    assert_eq!(*observed.lock().unwrap(), vec![(2, true, 102, Ok(()))]);
    assert_eq!(persister.calls(), vec![2, 102]);
    assert_eq!(form.model(), 202);
    assert_eq!(form.snapshot(), 202);
}

/// FORM-033 — an approve-errors subscriber may approve after a failed command approval
#[test]
fn an_approve_errors_subscriber_is_admitted_after_a_failed_command_approval() {
    let persister = GatedPersister::default();
    let form = persister.form(1);
    let (approved, _approved) = approvals(&form);
    let observed = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(true));
    let _subscriber = form.approve_errors().subscribe({
        let form = form.clone();
        let observed = Arc::clone(&observed);
        let armed = Arc::clone(&armed);
        move |message| {
            let state = (
                error_names(std::slice::from_ref(message)),
                form.model(),
                form.snapshot(),
                form.error_map().is_empty(),
                form.approve_command().can_execute(),
            );
            let retried = armed.swap(false, Ordering::SeqCst).then(|| form.approve());
            observed.lock().unwrap().push((state, retried));
        }
    });
    persister.fail_next("persist failed");
    form.set_model(2);

    form.approve_command().execute();

    assert_eq!(
        *observed.lock().unwrap(),
        vec![(
            (vec!["persist failed".to_string()], 2, 1, true, true),
            Some(Ok(()))
        )]
    );
    assert_eq!(persister.calls(), vec![2, 2]);
    assert_eq!(form.snapshot(), 2);
    assert_eq!(*approved.lock().unwrap(), vec![2]);
}

/// FORM-033 — an approval subscriber may approve through the command it settled
#[test]
fn an_approval_subscriber_executing_the_approve_command_is_admitted() {
    let persister = GatedPersister::default();
    let form = persister
        .builder()
        .initial(1)
        .reset_on_approved(|model| Ok(model + 100))
        .build()
        .unwrap();
    let observed = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(true));
    let _subscriber = form.subscribe_approved({
        let form = form.clone();
        let persister = persister.clone();
        let observed = Arc::clone(&observed);
        let armed = Arc::clone(&armed);
        move |approved| {
            if armed.swap(false, Ordering::SeqCst) {
                let can_execute = form.approve_command().can_execute();
                let model = form.model();
                // Re-enters the command whose approval is settling.
                form.approve_command().execute();
                observed
                    .lock()
                    .unwrap()
                    .push((approved, can_execute, model, persister.calls()));
            }
        }
    });
    let (approved, _approved) = approvals(&form);
    let approve_errors = form.approve_errors().record(64);
    form.set_model(2);

    settled(&execute_on_worker(&form)).unwrap();

    // The nested approval was admitted, captured the settled model, and
    // finished before its `execute` returned.
    assert_eq!(
        *observed.lock().unwrap(),
        vec![(2, true, 102, vec![2, 102])]
    );
    assert_eq!(persister.calls(), vec![2, 102]);
    assert_eq!(form.model(), 202);
    assert_eq!(form.snapshot(), 202);
    assert_eq!(*approved.lock().unwrap(), vec![102, 2]);
    assert!(approve_errors.is_empty());
    assert!(form.approve_command().can_execute());
}

/// FORM-033 — an approve-errors subscriber may approve through the command that failed
#[test]
fn an_approve_errors_subscriber_executing_the_approve_command_is_admitted() {
    let persister = GatedPersister::default();
    let form = persister.form(1);
    let (approved, _approved) = approvals(&form);
    let observed = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(true));
    let _subscriber = form.approve_errors().subscribe({
        let form = form.clone();
        let persister = persister.clone();
        let observed = Arc::clone(&observed);
        let armed = Arc::clone(&armed);
        move |message| {
            if armed.swap(false, Ordering::SeqCst) {
                let can_execute = form.approve_command().can_execute();
                // Re-enters the command whose approval failed.
                form.approve_command().execute();
                observed.lock().unwrap().push((
                    error_names(std::slice::from_ref(message)),
                    can_execute,
                    persister.calls(),
                    form.snapshot(),
                ));
            }
        }
    });
    persister.fail_next("persist failed");
    form.set_model(2);

    settled(&execute_on_worker(&form)).unwrap();

    assert_eq!(
        *observed.lock().unwrap(),
        vec![(vec!["persist failed".to_string()], true, vec![2, 2], 2)]
    );
    assert_eq!(persister.calls(), vec![2, 2]);
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 2);
    assert_eq!(*approved.lock().unwrap(), vec![2]);
    assert!(form.approve_command().can_execute());
}

/// FORM-033 — a settlement eligibility handler may approve through the settling command
#[test]
fn a_settlement_can_execute_changed_handler_executing_the_approve_command_is_admitted() {
    let persister = GatedPersister::default();
    let form = persister
        .builder()
        .initial(1)
        .reset_on_approved(|model| Ok(model + 100))
        .build()
        .unwrap();
    let (approved, _approved) = approvals(&form);
    let observed = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(false));
    let _handler = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        let persister = persister.clone();
        let observed = Arc::clone(&observed);
        let armed = Arc::clone(&armed);
        move |_| {
            if armed.swap(false, Ordering::SeqCst) {
                let can_execute = form.approve_command().can_execute();
                let model = form.model();
                form.approve_command().execute();
                observed
                    .lock()
                    .unwrap()
                    .push((can_execute, model, persister.calls()));
            }
        }
    });
    // Armed during the persist, so the settlement notification fires it.
    persister.reenter({
        let armed = Arc::clone(&armed);
        move || armed.store(true, Ordering::SeqCst)
    });
    form.set_model(2);

    settled(&execute_on_worker(&form)).unwrap();

    assert_eq!(*observed.lock().unwrap(), vec![(true, 102, vec![2, 102])]);
    assert_eq!(persister.calls(), vec![2, 102]);
    assert_eq!(form.model(), 202);
    assert_eq!(form.snapshot(), 202);
    assert_eq!(*approved.lock().unwrap(), vec![102, 2]);
    assert!(form.approve_command().can_execute());
}

/// FORM-033 — the awaiter of a failed approval may approve again
#[test]
fn the_awaiter_of_a_failed_approval_is_admitted_when_it_approves_again() {
    let persister = GatedPersister::default();
    let form = persister.form(1);
    let (approved, _approved) = approvals(&form);
    let approve_errors = form.approve_errors().record(64);
    persister.fail_next("persist failed");
    form.set_model(2);

    assert_eq!(form.approve(), Err(failure("persist failed")));
    assert!(form.approve_command().can_execute());
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 1);
    assert!(form.error_map().is_empty());
    assert_eq!(form.approve(), Ok(()));

    assert_eq!(persister.calls(), vec![2, 2]);
    assert_eq!(form.snapshot(), 2);
    assert_eq!(*approved.lock().unwrap(), vec![2]);
    assert!(approve_errors.is_empty());
}

/// FORM-033 — settlement observers see an idle form and the approval they start is admitted
#[test]
fn settlement_observers_see_an_idle_form_and_may_approve() {
    let persister = GatedPersister::default();
    let form = persister
        .builder()
        .initial(1)
        .validator("value", |model| {
            (*model == 0).then(|| "required".to_string())
        })
        .reset_on_approved(|model| Ok(model + 100))
        .build()
        .unwrap();
    let seen = Arc::new(Mutex::new(Vec::new()));
    let errors_armed = Arc::new(AtomicBool::new(false));
    let _errors_observer = form.errors_changed().subscribe({
        let form = form.clone();
        let seen = Arc::clone(&seen);
        let errors_armed = Arc::clone(&errors_armed);
        move |_| {
            if errors_armed.swap(false, Ordering::SeqCst) {
                seen.lock().unwrap().push(format!(
                    "errors:{}:{}",
                    form.model(),
                    form.can_approve()
                ));
                // Applied only after the approval subscribers see the commit.
                form.set_model(7);
            }
        }
    });
    let command_armed = Arc::new(AtomicBool::new(false));
    let _command_observer = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        let seen = Arc::clone(&seen);
        let command_armed = Arc::clone(&command_armed);
        move |_| {
            if command_armed.swap(false, Ordering::SeqCst) {
                let can_execute = form.approve_command().can_execute();
                let retried = form.approve();
                seen.lock()
                    .unwrap()
                    .push(format!("command:{can_execute}:{retried:?}"));
            }
        }
    });
    let _approved = form.subscribe_approved({
        let form = form.clone();
        let seen = Arc::clone(&seen);
        move |approved| {
            seen.lock().unwrap().push(format!(
                "approved:{approved}:{}:{}:{}",
                form.model(),
                form.snapshot(),
                form.is_dirty()
            ));
        }
    });
    form.set_model(2);
    let gate = persister.arm();
    let approval = approve_on_worker(&form);
    assert_eq!(gate.entered(), 2);
    // A racing edit invalidates the live model; the reset will clear it.
    form.set_model(0);
    errors_armed.store(true, Ordering::SeqCst);
    command_armed.store(true, Ordering::SeqCst);

    gate.release(Ok(()));
    assert_eq!(settled(&approval), Ok(()));

    assert_eq!(
        *seen.lock().unwrap(),
        vec![
            "errors:102:true",
            "approved:102:202:202:false",
            "command:true:Ok(())",
            "approved:2:202:202:false",
        ]
    );
    assert_eq!(persister.calls(), vec![2, 102]);
    assert_eq!(form.model(), 7);
    assert_eq!(form.snapshot(), 202);
    assert!(form.is_dirty());
}

/// FORM-034 — edits and deny during an in-flight approval are not blocked
#[test]
fn edits_and_deny_during_an_in_flight_approval_keep_the_captured_commit() {
    let persister = GatedPersister::default();
    let form = persister.form(1);
    let (approved, _approved) = approvals(&form);
    form.set_model(2);

    let gate = persister.arm();
    let approval = approve_on_worker(&form);
    assert_eq!(gate.entered(), 2);
    form.set_model(3);
    assert_eq!(form.model(), 3);
    gate.release(Ok(()));
    assert_eq!(settled(&approval), Ok(()));
    assert_eq!(form.snapshot(), 2);
    assert_eq!(form.model(), 3);
    assert!(form.is_dirty());
    assert_eq!(*approved.lock().unwrap(), vec![2]);

    let gate = persister.arm();
    let approval = approve_on_worker(&form);
    assert_eq!(gate.entered(), 3);
    form.deny_command().execute();
    assert_eq!(form.model(), 2);
    gate.release(Ok(()));
    assert_eq!(settled(&approval), Ok(()));
    assert_eq!(form.snapshot(), 3);
    assert_eq!(form.model(), 2);
    assert!(form.is_dirty());
    assert_eq!(*approved.lock().unwrap(), vec![2, 3]);
}

/// FORM-034 — a configured reset replaces a model edited or reverted during the approval
#[test]
fn a_configured_reset_replaces_edits_made_during_the_approval() {
    let persister = GatedPersister::default();
    let form = persister
        .builder()
        .initial(1)
        .reset_on_approved(|model| Ok(model * 10))
        .build()
        .unwrap();
    let (approved, _approved) = approvals(&form);
    form.set_model(2);

    let gate = persister.arm();
    let approval = approve_on_worker(&form);
    assert_eq!(gate.entered(), 2);
    form.set_model(5);
    gate.release(Ok(()));
    assert_eq!(settled(&approval), Ok(()));
    assert_eq!(form.model(), 20);
    assert_eq!(form.snapshot(), 20);
    assert!(!form.is_dirty());

    form.set_model(3);
    let gate = persister.arm();
    let approval = approve_on_worker(&form);
    assert_eq!(gate.entered(), 3);
    form.deny_command().execute();
    assert_eq!(form.model(), 20);
    gate.release(Ok(()));
    assert_eq!(settled(&approval), Ok(()));
    assert_eq!(form.model(), 30);
    assert_eq!(form.snapshot(), 30);
    assert!(!form.is_dirty());
    assert_eq!(*approved.lock().unwrap(), vec![2, 3]);
}

/// FORM-034 — disposal during an in-flight approval suppresses settlement
#[test]
fn disposal_during_an_in_flight_approval_suppresses_settlement() {
    let cases = [
        ("direct", Ok(())),
        ("direct", Err(failure("persist failed"))),
        ("command", Ok(())),
        ("command", Err(failure("persist failed"))),
    ];
    for (path, outcome) in cases {
        let persister = GatedPersister::default();
        let form = persister.form(1);
        let (approved, _approved) = approvals(&form);
        let (changes, _changes) = counter(&form.approve_command().can_execute_changed());
        let (approve_errors, _approve_errors) = counter(&form.approve_errors());
        let (errors_changed, _errors_changed) = counter(&form.errors_changed());
        form.set_model(2);
        let gate = persister.arm();
        let approval = if path == "direct" {
            approve_on_worker(&form)
        } else {
            execute_on_worker(&form)
        };
        assert_eq!(gate.entered(), 2);

        form.dispose();
        let after_disposal = [
            changes.load(Ordering::SeqCst),
            approve_errors.load(Ordering::SeqCst),
            errors_changed.load(Ordering::SeqCst),
        ];
        gate.release(outcome.clone());
        let result = settled(&approval);

        if path == "direct" {
            // The awaiter still observes the persister's own outcome.
            assert_eq!(result, outcome, "{path} {outcome:?}");
        }
        assert_eq!(
            [
                changes.load(Ordering::SeqCst),
                approve_errors.load(Ordering::SeqCst),
                errors_changed.load(Ordering::SeqCst),
            ],
            after_disposal,
            "{path} {outcome:?}"
        );
        assert!(approved.lock().unwrap().is_empty(), "{path} {outcome:?}");
        assert_eq!(form.model(), 2);
        assert_eq!(form.snapshot(), 1);
        assert_eq!(form.approve(), Ok(()));
        form.approve_command().execute();
        assert_eq!(persister.calls(), vec![2], "{path} {outcome:?}");
    }
}
