use std::sync::{Arc, Mutex};

use vmx::{ComponentVm, CompositeVm, Dispatcher, ManualDispatcher, Message, MessageHub};

/// THR-001 — PropertyChanged observed on foreground scheduler
#[test]
fn property_changed_can_be_observed_on_foreground_dispatcher() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::with_model("vm", 1, hub.clone(), dispatcher.clone());
    let observed = Arc::new(Mutex::new(0));
    let observed_inner = observed.clone();
    let observer_dispatcher = dispatcher.clone();
    let _subscription = hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(_)) {
            let observed_inner = observed_inner.clone();
            observer_dispatcher.dispatch(Box::new(move || *observed_inner.lock().unwrap() += 1));
        }
    });

    vm.set_model(2);
    assert_eq!(*observed.lock().unwrap(), 0);
    dispatcher.drain();
    assert_eq!(*observed.lock().unwrap(), 1);
}

/// THR-002 — Background construct dispatches on background scheduler
#[test]
fn construct_completion_can_be_scheduled() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::with_model("vm", 1, hub.clone(), dispatcher.clone());

    vm.construct().unwrap();

    assert_eq!(dispatcher.queued_len(), 1);
    dispatcher.drain();
    assert!(hub
        .history()
        .iter()
        .any(|message| matches!(message, Message::ConstructionStatusChanged(_))));
}

/// THR-003 — CollectionChanged observed on foreground scheduler
#[test]
fn collection_changed_can_be_observed_on_foreground_dispatcher() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let composite = CompositeVm::<ComponentVm, ManualDispatcher>::with_services(
        "items",
        hub.clone(),
        dispatcher.clone(),
    );
    let observed = Arc::new(Mutex::new(0));
    let observed_inner = observed.clone();
    let observer_dispatcher = dispatcher.clone();
    let _subscription = hub.subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(_)) {
            let observed_inner = observed_inner.clone();
            observer_dispatcher.dispatch(Box::new(move || *observed_inner.lock().unwrap() += 1));
        }
    });

    composite.add(ComponentVm::new("child")).unwrap();
    assert_eq!(*observed.lock().unwrap(), 0);
    dispatcher.drain();
    assert_eq!(*observed.lock().unwrap(), 1);
}

/// THR-004 — Subscriber observes on chosen scheduler via ObserveOn
#[test]
fn subscriber_can_observe_on_chosen_dispatcher() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let observed = Arc::new(Mutex::new(false));
    let observed_inner = observed.clone();
    let observer_dispatcher = dispatcher.clone();
    let _subscription = hub.subscribe(move |_| {
        let observed_inner = observed_inner.clone();
        observer_dispatcher.dispatch(Box::new(move || *observed_inner.lock().unwrap() = true));
    });

    hub.send(Message::Custom {
        sender_id: 1,
        sender_name: "sender".to_string(),
        name: "tick".to_string(),
    });
    assert!(!*observed.lock().unwrap());
    dispatcher.drain();
    assert!(*observed.lock().unwrap());
}
