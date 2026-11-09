//! Rust `FormVm::subscribe_approved_with_completion` tells a subscriber when
//! the form is disposed (spec/20 §10, ADR-0210, #1270).

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use vmx::{ApprovalSubscription, FormVm};

fn dirty_form() -> FormVm<i32> {
    let form = FormVm::new("form", 1);
    form.set_model(2);
    form
}

/// Returns a counter and a completion callback that increments it.
fn completion_counter() -> (Arc<AtomicUsize>, impl Fn() + Send + Sync + 'static) {
    let count = Arc::new(AtomicUsize::new(0));
    let counted = count.clone();
    (count, move || {
        counted.fetch_add(1, Ordering::SeqCst);
    })
}

#[test]
fn disposal_completes_the_subscription_once() {
    let form = dirty_form();
    let (completed, on_completed) = completion_counter();
    let subscription = form.subscribe_approved_with_completion(|_| {}, on_completed);

    form.dispose();

    assert_eq!(completed.load(Ordering::SeqCst), 1);
    assert!(!subscription.is_active());
}

#[test]
fn repeated_disposal_completes_once() {
    let form = dirty_form();
    let (completed, on_completed) = completion_counter();
    let _subscription = form.subscribe_approved_with_completion(|_| {}, on_completed);

    form.dispose();
    form.dispose();

    assert_eq!(completed.load(Ordering::SeqCst), 1);
}

#[test]
fn a_subscription_after_disposal_completes_at_once_and_is_inactive() {
    let form = dirty_form();
    form.dispose();
    let approved = Arc::new(AtomicUsize::new(0));
    let (completed, on_completed) = completion_counter();

    let subscription = {
        let approved = approved.clone();
        form.subscribe_approved_with_completion(
            move |_| {
                approved.fetch_add(1, Ordering::SeqCst);
            },
            on_completed,
        )
    };

    assert_eq!(completed.load(Ordering::SeqCst), 1);
    assert!(!subscription.is_active());
    let _ = form.approve();
    assert_eq!(approved.load(Ordering::SeqCst), 0);
    assert_eq!(completed.load(Ordering::SeqCst), 1);
}

#[test]
fn a_detached_subscription_is_not_completed() {
    let form = dirty_form();
    let (completed, on_completed) = completion_counter();
    let subscription = form.subscribe_approved_with_completion(|_| {}, on_completed);

    subscription.dispose();
    form.dispose();

    assert_eq!(completed.load(Ordering::SeqCst), 0);
}

#[test]
fn a_completion_that_subscribes_again_gets_an_inactive_handle() {
    let form = dirty_form();
    let resubscribed: Arc<Mutex<Option<ApprovalSubscription>>> = Arc::new(Mutex::new(None));
    let _subscription = {
        let target = form.clone();
        let resubscribed = resubscribed.clone();
        form.subscribe_approved_with_completion(
            |_| {},
            move || {
                let handle = target.subscribe_approved(|_| unreachable!("form disposed"));
                *resubscribed.lock().unwrap() = Some(handle);
            },
        )
    };

    form.dispose();

    let handle = resubscribed.lock().unwrap().take().expect("completion ran");
    assert!(!handle.is_active());
}

#[test]
fn a_panicking_completion_does_not_stop_the_other_completions() {
    let form = dirty_form();
    let errors_completed = Arc::new(AtomicUsize::new(0));
    let approve_errors_completed = Arc::new(AtomicUsize::new(0));
    let _errors = {
        let completed = errors_completed.clone();
        form.errors_changed().subscribe_with_completion(
            |_| {},
            move || {
                completed.fetch_add(1, Ordering::SeqCst);
            },
        )
    };
    let _approve_errors = {
        let completed = approve_errors_completed.clone();
        form.approve_errors().subscribe_with_completion(
            |_| {},
            move || {
                completed.fetch_add(1, Ordering::SeqCst);
            },
        )
    };
    let _panicking = form.subscribe_approved_with_completion(
        |_| {},
        || panic!("completion panic for the disposal test"),
    );
    let (completed, on_completed) = completion_counter();
    let _later = form.subscribe_approved_with_completion(|_| {}, on_completed);

    form.dispose();

    assert_eq!(completed.load(Ordering::SeqCst), 1);
    assert_eq!(errors_completed.load(Ordering::SeqCst), 1);
    assert_eq!(approve_errors_completed.load(Ordering::SeqCst), 1);
}

#[test]
fn an_approval_callback_panic_propagates_out_of_approve() {
    let form = dirty_form();
    let (completed, on_completed) = completion_counter();
    let _subscription = form.subscribe_approved_with_completion(
        |_| panic!("approval panic for the propagation test"),
        on_completed,
    );

    let outcome = catch_unwind(AssertUnwindSafe(|| form.approve()));

    let payload = outcome.expect_err("the approval callback panic propagates");
    assert_eq!(
        payload.downcast_ref::<&str>(),
        Some(&"approval panic for the propagation test")
    );
    assert_eq!(completed.load(Ordering::SeqCst), 0);
}
