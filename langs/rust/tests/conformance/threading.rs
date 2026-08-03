use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use vmx::{
    Command, ComponentVm, CompositeVm, ConstructionStatus, DefaultDispatcher, Dispatcher,
    ManualDispatcher, Message, MessageHub, ReadonlyComponentVm,
};

#[test]
fn default_dispatcher_separates_foreground_and_background_execution() {
    let dispatcher = DefaultDispatcher::new();
    let caller = thread::current().id();
    let (foreground_send, foreground_receive) = mpsc::channel();
    dispatcher.dispatch(Box::new(move || {
        foreground_send
            .send((
                thread::current().id(),
                thread::current().name().map(str::to_string),
            ))
            .unwrap();
    }));
    let (background_send, background_receive) = mpsc::channel();

    dispatcher.dispatch_background(Box::new(move || {
        background_send
            .send((
                thread::current().id(),
                thread::current().name().map(str::to_string),
            ))
            .unwrap();
    }));

    let foreground = foreground_receive
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    let background = background_receive
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    assert_ne!(foreground.0, caller);
    assert_ne!(background.0, caller);
    assert_ne!(foreground.0, background.0);
    assert_eq!(foreground.1.as_deref(), Some("vmx-foreground"));
    assert_eq!(background.1.as_deref(), Some("vmx-background"));
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
    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    assert_eq!(dispatcher.foreground_queued_len(), 1);
    dispatcher.drain_foreground();
    assert_eq!(vm.status(), ConstructionStatus::Constructed);
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
fn completed_background_hook_cannot_publish_after_foreground_disposal() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::builder()
        .name("vm")
        .model(1)
        .background(true)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();

    vm.construct().unwrap();
    dispatcher.drain_background();
    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    vm.dispose().unwrap();
    dispatcher.drain_foreground();

    assert_eq!(vm.status(), ConstructionStatus::Disposed);
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
            ConstructionStatus::Disposed
        ]
    );
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
    let (error_send, error_receive) = mpsc::channel();
    let _error_subscription = vm.background_errors().subscribe(move |error| {
        error_send.send(error).unwrap();
    });
    let expected_error = vmx::VmxError::Other("failed".to_string());
    let hook_error = expected_error.clone();
    vm.on_construct(move || Err(hook_error.clone()));

    vm.construct().unwrap();
    dispatcher.drain_background();

    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    assert_eq!(dispatcher.foreground_queued_len(), 1);
    dispatcher.drain_foreground();
    assert_eq!(vm.status(), ConstructionStatus::Destructed);
    assert_eq!(error_receive.try_recv().unwrap(), expected_error);
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
    assert_eq!(vm.status(), ConstructionStatus::Destructing);
    dispatcher.drain_foreground();
    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    dispatcher.drain_background();
    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    dispatcher.drain_foreground();
    assert_eq!(vm.status(), ConstructionStatus::Constructed);

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

#[test]
fn background_reconstruct_command_delegates_the_complete_transition() {
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::builder()
        .name("vm")
        .model(1)
        .background(true)
        .services(MessageHub::new(), dispatcher.clone())
        .build()
        .unwrap();
    vm.construct().unwrap();
    dispatcher.drain();

    vm.reconstruct_command().execute();
    assert_eq!(vm.status(), ConstructionStatus::Destructing);
    dispatcher.drain();

    assert_eq!(vm.status(), ConstructionStatus::Constructed);
}

#[test]
fn readonly_builder_preserves_background_lifecycle_configuration() {
    let dispatcher = ManualDispatcher::new();
    let vm = ReadonlyComponentVm::<i32>::builder()
        .name("readonly")
        .model(1)
        .background(true)
        .services(MessageHub::new(), dispatcher.clone())
        .build()
        .unwrap();

    vm.construct().unwrap();
    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    dispatcher.drain_background();
    assert_eq!(vm.status(), ConstructionStatus::Constructing);
    dispatcher.drain_foreground();
    assert_eq!(vm.status(), ConstructionStatus::Constructed);
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
