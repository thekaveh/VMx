//! Rust `FormVm` approval subscriptions detach individually and post-disposal
//! registration is inert (ADR-0139, #357).

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex, Weak};
use std::time::Duration;

use vmx::{ApprovalSubscription, FormVm};

struct Capture;

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

#[test]
fn disposal_during_an_emission_skips_the_callbacks_not_yet_invoked() {
    let form = approved_form();
    let (entered_tx, entered) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    let release_rx = Mutex::new(release_rx);
    let _blocking = form.subscribe_approved(move |_| {
        entered_tx.send(()).unwrap();
        release_rx.lock().unwrap().recv().unwrap();
    });
    let (count, callback) = counter();
    let _later = form.subscribe_approved(callback);
    let approving = form.clone();
    let approval = std::thread::spawn(move || approving.approve());
    entered.recv_timeout(Duration::from_secs(5)).unwrap();

    form.dispose();
    release.send(()).unwrap();

    assert!(approval.join().unwrap().is_ok());
    assert_eq!(count.load(Ordering::SeqCst), 0);
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
    /// How often the model 9 was assigned.
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
    assert_eq!(assignments_of_nine.load(Ordering::SeqCst), 1);
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
    assert_eq!(assignments_of_nine.load(Ordering::SeqCst), 1);
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

/// #1061 review — the publishing depth is per thread. Thread A waits inside its
/// first approval subscriber while thread B runs a whole approval. B's
/// settlement-deferred edit applies before B's `approve()` returns, and A's
/// later replay does not overwrite B's next edit.
#[test]
fn another_threads_approval_replays_its_own_deferred_edit() {
    let form = FormVm::new("form", 1);
    let armed = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let form = form.clone();
        let armed = Arc::clone(&armed);
        // B's settlement notification runs after the commit of 3.
        move |_| {
            if form.snapshot() == 3 && armed.swap(false, Ordering::SeqCst) {
                form.set_model(7);
            }
        }
    });
    let (entered, entered_rx) = mpsc::channel::<()>();
    let (release, release_rx) = mpsc::channel::<()>();
    let (entered, release_rx) = (Mutex::new(entered), Mutex::new(release_rx));
    let first = std::sync::atomic::AtomicBool::new(true);
    let _subscriber = form.subscribe_approved(move |_| {
        if first.swap(false, Ordering::SeqCst) {
            entered.lock().unwrap().send(()).unwrap();
            // A dropped sender also releases A, so a failed assertion below
            // cannot leave A waiting.
            let _ = release_rx
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(10));
        }
    });

    form.set_model(2);
    let a = std::thread::spawn({
        let form = form.clone();
        move || form.approve()
    });
    entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    form.set_model(3);
    form.approve().unwrap();
    let after_b = form.model();
    form.set_model(8);
    release.send(()).unwrap();
    a.join().unwrap().unwrap();

    assert_eq!(
        after_b, 7,
        "B's deferred edit applies before B's approve returns"
    );
    assert_eq!(
        form.model(),
        8,
        "A's replay does not overwrite B's later edit"
    );
}
