//! A token pager commit that waits for another thread's commit, or a pager
//! command that joins its worker, records the wait in the wait-for graph
//! (spec/03 §4.1, ADR-0172, ADR-0260). When the wait would close a cycle, the
//! call takes its refused-wait result instead of blocking.
//!
//! The threads are ordered by observed wait registrations, not by sleeps.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle, ThreadId};
use std::time::{Duration, Instant};

use vmx::{wait_registered_for_testing, Message, MessageHub, TokenPagedComposition};

/// The hang guard of every wait in this file.
const BOUND: Duration = Duration::from_secs(5);

/// The sender that thread B's hub message names. The pager's own messages
/// carry the pager's id, so the drainer's subscriber ignores them.
const DRAINER_SENDER: usize = 99;

type Pages = TokenPagedComposition<i32, u32>;

/// The pager call that the drainer thread B makes from its hub subscriber.
#[derive(Clone, Copy, Debug)]
enum Call {
    LoadMore,
    LoadNext,
    Refresh,
    Dispose,
}

/// Polls `condition` until it holds or the bound passes. Returns whether it
/// held, so a subscriber never panics inside the library.
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

fn drainer_message() -> Message {
    Message::Custom {
        sender_id: DRAINER_SENDER,
        sender_name: "drainer".to_string(),
        name: "drain".to_string(),
    }
}

fn call_from_drainer(pages: &Pages, call: Call) {
    match call {
        Call::LoadMore => pages.load_more(|_| (vec![2], Some(2))),
        Call::LoadNext => pages.load_next(),
        Call::Refresh => pages.refresh(),
        Call::Dispose => pages.dispose(),
    }
}

/// Thread B drains the hub, and its subscriber makes `call` while thread A
/// holds the pager's commit and publishes on that hub, which waits for B's
/// drain. Returns the pager's items afterwards.
fn call_from_the_drainer_during_a_commit(call: Call) -> Vec<i32> {
    let hub = MessageHub::new();
    let pages = Pages::with_loader_and_hub(None, |_| (vec![9], Some(9)), hub.clone());
    let deadline = Instant::now() + BOUND * 2;

    let a_thread = Slot::default();
    let draining = Arc::new(AtomicBool::new(false));
    let a_waited = Arc::new(Mutex::new(None::<bool>));
    let _drain = {
        let pages = pages.clone();
        let a_thread = a_thread.clone();
        let draining = Arc::clone(&draining);
        let a_waited = Arc::clone(&a_waited);
        hub.subscribe(move |message| {
            if message.sender_id() != DRAINER_SENDER {
                return;
            }
            draining.store(true, Ordering::SeqCst);
            // A's commit publishes on this hub, so A waits for this drain.
            let waits = eventually(|| a_thread.get().is_some_and(wait_registered_for_testing));
            if waits {
                call_from_drainer(&pages, call);
            }
            *a_waited.lock().unwrap() = Some(waits);
        })
    };

    let b = {
        let hub = hub.clone();
        thread::spawn(move || hub.send(drainer_message()))
    };
    let a = {
        let pages = pages.clone();
        let a_thread = a_thread.clone();
        let draining = Arc::clone(&draining);
        thread::spawn(move || {
            assert!(eventually(|| draining.load(Ordering::SeqCst)));
            a_thread.set(thread::current().id());
            pages.load_more(|_| (vec![1], Some(1)));
        })
    };

    join_by(b, deadline, "thread B (the drainer)");
    join_by(a, deadline, "thread A (the commit)");
    assert_eq!(
        a_waited.lock().unwrap().take(),
        Some(true),
        "A never waited for B's drain"
    );
    pages.items()
}

/// A `load_more` from the drainer whose commit wait closes a cycle is
/// refused: B's page is not committed, and the call returns.
#[test]
fn load_more_from_a_drainer_whose_commit_wait_closes_a_cycle_returns() {
    assert_eq!(
        call_from_the_drainer_during_a_commit(Call::LoadMore),
        vec![1]
    );
}

/// A `dispose` from the drainer whose wait closes a cycle is refused: the
/// dispose is requested, the commit ends the pager, and the call returns.
#[test]
fn dispose_from_a_drainer_whose_commit_wait_closes_a_cycle_returns() {
    assert_eq!(
        call_from_the_drainer_during_a_commit(Call::Dispose),
        vec![1]
    );
}

/// A `load_next` from the drainer returns. Its worker either waits for A's
/// commit and then commits its page, or is refused and commits nothing. The
/// order of those two checks decides which.
#[test]
fn load_next_from_a_drainer_whose_commit_wait_closes_a_cycle_returns() {
    let items = call_from_the_drainer_during_a_commit(Call::LoadNext);
    assert!(
        items == vec![1] || items == vec![1, 9],
        "unexpected items: {items:?}"
    );
}

/// A `refresh` from the drainer returns, as `load_next` does. The worker's
/// refresh either commits after A's commit or is refused.
#[test]
fn refresh_from_a_drainer_whose_commit_wait_closes_a_cycle_returns() {
    let items = call_from_the_drainer_during_a_commit(Call::Refresh);
    assert!(
        items == vec![1] || items == vec![9],
        "unexpected items: {items:?}"
    );
}

/// A load that waits for another thread's commit, with no cycle, records its
/// wait and still waits. Its page follows the committed one.
#[test]
fn a_load_without_a_cycle_waits_for_the_commit() {
    let hub = MessageHub::new();
    let pages = Pages::with_loader_and_hub(None, |_| (vec![9], Some(9)), hub.clone());
    let pages_id = pages.id();
    let deadline = Instant::now() + BOUND * 2;

    let b_thread = Slot::default();
    let b_waited = Arc::new(AtomicBool::new(false));
    let _hold = {
        let b_thread = b_thread.clone();
        let b_waited = Arc::clone(&b_waited);
        let gated = Arc::new(AtomicBool::new(false));
        hub.subscribe(move |message| {
            if message.sender_id() == pages_id && !gated.swap(true, Ordering::SeqCst) {
                // Hold A's commit until B records its wait for it.
                let waited = eventually(|| b_thread.get().is_some_and(wait_registered_for_testing));
                b_waited.store(waited, Ordering::SeqCst);
            }
        })
    };

    let a = {
        let pages = pages.clone();
        thread::spawn(move || pages.load_more(|_| (vec![1], Some(1))))
    };
    let b = {
        let pages = pages.clone();
        let b_thread = b_thread.clone();
        thread::spawn(move || {
            assert!(eventually(|| !pages.items().is_empty()));
            b_thread.set(thread::current().id());
            pages.load_more(|_| (vec![2], Some(2)));
        })
    };

    join_by(a, deadline, "thread A");
    join_by(b, deadline, "thread B");
    assert!(
        b_waited.load(Ordering::SeqCst),
        "B did not record its wait for A's commit"
    );
    assert_eq!(pages.items(), vec![1, 2]);
}
