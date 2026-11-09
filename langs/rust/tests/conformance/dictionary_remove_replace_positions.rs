//! COL-068 — dictionary Remove and Replace hub messages carry the entry
//! position (spec/21-collections.md §2.4 and §4.7, ADR-0193, #1316).
//!
//! The position is the entry's index in enumeration order. Rust has no local
//! dictionary event, so it is the commit position. Remove sends `old_index: Some(pre-removal)` and `new_index: None`.
//! Replace sends `Some(position)` in both fields.

use std::sync::{Arc, Mutex};

use vmx::{
    CollectionChangeAction, Message, MessageHub, ObservableDictionary, ObservableMultiDictionary,
    Subscription,
};

/// Action, old index, and new index of one collection change.
type Change = (CollectionChangeAction, Option<usize>, Option<usize>);

fn record(hub: &MessageHub) -> (Arc<Mutex<Vec<Change>>>, Subscription) {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&seen);
    let subscription = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            sink.lock()
                .unwrap()
                .push((change.action.clone(), change.old_index, change.new_index));
        }
    });
    (seen, subscription)
}

/// COL-068 — Replace and Remove carry the entry position in enumeration order
#[test]
fn col_068_multi_dictionary_remove_and_replace_carry_the_entry_position() {
    let hub = MessageHub::new();
    let dictionary = ObservableMultiDictionary::new(1, hub.clone());
    dictionary.add("a", 1, "one").unwrap();
    dictionary.add("b", 2, "two").unwrap();
    dictionary.add("c", 3, "three").unwrap();
    let (seen, _subscription) = record(&hub);

    dictionary.insert("c", 3, "THREE");
    assert_eq!(dictionary.remove(&"b", &2), Some("two"));

    assert_eq!(
        *seen.lock().unwrap(),
        vec![
            (CollectionChangeAction::Replace, Some(2), Some(2)),
            (CollectionChangeAction::Remove, Some(1), None),
        ]
    );
    assert_eq!(
        dictionary.entries(),
        vec![("a", 1, "one"), ("c", 3, "THREE")]
    );
}

/// The single-key `ObservableDictionary` follows the same positions.
#[test]
fn single_key_dictionary_remove_and_replace_carry_the_entry_position() {
    let hub = MessageHub::new();
    let dictionary = ObservableDictionary::new(1, hub.clone());
    dictionary.insert("a", 1);
    dictionary.insert("b", 2);
    dictionary.insert("c", 3);
    let (seen, _subscription) = record(&hub);

    dictionary.insert("c", 30);
    assert_eq!(dictionary.remove(&"b"), Some(2));
    dictionary.insert("d", 4);

    assert_eq!(
        *seen.lock().unwrap(),
        vec![
            (CollectionChangeAction::Replace, Some(2), Some(2)),
            (CollectionChangeAction::Remove, Some(1), None),
            (CollectionChangeAction::Add, None, Some(2)),
        ]
    );
    assert_eq!(dictionary.keys(), vec!["a", "c", "d"]);
}
