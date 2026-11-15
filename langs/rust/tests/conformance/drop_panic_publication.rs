//! Regression tests: a Rust collection publishes a committed change before
//! it drops the removed items, so an item whose `Drop` panics cannot suppress
//! the change (spec/21 §2.5, #1295). The panic still reaches the caller.

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use vmx::{
    KeyedServicedObservableCollection, Message, MessageHub, ObservableDictionary, ObservableList,
    ObservableMultiDictionary, ServicedObservableCollection, Subscription,
};

/// An item whose `Drop` panics once after the test arms it.
#[derive(Clone)]
struct PanicOnDrop {
    id: u32,
    armed: Arc<AtomicBool>,
}

impl PanicOnDrop {
    fn new(id: u32, armed: &Arc<AtomicBool>) -> Self {
        Self {
            id,
            armed: Arc::clone(armed),
        }
    }
}

impl PartialEq for PanicOnDrop {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl Drop for PanicOnDrop {
    fn drop(&mut self) {
        if self.armed.swap(false, Ordering::SeqCst) {
            panic!("user drop panicked");
        }
    }
}

/// Changes recorded as `"<action>"` for collection changes and
/// `"PropertyChanged:<name>"` for property changes.
type Recorded = Arc<Mutex<Vec<String>>>;

fn record(hub: &MessageHub) -> (Recorded, Subscription) {
    let recorded = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&recorded);
    let subscription = hub.subscribe(move |message| {
        let entry = match message {
            Message::CollectionChanged(change) => format!("{:?}", change.action),
            Message::PropertyChanged(change) => format!("PropertyChanged:{}", change.property_name),
            _ => return,
        };
        sink.lock().unwrap().push(entry);
    });
    (recorded, subscription)
}

fn recorded(recorded: &Recorded) -> Vec<String> {
    recorded.lock().unwrap().clone()
}

/// Arms the item drop, runs `mutation`, and asserts that its panic reached
/// the caller.
fn assert_panics(armed: &AtomicBool, mutation: impl FnOnce()) {
    armed.store(true, Ordering::SeqCst);
    let outcome = catch_unwind(AssertUnwindSafe(mutation));
    assert!(outcome.is_err(), "the drop panic propagates");
    assert!(!armed.load(Ordering::SeqCst), "the armed drop ran");
}

#[test]
fn serviced_collection_clear_publishes_its_reset_before_a_drop_panic() {
    let armed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let collection = ServicedObservableCollection::with_hub(1, hub.clone());
    collection.push(PanicOnDrop::new(1, &armed));
    let (local, _local) = record(&collection.collection_changed());
    let (external, _external) = record(&hub);

    assert_panics(&armed, || collection.clear());

    assert_eq!(collection.len(), 0);
    assert_eq!(recorded(&local), ["Reset"]);
    assert_eq!(recorded(&external), ["Reset"]);
}

#[test]
fn keyed_collection_clear_publishes_its_reset_before_a_drop_panic() {
    let armed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let collection =
        KeyedServicedObservableCollection::with_hub(1, hub.clone(), |item: &PanicOnDrop| {
            Ok(item.id)
        });
    collection.push(PanicOnDrop::new(1, &armed)).unwrap();
    let (local, _local) = record(&collection.collection_changed());
    let (external, _external) = record(&hub);

    assert_panics(&armed, || collection.clear());

    assert_eq!(collection.len(), 0);
    assert_eq!(recorded(&local), ["Reset"]);
    assert_eq!(recorded(&external), ["Reset"]);
}

#[test]
fn observable_list_clear_publishes_its_reset_and_count_before_a_drop_panic() {
    let armed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let list = ObservableList::with_hub(1, hub.clone());
    list.push(PanicOnDrop::new(1, &armed));
    let (external, _external) = record(&hub);

    assert_panics(&armed, || list.clear());

    assert_eq!(list.len(), 0);
    assert_eq!(recorded(&external), ["Reset", "PropertyChanged:Count"]);
}

#[test]
fn observable_dictionary_clear_publishes_its_reset_before_a_drop_panic() {
    let armed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let dictionary = ObservableDictionary::new(1, hub.clone());
    dictionary.insert("one", PanicOnDrop::new(1, &armed));
    let (external, _external) = record(&hub);

    assert_panics(&armed, || dictionary.clear());

    assert!(dictionary.keys().is_empty());
    assert_eq!(recorded(&external), ["Reset"]);
}

#[test]
fn observable_multi_dictionary_clear_publishes_its_reset_before_a_drop_panic() {
    let armed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let dictionary = ObservableMultiDictionary::with_hub(1, hub.clone());
    dictionary.add("a", 1, PanicOnDrop::new(1, &armed)).unwrap();
    let (external, _external) = record(&hub);

    assert_panics(&armed, || dictionary.clear());

    assert_eq!(dictionary.count(), 0);
    assert_eq!(recorded(&external), ["Reset"]);
}

#[test]
fn serviced_collection_remove_publishes_its_remove_before_a_drop_panic() {
    let armed = Arc::new(AtomicBool::new(false));
    let unarmed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let collection = ServicedObservableCollection::with_hub(1, hub.clone());
    collection.push(PanicOnDrop::new(1, &unarmed));
    collection.push(PanicOnDrop::new(2, &armed));
    let (local, _local) = record(&collection.collection_changed());
    let (external, _external) = record(&hub);

    let target = PanicOnDrop::new(2, &unarmed);
    assert_panics(&armed, || {
        collection.remove(&target);
    });

    assert_eq!(collection.len(), 1);
    assert_eq!(recorded(&local), ["Remove"]);
    assert_eq!(recorded(&external), ["Remove"]);
}

#[test]
fn observable_list_remove_publishes_its_remove_and_count_before_a_drop_panic() {
    let armed = Arc::new(AtomicBool::new(false));
    let unarmed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let list = ObservableList::with_hub(1, hub.clone());
    list.push(PanicOnDrop::new(1, &unarmed));
    list.push(PanicOnDrop::new(2, &armed));
    let (external, _external) = record(&hub);

    let target = PanicOnDrop::new(2, &unarmed);
    assert_panics(&armed, || {
        list.remove(&target);
    });

    assert_eq!(list.len(), 1);
    assert_eq!(recorded(&external), ["Remove", "PropertyChanged:Count"]);
}

#[test]
fn observable_multi_dictionary_replace_publishes_its_replace_before_a_drop_panic() {
    let armed = Arc::new(AtomicBool::new(false));
    let unarmed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let dictionary = ObservableMultiDictionary::with_hub(1, hub.clone());
    dictionary.insert("a", 1, PanicOnDrop::new(1, &armed));
    let (local, _local) = record(&dictionary.collection_changed());
    let (external, _external) = record(&hub);

    assert_panics(&armed, || {
        dictionary.insert("a", 1, PanicOnDrop::new(2, &unarmed));
    });

    assert_eq!(dictionary.count(), 1);
    assert_eq!(recorded(&local), ["Replace"]);
    assert_eq!(recorded(&external), ["Replace"]);
}

/// The bound on each wait of the snapshot sequence.
const SEQUENCE_BOUND: Duration = Duration::from_secs(10);

/// Orders a reader's `to_vec` clones against a writer's copy of the list.
///
/// Phase 1 starts the sequence. The reader's first item clone moves the phase
/// to 2 and waits for 3. The writer's copy clones on its own thread: its first
/// clone moves 2 to 3 and waits for 4, while it holds the list lock. The
/// reader sets 4 after `to_vec` returns, which releases its snapshot. Every
/// other clone does nothing. A wait that runs out sets `timed_out`.
#[derive(Default)]
struct Sequence {
    phase: AtomicU8,
    timed_out: AtomicBool,
}

impl Sequence {
    fn set(&self, phase: u8) {
        self.phase.store(phase, Ordering::SeqCst);
    }

    /// Waits until the phase reaches `target`. Returns `false` after the bound.
    fn wait_for(&self, target: u8) -> bool {
        let deadline = Instant::now() + SEQUENCE_BOUND;
        while self.phase.load(Ordering::SeqCst) < target {
            if Instant::now() >= deadline {
                self.timed_out.store(true, Ordering::SeqCst);
                return false;
            }
            thread::sleep(Duration::from_millis(1));
        }
        true
    }

    fn on_clone(&self) {
        if self
            .phase
            .compare_exchange(1, 2, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
        {
            self.wait_for(3);
        } else if self
            .phase
            .compare_exchange(2, 3, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
        {
            self.wait_for(4);
        }
    }
}

/// An item whose `Drop` panics once when armed. A clone makes an unarmed
/// copy and runs the sequence hook, so only an original of the list can panic.
struct SnapshotItem {
    id: u32,
    armed: Arc<AtomicBool>,
    sequence: Arc<Sequence>,
}

impl SnapshotItem {
    fn new(id: u32, armed: &Arc<AtomicBool>, sequence: &Arc<Sequence>) -> Self {
        Self {
            id,
            armed: Arc::clone(armed),
            sequence: Arc::clone(sequence),
        }
    }
}

impl Clone for SnapshotItem {
    fn clone(&self) -> Self {
        self.sequence.on_clone();
        Self {
            id: self.id,
            armed: Arc::new(AtomicBool::new(false)),
            sequence: Arc::clone(&self.sequence),
        }
    }
}

impl Drop for SnapshotItem {
    fn drop(&mut self) {
        if self.armed.swap(false, Ordering::SeqCst) {
            panic!("user drop panicked");
        }
    }
}

/// Starts a reader that takes a snapshot with `to_vec` and returns its length.
/// It returns with the snapshot released and phase 4 set.
fn spawn_snapshot_reader(
    list: &Arc<ObservableList<SnapshotItem>>,
    sequence: &Arc<Sequence>,
) -> thread::JoinHandle<usize> {
    let list = Arc::clone(list);
    let sequence = Arc::clone(sequence);
    thread::spawn(move || {
        let len = list.to_vec().len();
        sequence.set(4);
        len
    })
}

#[test]
fn observable_list_remove_at_publishes_its_remove_before_a_drop_panic_with_a_reader_snapshot() {
    let sequence = Arc::new(Sequence::default());
    let armed = Arc::new(AtomicBool::new(false));
    let unarmed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let list = Arc::new(ObservableList::with_hub(1, hub.clone()));
    list.push(SnapshotItem::new(1, &unarmed, &sequence));
    list.push(SnapshotItem::new(2, &unarmed, &sequence));
    list.push(SnapshotItem::new(3, &armed, &sequence));
    let (external, _external) = record(&hub);

    sequence.set(1);
    let reader = spawn_snapshot_reader(&list, &sequence);
    assert!(sequence.wait_for(2), "the reader started its clones");

    assert_panics(&armed, || {
        let _ = list.remove_at(0);
    });

    assert_eq!(reader.join().unwrap(), 3);
    assert!(
        !sequence.timed_out.load(Ordering::SeqCst),
        "the sequence ran"
    );
    assert_eq!(list.len(), 2);
    assert_eq!(recorded(&external), ["Remove", "PropertyChanged:Count"]);
}

#[test]
fn observable_list_replace_publishes_its_replace_before_a_drop_panic_with_a_reader_snapshot() {
    let sequence = Arc::new(Sequence::default());
    let armed = Arc::new(AtomicBool::new(false));
    let unarmed = Arc::new(AtomicBool::new(false));
    let hub = MessageHub::new();
    let list = Arc::new(ObservableList::with_hub(1, hub.clone()));
    list.push(SnapshotItem::new(1, &unarmed, &sequence));
    list.push(SnapshotItem::new(2, &unarmed, &sequence));
    list.push(SnapshotItem::new(3, &armed, &sequence));
    let (external, _external) = record(&hub);

    sequence.set(1);
    let reader = spawn_snapshot_reader(&list, &sequence);
    assert!(sequence.wait_for(2), "the reader started its clones");

    assert_panics(&armed, || {
        let _ = list.replace(0, SnapshotItem::new(9, &unarmed, &sequence));
    });

    assert_eq!(reader.join().unwrap(), 3);
    assert!(
        !sequence.timed_out.load(Ordering::SeqCst),
        "the sequence ran"
    );
    assert_eq!(list.len(), 3);
    assert_eq!(list.get(0).map(|item| item.id), Some(9));
    assert_eq!(recorded(&external), ["Replace"]);
}
