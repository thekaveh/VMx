//! COL-070 — dictionary key views give callers no mutator
//! (spec/21-collections.md §4.1–§4.2, ADR-0193, ADR-0208, #1316).
//!
//! Rust `keys1()` and `keys2()` return a `ReadOnlyObservableList`, which has
//! no mutator and no batch member, so the absence is checked by the compiler.
//! A caller may edit a `to_vec()` snapshot, but the edit does not reach the
//! view or the dictionary.

use vmx::{MessageHub, ObservableMultiDictionary, ReadOnlyObservableList};

/// COL-070 — an edit to a key snapshot leaves the views and the dictionary unchanged
#[test]
fn col_070_key_snapshot_edits_leave_the_dictionary_unchanged() {
    let dictionary = ObservableMultiDictionary::with_hub(1, MessageHub::new());
    dictionary.add("a", 1, "one").unwrap();
    dictionary.add("b", 2, "two").unwrap();
    dictionary.add("a", 2, "three").unwrap();

    let keys1: ReadOnlyObservableList<&str> = dictionary.keys1();
    let keys2: ReadOnlyObservableList<i32> = dictionary.keys2();
    assert_eq!(
        keys1.to_vec(),
        vec!["a", "b"],
        "distinct keys in first-appearance order"
    );
    assert_eq!(
        keys2.to_vec(),
        vec![1, 2],
        "distinct keys in first-appearance order"
    );

    let mut snapshot1 = keys1.to_vec();
    let mut snapshot2 = keys2.to_vec();
    snapshot1.push("z");
    snapshot1.retain(|key| *key != "a");
    snapshot2.clear();
    snapshot2.push(9);

    assert_eq!(keys1.to_vec(), vec!["a", "b"]);
    assert_eq!(keys2.to_vec(), vec![1, 2]);
    assert_eq!(dictionary.keys1().to_vec(), vec!["a", "b"]);
    assert_eq!(dictionary.keys2().to_vec(), vec![1, 2]);
    assert_eq!(
        dictionary.entries(),
        vec![("a", 1, "one"), ("b", 2, "two"), ("a", 2, "three")]
    );
}
