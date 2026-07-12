use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use vmx::{ComponentVm, Message, MessageHub, NullDispatcher, SubscribeValueOptions, Subscription};

#[derive(Clone, PartialEq)]
struct SelectedModel {
    value: i32,
}

#[derive(Clone)]
struct NonPartialEqValue {
    value: i32,
}

fn make_vm(
    hub: &MessageHub,
    name: &str,
    value: i32,
) -> Arc<ComponentVm<SelectedModel, NullDispatcher>> {
    Arc::new(ComponentVm::with_model(
        name,
        SelectedModel { value },
        hub.clone(),
        NullDispatcher::new(),
    ))
}

/// SUBV-001 — Fixed-source filtering, default equality, and immediate delivery
#[test]
fn subscribe_value_filters_source_and_uses_default_equality() {
    let hub = MessageHub::new();
    let vm = make_vm(&hub, "source", 0);
    let other = make_vm(&hub, "other", 0);
    let selector_calls = Arc::new(AtomicUsize::new(0));
    let observations = Arc::new(Mutex::new(Vec::new()));
    let selector_vm = vm.clone();
    let calls = selector_calls.clone();
    let seen = observations.clone();
    let _subscription = hub.subscribe_value(
        vm.id(),
        move || {
            calls.fetch_add(1, Ordering::SeqCst);
            selector_vm.model().value
        },
        move |current, previous| seen.lock().unwrap().push((current, previous)),
        SubscribeValueOptions::default().fire_immediately(true),
    );

    assert_eq!(*observations.lock().unwrap(), vec![(0, 0)]);
    assert_eq!(selector_calls.load(Ordering::SeqCst), 1);

    other.set_model(SelectedModel { value: 1 });
    hub.send(Message::Custom {
        sender_id: vm.id(),
        name: "not-property-changed".to_string(),
    });
    assert_eq!(selector_calls.load(Ordering::SeqCst), 1);

    vm.republish_model();
    vm.set_model(SelectedModel { value: 1 });
    vm.republish_model();
    vm.set_model(SelectedModel { value: 2 });

    assert_eq!(selector_calls.load(Ordering::SeqCst), 5);
    assert_eq!(*observations.lock().unwrap(), vec![(0, 0), (1, 0), (2, 1)]);
}

/// SUBV-002 — Custom equality evaluates exactly once per matching message
#[test]
fn subscribe_value_supports_counted_custom_equality_without_partial_eq() {
    let hub = MessageHub::new();
    let vm = make_vm(&hub, "source", 0);
    let other = make_vm(&hub, "other", 0);
    let selector_calls = Arc::new(AtomicUsize::new(0));
    let comparisons = Arc::new(Mutex::new(Vec::new()));
    let observations = Arc::new(Mutex::new(Vec::new()));

    let selector_vm = vm.clone();
    let calls = selector_calls.clone();
    let compared = comparisons.clone();
    let seen = observations.clone();
    let _subscription = hub.subscribe_value(
        vm.id(),
        move || {
            calls.fetch_add(1, Ordering::SeqCst);
            NonPartialEqValue {
                value: selector_vm.model().value,
            }
        },
        move |current, previous| {
            seen.lock().unwrap().push((current.value, previous.value));
        },
        SubscribeValueOptions::with_equality(
            move |current: &NonPartialEqValue, next: &NonPartialEqValue| {
                compared.lock().unwrap().push((current.value, next.value));
                current.value % 2 == next.value % 2
            },
        ),
    );

    vm.set_model(SelectedModel { value: 1 });
    vm.set_model(SelectedModel { value: 3 });
    other.set_model(SelectedModel { value: 2 });
    hub.send(Message::Custom {
        sender_id: vm.id(),
        name: "not-property-changed".to_string(),
    });

    assert_eq!(selector_calls.load(Ordering::SeqCst), 3);
    assert_eq!(*comparisons.lock().unwrap(), vec![(0, 1), (1, 3)]);
    assert_eq!(*observations.lock().unwrap(), vec![(1, 0)]);
}

/// SUBV-003 — Re-entrant FIFO, batch suppression, and deterministic disposal
#[test]
fn subscribe_value_preserves_order_until_disposed() {
    let hub = MessageHub::new();
    let vm = make_vm(&hub, "source", 0);
    let observations = Arc::new(Mutex::new(Vec::new()));
    let selector_vm = vm.clone();
    let callback_vm = vm.clone();
    let seen = observations.clone();
    let subscription = hub.subscribe_value(
        vm.id(),
        move || selector_vm.model().value,
        move |current, previous| {
            seen.lock().unwrap().push((current, previous));
            if current == 1 {
                callback_vm.set_model(SelectedModel { value: 2 });
            }
        },
        SubscribeValueOptions::default(),
    );

    vm.set_model(SelectedModel { value: 1 });
    assert_eq!(*observations.lock().unwrap(), vec![(1, 0), (2, 1)]);

    hub.batch(|| {
        vm.set_model(SelectedModel { value: 3 });
        vm.set_model(SelectedModel { value: 4 });
    });
    assert_eq!(*observations.lock().unwrap(), vec![(1, 0), (2, 1), (4, 2)]);

    subscription.dispose();
    vm.set_model(SelectedModel { value: 5 });
    assert_eq!(observations.lock().unwrap().len(), 3);

    let disposing_vm = make_vm(&hub, "disposing", 0);
    let disposing_observations = Arc::new(Mutex::new(Vec::new()));
    let disposing_selector_calls = Arc::new(AtomicUsize::new(0));
    let subscription_slot: Arc<Mutex<Option<Subscription>>> = Arc::new(Mutex::new(None));
    let selector_vm = disposing_vm.clone();
    let calls = disposing_selector_calls.clone();
    let callback_vm = disposing_vm.clone();
    let seen = disposing_observations.clone();
    let callback_slot = subscription_slot.clone();
    let disposing_subscription = hub.subscribe_value(
        disposing_vm.id(),
        move || {
            calls.fetch_add(1, Ordering::SeqCst);
            selector_vm.model().value
        },
        move |current, previous| {
            seen.lock().unwrap().push((current, previous));
            callback_slot
                .lock()
                .unwrap()
                .as_ref()
                .expect("subscription is installed before delivery")
                .dispose();
            callback_vm.set_model(SelectedModel { value: 2 });
        },
        SubscribeValueOptions::default(),
    );
    *subscription_slot.lock().unwrap() = Some(disposing_subscription);

    disposing_vm.set_model(SelectedModel { value: 1 });
    disposing_vm.set_model(SelectedModel { value: 3 });

    assert_eq!(*disposing_observations.lock().unwrap(), vec![(1, 0)]);
    assert_eq!(disposing_selector_calls.load(Ordering::SeqCst), 2);
}

/// SUBV-004 — Setup panics propagate and delivery panics retain the baseline
#[test]
fn subscribe_value_propagates_setup_panics_and_isolates_delivery_panics() {
    let hub = MessageHub::new();
    let selector_vm = make_vm(&hub, "selector", 0);
    let failed_selector_calls = Arc::new(AtomicUsize::new(0));
    let calls = failed_selector_calls.clone();
    let selector_result = catch_unwind(AssertUnwindSafe(|| {
        hub.subscribe_value(
            selector_vm.id(),
            move || {
                calls.fetch_add(1, Ordering::SeqCst);
                panic!("initial selector failed")
            },
            |_current: i32, _previous: i32| {},
            SubscribeValueOptions::default(),
        )
    }));
    assert!(selector_result.is_err());
    selector_vm.republish_model();
    assert_eq!(failed_selector_calls.load(Ordering::SeqCst), 1);

    let immediate_vm = make_vm(&hub, "immediate", 0);
    let immediate_selector_calls = Arc::new(AtomicUsize::new(0));
    let calls = immediate_selector_calls.clone();
    let selected_vm = immediate_vm.clone();
    let immediate_result = catch_unwind(AssertUnwindSafe(|| {
        hub.subscribe_value(
            immediate_vm.id(),
            move || {
                calls.fetch_add(1, Ordering::SeqCst);
                selected_vm.model().value
            },
            |_current, _previous| panic!("immediate callback failed"),
            SubscribeValueOptions::default().fire_immediately(true),
        )
    }));
    assert!(immediate_result.is_err());
    immediate_vm.republish_model();
    assert_eq!(immediate_selector_calls.load(Ordering::SeqCst), 1);

    let delivery_vm = make_vm(&hub, "delivery", 0);
    let observations = Arc::new(Mutex::new(Vec::new()));
    let healthy_deliveries = Arc::new(AtomicUsize::new(0));
    let healthy_vm_id = delivery_vm.id();
    let healthy_calls = healthy_deliveries.clone();
    let _healthy_subscription = hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(change) if change.sender_id == healthy_vm_id)
        {
            healthy_calls.fetch_add(1, Ordering::SeqCst);
        }
    });
    let selected_vm = delivery_vm.clone();
    let seen = observations.clone();
    let _failing_subscription = hub.subscribe_value(
        delivery_vm.id(),
        move || selected_vm.model().value,
        move |current, previous| {
            seen.lock().unwrap().push((current, previous));
            if current == 1 {
                panic!("delivery callback failed");
            }
        },
        SubscribeValueOptions::default(),
    );

    delivery_vm.set_model(SelectedModel { value: 1 });
    delivery_vm.set_model(SelectedModel { value: 2 });

    assert_eq!(*observations.lock().unwrap(), vec![(1, 0), (2, 1)]);
    assert_eq!(healthy_deliveries.load(Ordering::SeqCst), 2);

    let selector_delivery_vm = make_vm(&hub, "selector-delivery", 0);
    let selector_observations = Arc::new(Mutex::new(Vec::new()));
    let selector_calls = Arc::new(AtomicUsize::new(0));
    let selector_equality_calls = Arc::new(AtomicUsize::new(0));
    let selector_healthy_deliveries = Arc::new(AtomicUsize::new(0));
    let fail_next_selector = Arc::new(AtomicBool::new(false));
    let selector_vm_id = selector_delivery_vm.id();
    let healthy_calls = selector_healthy_deliveries.clone();
    let _selector_healthy_subscription = hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(change) if change.sender_id == selector_vm_id)
        {
            healthy_calls.fetch_add(1, Ordering::SeqCst);
        }
    });
    let selected_vm = selector_delivery_vm.clone();
    let calls = selector_calls.clone();
    let fail_next = fail_next_selector.clone();
    let equality_calls = selector_equality_calls.clone();
    let seen = selector_observations.clone();
    let _selector_subscription = hub.subscribe_value(
        selector_delivery_vm.id(),
        move || {
            calls.fetch_add(1, Ordering::SeqCst);
            if fail_next.swap(false, Ordering::SeqCst) {
                panic!("delivery selector failed");
            }
            selected_vm.model().value
        },
        move |current, previous| seen.lock().unwrap().push((current, previous)),
        SubscribeValueOptions::with_equality(move |current: &i32, next: &i32| {
            equality_calls.fetch_add(1, Ordering::SeqCst);
            current == next
        }),
    );

    fail_next_selector.store(true, Ordering::SeqCst);
    selector_delivery_vm.set_model(SelectedModel { value: 1 });
    selector_delivery_vm.set_model(SelectedModel { value: 2 });

    assert_eq!(selector_calls.load(Ordering::SeqCst), 3);
    assert_eq!(selector_equality_calls.load(Ordering::SeqCst), 1);
    assert_eq!(*selector_observations.lock().unwrap(), vec![(2, 0)]);
    assert_eq!(selector_healthy_deliveries.load(Ordering::SeqCst), 2);

    let equality_delivery_vm = make_vm(&hub, "equality-delivery", 0);
    let equality_observations = Arc::new(Mutex::new(Vec::new()));
    let equality_selector_calls = Arc::new(AtomicUsize::new(0));
    let equality_calls = Arc::new(AtomicUsize::new(0));
    let equality_healthy_deliveries = Arc::new(AtomicUsize::new(0));
    let equality_vm_id = equality_delivery_vm.id();
    let healthy_calls = equality_healthy_deliveries.clone();
    let _equality_healthy_subscription = hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(change) if change.sender_id == equality_vm_id)
        {
            healthy_calls.fetch_add(1, Ordering::SeqCst);
        }
    });
    let selected_vm = equality_delivery_vm.clone();
    let selector_calls = equality_selector_calls.clone();
    let compared = equality_calls.clone();
    let seen = equality_observations.clone();
    let _equality_subscription = hub.subscribe_value(
        equality_delivery_vm.id(),
        move || {
            selector_calls.fetch_add(1, Ordering::SeqCst);
            selected_vm.model().value
        },
        move |current, previous| seen.lock().unwrap().push((current, previous)),
        SubscribeValueOptions::with_equality(move |current: &i32, next: &i32| {
            let call = compared.fetch_add(1, Ordering::SeqCst);
            if call == 0 {
                panic!("delivery equality failed");
            }
            current == next
        }),
    );

    equality_delivery_vm.set_model(SelectedModel { value: 1 });
    equality_delivery_vm.set_model(SelectedModel { value: 2 });

    assert_eq!(equality_selector_calls.load(Ordering::SeqCst), 3);
    assert_eq!(equality_calls.load(Ordering::SeqCst), 2);
    assert_eq!(*equality_observations.lock().unwrap(), vec![(2, 0)]);
    assert_eq!(equality_healthy_deliveries.load(Ordering::SeqCst), 2);
}
