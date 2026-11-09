//! An `ObservableMultiDictionary` mutation that waits for another thread's
//! delivery records the wait in the wait-for graph (spec/03 §4.1, ADR-0172,
//! ADR-0208). When the wait would close a cycle, the mutation does not wait:
//! it commits and queues its change for the delivering thread, which delivers
//! it in commit order.
//!
//! The threads are ordered by observed wait registrations, not by sleeps.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle, ThreadId};
use std::time::{Duration, Instant};

use vmx::{
    wait_registered_for_testing, CollectionChangeAction, Message, MessageHub,
    ObservableMultiDictionary,
};

type Dictionary = ObservableMultiDictionary<u32, u32, u32>;
type Change = (CollectionChangeAction, Option<usize>);

/// The hang guard of every wait in this file.
const BOUND: Duration = Duration::from_secs(5);

fn changes(stream: &MessageHub) -> (Arc<Mutex<Vec<Change>>>, vmx::Subscription) {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&seen);
    let subscription = stream.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            sink.lock()
                .unwrap()
                .push((change.action.clone(), change.new_index));
        }
    });
    (seen, subscription)
}

/// Polls `condition` until it holds or the bound passes. Returns whether it
/// held, so a batch body never panics inside the library.
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

/// Thread A inserts, and its hub message waits for thread B's open hub batch.
/// Inside that batch, thread B inserts into the same dictionary. B's wait for
/// A's delivery would close the cycle, so B commits and queues its change,
/// and its batch ends. A then delivers both changes in commit order.
#[test]
fn a_mutation_whose_delivery_wait_closes_a_cycle_queues_its_change() {
    let hub = MessageHub::new();
    let dictionary = Dictionary::with_hub(1, hub.clone());
    let (local, _local) = changes(&dictionary.collection_changed());
    let (published, _hub) = changes(&hub);
    let deadline = Instant::now() + BOUND * 2;

    let a_thread = Slot::default();
    let batch_open = Arc::new(AtomicBool::new(false));

    let b = {
        let hub = hub.clone();
        let dictionary = dictionary.clone();
        let a_thread = a_thread.clone();
        let batch_open = Arc::clone(&batch_open);
        thread::spawn(move || {
            hub.batch(|| {
                batch_open.store(true, Ordering::SeqCst);
                // A's hub message waits for this batch.
                let a_waits =
                    eventually(|| a_thread.get().is_some_and(wait_registered_for_testing));
                if a_waits {
                    dictionary.insert(2, 2, 20);
                }
                a_waits
            })
        })
    };

    let a = {
        let dictionary = dictionary.clone();
        let a_thread = a_thread.clone();
        let batch_open = Arc::clone(&batch_open);
        thread::spawn(move || {
            assert!(eventually(|| batch_open.load(Ordering::SeqCst)));
            a_thread.set(thread::current().id());
            dictionary.insert(1, 1, 10);
        })
    };

    assert!(
        join_by(b, deadline, "thread B"),
        "A never waited for B's batch"
    );
    join_by(a, deadline, "thread A");

    let expected = vec![
        (CollectionChangeAction::Add, Some(0)),
        (CollectionChangeAction::Add, Some(1)),
    ];
    assert_eq!(*local.lock().unwrap(), expected);
    assert_eq!(*published.lock().unwrap(), expected);
    assert_eq!(dictionary.entries(), vec![(1, 1, 10), (2, 2, 20)]);
    assert_eq!(dictionary.keys1().to_vec(), vec![1, 2]);
    assert_eq!(dictionary.keys2().to_vec(), vec![1, 2]);
}

/// A mutation that waits for another thread's delivery, with no cycle,
/// records its wait and still waits, and its change follows the delivered one.
#[test]
fn a_mutation_without_a_cycle_waits_for_the_delivery() {
    let dictionary = Dictionary::new(1);
    let (local, _local) = changes(&dictionary.collection_changed());
    let deadline = Instant::now() + BOUND * 2;

    let b_thread = Slot::default();
    let release = Arc::new(AtomicBool::new(false));
    let _hold = {
        let b_thread = b_thread.clone();
        let release = Arc::clone(&release);
        dictionary.collection_changed().subscribe(move |message| {
            if matches!(message, Message::CollectionChanged(change)
                if change.new_index == Some(0))
            {
                // Hold the delivery until B records its wait for it.
                let waited = eventually(|| b_thread.get().is_some_and(wait_registered_for_testing));
                release.store(waited, Ordering::SeqCst);
            }
        })
    };

    let a = {
        let dictionary = dictionary.clone();
        thread::spawn(move || dictionary.insert(1, 1, 10))
    };
    let b = {
        let dictionary = dictionary.clone();
        let b_thread = b_thread.clone();
        let release = Arc::clone(&release);
        thread::spawn(move || {
            assert!(eventually(|| !dictionary.entries().is_empty()));
            b_thread.set(thread::current().id());
            dictionary.insert(2, 2, 20);
            release.load(Ordering::SeqCst)
        })
    };

    join_by(a, deadline, "thread A");
    assert!(
        join_by(b, deadline, "thread B"),
        "B did not record its wait for A's delivery"
    );
    assert_eq!(
        *local.lock().unwrap(),
        vec![
            (CollectionChangeAction::Add, Some(0)),
            (CollectionChangeAction::Add, Some(1)),
        ]
    );
    assert_eq!(dictionary.keys1().to_vec(), vec![1, 2]);
}
