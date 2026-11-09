//! Rust `FormVm` approval subscriptions detach individually and post-disposal
//! registration is inert (ADR-0139, #357).

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, Weak};

use vmx::{ApprovalSubscription, FormVm};

// The cross-thread cases observe the wait-for graph through a test seam.
#[cfg(feature = "test-seams")]
use {
    std::sync::mpsc,
    std::thread::{self, JoinHandle, ThreadId},
    std::time::{Duration, Instant},
    vmx::wait_registered_for_testing,
};

/// The hang guard of every cross-thread wait in this file.
#[cfg(feature = "test-seams")]
const BOUND: Duration = Duration::from_secs(10);

/// How long a test lets a thread run before it checks that the thread still
/// waits.
#[cfg(feature = "test-seams")]
const SETTLE: Duration = Duration::from_millis(200);

struct Capture;

/// Polls `condition` until it holds or the bound passes.
#[cfg(feature = "test-seams")]
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
#[cfg(feature = "test-seams")]
fn join_by<T>(handle: JoinHandle<T>, deadline: Instant, what: &str) -> T {
    while !handle.is_finished() {
        assert!(Instant::now() < deadline, "{what} did not return: deadlock");
        thread::sleep(Duration::from_millis(1));
    }
    handle.join().unwrap()
}

fn approved_form() -> FormVm<i32> {
    let form = FormVm::new("form", 1);
    form.set_model(2);
    form
}

fn counter() -> (Arc<AtomicUsize>, impl Fn(i32) + Send + Sync + 'static) {
    let count = Arc::new(AtomicUsize::new(0));
    let observed = count.clone();
    (count, move |_| {
        observed.fetch_add(1, Ordering::SeqCst);
    })
}

#[test]
fn subscribed_callbacks_receive_each_persisted_model_in_registration_order() {
    let form = FormVm::new("form", 1);
    let order = Arc::new(Mutex::new(Vec::new()));
    let first = {
        let order = order.clone();
        form.subscribe_approved(move |model| order.lock().unwrap().push(("first", model)))
    };
    let second = {
        let order = order.clone();
        form.subscribe_approved(move |model| order.lock().unwrap().push(("second", model)))
    };

    form.set_model(2);
    form.approve().unwrap();

    assert_eq!(*order.lock().unwrap(), vec![("first", 2), ("second", 2)]);
    assert!(first.is_active() && second.is_active());
}

#[test]
fn detaching_releases_the_callback_captures_before_disposal() {
    let form = approved_form();
    let capture = Arc::new(Capture);
    let weak: Weak<Capture> = Arc::downgrade(&capture);
    let subscription = form.subscribe_approved(move |_| {
        let _ = &capture;
    });
    assert!(weak.upgrade().is_some());

    subscription.dispose();

    assert!(weak.upgrade().is_none());
    assert!(!subscription.is_active());
    form.approve().unwrap();
}

#[test]
fn dropping_the_subscription_detaches_it() {
    let form = approved_form();
    let (count, callback) = counter();
    drop(form.subscribe_approved(callback));

    form.approve().unwrap();

    assert_eq!(count.load(Ordering::SeqCst), 0);
}

#[test]
fn a_callback_may_unsubscribe_itself_during_emission() {
    let form = FormVm::new("form", 1);
    let calls = Arc::new(AtomicUsize::new(0));
    let own = Arc::new(Mutex::new(None::<ApprovalSubscription>));
    let subscription = form.subscribe_approved({
        let calls = calls.clone();
        let own = own.clone();
        move |_| {
            calls.fetch_add(1, Ordering::SeqCst);
            drop(own.lock().unwrap().take());
        }
    });
    *own.lock().unwrap() = Some(subscription);

    form.set_model(2);
    form.approve().unwrap();
    form.set_model(3);
    form.approve().unwrap();

    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn a_callback_detached_by_an_earlier_callback_skips_the_current_emission() {
    let form = approved_form();
    let later = Arc::new(Mutex::new(None::<ApprovalSubscription>));
    let _earlier = form.subscribe_approved({
        let later = later.clone();
        move |_| {
            if let Some(subscription) = later.lock().unwrap().as_ref() {
                subscription.dispose();
            }
        }
    });
    let (count, callback) = counter();
    *later.lock().unwrap() = Some(form.subscribe_approved(callback));

    form.approve().unwrap();

    assert_eq!(count.load(Ordering::SeqCst), 0);
}

#[test]
fn a_callback_registered_during_emission_starts_with_the_next_approval() {
    let form = FormVm::new("form", 1);
    let (count, callback) = counter();
    let callback = Arc::new(Mutex::new(Some(callback)));
    let registered = Arc::new(Mutex::new(Vec::new()));
    let holder = Arc::new(Mutex::new(Some(form.clone())));
    let _registrar = form.subscribe_approved({
        let callback = callback.clone();
        let registered = registered.clone();
        let holder = holder.clone();
        move |_| {
            if let Some(callback) = callback.lock().unwrap().take() {
                let form = holder.lock().unwrap().clone().unwrap();
                registered
                    .lock()
                    .unwrap()
                    .push(form.subscribe_approved(callback));
            }
        }
    });

    form.set_model(2);
    form.approve().unwrap();
    assert_eq!(count.load(Ordering::SeqCst), 0);
    form.set_model(3);
    form.approve().unwrap();

    assert_eq!(count.load(Ordering::SeqCst), 1);
    holder.lock().unwrap().take();
}

#[test]
fn repeated_detach_is_inert() {
    let form = approved_form();
    let (count, callback) = counter();
    let subscription = form.subscribe_approved(callback);

    subscription.dispose();
    subscription.dispose();
    drop(subscription);
    form.approve().unwrap();

    assert_eq!(count.load(Ordering::SeqCst), 0);
}

#[test]
fn registration_after_disposal_is_inert_and_releases_captures() {
    let form = approved_form();
    form.dispose();
    let subscribed = Arc::new(Capture);
    let subscribed_weak = Arc::downgrade(&subscribed);
    let legacy = Arc::new(Capture);
    let legacy_weak = Arc::downgrade(&legacy);

    let subscription = form.subscribe_approved(move |_| {
        let _ = &subscribed;
    });
    #[allow(deprecated)]
    form.on_approved(move |_| {
        let _ = &legacy;
    });

    assert!(!subscription.is_active());
    assert!(subscribed_weak.upgrade().is_none());
    assert!(legacy_weak.upgrade().is_none());
}

#[test]
fn form_disposal_releases_every_remaining_callback() {
    let form = approved_form();
    let capture = Arc::new(Capture);
    let weak = Arc::downgrade(&capture);
    let subscription = form.subscribe_approved(move |_| {
        let _ = &capture;
    });

    form.dispose();

    assert!(weak.upgrade().is_none());
    assert!(!subscription.is_active());
    subscription.dispose();
}

/// A disposal made during an emission skips the callbacks not yet invoked. A
/// disposal from another thread waits for the emission instead (spec/20 §5.5,
/// ADR-0176), so this one runs on the approving thread.
#[test]
fn disposal_during_an_emission_skips_the_callbacks_not_yet_invoked() {
    let form = approved_form();
    let _disposing = form.subscribe_approved({
        let form = form.clone();
        move |_| form.dispose()
    });
    let (count, callback) = counter();
    let later = form.subscribe_approved(callback);

    assert!(form.approve().is_ok());

    assert_eq!(count.load(Ordering::SeqCst), 0);
    assert!(!later.is_active());
}

/// #1160 — a `dispose()` from another thread waits until the approval
/// subscribers have run (spec/20 §5.5, ADR-0176). It records its wait in the
/// wait-for graph, and every subscriber still receives the approval.
#[cfg(feature = "test-seams")]
#[test]
fn another_threads_disposal_waits_for_the_approval_subscribers() {
    let form = approved_form();
    let (entered_tx, entered) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    let release_rx = Mutex::new(release_rx);
    let _blocking = form.subscribe_approved(move |_| {
        entered_tx.send(()).unwrap();
        // A dropped sender also releases the subscriber, so a failed
        // assertion cannot leave it waiting.
        let _ = release_rx.lock().unwrap().recv_timeout(BOUND);
    });
    let (count, callback) = counter();
    let later = form.subscribe_approved(callback);
    let approval = thread::spawn({
        let form = form.clone();
        move || form.approve()
    });
    entered.recv_timeout(BOUND).unwrap();

    let disposer = thread::spawn({
        let form = form.clone();
        move || form.dispose()
    });
    let disposer_id = disposer.thread().id();
    assert!(
        eventually(|| wait_registered_for_testing(disposer_id)),
        "the disposal waits for the publication in the wait-for graph"
    );
    assert!(!disposer.is_finished());
    assert!(later.is_active());
    release.send(()).unwrap();

    let deadline = Instant::now() + BOUND;
    assert!(join_by(approval, deadline, "approve()").is_ok());
    join_by(disposer, deadline, "dispose()");
    assert_eq!(count.load(Ordering::SeqCst), 1);
    assert!(!later.is_active());
}

#[test]
fn a_subscriber_added_after_an_approval_does_not_receive_it() {
    let form = approved_form();
    form.approve().unwrap();
    let (count, callback) = counter();

    let _late = form.subscribe_approved(callback);

    assert_eq!(count.load(Ordering::SeqCst), 0);
}

#[test]
#[allow(deprecated)]
fn legacy_on_approved_callbacks_keep_firing_in_registration_order() {
    let form = FormVm::new("form", 1);
    let order = Arc::new(Mutex::new(Vec::new()));
    form.on_approved({
        let order = order.clone();
        move |model| order.lock().unwrap().push(("legacy", model))
    });
    let _subscription = form.subscribe_approved({
        let order = order.clone();
        move |model| order.lock().unwrap().push(("subscribed", model))
    });

    form.set_model(2);
    form.approve().unwrap();

    assert_eq!(
        *order.lock().unwrap(),
        vec![("legacy", 2), ("subscribed", 2)]
    );
}

#[test]
fn validators_registered_after_dispose_are_inactive() {
    let form = FormVm::new("form", 1);
    form.dispose();

    form.with_field_validator("value", |_| Some("bad".to_string()));
    form.with_model_validator(|_| {
        std::collections::BTreeMap::from([("value".to_string(), "bad".to_string())])
    });

    assert!(form.errors().is_empty());
}

#[test]
fn a_subscription_detached_mid_emission_releases_its_captures_at_once() {
    let form = FormVm::new("form", 1);
    let captured = Arc::new(());
    let weak: Weak<()> = Arc::downgrade(&captured);
    let slot: Arc<Mutex<Option<ApprovalSubscription>>> = Arc::new(Mutex::new(None));
    let alive_after_detach = Arc::new(Mutex::new(None));
    let (slot_in_first, weak_in_first, alive) =
        (slot.clone(), weak.clone(), alive_after_detach.clone());
    let _first = form.subscribe_approved(move |_| {
        if let Some(subscription) = slot_in_first.lock().unwrap().take() {
            subscription.dispose();
        }
        *alive.lock().unwrap() = Some(weak_in_first.upgrade().is_some());
    });
    let held = captured.clone();
    let second = form.subscribe_approved(move |_| {
        let _ = &held;
        panic!("a detached subscription must not run");
    });
    *slot.lock().unwrap() = Some(second);
    drop(captured);

    form.set_model(2);
    form.approve().unwrap();

    assert_eq!(*alive_after_detach.lock().unwrap(), Some(false));
    assert!(weak.upgrade().is_none());
}

/// #740 — an edit deferred during settlement still applies when an approval
/// subscriber panics, and is not replayed over a later edit.
#[test]
fn a_panicking_approval_subscriber_still_applies_the_deferred_edit() {
    let form = FormVm::new("form", 1);
    let armed = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        let armed = Arc::clone(&armed);
        // The settlement notification runs after the commit of 2.
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                form.set_model(5);
            }
        }
    });
    let panic_once = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let _subscriber = form.subscribe_approved({
        let panic_once = Arc::clone(&panic_once);
        move |_| {
            if panic_once.swap(false, Ordering::SeqCst) {
                panic!("approval subscriber panicked");
            }
        }
    });

    form.set_model(2);
    let first = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| form.approve()));
    assert!(
        first.is_err(),
        "the subscriber panic reaches the approve() caller"
    );
    assert_eq!(form.model(), 5, "the deferred edit applies");

    form.set_model(7);
    form.approve().unwrap();
    assert_eq!(form.model(), 7);
    assert_eq!(form.snapshot(), 7);
    assert!(!form.is_dirty(), "no stale edit is replayed");
}

/// #740 — an edit deferred in a nested settlement applies only after the
/// outer settlement's approval subscribers have run.
#[test]
fn a_nested_settlement_edit_waits_for_the_outer_subscribers() {
    let form = FormVm::new("form", 1);
    let notifications = Arc::new(AtomicUsize::new(0));
    let inner_result = Arc::new(Mutex::new(None));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        let notifications = Arc::clone(&notifications);
        let inner_result = Arc::clone(&inner_result);
        // 1: outer admission, 2: outer settlement, 3: inner admission,
        // 4: inner settlement.
        move |_| match notifications.fetch_add(1, Ordering::SeqCst) + 1 {
            2 => *inner_result.lock().unwrap() = Some(form.approve()),
            4 => form.set_model(9),
            _ => {}
        }
    });
    let models_at_callbacks = Arc::new(Mutex::new(Vec::new()));
    let _subscriber = form.subscribe_approved({
        let form = form.clone();
        let models_at_callbacks = Arc::clone(&models_at_callbacks);
        move |_| models_at_callbacks.lock().unwrap().push(form.model())
    });

    form.set_model(2);
    form.approve().unwrap();

    assert!(matches!(*inner_result.lock().unwrap(), Some(Ok(()))));
    assert_eq!(
        *models_at_callbacks.lock().unwrap(),
        vec![2, 2],
        "both settlements' subscribers run before the deferred edit applies"
    );
    assert_eq!(form.model(), 9);
}

/// The #1061 reproduction and what it records.
struct NestedApproval {
    form: FormVm<i32>,
    /// `(approved, model)` that `S2` saw, once per approval.
    records: Arc<Mutex<Vec<(i32, i32)>>>,
    /// The result of the nested approval that `S1` started.
    inner_result: Arc<Mutex<Option<vmx::VmxResult<()>>>>,
    /// How often the validator saw the model 9: once when the queued edit
    /// prepares at call time and once when it replays (ADR-0174).
    assignments_of_nine: Arc<AtomicUsize>,
    _subscriptions: Vec<ApprovalSubscription>,
    _observer: vmx::Subscription,
}

/// Builds the #1061 reproduction. The outer settlement notification makes an
/// edit to 9, which settlement defers. `S1` starts a nested approval on its
/// first call, and `S2` records `(approved, model)` for each approval. A
/// validator counts how often the model 9 is assigned.
fn nested_subscriber_approval(panic_in_outer_s2: bool) -> NestedApproval {
    let assignments_of_nine = Arc::new(AtomicUsize::new(0));
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .validator("value", {
            let assignments_of_nine = Arc::clone(&assignments_of_nine);
            move |model| {
                if *model == 9 {
                    assignments_of_nine.fetch_add(1, Ordering::SeqCst);
                }
                None
            }
        })
        .build()
        .unwrap();
    let notifications = Arc::new(AtomicUsize::new(0));
    let observer = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        // 1: outer admission, 2: outer settlement.
        move |_| {
            if notifications.fetch_add(1, Ordering::SeqCst) + 1 == 2 {
                form.set_model(9);
            }
        }
    });
    let inner_result = Arc::new(Mutex::new(None));
    let s1 = form.subscribe_approved({
        let (form, inner_result) = (form.clone(), Arc::clone(&inner_result));
        let started = std::sync::atomic::AtomicBool::new(false);
        move |_| {
            if !started.swap(true, Ordering::SeqCst) {
                *inner_result.lock().unwrap() = Some(form.approve());
            }
        }
    });
    let records = Arc::new(Mutex::new(Vec::new()));
    let s2 = form.subscribe_approved({
        let (form, records) = (form.clone(), Arc::clone(&records));
        move |approved| {
            let mut records = records.lock().unwrap();
            records.push((approved, form.model()));
            // The inner approval records first; the outer one second.
            if panic_in_outer_s2 && records.len() == 2 {
                drop(records);
                panic!("outer approval subscriber panicked");
            }
        }
    });
    NestedApproval {
        form,
        records,
        inner_result,
        assignments_of_nine,
        _subscriptions: vec![s1, s2],
        _observer: observer,
    }
}

/// #1061 — an approval started from an approval subscriber does not replay
/// the outer settlement's deferred edit. The outer approval's later
/// subscribers still see the committed model, and the edit applies once the
/// outer approval returns.
#[test]
fn a_nested_approval_from_a_subscriber_keeps_the_outer_deferred_edit() {
    // Every field is bound, so the subscriptions stay alive for the test.
    let NestedApproval {
        form,
        records,
        inner_result,
        assignments_of_nine,
        _subscriptions,
        _observer,
    } = nested_subscriber_approval(false);

    form.set_model(2);
    form.approve().unwrap();

    assert!(matches!(*inner_result.lock().unwrap(), Some(Ok(()))));
    assert_eq!(*records.lock().unwrap(), vec![(2, 2), (2, 2)]);
    assert_eq!(form.model(), 9);
    assert_eq!(
        assignments_of_nine.load(Ordering::SeqCst),
        2,
        "the edit prepares at call time and replays once"
    );
}

/// #1061 — the same when `S2` panics in the outer approval: the panic reaches
/// the `approve()` caller, and the deferred edit still applies, once.
#[test]
fn a_nested_approval_keeps_the_outer_deferred_edit_when_an_outer_subscriber_panics() {
    // Every field is bound, so the subscriptions stay alive for the test.
    let NestedApproval {
        form,
        records,
        inner_result,
        assignments_of_nine,
        _subscriptions,
        _observer,
    } = nested_subscriber_approval(true);

    form.set_model(2);
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| form.approve()));

    assert!(outcome.is_err(), "the subscriber panic reaches approve()");
    assert!(matches!(*inner_result.lock().unwrap(), Some(Ok(()))));
    assert_eq!(*records.lock().unwrap(), vec![(2, 2), (2, 2)]);
    assert_eq!(form.model(), 9);
    assert_eq!(
        assignments_of_nine.load(Ordering::SeqCst),
        2,
        "the edit prepares at call time and replays once"
    );
}

/// #1061 — an edit made by an approval subscriber itself is not deferred.
#[test]
fn an_edit_made_by_an_approval_subscriber_applies_at_once() {
    let form = FormVm::new("form", 1);
    let seen = Arc::new(Mutex::new(None));
    let _subscriber = form.subscribe_approved({
        let (form, seen) = (form.clone(), Arc::clone(&seen));
        move |_| {
            form.set_model(4);
            *seen.lock().unwrap() = Some(form.model());
        }
    });

    form.set_model(2);
    form.approve().unwrap();

    assert_eq!(*seen.lock().unwrap(), Some(4));
    assert_eq!(form.model(), 4);
}

/// #1160 — an approval started from the outer settlement notification runs
/// its subscribers outside the outer pre-publication window. An edit made by
/// the nested approval's subscriber applies at once, and the outer subscriber
/// then sees it.
#[test]
fn a_nested_settlement_subscriber_edit_applies_at_once() {
    let form = FormVm::new("form", 1);
    let armed = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let inner_result = Arc::new(Mutex::new(None));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, armed, inner_result) =
            (form.clone(), Arc::clone(&armed), Arc::clone(&inner_result));
        // The outer settlement notification runs after the commit of 2.
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                *inner_result.lock().unwrap() = Some(form.approve());
            }
        }
    });
    let seen = Arc::new(Mutex::new(Vec::new()));
    let _subscriber = form.subscribe_approved({
        let (form, seen) = (form.clone(), Arc::clone(&seen));
        let first = std::sync::atomic::AtomicBool::new(true);
        move |_| {
            if first.swap(false, Ordering::SeqCst) {
                // The nested approval's subscriber runs first.
                form.set_model(4);
                seen.lock()
                    .unwrap()
                    .push(("inner-after-edit", form.model()));
            } else {
                seen.lock().unwrap().push(("outer", form.model()));
            }
        }
    });

    form.set_model(2);
    form.approve().unwrap();

    assert!(matches!(*inner_result.lock().unwrap(), Some(Ok(()))));
    assert_eq!(
        *seen.lock().unwrap(),
        vec![("inner-after-edit", 4), ("outer", 4)],
        "the nested subscriber's edit is not deferred behind the outer notifications"
    );
    assert_eq!(form.model(), 4);
    assert_eq!(form.snapshot(), 2);
}

/// #1160 — the nested settlement restores the outer pre-publication state
/// when it ends. An edit made by the outer settlement notification, before or
/// after the nested approval, waits until the outer subscribers have run.
#[test]
fn a_nested_settlement_restores_the_outer_pre_publication() {
    let form = FormVm::new("form", 1);
    let armed = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let inner_result = Arc::new(Mutex::new(None));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, armed, inner_result) =
            (form.clone(), Arc::clone(&armed), Arc::clone(&inner_result));
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                form.set_model(9);
                *inner_result.lock().unwrap() = Some(form.approve());
                form.set_model(10);
            }
        }
    });
    let seen = Arc::new(Mutex::new(Vec::new()));
    let _subscriber = form.subscribe_approved({
        let (form, seen) = (form.clone(), Arc::clone(&seen));
        move |approved| seen.lock().unwrap().push((approved, form.model()))
    });

    form.set_model(2);
    form.approve().unwrap();

    assert!(matches!(*inner_result.lock().unwrap(), Some(Ok(()))));
    assert_eq!(
        *seen.lock().unwrap(),
        vec![(2, 2), (2, 2)],
        "both approvals' subscribers see the committed model"
    );
    assert_eq!(form.model(), 10, "the deferred edits apply in order");
    assert_eq!(form.snapshot(), 2);
}

/// #1160 — a nested settlement whose subscriber panics still restores the
/// outer pre-publication state. The outer notification catches the panic,
/// and its next edit still waits for the outer subscribers.
#[test]
fn a_panicking_nested_settlement_restores_the_outer_pre_publication() {
    let form = FormVm::new("form", 1);
    let armed = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let inner_panicked = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, armed, inner_panicked) = (
            form.clone(),
            Arc::clone(&armed),
            Arc::clone(&inner_panicked),
        );
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                let inner =
                    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| form.approve()));
                inner_panicked.store(inner.is_err(), Ordering::SeqCst);
                form.set_model(6);
            }
        }
    });
    let seen = Arc::new(Mutex::new(Vec::new()));
    let _subscriber = form.subscribe_approved({
        let (form, seen) = (form.clone(), Arc::clone(&seen));
        let first = std::sync::atomic::AtomicBool::new(true);
        move |_| {
            if first.swap(false, Ordering::SeqCst) {
                panic!("nested approval subscriber panicked");
            }
            seen.lock().unwrap().push(form.model());
        }
    });

    form.set_model(2);
    form.approve().unwrap();

    assert!(inner_panicked.load(Ordering::SeqCst));
    assert_eq!(
        *seen.lock().unwrap(),
        vec![2],
        "the outer subscriber sees the committed model"
    );
    assert_eq!(form.model(), 6, "the deferred edit applies afterwards");
    form.set_model(7);
    assert_eq!(form.model(), 7, "no pre-publication state is left behind");
}

/// Records each model a validator sees and the thread it runs on.
#[cfg(feature = "test-seams")]
type Validated = Arc<Mutex<Vec<(i32, ThreadId)>>>;

#[cfg(feature = "test-seams")]
fn recording_form() -> (FormVm<i32>, Validated) {
    let validated: Validated = Arc::default();
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .validator("value", {
            let validated = Arc::clone(&validated);
            move |model: &i32| {
                validated
                    .lock()
                    .unwrap()
                    .push((*model, thread::current().id()));
                None
            }
        })
        .build()
        .unwrap();
    (form, validated)
}

/// The threads on which the validator saw `value`.
#[cfg(feature = "test-seams")]
fn validated_on(validated: &Validated, value: i32) -> Vec<ThreadId> {
    validated
        .lock()
        .unwrap()
        .iter()
        .filter(|(model, _)| *model == value)
        .map(|(_, thread)| *thread)
        .collect()
}

/// Spawns `work` on a named thread.
#[cfg(feature = "test-seams")]
fn spawn_named<T: Send + 'static>(
    name: &str,
    work: impl FnOnce() -> T + Send + 'static,
) -> JoinHandle<T> {
    thread::Builder::new()
        .name(name.to_string())
        .spawn(work)
        .unwrap()
}

/// Reports whether the thread `handle` runs waits in the wait-for graph and
/// has not returned after [`SETTLE`].
#[cfg(feature = "test-seams")]
fn waits_in_the_graph<T>(handle: &JoinHandle<T>) -> bool {
    let id = handle.thread().id();
    let registered = eventually(|| wait_registered_for_testing(id));
    thread::sleep(SETTLE);
    registered && !handle.is_finished()
}

/// #1061 review, #1160 — each publishing thread replays only its own queue.
/// Thread B's approval waits while thread A's approval subscribers run. Each
/// thread's settlement-deferred edit prepares and replays on that thread. A
/// replay can no longer follow another thread's later edit, because that edit
/// waits for the scope, so the final edit only checks that no state is left.
#[cfg(feature = "test-seams")]
#[test]
fn another_threads_approval_waits_and_replays_only_its_own_deferred_edit() {
    let (form, validated) = recording_form();
    let notifications = Arc::new(Mutex::new(std::collections::HashMap::<String, usize>::new()));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        let notifications = Arc::clone(&notifications);
        // On each thread: 1 is the admission, 2 the settlement.
        move |_| {
            let name = thread::current().name().unwrap_or_default().to_string();
            let count = {
                let mut notifications = notifications.lock().unwrap();
                let count = notifications.entry(name.clone()).or_default();
                *count += 1;
                *count
            };
            match (name.as_str(), count) {
                ("a", 2) => form.set_model(7),
                ("b", 2) => form.set_model(5),
                _ => {}
            }
        }
    });
    let (entered, entered_rx) = mpsc::channel::<()>();
    let (release, release_rx) = mpsc::channel::<()>();
    let (entered, release_rx) = (Mutex::new(entered), Mutex::new(release_rx));
    let first = AtomicBool::new(true);
    let _subscriber = form.subscribe_approved(move |_| {
        if first.swap(false, Ordering::SeqCst) {
            entered.lock().unwrap().send(()).unwrap();
            // A dropped sender also releases A, so a failed assertion below
            // cannot leave A waiting.
            let _ = release_rx.lock().unwrap().recv_timeout(BOUND);
        }
    });

    form.set_model(2);
    let a = spawn_named("a", {
        let form = form.clone();
        move || (form.approve(), thread::current().id())
    });
    entered_rx.recv_timeout(BOUND).unwrap();
    let b = spawn_named("b", {
        let form = form.clone();
        move || (form.approve(), thread::current().id())
    });
    let b_waited = waits_in_the_graph(&b);
    release.send(()).unwrap();
    let deadline = Instant::now() + BOUND;
    let (a_result, a_id) = join_by(a, deadline, "A's approve()");
    let (b_result, b_id) = join_by(b, deadline, "B's approve()");
    a_result.unwrap();
    b_result.unwrap();
    form.set_model(8);
    form.approve().unwrap();

    assert!(b_waited, "B's approval waits for A's publication");
    assert_eq!(
        validated_on(&validated, 7),
        vec![a_id, a_id],
        "A's deferred edit prepares and replays on A"
    );
    assert_eq!(
        validated_on(&validated, 5),
        vec![b_id, b_id],
        "B's deferred edit prepares and replays on B"
    );
    assert_eq!(form.model(), 8, "the last edit stands");
    assert_eq!(form.snapshot(), 8);
    assert!(!form.is_dirty(), "no stale edit is replayed");
}

/// #1160 case 1 — another thread's approval waits until this thread's
/// approval subscribers have run, so its settlement never replays this
/// thread's deferred edit.
#[cfg(feature = "test-seams")]
#[test]
fn another_threads_approval_waits_until_the_approval_subscribers_have_run() {
    let (form, validated) = recording_form();
    let armed = Arc::new(AtomicBool::new(true));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, armed) = (form.clone(), Arc::clone(&armed));
        // A's settlement notification runs after the commit of 2.
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                form.set_model(9);
            }
        }
    });
    let b_slot = Arc::new(Mutex::new(None));
    let b_waited = Arc::new(AtomicBool::new(false));
    let first = AtomicBool::new(true);
    let _s1 = form.subscribe_approved({
        let (form, b_slot, b_waited) = (form.clone(), Arc::clone(&b_slot), Arc::clone(&b_waited));
        move |_| {
            if first.swap(false, Ordering::SeqCst) {
                let b = spawn_named("b", {
                    let form = form.clone();
                    move || form.approve()
                });
                b_waited.store(waits_in_the_graph(&b), Ordering::SeqCst);
                *b_slot.lock().unwrap() = Some(b);
            }
        }
    });
    let seen = Arc::new(Mutex::new(Vec::new()));
    let _s2 = form.subscribe_approved({
        let (form, seen) = (form.clone(), Arc::clone(&seen));
        move |_| seen.lock().unwrap().push(form.model())
    });

    form.set_model(2);
    let a = spawn_named("a", {
        let form = form.clone();
        move || (form.approve(), thread::current().id())
    });
    let deadline = Instant::now() + BOUND;
    let (a_result, a_id) = join_by(a, deadline, "A's approve()");
    let b = b_slot.lock().unwrap().take().expect("S1 started B");
    let b_result = join_by(b, deadline, "B's approve()");

    a_result.unwrap();
    assert!(b_waited.load(Ordering::SeqCst), "B's approval waits for A");
    assert_eq!(
        seen.lock().unwrap().first(),
        Some(&2),
        "S2 reads 2 in A's approval"
    );
    assert_eq!(b_result, Ok(()));
    assert_eq!(form.model(), 9);
    assert_eq!(
        validated_on(&validated, 9),
        vec![a_id, a_id],
        "the edit to 9 prepares and replays on A, never on B"
    );
}

/// #1160 case 2 — another thread's edit made during this thread's
/// settlement waits until the approval subscribers have run. It is not
/// deferred to this thread.
#[cfg(feature = "test-seams")]
#[test]
fn another_threads_edit_waits_until_the_approval_subscribers_have_run() {
    let (form, validated) = recording_form();
    let armed = Arc::new(AtomicBool::new(true));
    let b_slot = Arc::new(Mutex::new(None));
    let b_waited = Arc::new(AtomicBool::new(false));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, armed) = (form.clone(), Arc::clone(&armed));
        let (b_slot, b_waited) = (Arc::clone(&b_slot), Arc::clone(&b_waited));
        // A's settlement notification runs after the commit of 2.
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                let b = spawn_named("b", {
                    let form = form.clone();
                    move || {
                        form.set_model(5);
                        (form.model(), thread::current().id())
                    }
                });
                b_waited.store(waits_in_the_graph(&b), Ordering::SeqCst);
                *b_slot.lock().unwrap() = Some(b);
            }
        }
    });
    let seen = Arc::new(Mutex::new(Vec::new()));
    let _subscriber = form.subscribe_approved({
        let (form, seen) = (form.clone(), Arc::clone(&seen));
        move |_| seen.lock().unwrap().push(form.model())
    });

    form.set_model(2);
    form.approve().unwrap();
    let b = b_slot
        .lock()
        .unwrap()
        .take()
        .expect("the settlement started B");
    let (b_read, b_id) = join_by(b, Instant::now() + BOUND, "B's set_model");

    assert!(b_waited.load(Ordering::SeqCst), "B's edit waits for A");
    assert_eq!(*seen.lock().unwrap(), vec![2]);
    assert_eq!(b_read, 5, "B reads its own edit");
    assert_eq!(form.model(), 5);
    assert_eq!(validated_on(&validated, 5), vec![b_id]);
}

/// #1160 case 4 — another thread's revert during this thread's approval
/// publication waits until the approval subscribers have run.
#[cfg(feature = "test-seams")]
#[test]
fn another_threads_revert_waits_until_the_approval_subscribers_have_run() {
    let slot = Arc::new(Mutex::new(None::<FormVm<i32>>));
    let edited = Arc::new(AtomicBool::new(false));
    let form = FormVm::builder()
        .initial(1)
        .persister({
            let (slot, edited) = (Arc::clone(&slot), Arc::clone(&edited));
            move |_: &i32| {
                if !edited.swap(true, Ordering::SeqCst) {
                    let form = slot.lock().unwrap().clone().unwrap();
                    form.set_model(7);
                }
                Ok(())
            }
        })
        .build()
        .unwrap();
    *slot.lock().unwrap() = Some(form.clone());
    let b_slot = Arc::new(Mutex::new(None));
    let b_waited = Arc::new(AtomicBool::new(false));
    let first = AtomicBool::new(true);
    let _s1 = form.subscribe_approved({
        let (form, b_slot, b_waited) = (form.clone(), Arc::clone(&b_slot), Arc::clone(&b_waited));
        move |_| {
            if first.swap(false, Ordering::SeqCst) {
                let b = spawn_named("b", {
                    let form = form.clone();
                    move || form.revert()
                });
                b_waited.store(waits_in_the_graph(&b), Ordering::SeqCst);
                *b_slot.lock().unwrap() = Some(b);
            }
        }
    });
    let seen = Arc::new(Mutex::new(Vec::new()));
    let _s2 = form.subscribe_approved({
        let (form, seen) = (form.clone(), Arc::clone(&seen));
        move |_| seen.lock().unwrap().push(form.model())
    });

    form.set_model(2);
    let a = spawn_named("a", {
        let form = form.clone();
        move || form.approve()
    });
    let deadline = Instant::now() + BOUND;
    let a_result = join_by(a, deadline, "A's approve()");
    let b = b_slot.lock().unwrap().take().expect("S1 started B");
    join_by(b, deadline, "B's revert()");
    slot.lock().unwrap().take();

    a_result.unwrap();
    assert!(b_waited.load(Ordering::SeqCst), "B's revert waits for A");
    assert_eq!(*seen.lock().unwrap(), vec![7], "S2 reads the racing edit");
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 2);
}

/// spec/20 §5.5 — a `set_model` made in this thread's pre-publication window
/// still waits while another thread holds a publication scope. Thread Y's
/// reset callback edits the form while thread X's `errors_changed` subscriber
/// runs. Y's edit waits for X's update scope, and only then joins Y's queue.
#[cfg(feature = "test-seams")]
#[test]
fn a_pre_publication_edit_waits_for_another_threads_update_scope() {
    type FormSlot = Arc<Mutex<Option<FormVm<i32>>>>;
    let slot: FormSlot = Arc::default();
    let (in_reset, in_reset_rx) = mpsc::channel::<()>();
    let (go, go_rx) = mpsc::channel::<()>();
    let (in_reset, go_rx) = (Mutex::new(in_reset), Mutex::new(go_rx));
    let y_edit_returned = Arc::new(AtomicBool::new(false));
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .validator("value", |model: &i32| {
            (*model < 0).then(|| "negative".to_string())
        })
        .reset_on_approved({
            let (slot, y_edit_returned) = (Arc::clone(&slot), Arc::clone(&y_edit_returned));
            move |model: &i32| {
                let form = slot.lock().unwrap().clone().expect("the form is built");
                in_reset.lock().unwrap().send(()).unwrap();
                // A dropped sender also releases Y.
                let _ = go_rx.lock().unwrap().recv_timeout(BOUND);
                form.set_model(50);
                y_edit_returned.store(true, Ordering::SeqCst);
                Ok(*model)
            }
        })
        .build()
        .unwrap();
    *slot.lock().unwrap() = Some(form.clone());
    let (x_entered, x_entered_rx) = mpsc::channel::<()>();
    let (x_release, x_release_rx) = mpsc::channel::<()>();
    let (x_entered, x_release_rx) = (Mutex::new(x_entered), Mutex::new(x_release_rx));
    let _x_observer = form.errors_changed().subscribe({
        let form = form.clone();
        move |_| {
            if form.model() == -1 && thread::current().name() == Some("x") {
                x_entered.lock().unwrap().send(()).unwrap();
                let _ = x_release_rx.lock().unwrap().recv_timeout(BOUND);
            }
        }
    });

    form.set_model(2);
    let y = spawn_named("y", {
        let form = form.clone();
        move || form.approve()
    });
    in_reset_rx.recv_timeout(BOUND).unwrap();
    let x = spawn_named("x", {
        let form = form.clone();
        move || form.set_model(-1)
    });
    x_entered_rx.recv_timeout(BOUND).unwrap();
    go.send(()).unwrap();
    let y_waited = waits_in_the_graph(&y);
    let returned_during_scope = y_edit_returned.load(Ordering::SeqCst);
    x_release.send(()).unwrap();
    let deadline = Instant::now() + BOUND;
    join_by(x, deadline, "X's set_model");
    join_by(y, deadline, "Y's approve()").unwrap();

    assert!(
        !returned_during_scope,
        "Y's edit does not return while X's errors_changed subscriber runs"
    );
    assert!(y_waited, "Y's edit waits in the wait-for graph");
    assert_eq!(form.snapshot(), 2, "Y's approval commits its reset");
    assert_eq!(
        form.model(),
        50,
        "Y's queued edit replays after its settlement"
    );
}

/// spec/20 §5.5 — disposal ends another thread's wait for a publication
/// scope. Thread X disposes the form from its own `errors_changed` subscriber
/// and keeps running. Thread Y's waiting `set_model` returns at once and
/// finds the form disposed, as in C# and Python.
#[cfg(feature = "test-seams")]
#[test]
fn disposal_ends_another_threads_wait_for_a_publication_scope() {
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .validator("value", |model: &i32| {
            (*model < 0).then(|| "negative".to_string())
        })
        .build()
        .unwrap();
    let (x_entered, x_entered_rx) = mpsc::channel::<()>();
    let (dispose, dispose_rx) = mpsc::channel::<()>();
    let (x_release, x_release_rx) = mpsc::channel::<()>();
    let (x_entered, dispose_rx, x_release_rx) = (
        Mutex::new(x_entered),
        Mutex::new(dispose_rx),
        Mutex::new(x_release_rx),
    );
    let _x_observer = form.errors_changed().subscribe({
        let form = form.clone();
        move |_| {
            if thread::current().name() == Some("x") {
                x_entered.lock().unwrap().send(()).unwrap();
                // Dropped senders also release X.
                let _ = dispose_rx.lock().unwrap().recv_timeout(BOUND);
                form.dispose();
                let _ = x_release_rx.lock().unwrap().recv_timeout(BOUND);
            }
        }
    });

    let x = spawn_named("x", {
        let form = form.clone();
        move || form.set_model(-1)
    });
    x_entered_rx.recv_timeout(BOUND).unwrap();
    let y = spawn_named("y", {
        let form = form.clone();
        move || form.set_model(5)
    });
    let y_waited = waits_in_the_graph(&y);
    dispose.send(()).unwrap();
    let y_returned = eventually(|| y.is_finished());
    x_release.send(()).unwrap();
    let deadline = Instant::now() + BOUND;
    join_by(x, deadline, "X's set_model");
    join_by(y, deadline, "Y's set_model");

    assert!(y_waited, "Y's edit waits for X's update scope");
    assert!(
        y_returned,
        "Y stops waiting once X disposes the form, while X's scope is open"
    );
    assert_eq!(form.model(), -1, "Y's edit finds the form disposed");
}

/// #1160 — an approval started from the outer settlement notification
/// suspends the outer window only while it delivers `OnApproved`. An edit
/// that the outer notification makes after it is still deferred until the
/// outer approval subscribers have run (spec/20 §5.5, ADR-0176).
#[test]
fn an_outer_settlement_edit_after_a_nested_approval_is_deferred() {
    let form = FormVm::new("form", 1);
    let armed = Arc::new(AtomicBool::new(true));
    let inner_result = Arc::new(Mutex::new(None));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, armed, inner_result) =
            (form.clone(), Arc::clone(&armed), Arc::clone(&inner_result));
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                *inner_result.lock().unwrap() = Some(form.approve());
                form.set_model(9);
            }
        }
    });
    let seen = Arc::new(Mutex::new(Vec::new()));
    let _subscriber = form.subscribe_approved({
        let (form, seen) = (form.clone(), Arc::clone(&seen));
        move |approved| seen.lock().unwrap().push((approved, form.model()))
    });

    form.set_model(2);
    form.approve().unwrap();

    assert!(matches!(*inner_result.lock().unwrap(), Some(Ok(()))));
    assert_eq!(*seen.lock().unwrap(), vec![(2, 2), (2, 2)]);
    assert_eq!(form.model(), 9);
}
