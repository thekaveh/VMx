//! COL-067 — dictionary events and the hub message follow both key-view
//! updates.
//!
//! Rust `ObservableMultiDictionary` updates its live `keys1()` and `keys2()`
//! views, then sends its local `collection_changed()` event, then the hub
//! message. Each key-view subscriber reads the updated entries, the count and
//! its own view. The dictionary-event and hub subscribers read both views
//! (spec/21-collections.md §4.2, ADR-0177, ADR-0208, #1176, #1257).

use std::sync::{Arc, Mutex};

use vmx::{
    CollectionChangeAction, EventSubscription, Message, MessageHub, ObservableMultiDictionary,
    ReadOnlyObservableList, Subscription,
};

type Dictionary = ObservableMultiDictionary<&'static str, i32, &'static str>;
type Entries = Vec<(&'static str, i32, &'static str)>;
type Snapshot = (Entries, usize, Vec<&'static str>, Vec<i32>);
type Log = Arc<Mutex<Vec<(&'static str, Snapshot)>>>;
type Case = (
    &'static str,
    fn(&Dictionary),
    CollectionChangeAction,
    Snapshot,
);

fn read(dictionary: &Dictionary) -> Snapshot {
    (
        dictionary.entries(),
        dictionary.count(),
        dictionary.keys1().to_vec(),
        dictionary.keys2().to_vec(),
    )
}

/// Subscribes to every granular event of one key view. Each delivery logs
/// `label` with the entries, the count and the view's own items; the other
/// view is left out, because its state is not specified (ADR-0177).
fn observe_view<K: Clone + Send + Sync + 'static>(
    view: ReadOnlyObservableList<K>,
    dictionary: &Dictionary,
    label: &'static str,
    log: &Log,
    own: fn(&Dictionary, &mut Snapshot),
) -> [EventSubscription; 3] {
    let record = move |dictionary: &Dictionary, log: &Log| {
        let (entries, count, _, _) = read(dictionary);
        let mut snapshot = (entries, count, Vec::new(), Vec::new());
        own(dictionary, &mut snapshot);
        log.lock().unwrap().push((label, snapshot));
    };
    let handler = || {
        let (dictionary, log) = (dictionary.clone(), Arc::clone(log));
        move || record(&dictionary, &log)
    };
    let (added, removed, reset) = (handler(), handler(), handler());
    [
        view.item_added().subscribe(move |_| added()),
        view.item_removed().subscribe(move |_| removed()),
        view.reset().subscribe(move |()| reset()),
    ]
}

fn observe_messages(
    stream: &MessageHub,
    dictionary: &Dictionary,
    label: &'static str,
    log: &Log,
    actions: &Arc<Mutex<Vec<CollectionChangeAction>>>,
) -> Subscription {
    let (dictionary, log, actions) = (dictionary.clone(), Arc::clone(log), Arc::clone(actions));
    stream.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            actions.lock().unwrap().push(change.action.clone());
            log.lock().unwrap().push((label, read(&dictionary)));
        }
    })
}

/// COL-067 — key-view subscribers see their update first, then the dictionary event, then the hub
#[test]
fn dictionary_event_and_hub_message_follow_both_key_view_updates() {
    let added: Snapshot = (
        vec![("a", 1, "one"), ("b", 2, "two"), ("c", 3, "three")],
        3,
        vec!["a", "b", "c"],
        vec![1, 2, 3],
    );
    let cases: [Case; 4] = [
        (
            "add",
            |d| d.add("c", 3, "three").unwrap(),
            CollectionChangeAction::Add,
            added.clone(),
        ),
        (
            "insert",
            |d| d.insert("c", 3, "three"),
            CollectionChangeAction::Add,
            added,
        ),
        (
            "remove",
            |d| assert_eq!(d.remove(&"a", &1), Some("one")),
            CollectionChangeAction::Remove,
            (vec![("b", 2, "two")], 1, vec!["b"], vec![2]),
        ),
        (
            "clear",
            |d| d.clear(),
            CollectionChangeAction::Reset,
            (Vec::new(), 0, Vec::new(), Vec::new()),
        ),
    ];
    for (mutation, act, action, expected) in cases {
        let hub = MessageHub::new();
        let dictionary: Dictionary = ObservableMultiDictionary::with_hub(1, hub.clone());
        dictionary.add("a", 1, "one").unwrap();
        dictionary.add("b", 2, "two").unwrap();
        let log: Log = Arc::new(Mutex::new(Vec::new()));
        let actions = Arc::new(Mutex::new(Vec::new()));
        let _keys1 = observe_view(dictionary.keys1(), &dictionary, "keys1", &log, |d, s| {
            s.2 = d.keys1().to_vec();
        });
        let _keys2 = observe_view(dictionary.keys2(), &dictionary, "keys2", &log, |d, s| {
            s.3 = d.keys2().to_vec();
        });
        let _local = observe_messages(
            &dictionary.collection_changed(),
            &dictionary,
            "local",
            &log,
            &actions,
        );
        let _hub = observe_messages(&hub, &dictionary, "hub", &log, &actions);

        act(&dictionary);

        assert_eq!(read(&dictionary), expected, "{mutation}");
        assert_eq!(*actions.lock().unwrap(), vec![action.clone(); 2]);
        let log = log.lock().unwrap().clone();
        assert_eq!(log.len(), 4, "{mutation}: {log:?}");
        let (views, messages) = log.split_at(2);
        let mut labels: Vec<_> = views.iter().map(|(label, _)| *label).collect();
        labels.sort_unstable();
        assert_eq!(labels, ["keys1", "keys2"], "{mutation}");
        for (label, snapshot) in views {
            let own = if *label == "keys1" {
                (
                    expected.0.clone(),
                    expected.1,
                    expected.2.clone(),
                    Vec::new(),
                )
            } else {
                (
                    expected.0.clone(),
                    expected.1,
                    Vec::new(),
                    expected.3.clone(),
                )
            };
            assert_eq!(snapshot, &own, "{mutation}: {label} reads its update");
        }
        assert_eq!(
            messages,
            [("local", expected.clone()), ("hub", expected)],
            "{mutation}: the dictionary event, then the hub, read both views"
        );
    }
}

/// COL-067 — a mutation that leaves both key views unchanged notifies no view
#[test]
fn dictionary_value_replacement_changes_no_key_view() {
    let dictionary: Dictionary = ObservableMultiDictionary::new(1);
    dictionary.add("a", 1, "one").unwrap();
    dictionary.add("a", 2, "two").unwrap();
    let log: Log = Arc::new(Mutex::new(Vec::new()));
    let actions = Arc::new(Mutex::new(Vec::new()));
    let _keys1 = observe_view(dictionary.keys1(), &dictionary, "keys1", &log, |d, s| {
        s.2 = d.keys1().to_vec();
    });
    let _keys2 = observe_view(dictionary.keys2(), &dictionary, "keys2", &log, |d, s| {
        s.3 = d.keys2().to_vec();
    });
    let _local = observe_messages(
        &dictionary.collection_changed(),
        &dictionary,
        "local",
        &log,
        &actions,
    );

    dictionary.insert("a", 1, "uno");
    // "a" still has an entry, and 2 is still a second key.
    assert_eq!(dictionary.remove(&"a", &1), Some("uno"));

    assert_eq!(
        *actions.lock().unwrap(),
        vec![
            CollectionChangeAction::Replace,
            CollectionChangeAction::Remove
        ]
    );
    let labels: Vec<_> = log
        .lock()
        .unwrap()
        .iter()
        .map(|(label, _)| *label)
        .collect();
    assert_eq!(labels, ["local", "keys2", "local"]);
    assert_eq!(dictionary.keys1().to_vec(), vec!["a"]);
    assert_eq!(dictionary.keys2().to_vec(), vec![2]);
}
