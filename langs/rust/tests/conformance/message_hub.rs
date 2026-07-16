use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::time::Duration;
use vmx::{Message, MessageHub, Subscription};

fn make_msg(name: &str) -> Message {
    Message::Custom {
        sender_id: 1,
        name: name.to_string(),
    }
}

fn custom_name(message: &Message) -> &str {
    match message {
        Message::Custom { name, .. } => name,
        _ => panic!("expected custom message"),
    }
}

/// HUB-001 — Send delivers to current subscribers
#[test]
fn send_delivers_to_current_subscribers() {
    let hub = MessageHub::new();
    let received = Arc::new(Mutex::new(Vec::new()));
    let received_clone = received.clone();
    let _subscription =
        hub.subscribe(move |message| received_clone.lock().unwrap().push(message.clone()));

    hub.send(make_msg("A"));

    assert_eq!(received.lock().unwrap().len(), 1);
    assert_eq!(custom_name(&received.lock().unwrap()[0]), "A");
}

/// HUB-002 — Late subscribers do not see prior messages
#[test]
fn late_subscribers_do_not_see_prior_messages() {
    let hub = MessageHub::new();
    hub.send(make_msg("A"));
    let received = Arc::new(Mutex::new(Vec::new()));
    let received_clone = received.clone();
    let _subscription = hub.subscribe(move |message| {
        received_clone
            .lock()
            .unwrap()
            .push(custom_name(message).to_string());
    });

    hub.send(make_msg("B"));
    hub.send(make_msg("C"));

    assert_eq!(*received.lock().unwrap(), vec!["B", "C"]);
}

/// HUB-003 — Single-producer FIFO order
#[test]
fn single_producer_fifo_order() {
    let hub = MessageHub::new();
    let received = Arc::new(Mutex::new(Vec::new()));
    let received_clone = received.clone();
    let _subscription = hub.subscribe(move |message| {
        received_clone
            .lock()
            .unwrap()
            .push(custom_name(message).to_string());
    });

    hub.send(make_msg("A"));
    hub.send(make_msg("B"));
    hub.send(make_msg("C"));

    assert_eq!(*received.lock().unwrap(), vec!["A", "B", "C"]);
}

/// HUB-004 — Subscriber dispose during emit does not crash
#[test]
fn subscriber_dispose_during_emit_does_not_crash() {
    let hub = MessageHub::new();
    let received = Arc::new(Mutex::new(Vec::new()));
    let subscription_slot: Arc<Mutex<Option<Subscription>>> = Arc::new(Mutex::new(None));
    let received_clone = received.clone();
    let subscription_slot_clone = subscription_slot.clone();
    let subscription = hub.subscribe(move |message| {
        received_clone
            .lock()
            .unwrap()
            .push(custom_name(message).to_string());
        if let Some(subscription) = subscription_slot_clone.lock().unwrap().as_ref() {
            subscription.dispose();
        }
    });
    *subscription_slot.lock().unwrap() = Some(subscription);

    hub.send(make_msg("A"));
    hub.send(make_msg("B"));

    assert_eq!(*received.lock().unwrap(), vec!["A"]);
}

/// HUB-005 — Multiple subscribers each observe every post-subscribe message
#[test]
fn multiple_subscribers_each_observe_every_message() {
    let hub = MessageHub::new();
    let mut buckets = Vec::new();
    for _ in 0..3 {
        let bucket = Arc::new(Mutex::new(Vec::new()));
        let bucket_clone = bucket.clone();
        let _subscription = hub.subscribe(move |message| {
            bucket_clone
                .lock()
                .unwrap()
                .push(custom_name(message).to_string());
        });
        std::mem::forget(_subscription);
        buckets.push(bucket);
    }

    hub.send(make_msg("A"));
    hub.send(make_msg("B"));

    for bucket in buckets {
        assert_eq!(*bucket.lock().unwrap(), vec!["A", "B"]);
    }
}

/// HUB-006 — Hub matches message-ordering fixture
#[test]
fn hub_matches_message_ordering_fixture() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../spec/fixtures/message-ordering.json"
    ))
    .unwrap();
    assert_eq!(
        fixture["scenarios"][0]["id"], "single-producer-fifo",
        "fixture must be available to Rust tests"
    );
    single_producer_fifo_order();
    late_subscribers_do_not_see_prior_messages();
    multiple_subscribers_each_observe_every_message();
    subscriber_dispose_during_emit_does_not_crash();
}

/// HUB-007 — Subscriber handler that raises does not break the hub
#[test]
fn throwing_subscriber_does_not_break_hub() {
    let hub = MessageHub::new();
    let _bad = hub.subscribe(|_| panic!("subscriber failed"));
    let received = Arc::new(Mutex::new(Vec::new()));
    let received_clone = received.clone();
    let _good = hub.subscribe(move |message| {
        received_clone
            .lock()
            .unwrap()
            .push(custom_name(message).to_string());
    });

    hub.send(make_msg("msg1"));
    hub.send(make_msg("msg2"));

    assert_eq!(*received.lock().unwrap(), vec!["msg1", "msg2"]);
}

/// HUB-008 — Nested transactions defer and preserve every message
#[test]
fn nested_batches_defer_and_preserve_fifo() {
    let hub = MessageHub::new();
    let received = Arc::new(Mutex::new(Vec::new()));
    let received_clone = received.clone();
    let _subscription = hub.subscribe(move |message| {
        received_clone
            .lock()
            .unwrap()
            .push(custom_name(message).to_string());
    });

    hub.batch(|| {
        hub.send(make_msg("A"));
        hub.batch(|| hub.send(make_msg("B")));
        hub.send(make_msg("C"));
        assert!(received.lock().unwrap().is_empty());
    });

    assert_eq!(*received.lock().unwrap(), vec!["A", "B", "C"]);
}

/// HUB-009 — Transaction error drains then rethrows the original error
#[test]
fn batch_panic_drains_then_resumes_original_panic() {
    #[derive(Debug)]
    struct Sentinel;

    let hub = MessageHub::new();
    let received = Arc::new(Mutex::new(Vec::new()));
    let received_clone = received.clone();
    let _subscription = hub.subscribe(move |message| {
        received_clone
            .lock()
            .unwrap()
            .push(custom_name(message).to_string());
    });

    let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        hub.batch(|| {
            hub.send(make_msg("A"));
            std::panic::panic_any(Sentinel);
        });
    }))
    .expect_err("the original panic must be resumed");

    assert!(panic.downcast_ref::<Sentinel>().is_some());
    assert_eq!(*received.lock().unwrap(), vec!["A"]);
}

/// HUB-010 — Re-entrant send joins the iterative FIFO drain
#[test]
fn reentrant_send_joins_iterative_fifo_drain() {
    let hub = MessageHub::new();
    let trace = Arc::new(Mutex::new(Vec::new()));
    let first_trace = trace.clone();
    let reentrant_hub = hub.clone();
    let _first = hub.subscribe(move |message| {
        first_trace
            .lock()
            .unwrap()
            .push(format!("first:{}", custom_name(message)));
        if custom_name(message) == "A" {
            reentrant_hub.batch(|| reentrant_hub.send(make_msg("B")));
        }
    });
    let second_trace = trace.clone();
    let _second = hub.subscribe(move |message| {
        second_trace
            .lock()
            .unwrap()
            .push(format!("second:{}", custom_name(message)));
    });

    hub.send(make_msg("A"));

    assert_eq!(
        *trace.lock().unwrap(),
        vec!["first:A", "second:A", "first:B", "second:B"]
    );
}

/// HUB-011 — Subscriber failure does not abort a transaction drain
#[test]
fn subscriber_failure_does_not_abort_batch_drain() {
    let hub = MessageHub::new();
    let _bad = hub.subscribe(|_| panic!("subscriber failed"));
    let received = Arc::new(Mutex::new(Vec::new()));
    let received_clone = received.clone();
    let _good = hub.subscribe(move |message| {
        received_clone
            .lock()
            .unwrap()
            .push(custom_name(message).to_string());
    });

    hub.batch(|| {
        hub.send(make_msg("A"));
        hub.send(make_msg("B"));
    });

    assert_eq!(*received.lock().unwrap(), vec!["A", "B"]);
}

/// HUB-012 — Disposing during a transaction drops queued messages
#[test]
fn dispose_during_batch_drops_queued_messages() {
    let hub = MessageHub::new();
    let received = Arc::new(Mutex::new(Vec::new()));
    let received_clone = received.clone();
    let _subscription = hub.subscribe(move |message| {
        received_clone
            .lock()
            .unwrap()
            .push(custom_name(message).to_string());
    });

    hub.batch(|| {
        hub.send(make_msg("A"));
        hub.dispose();
        hub.send(make_msg("B"));
    });
    hub.send(make_msg("C"));

    assert!(received.lock().unwrap().is_empty());
}

/// HUB-013 — Ordinary sends remain synchronous outside transactions
#[test]
fn ordinary_send_remains_synchronous() {
    let hub = MessageHub::new();
    let delivered = Arc::new(Mutex::new(false));
    let delivered_clone = delivered.clone();
    let _subscription = hub.subscribe(move |_| *delivered_clone.lock().unwrap() = true);

    hub.send(make_msg("A"));

    assert!(*delivered.lock().unwrap());
}

#[test]
fn opposing_hub_callbacks_do_not_deadlock() {
    let left = MessageHub::new();
    let right = MessageHub::new();
    let callbacks_entered = Arc::new(Barrier::new(2));
    let inner_deliveries = Arc::new(AtomicUsize::new(0));

    let _left_subscription = left.subscribe({
        let right = right.clone();
        let callbacks_entered = callbacks_entered.clone();
        let inner_deliveries = inner_deliveries.clone();
        move |message| {
            if custom_name(message) == "outer" {
                callbacks_entered.wait();
                right.send(make_msg("inner"));
            } else {
                inner_deliveries.fetch_add(1, Ordering::SeqCst);
            }
        }
    });
    let _right_subscription = right.subscribe({
        let left = left.clone();
        let callbacks_entered = callbacks_entered.clone();
        let inner_deliveries = inner_deliveries.clone();
        move |message| {
            if custom_name(message) == "outer" {
                callbacks_entered.wait();
                left.send(make_msg("inner"));
            } else {
                inner_deliveries.fetch_add(1, Ordering::SeqCst);
            }
        }
    });

    let (returned_tx, returned_rx) = mpsc::channel();
    let left_worker = std::thread::spawn({
        let left = left.clone();
        let returned_tx = returned_tx.clone();
        move || {
            left.send(make_msg("outer"));
            returned_tx.send(()).unwrap();
        }
    });
    let right_worker = std::thread::spawn(move || {
        right.send(make_msg("outer"));
        returned_tx.send(()).unwrap();
    });

    returned_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    returned_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    left_worker.join().unwrap();
    right_worker.join().unwrap();
    assert_eq!(inner_deliveries.load(Ordering::SeqCst), 2);
}

#[test]
fn concurrent_producer_waits_for_batch_and_delivers_on_own_thread() {
    let hub = MessageHub::new();
    let delivery_thread = Arc::new(Mutex::new(None));
    let delivery_thread_clone = delivery_thread.clone();
    let _subscription = hub.subscribe(move |_| {
        *delivery_thread_clone.lock().unwrap() = Some(std::thread::current().id());
    });
    let (batch_entered_tx, batch_entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let batch_hub = hub.clone();
    let batch_worker = std::thread::spawn(move || {
        batch_hub.batch(|| {
            batch_entered_tx.send(()).unwrap();
            release_rx.recv().unwrap();
        });
    });
    batch_entered_rx.recv().unwrap();

    let (started_tx, started_rx) = mpsc::channel();
    let (finished_tx, finished_rx) = mpsc::channel();
    let sender_hub = hub.clone();
    let send_worker = std::thread::spawn(move || {
        let producer_thread = std::thread::current().id();
        started_tx.send(()).unwrap();
        sender_hub.send(make_msg("concurrent"));
        finished_tx.send(producer_thread).unwrap();
    });
    started_rx.recv().unwrap();
    assert!(finished_rx.recv_timeout(Duration::from_millis(50)).is_err());
    release_tx.send(()).unwrap();
    batch_worker.join().unwrap();
    let producer_thread = finished_rx.recv_timeout(Duration::from_secs(1)).unwrap();
    send_worker.join().unwrap();

    assert_eq!(*delivery_thread.lock().unwrap(), Some(producer_thread));
}

#[cfg(debug_assertions)]
#[test]
fn development_drain_diagnostic_names_message_type() {
    let hub = MessageHub::new();
    let reentrant_hub = hub.clone();
    let _subscription = hub.subscribe(move |message| reentrant_hub.send(message.clone()));

    let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        hub.send(make_msg("cycle"));
    }))
    .expect_err("a development publish cycle must panic");
    let text = panic
        .downcast_ref::<String>()
        .map(String::as_str)
        .or_else(|| panic.downcast_ref::<&str>().copied())
        .unwrap_or_default();

    assert!(text.contains("CustomMessage"), "diagnostic was: {text}");
}
