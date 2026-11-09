//! COL-072 — a failing subscriber skips no later notification step of a
//! committed change.
//!
//! Rust `EventStream` and `PropertyChangedStream` run each subscriber inside
//! `catch_unwind`, so a panicking `ObservableList` or key-view subscriber
//! skips no later subscriber, no `Count` notification, no dictionary event and
//! no hub message, and the mutation returns normally
//! (spec/21-collections.md §2.5, §3.3, §4.6, ADR-0220, #1367, #1430).

use std::sync::{Arc, Mutex};

use vmx::{EventSubscription, Message, MessageHub, ObservableList, ObservableMultiDictionary};

type List = ObservableList<i32>;
type Dictionary = ObservableMultiDictionary<&'static str, i32, &'static str>;

/// Subscribes a panicking subscriber, then a counting one, to the stream of
/// `list` that `event` names.
fn fail_then_count(list: &List, event: &str) -> (Arc<Mutex<usize>>, [EventSubscription; 2]) {
    let later = Arc::new(Mutex::new(0_usize));
    let seen = Arc::clone(&later);
    let subscriptions = match event {
        "item_added" => [
            list.item_added().subscribe(|_| panic!("subscriber failed")),
            list.item_added()
                .subscribe(move |_| *seen.lock().unwrap() += 1),
        ],
        "item_removed" => [
            list.item_removed()
                .subscribe(|_| panic!("subscriber failed")),
            list.item_removed()
                .subscribe(move |_| *seen.lock().unwrap() += 1),
        ],
        _ => [
            list.reset().subscribe(|()| panic!("subscriber failed")),
            list.reset().subscribe(move |()| *seen.lock().unwrap() += 1),
        ],
    };
    (later, subscriptions)
}

/// COL-072 — a panicking `ObservableList` subscriber skips neither the later subscriber nor `Count`
#[test]
fn observable_list_failing_subscriber_skips_no_later_step() {
    type Mutation = fn(&List);
    let cases: [(&str, usize, &str, Mutation, usize); 7] = [
        ("push", 0, "item_added", |l| l.push(1), 1),
        ("insert", 0, "item_added", |l| l.insert(0, 1).unwrap(), 1),
        ("remove", 1, "item_removed", |l| assert!(l.remove(&1)), 0),
        (
            "remove_at",
            1,
            "item_removed",
            |l| assert_eq!(l.remove_at(0).unwrap(), 1),
            0,
        ),
        ("clear", 1, "reset", |l| l.clear(), 0),
        ("replace_all", 1, "reset", |l| l.replace_all([1, 2]), 2),
        (
            "batch_update",
            0,
            "reset",
            |l| l.batch_update(|| l.push(1)),
            1,
        ),
    ];
    for (mutation, initial, event, act, count) in cases {
        let list = List::new(1);
        for _ in 0..initial {
            list.push(1);
        }
        let names = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&names);
        let _count = list
            .property_changed()
            .subscribe(move |name| sink.lock().unwrap().push(name.to_string()));
        let (later, _subscriptions) = fail_then_count(&list, event);

        act(&list);

        assert_eq!(list.len(), count, "{mutation}");
        assert_eq!(*later.lock().unwrap(), 1, "{mutation}");
        assert_eq!(
            *names.lock().unwrap(),
            vec!["Count".to_string()],
            "{mutation}"
        );
    }
}

/// Distinct first-appearance keys of the entries.
fn expected_views(dictionary: &Dictionary) -> (Vec<&'static str>, Vec<i32>) {
    let (mut keys1, mut keys2) = (Vec::new(), Vec::new());
    for (key1, key2, _) in dictionary.entries() {
        if !keys1.contains(&key1) {
            keys1.push(key1);
        }
        if !keys2.contains(&key2) {
            keys2.push(key2);
        }
    }
    (keys1, keys2)
}

/// COL-072 — a panicking key-view subscriber skips no dictionary event or hub message
#[test]
fn dictionary_failing_key_view_subscriber_skips_no_later_step() {
    type Mutation = fn(&Dictionary);
    let cases: [(&str, Mutation); 4] = [
        ("add", |d| d.add("b", 2, "x").unwrap()),
        ("insert", |d| d.insert("b", 2, "x")),
        ("remove", |d| assert_eq!(d.remove(&"a", &1), Some("v"))),
        ("clear", |d| d.clear()),
    ];
    for view in ["keys1", "keys2"] {
        for (mutation, act) in cases {
            let hub = MessageHub::new();
            let dictionary = Dictionary::with_hub(1, hub.clone());
            dictionary.add("a", 1, "v").unwrap();
            let hub_messages = Arc::new(Mutex::new(0_usize));
            let sink = Arc::clone(&hub_messages);
            let _hub = hub.subscribe(move |message| {
                if let Message::CollectionChanged(_) = message {
                    *sink.lock().unwrap() += 1;
                }
            });
            let events = Arc::new(Mutex::new(0_usize));
            let sink = Arc::clone(&events);
            let _events = dictionary
                .collection_changed()
                .subscribe(move |_| *sink.lock().unwrap() += 1);
            let _failing = if view == "keys1" {
                let keys = dictionary.keys1();
                [
                    keys.item_added().subscribe(|_| panic!("key view failed")),
                    keys.item_removed().subscribe(|_| panic!("key view failed")),
                    keys.reset().subscribe(|()| panic!("key view failed")),
                ]
            } else {
                let keys = dictionary.keys2();
                [
                    keys.item_added().subscribe(|_| panic!("key view failed")),
                    keys.item_removed().subscribe(|_| panic!("key view failed")),
                    keys.reset().subscribe(|()| panic!("key view failed")),
                ]
            };

            act(&dictionary);

            assert_eq!(*events.lock().unwrap(), 1, "{view} {mutation}");
            assert_eq!(*hub_messages.lock().unwrap(), 1, "{view} {mutation}");
            let (keys1, keys2) = expected_views(&dictionary);
            assert_eq!(dictionary.keys1().to_vec(), keys1, "{view} {mutation}");
            assert_eq!(dictionary.keys2().to_vec(), keys2, "{view} {mutation}");
        }
    }
}

/// COL-072 — after a panicking `keys2` subscriber on add, `keys1` lists the new key
#[test]
fn failed_keys2_add_still_lists_the_new_key1() {
    let dictionary = Dictionary::new(1);
    let failing = dictionary
        .keys2()
        .item_added()
        .subscribe(|_| panic!("key view failed"));

    dictionary.add("a", 1, "v").unwrap();

    assert_eq!(dictionary.keys1().to_vec(), vec!["a"]);
    assert_eq!(dictionary.keys2().to_vec(), vec![1]);
    failing.dispose();
    dictionary.add("a", 2, "z").unwrap();
    assert_eq!(dictionary.keys1().to_vec(), vec!["a"]);
    assert_eq!(dictionary.keys2().to_vec(), vec![1, 2]);
    assert_eq!(dictionary.count(), 2);
}
