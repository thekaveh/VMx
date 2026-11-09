//! COL-071 — a duplicate dictionary add fails and changes nothing.
//!
//! `ObservableMultiDictionary::add` of a key pair that is already present
//! returns `Err(VmxError::InvalidArgument(_))`. The stored value, the entries,
//! the key snapshots and the count do not change, and no hub message is sent.
//! Rust has no local dictionary event, so only the hub is checked
//! (spec/21-collections.md §4.1, ADR-0214, #1308).

use std::sync::{Arc, Mutex};

use vmx::{Message, MessageHub, ObservableMultiDictionary, VmxError};

/// COL-071 — a duplicate add returns InvalidArgument and changes nothing
#[test]
fn duplicate_add_returns_invalid_argument_and_changes_nothing() {
    let hub = MessageHub::new();
    let dictionary: ObservableMultiDictionary<&'static str, i32, &'static str> =
        ObservableMultiDictionary::new(1, hub.clone());
    dictionary.add("a", 1, "one").unwrap();
    dictionary.add("b", 2, "two").unwrap();
    let messages = Arc::new(Mutex::new(0_usize));
    let sink = messages.clone();
    let _subscription = hub.subscribe(move |message| {
        if let Message::CollectionChanged(_) = message {
            *sink.lock().unwrap() += 1;
        }
    });

    let result = dictionary.add("a", 1, "uno");

    assert!(matches!(result, Err(VmxError::InvalidArgument(_))));
    assert_eq!(dictionary.get(&"a", &1), Some("one"));
    assert_eq!(dictionary.count(), 2);
    assert_eq!(dictionary.entries(), vec![("a", 1, "one"), ("b", 2, "two")]);
    assert_eq!(dictionary.keys1(), vec!["a", "b"]);
    assert_eq!(dictionary.keys2(), vec![1, 2]);
    assert_eq!(*messages.lock().unwrap(), 0);
}
