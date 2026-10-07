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
