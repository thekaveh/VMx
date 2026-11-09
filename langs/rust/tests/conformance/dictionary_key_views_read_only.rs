//! COL-070 — dictionary key views give callers no mutator
//! (spec/21-collections.md §4.1–§4.2, ADR-0193, #1316).
//!
//! Rust `keys1()` and `keys2()` return `Vec` snapshots. A caller may edit a
//! snapshot, but the edit does not reach the dictionary.

use vmx::{MessageHub, ObservableMultiDictionary};

/// COL-070 — an edit to a key snapshot leaves the dictionary unchanged
#[test]
fn col_070_key_snapshot_edits_leave_the_dictionary_unchanged() {
    let dictionary = ObservableMultiDictionary::new(1, MessageHub::new());
    dictionary.add("a", 1, "one").unwrap();
    dictionary.add("b", 2, "two").unwrap();
    dictionary.add("a", 2, "three").unwrap();

    let mut keys1 = dictionary.keys1();
    let mut keys2 = dictionary.keys2();
    assert_eq!(
        keys1,
        vec!["a", "b"],
        "distinct keys in first-appearance order"
    );
    assert_eq!(keys2, vec![1, 2], "distinct keys in first-appearance order");

    keys1.push("z");
    keys1.retain(|key| *key != "a");
    keys2.clear();
    keys2.push(9);

    assert_eq!(dictionary.keys1(), vec!["a", "b"]);
    assert_eq!(dictionary.keys2(), vec![1, 2]);
    assert_eq!(
        dictionary.entries(),
        vec![("a", 1, "one"), ("b", 2, "two"), ("a", 2, "three")]
    );
}
