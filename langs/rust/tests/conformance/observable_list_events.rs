//! `ObservableList<T>` local streams (spec/21-collections.md §3.1–§3.5,
//! ADR-0026, ADR-0208, #1257).
//!
//! A list made with `ObservableList::new` has no hub. Each mutation sends one
//! granular event on `item_added`, `item_removed`, `item_replaced` or
//! `reset`, then the spec-literal `Count` name on `property_changed` when the
//! count changed.

use std::sync::{Arc, Mutex};

use vmx::{
    EventSubscription, ItemAddedEvent, ItemRemovedEvent, ItemReplacedEvent, ObservableList,
    PropertyChangedSubscription,
};

/// Every local notification of one list, in delivery order.
struct Recorded {
    log: Arc<Mutex<Vec<String>>>,
    _events: [EventSubscription; 4],
    _count: PropertyChangedSubscription,
}

impl Recorded {
    fn on(list: &ObservableList<&'static str>) -> Self {
        let log = Arc::new(Mutex::new(Vec::new()));
        let sink = |log: &Arc<Mutex<Vec<String>>>| Arc::clone(log);
        let (added, removed, replaced, reset, count) =
            (sink(&log), sink(&log), sink(&log), sink(&log), sink(&log));
        let length = list.clone();
        Self {
            _events: [
                list.item_added()
                    .subscribe(move |ItemAddedEvent { item, index }| {
                        added.lock().unwrap().push(format!("added {item}@{index}"));
                    }),
                list.item_removed()
                    .subscribe(move |ItemRemovedEvent { item, index }| {
                        removed
                            .lock()
                            .unwrap()
                            .push(format!("removed {item}@{index}"));
                    }),
                list.item_replaced().subscribe(
                    move |ItemReplacedEvent {
                              new_item,
                              old_item,
                              index,
                          }| {
                        replaced
                            .lock()
                            .unwrap()
                            .push(format!("replaced {old_item}->{new_item}@{index}"));
                    },
                ),
                list.reset()
                    .subscribe(move |()| reset.lock().unwrap().push("reset".to_string())),
            ],
            // The handler reads the count, which is already updated.
            _count: list.property_changed().subscribe(move |name| {
                count
                    .lock()
                    .unwrap()
                    .push(format!("{name}={}", length.len()));
            }),
            log,
        }
    }

    fn take(&self) -> Vec<String> {
        std::mem::take(&mut *self.log.lock().unwrap())
    }
}

/// COL-005 — `ItemAdded` carries the item and its insertion index
#[test]
fn col_005_item_added_carries_the_item_and_insertion_index() {
    let list = ObservableList::new(1);
    let recorded = Recorded::on(&list);

    list.push("a");
    list.push("c");
    list.insert(1, "b").unwrap();
    assert!(list.insert(9, "z").is_err());

    assert_eq!(list.to_vec(), vec!["a", "b", "c"]);
    assert_eq!(
        recorded.take(),
        vec![
            "added a@0",
            "Count=1",
            "added c@1",
            "Count=2",
            "added b@1",
            "Count=3"
        ]
    );
}

/// COL-006 — `ItemRemoved` carries the item and its index before removal
#[test]
fn col_006_item_removed_carries_the_item_and_index_before_removal() {
    let list = ObservableList::new(1);
    for item in ["a", "b", "c"] {
        list.push(item);
    }
    let recorded = Recorded::on(&list);

    assert_eq!(list.remove_at(1).unwrap(), "b");
    assert!(list.remove_at(5).is_err());

    assert_eq!(list.to_vec(), vec!["a", "c"]);
    assert_eq!(recorded.take(), vec!["removed b@1", "Count=2"]);
}

/// COL-006 — a value removal removes the first equal item and reports it
#[test]
fn col_006_value_removal_removes_the_first_equal_item() {
    let list = ObservableList::new(1);
    for item in ["a", "b", "a"] {
        list.push(item);
    }
    let recorded = Recorded::on(&list);

    assert!(list.remove(&"a"));
    assert_eq!(list.to_vec(), vec!["b", "a"]);
    assert_eq!(recorded.take(), vec!["removed a@0", "Count=2"]);

    assert!(!list.remove(&"z"));
    assert_eq!(list.to_vec(), vec!["b", "a"]);
    assert!(recorded.take().is_empty(), "a missing item emits nothing");
}

/// COL-007 — `ItemReplaced` carries the new item, the old item and the index
#[test]
fn col_007_item_replaced_carries_both_items_and_the_index() {
    let list = ObservableList::new(1);
    list.push("a");
    list.push("b");
    let recorded = Recorded::on(&list);

    assert_eq!(list.replace(1, "z").unwrap(), "b");

    assert_eq!(list.to_vec(), vec!["a", "z"]);
    assert_eq!(
        recorded.take(),
        vec!["replaced b->z@1"],
        "a replacement does not change Count"
    );
}

/// COL-008 — each granular event comes before the local `Count` notification
#[test]
fn col_008_granular_events_precede_the_count_notification() {
    let list = ObservableList::new(1);
    let recorded = Recorded::on(&list);

    list.push("a");
    list.push("b");
    list.remove_at(0).unwrap();
    assert!(list.remove(&"b"));
    list.push("c");
    list.clear();
    list.clear();

    assert_eq!(
        recorded.take(),
        vec![
            "added a@0",
            "Count=1",
            "added b@1",
            "Count=2",
            "removed a@0",
            "Count=1",
            "removed b@0",
            "Count=0",
            "added c@0",
            "Count=1",
            "reset",
            "Count=0",
        ],
        "clearing an empty list emits nothing"
    );
}

/// COL-009 — a batch suppresses granular events and emits one `Reset`
#[test]
fn col_009_batch_suppresses_granular_events_and_emits_one_reset() {
    let list = ObservableList::new(1);
    list.push("a");
    let recorded = Recorded::on(&list);

    list.batch_update(|| {
        list.push("b");
        list.batch_update(|| {
            list.replace(0, "z").unwrap();
            assert!(list.remove(&"b"));
            list.push("c");
        });
        list.push("d");
    });

    assert_eq!(list.to_vec(), vec!["z", "c", "d"]);
    assert_eq!(recorded.take(), vec!["reset", "Count=3"]);

    list.batch_update(|| {
        list.replace(0, "y").unwrap();
    });
    assert_eq!(
        recorded.take(),
        vec!["reset"],
        "a count-preserving batch emits no Count"
    );

    list.batch_update(|| {});
    assert!(recorded.take().is_empty(), "an empty batch emits nothing");
}

/// COL-005 — a list without a hub updates its contents and local streams
#[test]
fn list_without_a_hub_reaches_only_its_local_streams() {
    let list = ObservableList::new(1);
    let recorded = Recorded::on(&list);

    list.push("a");
    list.replace_all(["x", "y"]);

    assert_eq!(list.to_vec(), vec!["x", "y"]);
    assert_eq!(
        recorded.take(),
        vec!["added a@0", "Count=1", "reset", "Count=2"]
    );
}

/// A panicking subscriber does not stop the other subscribers or the
/// mutation, and a disposed subscription receives nothing more.
#[test]
fn list_subscribers_are_isolated_and_disposable() {
    let list = ObservableList::new(1);
    let _failing = list.item_added().subscribe(|_| panic!("subscriber failed"));
    let recorded = Recorded::on(&list);

    list.push("a");
    assert_eq!(recorded.take(), vec!["added a@0", "Count=1"]);

    let seen = Arc::new(Mutex::new(0));
    let sink = Arc::clone(&seen);
    let subscription = list
        .item_added()
        .subscribe(move |_| *sink.lock().unwrap() += 1);
    list.push("b");
    subscription.dispose();
    list.push("c");
    assert_eq!(*seen.lock().unwrap(), 1);
    assert_eq!(list.to_vec(), vec!["a", "b", "c"]);
}
