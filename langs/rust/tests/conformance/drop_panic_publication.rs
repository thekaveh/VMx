//! Regression tests: a Rust collection publishes a committed change before
//! it drops the removed items, so an item whose `Drop` panics cannot suppress
//! the change (spec/21 §2.5, #1295). The panic still reaches the caller.

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
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
