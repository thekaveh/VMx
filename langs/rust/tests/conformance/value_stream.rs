use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::time::{Duration, Instant};

use vmx::ValueStream;

fn wait_until(mut predicate: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(1);
    while !predicate() {
        assert!(
            Instant::now() < deadline,
            "condition did not become true before the deadline"
        );
        std::thread::yield_now();
    }
}

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

#[test]
fn reentrant_terminal_follows_every_previously_accepted_value() {
    let stream = ValueStream::hot(0);
    let trace = Arc::new(Mutex::new(Vec::new()));
    let first_trace = trace.clone();
    let first_completion = trace.clone();
    let reentrant_send = stream.clone();
    let reentrant_dispose = stream.clone();
    let _first = stream.subscribe_with_completion(
        move |value| {
            first_trace.lock().unwrap().push(format!("first:{value}"));
            if value == 1 {
                reentrant_send.send(2);
                reentrant_dispose.dispose();
            }
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
    stream.send(3);

    assert_eq!(
        *trace.lock().unwrap(),
        vec![
            "first:1",
            "second:1",
            "first:2",
            "second:2",
            "first:complete",
            "second:complete",
        ]
    );
}

#[test]
fn foreign_send_returns_only_after_its_queued_value_is_delivered() {
    let stream = ValueStream::hot(0);
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let release = release_rx.clone();
    let _subscription = stream.subscribe(move |value| {
        if value == 1 {
            entered_tx.send(()).unwrap();
            release.lock().unwrap().recv().unwrap();
        }
    });

    let first_stream = stream.clone();
    let first_sender = std::thread::spawn(move || first_stream.send(1));
    entered_rx.recv().unwrap();

    let (returned_tx, returned_rx) = mpsc::channel();
    let second_stream = stream.clone();
    let second_sender = std::thread::spawn(move || {
        second_stream.send(2);
        returned_tx.send(()).unwrap();
    });
    wait_until(|| stream.value() == 2);
    let returned_before_delivery = returned_rx.recv_timeout(Duration::from_millis(50)).is_ok();

    release_tx.send(()).unwrap();
    first_sender.join().unwrap();
    second_sender.join().unwrap();

    assert!(
        !returned_before_delivery,
        "a foreign sender returned before its accepted value was delivered"
    );
    assert_eq!(returned_rx.try_recv(), Ok(()));
}

#[test]
fn replay_subscriber_does_not_receive_an_accepted_in_flight_value_twice() {
    let stream = ValueStream::new(0);
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let release = release_rx.clone();
    let _blocking = stream.subscribe(move |value| {
        if value == 1 {
            entered_tx.send(()).unwrap();
            release.lock().unwrap().recv().unwrap();
        }
    });

    let first_stream = stream.clone();
    let first_sender = std::thread::spawn(move || first_stream.send(1));
    entered_rx.recv().unwrap();

    let second_stream = stream.clone();
    let second_sender = std::thread::spawn(move || second_stream.send(2));
    wait_until(|| stream.value() == 2);

    let observed = Arc::new(Mutex::new(Vec::new()));
    let values = observed.clone();
    let _late = stream.subscribe(move |value| values.lock().unwrap().push(value));
    assert_eq!(*observed.lock().unwrap(), vec![2]);

    release_tx.send(()).unwrap();
    first_sender.join().unwrap();
    second_sender.join().unwrap();

    assert_eq!(
        *observed.lock().unwrap(),
        vec![2],
        "the replayed in-flight value must not also arrive from its queued delivery"
    );
}

#[test]
fn foreign_dispose_returns_only_after_terminal_callbacks_finish() {
    let stream = ValueStream::hot(0);
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let release = release_rx.clone();
    let completions = Arc::new(AtomicUsize::new(0));
    let completed = completions.clone();
    let _subscription = stream.subscribe_with_completion(
        move |value| {
            if value == 1 {
                entered_tx.send(()).unwrap();
                release.lock().unwrap().recv().unwrap();
            }
        },
        move || {
            completed.fetch_add(1, Ordering::SeqCst);
        },
    );

    let sender_stream = stream.clone();
    let sender = std::thread::spawn(move || sender_stream.send(1));
    entered_rx.recv().unwrap();

    let (returned_tx, returned_rx) = mpsc::channel();
    let disposer_stream = stream.clone();
    let disposer = std::thread::spawn(move || {
        disposer_stream.dispose();
        returned_tx.send(()).unwrap();
    });
    let terminal_seen = Arc::new(std::sync::atomic::AtomicBool::new(false));
    wait_until(|| {
        let observed = terminal_seen.clone();
        let late = stream.subscribe_with_completion(
            |_| {},
            move || {
                observed.store(true, Ordering::SeqCst);
            },
        );
        drop(late);
        terminal_seen.load(Ordering::SeqCst)
    });
    let returned_before_completion = returned_rx.recv_timeout(Duration::from_millis(50)).is_ok();

    release_tx.send(()).unwrap();
    sender.join().unwrap();
    disposer.join().unwrap();

    assert!(
        !returned_before_completion,
        "a foreign disposer returned before terminal callbacks finished"
    );
    assert_eq!(completions.load(Ordering::SeqCst), 1);
    assert_eq!(returned_rx.try_recv(), Ok(()));
}

#[test]
fn opposing_cross_stream_callbacks_do_not_deadlock_two_drainers() {
    let left = ValueStream::hot(0);
    let right = ValueStream::hot(0);
    let callbacks_entered = Arc::new(Barrier::new(2));
    let (returned_tx, returned_rx) = mpsc::channel();

    let left_barrier = callbacks_entered.clone();
    let left_to_right = right.clone();
    let left_returned = returned_tx.clone();
    let _left_subscription = left.subscribe(move |value| {
        if value == 1 {
            left_barrier.wait();
            left_to_right.send(2);
            left_returned.send("left").unwrap();
        }
    });

    let right_barrier = callbacks_entered;
    let right_to_left = left.clone();
    let right_returned = returned_tx;
    let _right_subscription = right.subscribe(move |value| {
        if value == 1 {
            right_barrier.wait();
            right_to_left.send(2);
            right_returned.send("right").unwrap();
        }
    });

    let left_sender = {
        let left = left.clone();
        std::thread::spawn(move || left.send(1))
    };
    let right_sender = {
        let right = right.clone();
        std::thread::spawn(move || right.send(1))
    };

    let first = returned_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("one callback should return from its cross-stream send");
    let second = returned_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("both callbacks should return from their cross-stream sends");
    left_sender.join().unwrap();
    right_sender.join().unwrap();

    assert_ne!(first, second);
    assert_eq!(left.value(), 2);
    assert_eq!(right.value(), 2);
}
