//! COL-067 — dictionary events and the hub message follow the key-view
//! updates.
//!
//! Rust `ObservableMultiDictionary` has no local event, and `keys1()` and
//! `keys2()` return snapshots. A hub subscriber therefore reads the entries,
//! the count and both key snapshots, and each must show the mutation. A
//! mutation can change both key views, one view, or none; each snapshot keeps
//! one copy of a key that stays in other entries
//! (spec/21-collections.md §4.2, ADR-0177, #1176, #1429).

use std::sync::{Arc, Mutex};

use vmx::{CollectionChangeAction, Message, MessageHub, ObservableMultiDictionary};

type Dictionary = ObservableMultiDictionary<&'static str, i32, &'static str>;
type Entries = Vec<(&'static str, i32, &'static str)>;
type Snapshot = (Entries, usize, Vec<&'static str>, Vec<i32>);
type Seen = Arc<Mutex<Vec<(CollectionChangeAction, Snapshot)>>>;
type Case = (
    &'static str,
    &'static [(&'static str, i32, &'static str)],
    fn(&Dictionary),
    CollectionChangeAction,
    Snapshot,
);

fn read(dictionary: &Dictionary) -> Snapshot {
    (
        dictionary.entries(),
        dictionary.count(),
        dictionary.keys1(),
        dictionary.keys2(),
    )
}

/// COL-067 — the hub subscriber reads the updated entries, count and key snapshots
#[test]
fn dictionary_hub_message_follows_the_key_view_updates() {
    let added: Snapshot = (
        vec![("a", 1, "one"), ("b", 2, "two"), ("c", 3, "three")],
        3,
        vec!["a", "b", "c"],
        vec![1, 2, 3],
    );
    let cases: [Case; 7] = [
        (
            "add",
            &[],
            |d| d.add("c", 3, "three").unwrap(),
            CollectionChangeAction::Add,
            added.clone(),
        ),
        (
            "insert",
            &[],
            |d| d.insert("c", 3, "three"),
            CollectionChangeAction::Add,
            added,
        ),
        (
            "remove",
            &[],
            |d| assert_eq!(d.remove(&"a", &1), Some("one")),
            CollectionChangeAction::Remove,
            (vec![("b", 2, "two")], 1, vec!["b"], vec![2]),
        ),
        (
            "clear",
            &[],
            |d| d.clear(),
            CollectionChangeAction::Reset,
            (Vec::new(), 0, Vec::new(), Vec::new()),
        ),
        // Only a new keys2 value appears; keys1() keeps one "a".
        (
            "add of a new keys2 value only",
            &[],
            |d| d.add("a", 3, "three").unwrap(),
            CollectionChangeAction::Add,
            (
                vec![("a", 1, "one"), ("b", 2, "two"), ("a", 3, "three")],
                3,
                vec!["a", "b"],
                vec![1, 2, 3],
            ),
        ),
        // Only the keys2 value 1 disappears; ("a", 3) keeps "a" in keys1().
        (
            "remove of the last keys2 value only",
            &[("a", 3, "three")],
            |d| assert_eq!(d.remove(&"a", &1), Some("one")),
            CollectionChangeAction::Remove,
            (
                vec![("b", 2, "two"), ("a", 3, "three")],
                2,
                vec!["b", "a"],
                vec![2, 3],
            ),
        ),
        // Both keys already appear in other entries, so no key view changes.
        (
            "add that changes no key view",
            &[],
            |d| d.add("a", 2, "a-two").unwrap(),
            CollectionChangeAction::Add,
            (
                vec![("a", 1, "one"), ("b", 2, "two"), ("a", 2, "a-two")],
                3,
                vec!["a", "b"],
                vec![1, 2],
            ),
        ),
    ];
    for (mutation, extra, act, action, expected) in cases {
        let hub = MessageHub::new();
        let dictionary: Dictionary = ObservableMultiDictionary::new(1, hub.clone());
        dictionary.add("a", 1, "one").unwrap();
        dictionary.add("b", 2, "two").unwrap();
        for &(key1, key2, value) in extra {
            dictionary.add(key1, key2, value).unwrap();
        }
        let seen: Seen = Arc::new(Mutex::new(Vec::new()));
        let (sink, observed) = (seen.clone(), dictionary.clone());
        let _subscription = hub.subscribe(move |message| {
            if let Message::CollectionChanged(change) = message {
                sink.lock()
                    .unwrap()
                    .push((change.action.clone(), read(&observed)));
            }
        });

        act(&dictionary);

        assert_eq!(read(&dictionary), expected, "{mutation}");
        assert_eq!(
            *seen.lock().unwrap(),
            vec![(action, expected)],
            "{mutation}: the hub subscriber reads the updated state"
        );
    }
}
