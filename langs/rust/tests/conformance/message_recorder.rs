//! A `MessageHub` retains nothing by default; a `MessageRecorder` keeps a
//! bounded record of accepted messages without changing delivery (ADR-0141).

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Arc, Mutex};
use vmx::{Message, MessageHub, MessageRecorder, Subscription};

fn make_msg(name: &str) -> Message {
    Message::Custom {
        sender_id: 1,
        sender_name: "sender".to_string(),
        name: name.to_string(),
    }
}

fn names(recorder: &MessageRecorder) -> Vec<String> {
    recorder
        .messages()
        .into_iter()
        .map(|message| match message {
            Message::Custom { name, .. } => name,
            other => panic!("unexpected message {other:?}"),
        })
        .collect()
}

#[test]
fn a_million_sends_through_an_ordinary_hub_keep_only_the_recorder_bound() {
    const SENDS: u64 = 1_000_000;
    const CAPACITY: usize = 1024;
    let hub = MessageHub::new();
    let recorder = hub.record(CAPACITY);
    let message = make_msg("tick");

    for _ in 0..SENDS {
        hub.send(message.clone());
    }

    assert_eq!(recorder.len(), CAPACITY);
    assert_eq!(recorder.dropped(), SENDS - CAPACITY as u64);
    #[allow(deprecated)]
    let history = hub.history();
    assert!(history.is_empty(), "the hub itself retains nothing");
}

#[test]
fn zero_capacity_retains_nothing_and_counts_every_message() {
    let hub = MessageHub::new();
    let recorder = hub.record(0);

    hub.send(make_msg("a"));
    hub.send(make_msg("b"));

    assert!(recorder.is_empty());
    assert_eq!(recorder.dropped(), 2);
    assert!(recorder.is_active());
}

#[test]
fn capacity_one_keeps_only_the_newest_message() {
    let hub = MessageHub::new();
    let recorder = hub.record(1);

    hub.send(make_msg("a"));
    hub.send(make_msg("b"));

    assert_eq!(names(&recorder), ["b"]);
    assert_eq!(recorder.dropped(), 1);
}

#[test]
fn eviction_drops_the_oldest_messages_first() {
    let hub = MessageHub::new();
    let recorder = hub.record(3);

    for name in ["a", "b", "c", "d", "e"] {
        hub.send(make_msg(name));
    }

    assert_eq!(names(&recorder), ["c", "d", "e"]);
    assert_eq!(recorder.capacity(), 3);
    assert_eq!(recorder.dropped(), 2);
}

#[test]
fn batched_sends_are_recorded_at_acceptance_in_delivery_order() {
    let hub = MessageHub::new();
    let recorder = hub.record(8);
    let delivered = Arc::new(Mutex::new(Vec::new()));
    let log = delivered.clone();
    let _subscription = hub.subscribe(move |message| {
        if let Message::Custom { name, .. } = message {
            log.lock().unwrap().push(name.clone());
        }
    });

    let recorded_inside = hub.batch(|| {
        hub.send(make_msg("a"));
        hub.batch(|| hub.send(make_msg("b")));
        hub.send(make_msg("c"));
        names(&recorder)
    });

    assert_eq!(recorded_inside, ["a", "b", "c"], "recorded before delivery");
    assert_eq!(*delivered.lock().unwrap(), ["a", "b", "c"]);
    assert_eq!(names(&recorder), ["a", "b", "c"]);
}

#[test]
fn reentrant_sends_are_recorded_in_delivery_order() {
    let hub = MessageHub::new();
    let recorder = Arc::new(hub.record(8));
    let reentrant_hub = hub.clone();
    let seen_during_a = Arc::new(Mutex::new(Vec::new()));
    let seen = seen_during_a.clone();
    let observed = recorder.clone();
    let _producer = hub.subscribe(move |message| {
        if matches!(message, Message::Custom { name, .. } if name == "a") {
            reentrant_hub.send(make_msg("b"));
            reentrant_hub.send(make_msg("c"));
            *seen.lock().unwrap() = names(&observed);
        }
    });

    hub.send(make_msg("a"));
    hub.send(make_msg("d"));

    assert_eq!(*seen_during_a.lock().unwrap(), ["a", "b", "c"]);
    assert_eq!(names(&recorder), ["a", "b", "c", "d"]);
}

#[test]
fn disposing_the_hub_stops_recording_and_keeps_recorded_messages() {
    let hub = MessageHub::new();
    let recorder = hub.record(8);
    hub.send(make_msg("before"));

    hub.dispose();
    hub.send(make_msg("after"));

    assert!(!recorder.is_active());
    assert_eq!(names(&recorder), ["before"]);
    assert_eq!(recorder.dropped(), 0);
}

#[test]
fn a_recorder_made_on_a_disposed_hub_is_inactive() {
    let hub = MessageHub::new();
    hub.dispose();

    let recorder = hub.record(8);
    hub.send(make_msg("ignored"));

    assert!(!recorder.is_active());
    assert!(recorder.is_empty());
}

#[test]
fn disposing_a_recorder_detaches_it_and_keeps_its_messages() {
    let hub = MessageHub::new();
    let recorder = hub.record(8);
    hub.send(make_msg("kept"));

    recorder.dispose();
    recorder.dispose();
    hub.send(make_msg("ignored"));

    assert!(!recorder.is_active());
    assert_eq!(names(&recorder), ["kept"]);
}

#[test]
fn dropping_a_recorder_leaves_other_recorders_recording() {
    let hub = MessageHub::new();
    let kept = hub.record(8);
    drop(hub.record(8));

    hub.send(make_msg("a"));

    assert_eq!(names(&kept), ["a"]);
}

#[test]
fn clear_empties_the_recorder_and_keeps_the_drop_count() {
    let hub = MessageHub::new();
    let recorder = hub.record(1);
    hub.send(make_msg("a"));
    hub.send(make_msg("b"));

    recorder.clear();
    hub.send(make_msg("c"));

    assert_eq!(names(&recorder), ["c"]);
    assert_eq!(recorder.dropped(), 1);
}

#[test]
fn several_recorders_keep_independent_bounds() {
    let hub = MessageHub::new();
    let small = hub.record(1);
    let large = hub.record(4);

    for name in ["a", "b", "c"] {
        hub.send(make_msg(name));
    }

    assert_eq!(names(&small), ["c"]);
    assert_eq!(names(&large), ["a", "b", "c"]);
    assert_eq!((small.dropped(), large.dropped()), (2, 0));
}

#[test]
fn a_recorder_does_not_keep_its_hub_alive() {
    let capture = Arc::new(());
    let hub = MessageHub::new();
    let recorder = hub.record(8);
    let held = capture.clone();
    let _subscription = hub.subscribe(move |_| {
        let _ = &held;
    });

    drop(hub);

    assert_eq!(
        Arc::strong_count(&capture),
        1,
        "the hub and its subscribers were freed"
    );
    assert!(!recorder.is_active());
}

#[test]
#[allow(deprecated)]
fn deprecated_history_is_always_empty() {
    let hub = MessageHub::new();
    let _recorder = hub.record(8);

    hub.send(make_msg("a"));

    assert!(hub.history().is_empty());
}

// Delivery is identical with and without a recorder: each scenario runs on a
// fresh hub twice and must produce the same observations.
fn with_and_without_recording(scenario: impl Fn(&MessageHub) -> Vec<String>) -> Vec<String> {
    let plain = scenario(&MessageHub::new());
    let hub = MessageHub::new();
    let recorder = hub.record(64);
    let recorded = scenario(&hub);
    assert_eq!(plain, recorded, "recording changed delivery");
    assert!(recorder.len() + recorder.dropped() as usize > 0 || plain.is_empty());
    plain
}

fn logging_subscriber(hub: &MessageHub, log: &Arc<Mutex<Vec<String>>>, tag: &str) -> Subscription {
    let log = log.clone();
    let tag = tag.to_string();
    hub.subscribe(move |message| {
        if let Message::Custom { name, .. } = message {
            log.lock().unwrap().push(format!("{tag}:{name}"));
        }
    })
}

#[test]
fn recording_does_not_change_reentrant_fifo_order() {
    let observed = with_and_without_recording(|hub| {
        let log = Arc::new(Mutex::new(Vec::new()));
        let reentrant = hub.clone();
        let _producer = hub.subscribe(move |message| {
            if matches!(message, Message::Custom { name, .. } if name == "a") {
                reentrant.send(make_msg("b"));
                reentrant.batch(|| reentrant.send(make_msg("c")));
            }
        });
        let _logger = logging_subscriber(hub, &log, "s");
        hub.send(make_msg("a"));
        hub.batch(|| {
            hub.send(make_msg("d"));
            hub.send(make_msg("e"));
        });
        let result = log.lock().unwrap().clone();
        result
    });

    assert_eq!(observed, ["s:a", "s:b", "s:c", "s:d", "s:e"]);
}

#[test]
fn recording_does_not_change_subscriber_panic_isolation() {
    let observed = with_and_without_recording(|hub| {
        let log = Arc::new(Mutex::new(Vec::new()));
        let _failing = hub.subscribe(|_| panic!("subscriber failed"));
        let _logger = logging_subscriber(hub, &log, "s");
        hub.send(make_msg("a"));
        let batch = catch_unwind(AssertUnwindSafe(|| {
            hub.batch(|| {
                hub.send(make_msg("b"));
                panic!("transaction failed");
            })
        }));
        let mut result = log.lock().unwrap().clone();
        result.push(format!("batch panicked: {}", batch.is_err()));
        result
    });

    assert_eq!(observed, ["s:a", "s:b", "batch panicked: true"]);
}

#[test]
fn recording_does_not_change_disposal() {
    let observed = with_and_without_recording(|hub| {
        let log = Arc::new(Mutex::new(Vec::new()));
        let disposing = hub.clone();
        let _disposer = hub.subscribe(move |message| {
            if matches!(message, Message::Custom { name, .. } if name == "b") {
                disposing.send(make_msg("queued"));
                disposing.dispose();
            }
        });
        let _logger = logging_subscriber(hub, &log, "s");
        hub.batch(|| {
            hub.send(make_msg("a"));
            hub.send(make_msg("b"));
            hub.send(make_msg("c"));
        });
        hub.send(make_msg("after"));
        let result = log.lock().unwrap().clone();
        result
    });

    assert_eq!(observed, ["s:a", "s:b"]);
}
