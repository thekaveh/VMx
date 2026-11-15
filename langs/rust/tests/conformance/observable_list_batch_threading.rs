//! Threaded tests for the `ObservableList` batch state (#1924).
//!
//! A batch's depth, dirty flag and start count change under one lock, so a
//! change that marks an open batch dirty is never lost to a concurrent close.
//! Each test pauses one thread at a seam with a test-only probe. A probe that
//! waits on another thread waits no longer than [`PROBE_WAIT`], so the test
//! reports the outcome instead of hanging.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use super::bounded_wait::within_timeout;
use vmx::{CollectionChangeAction, Message, MessageHub, MessageRecorder, ObservableList};

/// The bound on each wait by a test thread.
const BOUND: Duration = Duration::from_secs(5);

/// The release sender and the thread of a second batch that a probe starts.
type SecondBatch = (Sender<()>, JoinHandle<()>);

/// The bound on each wait inside a probe. Under the fix, a probe's wait
/// times out, because the other thread blocks on the batch lock that the
/// probe holds.
const PROBE_WAIT: Duration = Duration::from_millis(200);

fn collection_actions(recorder: &MessageRecorder) -> Vec<CollectionChangeAction> {
    recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) => Some(change.action),
            _ => None,
        })
        .collect()
}

fn count_notifications(recorder: &MessageRecorder) -> usize {
    recorder
        .messages()
        .into_iter()
        .filter(|message| {
            matches!(
                message,
                Message::PropertyChanged(change) if change.property_name == "Count"
            )
        })
        .count()
}

/// Opens a batch on a worker thread, pauses the push on the test thread
/// between the batch-open check and the dirty write, and lets the worker's
/// batch close inside that pause. Returns once the push and the worker finish.
fn push_while_batch_closes(list: &ObservableList<&'static str>) {
    let (opened_tx, opened_rx) = mpsc::channel::<()>();
    let (release_tx, release_rx) = mpsc::channel::<()>();
    let (finished_tx, finished_rx) = mpsc::channel::<()>();
    let worker_list = list.clone();
    let worker = thread::spawn(move || {
        worker_list.batch_update(move || {
            let _ = opened_tx.send(());
            let _ = release_rx.recv();
        });
        let _ = finished_tx.send(());
    });
    opened_rx
        .recv_timeout(BOUND)
        .expect("the worker's batch never opened");

    let release_tx = Mutex::new(release_tx);
    let finished_rx = Mutex::new(finished_rx);
    let fired = AtomicBool::new(false);
    list.set_batch_publish_probe_for_testing(move || {
        if fired.swap(true, Ordering::AcqRel) {
            return;
        }
        let _ = release_tx.lock().unwrap().send(());
        // Before the fix the worker finishes here. After it, the worker
        // blocks on the batch lock that this probe holds, so the wait times out.
        let _ = finished_rx.lock().unwrap().recv_timeout(PROBE_WAIT);
    });

    list.push("a");
    worker.join().expect("the worker batch panicked");
}

#[test]
fn close_inside_publish_gap_delivers_exactly_one_reset() {
    within_timeout("a batch close inside the publish gap", BOUND, || {
        let hub = MessageHub::new();
        let recorder = hub.record(1024);
        let list = ObservableList::with_hub(1, hub.clone());
        let local_resets = Arc::new(AtomicUsize::new(0));
        let counted = local_resets.clone();
        let _reset = list.reset().subscribe(move |()| {
            counted.fetch_add(1, Ordering::SeqCst);
        });

        push_while_batch_closes(&list);

        assert_eq!(
            local_resets.load(Ordering::SeqCst),
            1,
            "the local stream should receive exactly one Reset"
        );
        assert_eq!(
            collection_actions(&recorder),
            vec![CollectionChangeAction::Reset],
            "the hub should receive exactly one Reset"
        );
    });
}

#[test]
fn batch_with_no_change_after_a_publish_gap_close_publishes_nothing() {
    within_timeout("an empty batch after the publish gap", BOUND, || {
        let hub = MessageHub::new();
        let recorder = hub.record(1024);
        let list = ObservableList::with_hub(1, hub.clone());
        let local_resets = Arc::new(AtomicUsize::new(0));
        let counted = local_resets.clone();
        let _reset = list.reset().subscribe(move |()| {
            counted.fetch_add(1, Ordering::SeqCst);
        });

        push_while_batch_closes(&list);
        let hub_before = recorder.messages().len();
        let local_before = local_resets.load(Ordering::SeqCst);

        list.batch_update(|| {});

        assert_eq!(
            recorder.messages().len(),
            hub_before,
            "an empty batch should send no hub message"
        );
        assert_eq!(
            local_resets.load(Ordering::SeqCst),
            local_before,
            "an empty batch should send no local Reset"
        );
    });
}

#[test]
fn count_change_survives_a_close_that_races_another_batch_open() {
    within_timeout("a count-changing close beside another batch", BOUND, || {
        let hub = MessageHub::new();
        let recorder = hub.record(1024);
        let list = ObservableList::with_hub(1, hub.clone());
        let local_counts = Arc::new(AtomicUsize::new(0));
        let counted = local_counts.clone();
        let _count = list.property_changed().subscribe(move |name| {
            if name == "Count" {
                counted.fetch_add(1, Ordering::SeqCst);
            }
        });

        // The close probe starts a second batch on another thread, and the
        // handoff carries the release sender and the thread to this test.
        let handoff: Arc<Mutex<Option<SecondBatch>>> = Arc::new(Mutex::new(None));
        let probe_handoff = handoff.clone();
        let opener_list = list.clone();
        let fired = AtomicBool::new(false);
        list.set_batch_close_probe_for_testing(move || {
            if fired.swap(true, Ordering::AcqRel) {
                return;
            }
            let (opened_tx, opened_rx) = mpsc::channel::<()>();
            let (release_tx, release_rx) = mpsc::channel::<()>();
            let opener_list = opener_list.clone();
            let opener = thread::spawn(move || {
                opener_list.batch_update(move || {
                    let _ = opened_tx.send(());
                    let _ = release_rx.recv();
                });
            });
            // Before the fix the opener's batch opens here. After it, the
            // opener blocks on the batch lock that this probe holds.
            let _ = opened_rx.recv_timeout(PROBE_WAIT);
            *probe_handoff.lock().unwrap() = Some((release_tx, opener));
        });

        list.batch_update(|| list.push("a"));

        // Read what the closing batch delivered before the second batch closes.
        let at_close = collection_actions(&recorder);
        let counts_at_close = count_notifications(&recorder);
        let local_counts_at_close = local_counts.load(Ordering::SeqCst);

        let (release_tx, opener) = handoff
            .lock()
            .unwrap()
            .take()
            .expect("the close probe did not start the second batch");
        let _ = release_tx.send(());
        opener.join().expect("the second batch panicked");

        assert_eq!(
            counts_at_close, 1,
            "the closing batch should deliver its Count change to the hub"
        );
        assert_eq!(
            local_counts_at_close, 1,
            "the closing batch should deliver its Count change to the local stream"
        );
        assert_eq!(
            at_close,
            vec![CollectionChangeAction::Reset],
            "the closing batch should deliver its Reset to the hub"
        );
        assert_eq!(
            collection_actions(&recorder),
            vec![CollectionChangeAction::Reset],
            "the second batch has no change, so it should add no hub message"
        );
    });
}
