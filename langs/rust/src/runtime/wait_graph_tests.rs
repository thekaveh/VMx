//! One wait-for graph: hub and hook-owner waits release their edges before
//! they wake the waiter, borrowed hub scopes are wait-for owners, and a
//! borrower's own hub calls do not wait (spec/03 §4.1, §4.2, spec/02 §2.4,
//! ADR-0172, #1180, #1183).
//!
//! A stale edge lives only between an owner's release and the waiter's own
//! cleanup. These tests hold the woken waiter there through the `wake_hold`
//! seam, and the forced borrowed scope of `borrow_for_testing` reaches the
//! borrower states directly. An integration test can reach neither.

use super::wake_hold;
use crate::wait_for_graph::wait_registered_for_testing;
use crate::{ComponentVm, ConstructionStatus, Message, MessageHub, VmxError};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread::{self, JoinHandle, ThreadId};
use std::time::{Duration, Instant};

const BOUND: Duration = Duration::from_secs(5);

fn custom(name: &str) -> Message {
    Message::Custom {
        sender_id: 1,
        sender_name: "test".into(),
        name: name.into(),
    }
}

fn name_of(message: &Message) -> String {
    match message {
        Message::Custom { name, .. } => name.clone(),
        _ => String::new(),
    }
}

/// Polls `condition` until it holds or `bound` passes. Returns whether it held.
fn eventually(bound: Duration, condition: impl Fn() -> bool) -> bool {
    let deadline = Instant::now() + bound;
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

/// Records the names of the custom messages a hub delivers, with the thread
/// that delivered each.
type Seen = Arc<Mutex<Vec<(String, ThreadId)>>>;

fn deliveries(hub: &MessageHub) -> (Seen, super::Subscription) {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&seen);
    let subscription = hub.subscribe(move |message| {
        sink.lock()
            .unwrap()
            .push((name_of(message), thread::current().id()));
    });
    (seen, subscription)
}

fn count(seen: &Mutex<Vec<(String, ThreadId)>>, name: &str) -> usize {
    seen.lock()
        .unwrap()
        .iter()
        .filter(|(seen, _)| seen == name)
        .count()
}

#[derive(Clone, Copy, Debug)]
enum HubOp {
    Send,
    NestedBatch,
    Dispose,
}

impl HubOp {
    const ALL: [HubOp; 3] = [HubOp::Send, HubOp::NestedBatch, HubOp::Dispose];

    fn run(self, hub: &MessageHub, name: &str) {
        match self {
            HubOp::Send => hub.send(custom(name)),
            HubOp::NestedBatch => hub.batch(|| hub.send(custom(name))),
            HubOp::Dispose => hub.dispose(),
        }
    }
}

/// #1180 — Q's wait on `h2` ends when P's `h2` batch ends. Q is held after it
/// wakes, before its own cleanup, until P's `h.batch` has decided. P's batch
/// must wait for Q's step-2 work on `h` and own the batch, not borrow it.
///
/// Reproduction 1: Q drains `h`, and the `q0` subscriber sends on `h2`.
/// Reproduction 2: Q holds an `h` batch whose body sends on `h2`.
fn a_released_hub_wait_does_not_let_a_batch_borrow(q_holds_batch: bool, op: HubOp) {
    let h = MessageHub::new();
    let h2 = MessageHub::new();
    let q_work_done = Arc::new(AtomicBool::new(false));
    let (seen, _seen) = deliveries(&h);
    let _q0 = h.subscribe({
        let (h2, q_work_done) = (h2.clone(), Arc::clone(&q_work_done));
        move |message| {
            if name_of(message) == "q0" {
                h2.send(custom("q1"));
                q_work_done.store(true, Ordering::SeqCst);
            }
        }
    });

    let p_in_h2 = Arc::new(AtomicBool::new(false));
    let q = thread::spawn({
        let (h, h2, q_work_done) = (h.clone(), h2.clone(), Arc::clone(&q_work_done));
        let p_in_h2 = Arc::clone(&p_in_h2);
        move || {
            // Step 2 starts once P holds the h2 batch (step 1).
            assert!(eventually(BOUND, || p_in_h2.load(Ordering::SeqCst)));
            if q_holds_batch {
                h.batch(|| {
                    h2.send(custom("q1"));
                    q_work_done.store(true, Ordering::SeqCst);
                });
            } else {
                h.send(custom("q0"));
            }
        }
    });
    let q_id = q.thread().id();
    let p_body_started = Arc::new(AtomicBool::new(false));
    let body_saw_q_done = Arc::new(AtomicBool::new(false));
    let p = thread::spawn({
        let (h, h2) = (h.clone(), h2.clone());
        let (p_body_started, body_saw_q_done) =
            (Arc::clone(&p_body_started), Arc::clone(&body_saw_q_done));
        let q_work_done = Arc::clone(&q_work_done);
        move || {
            let p_id = thread::current().id();
            h2.batch(|| {
                p_in_h2.store(true, Ordering::SeqCst);
                assert!(
                    eventually(BOUND, || wait_registered_for_testing(q_id)),
                    "Q never waited for P's h2 batch"
                );
                let p_body_started = Arc::clone(&p_body_started);
                wake_hold::arm(q_id, move || {
                    // Hold Q until P's h.batch has decided: it waits, or its
                    // body runs.
                    eventually(BOUND, || {
                        wait_registered_for_testing(p_id) || p_body_started.load(Ordering::SeqCst)
                    });
                });
            });
            h.batch(|| {
                body_saw_q_done.store(q_work_done.load(Ordering::SeqCst), Ordering::SeqCst);
                p_body_started.store(true, Ordering::SeqCst);
                op.run(&h, "p1");
            });
        }
    });
    let deadline = Instant::now() + BOUND;
    join_by(p, deadline, "P");
    join_by(q, deadline, "Q");

    assert!(
        body_saw_q_done.load(Ordering::SeqCst),
        "P's h.batch borrowed h on a cycle that had ended ({op:?})"
    );
    match op {
        HubOp::Send | HubOp::NestedBatch => assert_eq!(count(&seen, "p1"), 1),
        HubOp::Dispose => {
            h.send(custom("after"));
            assert_eq!(count(&seen, "after"), 0);
        }
    }
}

#[test]
fn a_released_drain_wait_does_not_let_a_batch_borrow() {
    for op in HubOp::ALL {
        a_released_hub_wait_does_not_let_a_batch_borrow(false, op);
    }
}

#[test]
fn a_released_batch_wait_does_not_let_a_batch_borrow() {
    for op in HubOp::ALL {
        a_released_hub_wait_does_not_let_a_batch_borrow(true, op);
    }
}

/// #1180 — a borrower's own `send`, nested `batch` and `dispose` on the hub it
/// borrowed do not wait, and the last borrowed scope's exit delivers each
/// message once (spec/03 §4.2 rule 3). The hub has no batch or drain owner.
#[test]
fn a_borrowers_own_calls_do_not_wait_without_an_owner() {
    for op in HubOp::ALL {
        let h = MessageHub::new();
        let (seen, _seen) = deliveries(&h);
        let p = thread::spawn({
            let h = h.clone();
            move || {
                h.borrow_for_testing(|| {
                    op.run(&h, "p1");
                    h.send(custom("p2"));
                });
            }
        });
        join_by(p, Instant::now() + BOUND, "the borrower");

        match op {
            HubOp::Send | HubOp::NestedBatch => {
                let names = seen
                    .lock()
                    .unwrap()
                    .iter()
                    .map(|(name, _)| name.clone())
                    .collect::<Vec<_>>();
                assert_eq!(names, ["p1", "p2"], "{op:?}");
            }
            HubOp::Dispose => {
                h.send(custom("after"));
                assert!(seen.lock().unwrap().is_empty(), "{op:?}");
            }
        }
    }
}

/// #1180 — while Q drains `h` with a queued message, P's own calls in its
/// borrowed scope do not wait, whether Q waits for the borrow before or after
/// P's call. Q delivers the queue after the scope exits, in FIFO order.
fn a_borrowers_own_calls_do_not_wait_for_a_waiting_drainer(drainer_waits_first: bool, op: HubOp) {
    let h = MessageHub::new();
    let (seen, _seen) = deliveries(&h);
    let borrowed = Arc::new(AtomicBool::new(false));
    let p_op_done = Arc::new(AtomicBool::new(false));
    let q_ready = Arc::new(AtomicBool::new(false));
    let _m1 = h.subscribe({
        let h = h.clone();
        let (borrowed, p_op_done) = (Arc::clone(&borrowed), Arc::clone(&p_op_done));
        let q_ready = Arc::clone(&q_ready);
        move |message| {
            if name_of(message) == "m1" {
                h.send(custom("m2"));
                q_ready.store(true, Ordering::SeqCst);
                eventually(BOUND, || borrowed.load(Ordering::SeqCst));
                if !drainer_waits_first {
                    eventually(BOUND, || p_op_done.load(Ordering::SeqCst));
                }
            }
        }
    });
    let q = thread::spawn({
        let h = h.clone();
        move || h.send(custom("m1"))
    });
    let q_id = q.thread().id();
    let p = thread::spawn({
        let h = h.clone();
        move || {
            // Borrow only once Q drains h with m2 queued.
            assert!(eventually(BOUND, || q_ready.load(Ordering::SeqCst)));
            h.borrow_for_testing(|| {
                borrowed.store(true, Ordering::SeqCst);
                if drainer_waits_first {
                    assert!(
                        eventually(BOUND, || wait_registered_for_testing(q_id)),
                        "Q never waited for the borrowed scope"
                    );
                }
                op.run(&h, "p1");
                p_op_done.store(true, Ordering::SeqCst);
                if !drainer_waits_first {
                    assert!(
                        eventually(BOUND, || wait_registered_for_testing(q_id)),
                        "Q never waited for the borrowed scope"
                    );
                }
            });
        }
    });
    let deadline = Instant::now() + BOUND;
    join_by(p, deadline, "the borrower");
    join_by(q, deadline, "the drainer");

    let names = seen
        .lock()
        .unwrap()
        .iter()
        .map(|(name, _)| name.clone())
        .collect::<Vec<_>>();
    match op {
        HubOp::Send | HubOp::NestedBatch => {
            assert_eq!(names, ["m1", "m2", "p1"], "{op:?}");
        }
        HubOp::Dispose => {
            // Disposal drops the queued message (HUB-012).
            assert_eq!(names, ["m1"], "{op:?}");
            h.send(custom("after"));
            assert_eq!(count(&seen, "after"), 0);
        }
    }
}

#[test]
fn a_borrowers_own_calls_do_not_wait_for_a_drainer_that_waits_first() {
    for op in HubOp::ALL {
        a_borrowers_own_calls_do_not_wait_for_a_waiting_drainer(true, op);
    }
}

#[test]
fn a_borrowers_own_calls_do_not_wait_for_a_drainer_that_waits_later() {
    for op in HubOp::ALL {
        a_borrowers_own_calls_do_not_wait_for_a_waiting_drainer(false, op);
    }
}

/// spec/03 §4.2 rule 2 — a drainer whose queue is empty does not wait for a
/// borrowed scope. It releases the drain, and the scope's exit drains what the
/// body enqueued.
#[test]
fn a_drainer_with_an_empty_queue_releases_the_drain_to_the_borrowed_scope() {
    let h = MessageHub::new();
    let (seen, _seen) = deliveries(&h);
    let borrowed = Arc::new(AtomicBool::new(false));
    let q_returned = Arc::new(AtomicBool::new(false));
    let q_ready = Arc::new(AtomicBool::new(false));
    let _m1 = h.subscribe({
        let (borrowed, q_ready) = (Arc::clone(&borrowed), Arc::clone(&q_ready));
        move |message| {
            if name_of(message) == "m1" {
                q_ready.store(true, Ordering::SeqCst);
                eventually(BOUND, || borrowed.load(Ordering::SeqCst));
            }
        }
    });
    let q = thread::spawn({
        let (h, q_returned) = (h.clone(), Arc::clone(&q_returned));
        move || {
            h.send(custom("m1"));
            q_returned.store(true, Ordering::SeqCst);
        }
    });
    let p = thread::spawn({
        let (h, q_returned) = (h.clone(), Arc::clone(&q_returned));
        move || {
            assert!(eventually(BOUND, || q_ready.load(Ordering::SeqCst)));
            h.borrow_for_testing(|| {
                borrowed.store(true, Ordering::SeqCst);
                assert!(
                    eventually(BOUND, || q_returned.load(Ordering::SeqCst)),
                    "the drainer waited for the borrowed scope with an empty queue"
                );
                h.send(custom("p1"));
            });
            thread::current().id()
        }
    });
    let deadline = Instant::now() + BOUND;
    let p_id = join_by(p, deadline, "the borrower");
    join_by(q, deadline, "the drainer");

    let seen = seen.lock().unwrap().clone();
    assert_eq!(seen.len(), 2);
    assert_eq!(seen[1], ("p1".to_string(), p_id));
}

/// spec/03 §4.2 rule 5 — a drainer with queued messages waits for a borrowed
/// scope. When the borrower already waits for the drainer, the drainer's wait
/// is refused, and it releases the drain: its outermost send returns, and the
/// last borrowed scope's exit delivers the queue in FIFO order on the
/// borrower's thread. When the drainer waits first, the borrower's wait is
/// refused instead.
fn a_cyclic_drainer_wait_hands_the_queue_to_the_borrower(borrower_waits_first: bool) {
    let h = MessageHub::new();
    let h4 = MessageHub::new();
    let (seen, _seen) = deliveries(&h);
    let (seen4, _seen4) = deliveries(&h4);
    let borrowed = Arc::new(AtomicBool::new(false));
    let q_send_returned = Arc::new(AtomicBool::new(false));
    let q_slot: Arc<Mutex<Option<ThreadId>>> = Arc::default();
    let p_slot: Arc<Mutex<Option<ThreadId>>> = Arc::default();
    let q_ready = Arc::new(AtomicBool::new(false));
    let _m1 = h.subscribe({
        let h = h.clone();
        let borrowed = Arc::clone(&borrowed);
        let (p_slot, q_ready) = (Arc::clone(&p_slot), Arc::clone(&q_ready));
        move |message| {
            if name_of(message) == "m1" {
                h.send(custom("m2"));
                q_ready.store(true, Ordering::SeqCst);
                eventually(BOUND, || borrowed.load(Ordering::SeqCst));
                if borrower_waits_first {
                    let p_id = p_slot.lock().unwrap().expect("P recorded");
                    eventually(BOUND, || wait_registered_for_testing(p_id));
                }
            }
        }
    });
    let q = thread::spawn({
        let (h, h4) = (h.clone(), h4.clone());
        let q_send_returned = Arc::clone(&q_send_returned);
        move || {
            h4.batch(|| {
                h.send(custom("m1"));
                q_send_returned.store(true, Ordering::SeqCst);
            });
        }
    });
    *q_slot.lock().unwrap() = Some(q.thread().id());
    let p = thread::spawn({
        let (h, h4) = (h.clone(), h4.clone());
        let q_slot = Arc::clone(&q_slot);
        move || {
            *p_slot.lock().unwrap() = Some(thread::current().id());
            assert!(eventually(BOUND, || q_ready.load(Ordering::SeqCst)));
            h.borrow_for_testing(|| {
                borrowed.store(true, Ordering::SeqCst);
                let q_id = q_slot.lock().unwrap().expect("Q recorded");
                if !borrower_waits_first {
                    assert!(
                        eventually(BOUND, || wait_registered_for_testing(q_id)),
                        "the drainer never waited for the borrowed scope"
                    );
                }
                // Waits for Q's h4 batch, unless that wait closes the cycle.
                h4.send(custom("p4"));
            });
            thread::current().id()
        }
    });
    let deadline = Instant::now() + BOUND;
    let p_id = join_by(p, deadline, "the borrower");
    let q_id = join_by_id(q, deadline);

    let names = seen
        .lock()
        .unwrap()
        .iter()
        .map(|(name, _)| name.clone())
        .collect::<Vec<_>>();
    assert_eq!(names, ["m1", "m2"]);
    assert_eq!(count(&seen4, "p4"), 1);
    let m2_thread = seen.lock().unwrap()[1].1;
    if borrower_waits_first {
        // The drainer released the drain; the borrower delivered m2.
        assert_eq!(m2_thread, p_id);
    } else {
        assert_eq!(m2_thread, q_id);
    }
    assert!(q_send_returned.load(Ordering::SeqCst));
}

fn join_by_id(handle: JoinHandle<()>, deadline: Instant) -> ThreadId {
    let id = handle.thread().id();
    join_by(handle, deadline, "the drainer");
    id
}

#[test]
fn a_cyclic_drainer_wait_releases_the_drain_to_the_borrower() {
    a_cyclic_drainer_wait_hands_the_queue_to_the_borrower(true);
}

#[test]
fn a_cyclic_borrower_wait_lets_the_drainer_deliver_after_the_scope() {
    a_cyclic_drainer_wait_hands_the_queue_to_the_borrower(false);
}

/// HUB-013, spec/03 §4.2 rule 4 — a send from inside an unrelated hub
/// callback waits for an open borrowed scope and delivers before it returns.
/// Being inside a callback is no escape.
#[test]
fn a_callback_send_waits_for_a_borrowed_scope_and_delivers_synchronously() {
    let h = MessageHub::new();
    let x = MessageHub::new();
    let (seen, _seen) = deliveries(&h);
    let delivered_before_return = Arc::new(Mutex::new(None));
    let _x0 = x.subscribe({
        let (h, seen) = (h.clone(), Arc::clone(&seen));
        let delivered_before_return = Arc::clone(&delivered_before_return);
        move |_| {
            h.send(custom("r"));
            *delivered_before_return.lock().unwrap() = Some(count(&seen, "r"));
        }
    });
    let (borrowed_tx, borrowed_rx) = mpsc::channel();
    let r_slot: Arc<Mutex<Option<ThreadId>>> = Arc::default();
    let p = thread::spawn({
        let (h, r_slot) = (h.clone(), Arc::clone(&r_slot));
        move || {
            h.borrow_for_testing(|| {
                borrowed_tx.send(()).unwrap();
                // A send that escapes returns at once and never waits.
                eventually(Duration::from_secs(1), || {
                    r_slot
                        .lock()
                        .unwrap()
                        .is_some_and(wait_registered_for_testing)
                });
            });
        }
    });
    borrowed_rx.recv_timeout(BOUND).unwrap();
    let r = thread::spawn({
        let x = x.clone();
        move || x.send(custom("x0"))
    });
    *r_slot.lock().unwrap() = Some(r.thread().id());
    let deadline = Instant::now() + BOUND;
    join_by(p, deadline, "the borrower");
    join_by(r, deadline, "the callback sender");

    assert_eq!(*delivered_before_return.lock().unwrap(), Some(1));
}

/// #1183 form 1 — Q's foreign `a.dispose()` waits for P's hook on `a`. P's
/// hook returns, and Q is held after it wakes, before its own cleanup, until
/// P's `b.dispose()` has decided. The edge Q→P was removed before Q woke, so
/// P's `b.dispose()` waits for `b`'s hook on Q instead of deferring to it.
fn a_released_hook_wait_does_not_defer_a_disposal(failing_dispose_hook: bool) {
    let a = ComponentVm::new("a");
    let b = ComponentVm::new("b");
    let p_in_a_hook = Arc::new(AtomicBool::new(false));
    let b_hook_returned = Arc::new(AtomicBool::new(false));
    let p_dispose_returned = Arc::new(AtomicBool::new(false));
    let dispose_hook_runs: Arc<Mutex<Vec<(ThreadId, bool)>>> = Arc::default();
    let q_slot: Arc<Mutex<Option<ThreadId>>> = Arc::default();
    b.on_dispose({
        let (runs, b_hook_returned) =
            (Arc::clone(&dispose_hook_runs), Arc::clone(&b_hook_returned));
        move || {
            runs.lock().unwrap().push((
                thread::current().id(),
                b_hook_returned.load(Ordering::SeqCst),
            ));
            if failing_dispose_hook {
                Err(VmxError::Other("b cleanup failure".into()))
            } else {
                Ok(())
            }
        }
    });
    b.on_construct({
        let (a, p_in_a_hook) = (a.clone(), Arc::clone(&p_in_a_hook));
        let b_hook_returned = Arc::clone(&b_hook_returned);
        move || {
            eventually(BOUND, || p_in_a_hook.load(Ordering::SeqCst));
            a.dispose()?;
            thread::sleep(Duration::from_millis(300));
            b_hook_returned.store(true, Ordering::SeqCst);
            Ok(())
        }
    });
    a.on_construct({
        let (q_slot, p_in_a_hook) = (Arc::clone(&q_slot), Arc::clone(&p_in_a_hook));
        let p_dispose_returned = Arc::clone(&p_dispose_returned);
        move || {
            p_in_a_hook.store(true, Ordering::SeqCst);
            let q_id = loop {
                if let Some(q_id) = *q_slot.lock().unwrap() {
                    break q_id;
                }
                thread::yield_now();
            };
            if !eventually(BOUND, || wait_registered_for_testing(q_id)) {
                return Err(VmxError::Other("Q never waited for a's hook".into()));
            }
            let p_id = thread::current().id();
            let p_dispose_returned = Arc::clone(&p_dispose_returned);
            wake_hold::arm(q_id, move || {
                eventually(BOUND, || {
                    wait_registered_for_testing(p_id) || p_dispose_returned.load(Ordering::SeqCst)
                });
            });
            Ok(())
        }
    });

    let q = thread::spawn({
        let b = b.clone();
        move || b.construct()
    });
    *q_slot.lock().unwrap() = Some(q.thread().id());
    let p = thread::spawn({
        let (a, b) = (a.clone(), b.clone());
        move || {
            let _ = a.construct();
            let result = b.dispose();
            p_dispose_returned.store(true, Ordering::SeqCst);
            (thread::current().id(), result)
        }
    });
    let deadline = Instant::now() + BOUND;
    let (p_id, p_result) = join_by(p, deadline, "P");
    let q_result = join_by(q, deadline, "Q");

    assert_eq!(
        *dispose_hook_runs.lock().unwrap(),
        vec![(p_id, true)],
        "b's dispose hook must run once, on P, after b's construct hook"
    );
    if failing_dispose_hook {
        assert_eq!(p_result, Err(VmxError::Other("b cleanup failure".into())));
    } else {
        assert_eq!(p_result, Ok(()));
    }
    assert_eq!(q_result, Ok(()));
    assert_eq!(a.status(), ConstructionStatus::Disposed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);
}

#[test]
fn a_released_hook_wait_does_not_defer_a_disposal_with_an_ok_hook() {
    a_released_hook_wait_does_not_defer_a_disposal(false);
}

#[test]
fn a_released_hook_wait_does_not_defer_a_disposal_with_a_failing_hook() {
    a_released_hook_wait_does_not_defer_a_disposal(true);
}

/// #1183 real-cycle control — P disposes `b` from inside `a`'s hook while Q's
/// `a.dispose()` waits for that hook. P still holds `a`'s hook lease, so the
/// cycle is live: P's disposal defers `b`'s terminal cleanup to `b`'s hook.
#[test]
fn a_live_hook_cycle_still_defers_the_disposal() {
    let a = ComponentVm::new("a");
    let b = ComponentVm::new("b");
    let p_in_a_hook = Arc::new(AtomicBool::new(false));
    let dispose_hook_runs = Arc::new(AtomicUsize::new(0));
    let q_slot: Arc<Mutex<Option<ThreadId>>> = Arc::default();
    b.on_dispose({
        let runs = Arc::clone(&dispose_hook_runs);
        move || {
            runs.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    });
    b.on_construct({
        let (a, p_in_a_hook) = (a.clone(), Arc::clone(&p_in_a_hook));
        move || {
            eventually(BOUND, || p_in_a_hook.load(Ordering::SeqCst));
            a.dispose()
        }
    });
    a.on_construct({
        let (b, q_slot, p_in_a_hook) = (b.clone(), Arc::clone(&q_slot), Arc::clone(&p_in_a_hook));
        move || {
            p_in_a_hook.store(true, Ordering::SeqCst);
            let q_id = loop {
                if let Some(q_id) = *q_slot.lock().unwrap() {
                    break q_id;
                }
                thread::yield_now();
            };
            if !eventually(BOUND, || wait_registered_for_testing(q_id)) {
                return Err(VmxError::Other("Q never waited for a's hook".into()));
            }
            b.dispose()
        }
    });

    let q = thread::spawn({
        let b = b.clone();
        move || b.construct()
    });
    *q_slot.lock().unwrap() = Some(q.thread().id());
    let p = thread::spawn({
        let a = a.clone();
        move || a.construct()
    });
    let deadline = Instant::now() + BOUND;
    let _ = join_by(p, deadline, "P");
    let _ = join_by(q, deadline, "Q");

    assert_eq!(a.status(), ConstructionStatus::Disposed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);
    assert_eq!(dispose_hook_runs.load(Ordering::SeqCst), 1);
}
