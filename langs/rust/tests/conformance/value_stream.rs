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

#[test]
fn reentrant_send_is_deferred_until_the_current_value_reaches_all_subscribers() {
    let stream = ValueStream::hot(0);
    let trace = Arc::new(Mutex::new(Vec::new()));
    let first_trace = trace.clone();
    let reentrant = stream.clone();
    let _first = stream.subscribe(move |value| {
        first_trace.lock().unwrap().push(format!("first:{value}"));
        if value == 1 {
            reentrant.send(2);
        }
    });
    let second_trace = trace.clone();
    let _second = stream.subscribe(move |value| {
        second_trace.lock().unwrap().push(format!("second:{value}"));
    });

    stream.send(1);

    assert_eq!(
        *trace.lock().unwrap(),
        vec!["first:1", "second:1", "first:2", "second:2"]
    );
}

#[test]
fn reentrant_dispose_completes_after_the_current_value_reaches_all_subscribers() {
    let stream = ValueStream::hot(0);
    let trace = Arc::new(Mutex::new(Vec::new()));
    let first_trace = trace.clone();
    let first_completion = trace.clone();
    let reentrant = stream.clone();
    let _first = stream.subscribe_with_completion(
        move |value| {
            first_trace.lock().unwrap().push(format!("first:{value}"));
            reentrant.dispose();
        },
        move || {
            first_completion
                .lock()
                .unwrap()
                .push("first:complete".into())
        },
    );
    let second_trace = trace.clone();
    let second_completion = trace.clone();
    let _second = stream.subscribe_with_completion(
        move |value| {
            second_trace.lock().unwrap().push(format!("second:{value}"));
        },
        move || {
            second_completion
                .lock()
                .unwrap()
                .push("second:complete".into());
        },
    );

    stream.send(1);

    assert_eq!(
        *trace.lock().unwrap(),
        vec!["first:1", "second:1", "first:complete", "second:complete"]
    );
}
