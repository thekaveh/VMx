//! A `ValueStream` send or dispose that waits for another thread's delivery
//! records the wait in the wait-for graph (spec/03 §4.1, ADR-0209, #1298).
//! A hub and a stream that send to each other from two threads therefore
//! complete: the wait that closes the cycle is refused. A stream wait that
//! closes no cycle still blocks until the drainer delivers the value.

use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::thread;
use std::time::Duration;
use vmx::{Message, MessageHub, ValueStream};

const BOUND: Duration = Duration::from_secs(5);

fn custom(name: &str) -> Message {
    Message::Custom {
        sender_id: 0,
        sender_name: "test".into(),
        name: name.into(),
    }
}

fn is_named(message: &Message, expected: &str) -> bool {
    matches!(message, Message::Custom { name, .. } if name == expected)
}

/// What the stream's second action does from inside the hub subscriber.
#[derive(Clone, Copy)]
enum StreamAction {
    Send,
    Dispose,
}

/// Thread A sends on hub H, and the H subscriber acts on stream S. Thread B
/// sends on S, and the S subscriber sends on H. A barrier makes both
/// subscribers act at once, so each waits for the other thread's drain.
/// Returns what the H subscriber and the S subscriber received.
fn hub_and_stream_wait_for_each_other(action: StreamAction) -> (Vec<String>, Vec<u32>) {
    let hub = MessageHub::new();
    let stream = ValueStream::hot(0_u32);
    let barrier = Arc::new(Barrier::new(2));
    let hub_seen = Arc::new(Mutex::new(Vec::new()));
    let stream_seen = Arc::new(Mutex::new(Vec::new()));

    let _hub_subscription = hub.subscribe({
        let (stream, barrier, seen) = (stream.clone(), barrier.clone(), hub_seen.clone());
        move |message| {
            if is_named(message, "from-a") {
                barrier.wait();
                match action {
                    StreamAction::Send => stream.send(42),
                    StreamAction::Dispose => stream.dispose(),
                }
            } else if let Message::Custom { name, .. } = message {
                seen.lock().unwrap().push(name.clone());
            }
        }
    });
    let _stream_subscription = stream.subscribe({
        let (hub, barrier, seen) = (hub.clone(), barrier.clone(), stream_seen.clone());
        move |value| {
            if value == 1 {
                barrier.wait();
                hub.send(custom("from-s"));
            } else {
                seen.lock().unwrap().push(value);
            }
        }
    });

    let (done, finished) = mpsc::channel();
    let thread_a = thread::spawn({
        let (hub, done) = (hub.clone(), done.clone());
        move || {
            hub.send(custom("from-a"));
            let _ = done.send("A");
        }
    });
    let thread_b = thread::spawn({
        let stream = stream.clone();
        move || {
            stream.send(1);
            let _ = done.send("B");
        }
    });
    for _ in 0..2 {
        finished
            .recv_timeout(BOUND)
            .expect("both threads finish: the hub and the stream deadlocked");
    }
    thread_a.join().unwrap();
    thread_b.join().unwrap();

    let hub_seen = hub_seen.lock().unwrap().clone();
    let stream_seen = stream_seen.lock().unwrap().clone();
    (hub_seen, stream_seen)
}

#[test]
fn a_hub_and_a_stream_that_send_to_each_other_across_threads_complete() {
    let (hub_seen, stream_seen) = hub_and_stream_wait_for_each_other(StreamAction::Send);

    assert_eq!(
        hub_seen,
        ["from-s"],
        "H received the S subscriber's message"
    );
    assert_eq!(stream_seen, [42], "S received the H subscriber's value");
}

#[test]
fn a_stream_dispose_that_waits_for_a_hub_sender_completes() {
    let (hub_seen, stream_seen) = hub_and_stream_wait_for_each_other(StreamAction::Dispose);

    assert_eq!(
        hub_seen,
        ["from-s"],
        "H received the S subscriber's message"
    );
    assert!(stream_seen.is_empty());
}

#[test]
fn a_stream_send_without_a_cycle_returns_after_the_drainer_delivers_it() {
    let stream = ValueStream::hot(0_u32);
    let delivered = Arc::new(Mutex::new(Vec::new()));
    let (draining, drain_started) = mpsc::channel();
    let _subscription = stream.subscribe({
        let delivered = delivered.clone();
        move |value| {
            if value == 1 {
                let _ = draining.send(());
                // Thread B sends while this drain is still busy.
                thread::sleep(Duration::from_millis(200));
            }
            delivered.lock().unwrap().push(value);
        }
    });

    let thread_a = thread::spawn({
        let stream = stream.clone();
        move || stream.send(1)
    });
    drain_started
        .recv_timeout(BOUND)
        .expect("A started to drain the stream");
    let (done, finished) = mpsc::channel();
    let thread_b = thread::spawn({
        let (stream, delivered) = (stream.clone(), delivered.clone());
        move || {
            stream.send(2);
            let _ = done.send(delivered.lock().unwrap().clone());
        }
    });

    let seen_by_b = finished.recv_timeout(BOUND).expect("B's send returned");
    thread_a.join().unwrap();
    thread_b.join().unwrap();

    assert_eq!(
        seen_by_b,
        [1, 2],
        "B's send returned after A delivered B's value"
    );
}
