use std::sync::atomic::{AtomicBool, Ordering};
use vmx::{Dispatcher, Message, NullDispatcher, NullMessageHub};

/// NULL-001 — NullMessageHub is a safe no-op
#[test]
fn null_message_hub_is_safe_noop() {
    let hub = NullMessageHub::hub();
    let observed = std::sync::Arc::new(AtomicBool::new(false));
    let observed_clone = observed.clone();
    let _subscription = hub.subscribe(move |_| {
        observed_clone.store(true, Ordering::SeqCst);
    });

    hub.send(Message::Custom {
        sender_id: 1,
        sender_name: "sender".to_string(),
        name: "ignored".to_string(),
    });
    let body_ran = AtomicBool::new(false);
    hub.batch(|| {
        body_ran.store(true, Ordering::SeqCst);
        hub.send(Message::Custom {
            sender_id: 1,
            sender_name: "sender".to_string(),
            name: "also ignored".to_string(),
        });
    });

    assert!(!observed.load(Ordering::SeqCst));
    assert!(body_ran.load(Ordering::SeqCst));
    assert!(hub.history().is_empty());
}

/// NULL-002 — NullDispatcher schedules synchronously on the calling thread
#[test]
fn null_dispatcher_schedules_synchronously() {
    let dispatcher = NullDispatcher::new();
    let ran = std::sync::Arc::new(AtomicBool::new(false));
    let ran_clone = ran.clone();

    dispatcher.dispatch(Box::new(move || {
        ran_clone.store(true, Ordering::SeqCst);
    }));

    assert!(ran.load(Ordering::SeqCst));
}

/// NULL-003 — Null-object convention is satisfied for the base core service contracts
#[test]
fn null_object_convention_is_satisfied() {
    null_message_hub_is_safe_noop();
    null_dispatcher_schedules_synchronously();
}
