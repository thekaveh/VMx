//! A `DerivedProperty::recompute` that waits for another thread's recompute
//! gate records the wait in the wait-for graph (spec/03 §4.1, ADR-0209,
//! #1463). Thread A's transform sends on a hub that thread B drains, and B's
//! handler recomputes the same property. Whichever wait closes the cycle is
//! refused, so both threads return, and the stored value is the last value
//! that `value_changes` published.
//!
//! The threads are ordered by observed wait registrations, not by sleeps.

use std::sync::{mpsc, Arc, Mutex};
use std::thread::{self, ThreadId};
use std::time::{Duration, Instant};
use vmx::{wait_registered_for_testing, DerivedProperty, Message, MessageHub};

const BOUND: Duration = Duration::from_secs(5);

fn custom(name: &str) -> Message {
    Message::Custom {
        sender_id: 0,
        sender_name: "test".into(),
        name: name.into(),
    }
}

fn is_named(message: &Message, expected: &str) -> bool {
    matches!(message, Message::Custom { name, .. } if name == expected)
}

/// Polls `condition` until it holds or the bound passes, and reports whether
/// it held, so a handler or a transform never panics inside the library.
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

/// Which wait closes the cycle.
#[derive(Clone, Copy, PartialEq)]
enum Closing {
    /// A waits for drainer B first; B's gate wait is refused.
    GateWait,
    /// B waits for A's gate first; A's hub send is refused.
    HubSend,
}

/// Runs the cycle and returns the final value and the published values.
fn recompute_cycle(closing: Closing) -> (i32, Vec<i32>) {
    let property = DerivedProperty::new(0);
    let published = Arc::new(Mutex::new(Vec::new()));
    let _published = property.value_changes().subscribe({
        let published = published.clone();
        move |value| published.lock().unwrap().push(value)
    });
    let hub = MessageHub::new();
    let thread_a: Arc<Mutex<Option<ThreadId>>> = Arc::new(Mutex::new(None));
    let thread_b: Arc<Mutex<Option<ThreadId>>> = Arc::new(Mutex::new(None));
    let (draining, b_draining) = mpsc::channel::<()>();
    let (in_transform, a_in_transform) = mpsc::channel::<()>();
    let ordered = Arc::new(Mutex::new(true));

    let _handler = hub.subscribe({
        let (property, thread_a, ordered) = (property.clone(), thread_a.clone(), ordered.clone());
        let draining = Mutex::new(Some(draining));
        let a_in_transform = Mutex::new(a_in_transform);
        move |message| {
            if !is_named(message, "start") {
                return;
            }
            if let Some(draining) = draining.lock().unwrap().take() {
                let _ = draining.send(());
            }
            let mut in_order = a_in_transform.lock().unwrap().recv_timeout(BOUND).is_ok();
            if closing == Closing::GateWait {
                let a = *thread_a.lock().unwrap();
                in_order &= a.is_some_and(|a| eventually(|| wait_registered_for_testing(a)));
            }
            *ordered.lock().unwrap() &= in_order;
            property.recompute(|value| value + 10);
        }
    });

    let (done, finished) = mpsc::channel();
    let b = thread::spawn({
        let (hub, done, thread_b) = (hub.clone(), done.clone(), thread_b.clone());
        move || {
            *thread_b.lock().unwrap() = Some(thread::current().id());
            hub.send(custom("start"));
            let _ = done.send("B");
        }
    });
    b_draining
        .recv_timeout(BOUND)
        .expect("B started to drain the hub");
    let a = thread::spawn({
        let (property, hub, thread_b, ordered) = (
            property.clone(),
            hub.clone(),
            thread_b.clone(),
            ordered.clone(),
        );
        let thread_a = thread_a.clone();
        move || {
            *thread_a.lock().unwrap() = Some(thread::current().id());
            property.recompute(|value| {
                let _ = in_transform.send(());
                if closing == Closing::HubSend {
                    let b = *thread_b.lock().unwrap();
                    let in_order = b.is_some_and(|b| eventually(|| wait_registered_for_testing(b)));
                    *ordered.lock().unwrap() &= in_order;
                }
                hub.send(custom("from-transform"));
                value + 1
            });
            let _ = done.send("A");
        }
    });
    for _ in 0..2 {
        finished
            .recv_timeout(BOUND)
            .expect("both threads return: the recompute gate deadlocked");
    }
    a.join().unwrap();
    b.join().unwrap();
    assert!(
        *ordered.lock().unwrap(),
        "the threads reached the intended order"
    );

    let published = published.lock().unwrap().clone();
    (property.value(), published)
}

#[test]
fn a_refused_recompute_gate_wait_runs_without_the_gate() {
    let (value, published) = recompute_cycle(Closing::GateWait);

    // B's transform ran while A held the gate and committed first, so A's
    // result, computed from a stale snapshot, is discarded.
    assert_eq!(value, 10);
    assert_eq!(published.last(), Some(&value));
}

#[test]
fn a_hub_send_refused_inside_a_transform_lets_the_waiting_recompute_run_next() {
    let (value, published) = recompute_cycle(Closing::HubSend);

    // A's send enqueued for drainer B, A committed, and B then recomputed
    // from A's result. A's own publication is skipped when B commits first.
    assert_eq!(value, 11);
    assert_eq!(published.last(), Some(&value));
}
