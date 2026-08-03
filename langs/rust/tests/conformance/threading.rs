use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, DefaultDispatcher, Dispatcher, ManualDispatcher,
    Message, MessageHub,
};

#[test]
fn default_dispatcher_separates_foreground_and_background_execution() {
    let dispatcher = DefaultDispatcher::new();
    let caller = thread::current().id();
    let (send, receive) = mpsc::channel();

    dispatcher.dispatch_background(Box::new(move || {
        send.send(thread::current().id()).unwrap();
    }));

    assert_ne!(receive.recv().unwrap(), caller);
}

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
    let vm = ComponentVm::builder()
        .name("vm")
        .model(1)
        .background(true)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let hook_ran = Arc::new(Mutex::new(false));
    let hook_observed = Arc::clone(&hook_ran);
    vm.on_construct(move || {
        *hook_observed.lock().unwrap() = true;
        Ok(())
    });

    vm.construct().unwrap();

    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    assert!(!*hook_ran.lock().unwrap());
    assert_eq!(dispatcher.background_queued_len(), 1);
    dispatcher.drain_background();
    assert!(*hook_ran.lock().unwrap());
    assert_eq!(vm.status(), ConstructionStatus::Constructed);
    assert_eq!(dispatcher.foreground_queued_len(), 1);
    dispatcher.drain_foreground();
    assert_eq!(
        hub.history()
            .iter()
            .filter(|message| matches!(message, Message::ConstructionStatusChanged(_)))
            .count(),
        2
    );
}

#[test]
fn queued_background_construct_cannot_resurrect_a_disposed_component() {
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::builder()
        .name("vm")
        .model(1)
        .background(true)
        .services(MessageHub::new(), dispatcher.clone())
        .build()
        .unwrap();
    let hook_ran = Arc::new(AtomicBool::new(false));
    let hook_observed = Arc::clone(&hook_ran);
    vm.on_construct(move || {
        hook_observed.store(true, Ordering::SeqCst);
        Ok(())
    });

    vm.construct().unwrap();
    vm.dispose().unwrap();
    dispatcher.drain();

    assert_eq!(vm.status(), ConstructionStatus::Disposed);
    assert!(!hook_ran.load(Ordering::SeqCst));
}

#[test]
fn background_hook_failure_rolls_back_and_publishes_on_foreground() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::builder()
        .name("vm")
        .model(1)
        .background(true)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    vm.on_construct(|| Err(vmx::VmxError::Other("failed".to_string())));

    vm.construct().unwrap();
    dispatcher.drain_background();

    assert_eq!(vm.status(), ConstructionStatus::Destructed);
    assert_eq!(dispatcher.foreground_queued_len(), 1);
    dispatcher.drain_foreground();
    let statuses = hub
        .history()
        .iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change) => Some(change.status),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        statuses,
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Destructed
        ]
    );
}

#[test]
fn background_hook_panic_rolls_back_instead_of_wedging_lifecycle() {
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::builder()
        .name("vm")
        .model(1)
        .background(true)
        .services(MessageHub::new(), dispatcher.clone())
        .build()
        .unwrap();
    vm.on_construct(|| panic!("boom"));

    vm.construct().unwrap();
    dispatcher.drain_background();
    dispatcher.drain_foreground();

    assert_eq!(vm.status(), ConstructionStatus::Destructed);
    assert!(vm.construct().is_ok());
}

#[test]
fn background_reconstruct_sequences_both_hooks_across_paired_channels() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::builder()
        .name("vm")
        .model(1)
        .background(true)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let hooks = Arc::new(Mutex::new(Vec::new()));
    let construct_hooks = Arc::clone(&hooks);
    vm.on_construct(move || {
        construct_hooks.lock().unwrap().push("construct");
        Ok(())
    });
    let destruct_hooks = Arc::clone(&hooks);
    vm.on_destruct(move || {
        destruct_hooks.lock().unwrap().push("destruct");
        Ok(())
    });
    vm.construct().unwrap();
    dispatcher.drain();

    vm.reconstruct().unwrap();
    assert_eq!(vm.status(), ConstructionStatus::Destructing);
    dispatcher.drain_background();
    assert_eq!(vm.status(), ConstructionStatus::Destructed);
    dispatcher.drain_foreground();
    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    dispatcher.drain_background();
    assert_eq!(vm.status(), ConstructionStatus::Constructed);
    dispatcher.drain_foreground();

    assert_eq!(
        *hooks.lock().unwrap(),
        vec!["construct", "destruct", "construct"]
    );
    let statuses = hub
        .history()
        .iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change) => Some(change.status),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        statuses,
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed,
            ConstructionStatus::Destructing,
            ConstructionStatus::Destructed,
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed,
        ]
    );
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
