use std::sync::{Arc, Mutex};
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
