//! A children materialization that waits for another thread's materialization
//! records the wait in the wait-for graph (spec/03 §4.1, ADR-0172, ADR-0260).
//! When the wait would close a cycle, the caller takes the overlap error that
//! a structural call takes while a materialization is active.
//!
//! The threads are ordered by observed wait registrations, not by sleeps.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle, ThreadId};
use std::time::{Duration, Instant};

use vmx::{wait_registered_for_testing, HierarchicalVm, Message, MessageHub};

/// The hang guard of every wait in this file.
const BOUND: Duration = Duration::from_secs(5);

type Node = HierarchicalVm<String>;

/// Polls `condition` until it holds or the bound passes. Returns whether it
/// held, so a factory or subscriber never panics inside the library.
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

/// A thread id that a test publishes once the thread runs.
#[derive(Clone, Default)]
struct Slot(Arc<Mutex<Option<ThreadId>>>);

impl Slot {
    fn set(&self, id: ThreadId) {
        *self.0.lock().unwrap() = Some(id);
    }

    fn get(&self) -> Option<ThreadId> {
        *self.0.lock().unwrap()
    }
}

fn custom(sender_id: usize) -> Message {
    Message::Custom {
        sender_id,
        sender_name: "materialization".to_string(),
        name: "drain".to_string(),
    }
}

/// Thread A drains the hub, and its subscriber calls `try_children` on the
/// node. Thread B materializes the node, and its factory sends on that hub,
/// which waits for A's drain. A's call would wait for B's materialization and
/// close the cycle, so A is refused and records the overlap error. B's
/// materialization still commits.
#[test]
fn try_children_from_a_drainer_whose_materialization_wait_closes_a_cycle_is_refused() {
    let hub = MessageHub::new();
    let factory_hub = hub.clone();
    let root = Node::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            // B's send waits for A's drain, the other half of the cycle.
            factory_hub.send(custom(2));
            Vec::new()
        },
        false,
        MessageHub::new(),
    );
    let deadline = Instant::now() + BOUND * 2;

    let a_thread = Slot::default();
    let b_thread = Slot::default();
    let draining = Arc::new(AtomicBool::new(false));
    let a_result = Arc::new(Mutex::new(None::<bool>));
    let _drain = {
        let root = root.clone();
        let b_thread = b_thread.clone();
        let draining = Arc::clone(&draining);
        let a_result = Arc::clone(&a_result);
        hub.subscribe(move |message| {
            if message.sender_id() != 1 {
                return;
            }
            draining.store(true, Ordering::SeqCst);
            let b_waits = eventually(|| b_thread.get().is_some_and(wait_registered_for_testing));
            let refused = b_waits && root.try_children().is_err();
            *a_result.lock().unwrap() = Some(refused);
        })
    };

    let a = {
        let hub = hub.clone();
        let a_thread = a_thread.clone();
        thread::spawn(move || {
            a_thread.set(thread::current().id());
            hub.send(custom(1));
        })
    };
    let b = {
        let root = root.clone();
        let b_thread = b_thread.clone();
        let draining = Arc::clone(&draining);
        thread::spawn(move || {
            assert!(eventually(|| draining.load(Ordering::SeqCst)));
            b_thread.set(thread::current().id());
            root.try_children().is_ok()
        })
    };

    join_by(a, deadline, "thread A (the drainer)");
    let b_committed = join_by(b, deadline, "thread B (the materialization)");
    assert_eq!(
        *a_result.lock().unwrap(),
        Some(true),
        "A's try_children was not refused, or B never waited for A's drain"
    );
    assert!(b_committed, "B's materialization did not commit");
    assert!(root.is_children_materialized());
}

/// A `try_children` that waits for another thread's materialization, with no
/// cycle, records its wait and still waits. It then returns the children
/// that the owner committed.
#[test]
fn try_children_without_a_cycle_waits_for_the_materialization() {
    let a_thread = Slot::default();
    let factory_running = Arc::new(AtomicBool::new(false));
    let a_waited = Arc::new(AtomicBool::new(false));
    let root = {
        let factory_running = Arc::clone(&factory_running);
        let a_waited = Arc::clone(&a_waited);
        let a_thread = a_thread.clone();
        Node::with_children_factory(
            "root",
            "root".to_string(),
            move |_| {
                factory_running.store(true, Ordering::SeqCst);
                // Hold B's materialization until A records its wait for it.
                let waited = eventually(|| a_thread.get().is_some_and(wait_registered_for_testing));
                a_waited.store(waited, Ordering::SeqCst);
                Vec::new()
            },
            false,
            MessageHub::new(),
        )
    };
    let deadline = Instant::now() + BOUND * 2;

    let b = {
        let root = root.clone();
        thread::spawn(move || root.try_children().is_ok())
    };
    let a = {
        let root = root.clone();
        let a_thread = a_thread.clone();
        let factory_running = Arc::clone(&factory_running);
        thread::spawn(move || {
            assert!(eventually(|| factory_running.load(Ordering::SeqCst)));
            a_thread.set(thread::current().id());
            root.try_children().is_ok()
        })
    };

    assert!(join_by(b, deadline, "thread B (the materialization)"));
    assert!(join_by(a, deadline, "thread A (the waiter)"));
    assert!(
        a_waited.load(Ordering::SeqCst),
        "A did not record its wait for B's materialization"
    );
}
