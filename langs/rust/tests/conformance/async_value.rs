use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Arc, Mutex};

use vmx::AsyncValue;

#[test]
fn async_value_maps_and_composes_without_an_executor() {
    let source = AsyncValue::pending();
    let mapped = source.map(|value: i32| value * 2);
    let composed = mapped.and_then(|value| AsyncValue::ready(value.to_string()));

    assert_eq!(source.pending_continuation_count(), 1);
    source.resolve(3);

    assert_eq!(composed.wait(), "6");
    assert_eq!(source.pending_continuation_count(), 0);
}

#[test]
fn async_value_continuation_panics_are_isolated_and_first_resolution_wins() {
    let source = AsyncValue::pending();
    let _failing = source.map(|_: i32| -> i32 { panic!("continuation boom") });
    let observed = Arc::new(Mutex::new(Vec::new()));
    let values = observed.clone();
    let healthy = source.map(move |value| {
        values.lock().unwrap().push(value);
        value
    });

    assert!(catch_unwind(AssertUnwindSafe(|| source.resolve(1))).is_ok());
    assert!(!source.resolve(2));

    assert_eq!(healthy.wait(), 1);
    assert_eq!(*observed.lock().unwrap(), vec![1]);
}
