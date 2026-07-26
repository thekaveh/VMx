use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use vmx::ValueStream;

#[test]
fn value_stream_replays_current_value_and_completes_late_subscribers() {
    let stream = ValueStream::new(1);
    let values = Arc::new(Mutex::new(Vec::new()));
    let observed = values.clone();
    let completions = Arc::new(AtomicUsize::new(0));
    let completed = completions.clone();
    let _subscription = stream.subscribe_with_completion(
        move |value| observed.lock().unwrap().push(value),
        move || {
            completed.fetch_add(1, Ordering::SeqCst);
        },
    );

    stream.send(2);
    stream.dispose();

    assert_eq!(*values.lock().unwrap(), vec![1, 2]);
    assert_eq!(completions.load(Ordering::SeqCst), 1);

    let late_values = Arc::new(Mutex::new(Vec::new()));
    let late_observed = late_values.clone();
    let late_completions = Arc::new(AtomicUsize::new(0));
    let late_completed = late_completions.clone();
    let _late = stream.subscribe_with_completion(
        move |value| late_observed.lock().unwrap().push(value),
        move || {
            late_completed.fetch_add(1, Ordering::SeqCst);
        },
    );

    assert_eq!(*late_values.lock().unwrap(), vec![2]);
    assert_eq!(late_completions.load(Ordering::SeqCst), 1);
}

#[test]
fn value_stream_isolates_subscriber_panics() {
    let stream = ValueStream::new(1);
    let _failing = stream.subscribe(|_| panic!("subscriber boom"));
    let values = Arc::new(Mutex::new(Vec::new()));
    let observed = values.clone();
    let _healthy = stream.subscribe(move |value| observed.lock().unwrap().push(value));

    stream.send(2);

    assert_eq!(*values.lock().unwrap(), vec![1, 2]);
}

#[test]
fn hot_value_stream_skips_replay_but_still_completes() {
    let stream = ValueStream::hot(1);
    let values = Arc::new(Mutex::new(Vec::new()));
    let observed = values.clone();
    let completions = Arc::new(AtomicUsize::new(0));
    let completed = completions.clone();
    let _subscription = stream.subscribe_with_completion(
        move |value| observed.lock().unwrap().push(value),
        move || {
            completed.fetch_add(1, Ordering::SeqCst);
        },
    );

    stream.send(2);
    stream.dispose();

    assert_eq!(*values.lock().unwrap(), vec![2]);
    assert_eq!(completions.load(Ordering::SeqCst), 1);
}
