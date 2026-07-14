use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use vmx::{
    Command, ComponentVm, ConstructionStatus, ForwardingComponentVm, Message, MessageHub,
    NullDispatcher, NullMessageHub, ReadonlyComponentVm,
};

/// CVM-001 — Construct emits ConstructionStatusChangedMessage(Constructed)
#[test]
fn component_construct_emits_status_messages() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model("vm", 1, hub.clone(), NullDispatcher::new());

    vm.construct().unwrap();

    let statuses = hub
        .history()
        .into_iter()
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
        ]
    );
}

/// CVM-002 — Modeled component fires PropertyChanged("Model") on set
#[test]
fn modeled_component_fires_model_property_changed() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model("vm", 1, hub.clone(), NullDispatcher::new());

    vm.set_model(2);

    assert!(hub.history().iter().any(
        |message| matches!(message, Message::PropertyChanged(change) if change.property_name == "model")
    ));
}

/// CVM-003 — ReadonlyComponentVM has no Model setter
#[test]
fn readonly_component_exposes_model_without_setter_surface() {
    let vm = ReadonlyComponentVm::new("readonly", 7, MessageHub::new(), NullDispatcher::new());

    assert_eq!(vm.model(), 7);
}

/// CVM-004 — ModeledHint recomputes when Model changes
#[test]
fn modeled_hint_recomputes_when_model_changes() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model("vm", 7, hub.clone(), NullDispatcher::new())
        .with_model_hint(|model| Some(format!("hint:{model}")));

    vm.set_model(8);

    assert_eq!(vm.hint(), Some("hint:8".to_string()));
    assert!(hub.history().iter().any(
        |message| matches!(message, Message::PropertyChanged(change) if change.property_name == "modeled_hint")
    ));
}

#[test]
fn modeled_hint_may_read_model_reentrantly() {
    let holder = Arc::new(Mutex::new(None::<ComponentVm<i32>>));
    let reentrant_holder = Arc::clone(&holder);
    let vm = ComponentVm::with_model("vm", 7, MessageHub::new(), NullDispatcher::new())
        .with_model_hint(move |model| {
            let vm = reentrant_holder.lock().unwrap().clone().unwrap();
            assert_eq!(vm.model(), *model);
            Some(format!("hint:{model}"))
        });
    *holder.lock().unwrap() = Some(vm.clone());
    let (completed, completion) = mpsc::channel();

    std::thread::spawn(move || {
        completed.send(vm.hint()).unwrap();
    });

    assert_eq!(
        completion
            .recv_timeout(Duration::from_secs(1))
            .expect("hint callback deadlocked while reading the model"),
        Some("hint:7".to_string())
    );
}

/// CVM-005 — Name and Hint are immutable post-construction
#[test]
fn name_and_hint_are_stable_after_construction() {
    let vm = ComponentVm::new("orig").with_model_hint(|_| Some("h".to_string()));

    vm.construct().unwrap();

    assert_eq!(vm.name(), "orig");
    assert_eq!(vm.hint(), Some("h".to_string()));
}

/// CVM-006 — SelectCommand can_execute reflects selection state
#[test]
fn select_command_can_execute_reflects_selection_state() {
    let vm = ComponentVm::new("vm");
    vm.construct().unwrap();
    let command = vm.select_command();

    assert!(command.can_execute());
    command.execute();
    assert!(!command.can_execute());
}

/// CVM-007 — Notification helper emits hub then local exactly once
#[test]
fn notification_helper_emits_hub_then_local_exactly_once() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model("probe", 0, hub.clone(), NullDispatcher::new());
    let value = Arc::new(Mutex::new(0));
    let trace = Arc::new(Mutex::new(Vec::new()));
    let hub_trace = trace.clone();
    let hub_value = value.clone();
    let _hub_subscription = hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(change) if change.property_name == "value") {
            hub_trace
                .lock()
                .unwrap()
                .push(format!("hub:{}", *hub_value.lock().unwrap()));
        }
    });
    let local_trace = trace.clone();
    let local_value = value.clone();
    let _local_subscription = vm.property_changed().subscribe(move |name| {
        local_trace
            .lock()
            .unwrap()
            .push(format!("local:{name}:{}", *local_value.lock().unwrap()));
    });

    *value.lock().unwrap() = 7;
    vm.notify_property_changed("value");

    assert_eq!(*trace.lock().unwrap(), vec!["hub:7", "local:value:7"]);
}

/// CVM-007 — Deferred delivery and re-entrant disposal preserve the admitted pair
#[test]
fn deferred_delivery_and_reentrant_disposal_complete_pair() {
    let batched_hub = MessageHub::new();
    let batched_vm =
        ComponentVm::with_model("batched", 0, batched_hub.clone(), NullDispatcher::new());
    let batched_trace = Arc::new(Mutex::new(Vec::new()));
    let hub_trace = batched_trace.clone();
    let _hub_subscription = batched_hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(change) if change.property_name == "value") {
            hub_trace.lock().unwrap().push("hub");
        }
    });
    let local_trace = batched_trace.clone();
    let _local_subscription = batched_vm
        .property_changed()
        .subscribe(move |_| local_trace.lock().unwrap().push("local"));

    batched_hub.batch(|| batched_vm.notify_property_changed("value"));

    assert_eq!(*batched_trace.lock().unwrap(), vec!["local", "hub"]);

    let disposing_hub = MessageHub::new();
    let disposing_vm =
        ComponentVm::with_model("disposing", 0, disposing_hub.clone(), NullDispatcher::new());
    let disposing_trace = Arc::new(Mutex::new(Vec::new()));
    let hub_trace = disposing_trace.clone();
    let vm_for_hub = disposing_vm.clone();
    let _disposing_hub_subscription = disposing_hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(change) if change.property_name == "value") {
            hub_trace.lock().unwrap().push("hub");
            vm_for_hub.dispose().unwrap();
        }
    });
    let local_trace = disposing_trace.clone();
    let _disposing_local_subscription = disposing_vm
        .property_changed()
        .subscribe(move |_| local_trace.lock().unwrap().push("local"));

    disposing_vm.notify_property_changed("value");

    assert_eq!(*disposing_trace.lock().unwrap(), vec!["hub", "local"]);
}

/// CVM-008 — Notification helper leaves equality to the caller
#[test]
fn equality_guard_suppresses_both_notification_channels() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model("probe", 0, hub.clone(), NullDispatcher::new());
    let local_names = Arc::new(Mutex::new(Vec::new()));
    let local_names_clone = local_names.clone();
    let _local_subscription = vm
        .property_changed()
        .subscribe(move |name| local_names_clone.lock().unwrap().push(name.to_string()));
    let mut value = 0;
    let mut set_value = |next| {
        if value == next {
            return;
        }
        value = next;
        vm.notify_property_changed("value");
    };

    set_value(7);
    set_value(7);

    let hub_count = hub
        .history()
        .iter()
        .filter(|message| {
            matches!(message, Message::PropertyChanged(change) if change.property_name == "value")
        })
        .count();
    assert_eq!(hub_count, 1);
    assert_eq!(*local_names.lock().unwrap(), vec!["value"]);
}

/// CVM-009 — Notification helper is inert after disposal
#[test]
fn notification_helper_is_inert_after_disposal() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model("probe", 0, hub.clone(), NullDispatcher::new());
    let local_names = Arc::new(Mutex::new(Vec::new()));
    let local_names_clone = local_names.clone();
    let _local_subscription = vm
        .property_changed()
        .subscribe(move |name| local_names_clone.lock().unwrap().push(name.to_string()));
    vm.dispose().unwrap();
    let hub_before = hub.history().len();

    vm.notify_property_changed("value");

    assert_eq!(hub.history().len(), hub_before);
    assert!(local_names.lock().unwrap().is_empty());
}

/// CVM-010 — Modeled components explicitly republish the retained model
#[test]
fn modeled_components_explicitly_republish_the_retained_model() {
    #[derive(Clone)]
    struct CountingModel {
        value: &'static str,
        equality_calls: Arc<AtomicUsize>,
    }

    impl PartialEq for CountingModel {
        fn eq(&self, other: &Self) -> bool {
            self.equality_calls.fetch_add(1, Ordering::SeqCst);
            self.value == other.value
        }
    }

    let equality_calls = Arc::new(AtomicUsize::new(0));
    let model = Arc::new(CountingModel {
        value: "model",
        equality_calls: equality_calls.clone(),
    });
    let hinter_calls = Arc::new(AtomicUsize::new(0));
    let hinter_calls_for_vm = hinter_calls.clone();
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model(
        "writable",
        model.clone(),
        hub.clone(),
        NullDispatcher::new(),
    )
    .with_model_hint(move |value| {
        hinter_calls_for_vm.fetch_add(1, Ordering::SeqCst);
        Some(format!("hint:{}", value.value))
    });
    let hint_before = vm.hint();
    let hinter_calls_before = hinter_calls.load(Ordering::SeqCst);
    let equality_calls_before_republish = equality_calls.load(Ordering::SeqCst);
    let trace = Arc::new(Mutex::new(Vec::new()));
    let hub_trace = trace.clone();
    let vm_id = vm.id();
    let _hub_subscription = hub.subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(change) if change.property_name == "model" && change.sender_id == vm_id)
        {
            hub_trace.lock().unwrap().push("hub:model");
        }
    });
    let local_trace = trace.clone();
    let _local_subscription = vm.property_changed().subscribe(move |name| {
        if name == "model" {
            local_trace.lock().unwrap().push("local:model");
        }
    });

    vm.republish_model();

    assert!(Arc::ptr_eq(&vm.model(), &model));
    assert_eq!(hinter_calls.load(Ordering::SeqCst), hinter_calls_before);
    assert_eq!(
        equality_calls.load(Ordering::SeqCst),
        equality_calls_before_republish
    );
    assert_eq!(vm.hint(), hint_before);
    assert_eq!(*trace.lock().unwrap(), vec!["hub:model", "local:model"]);

    trace.lock().unwrap().clear();
    vm.set_model(model.clone());
    assert!(trace.lock().unwrap().is_empty());

    let replacement = Arc::new(CountingModel {
        value: "replacement",
        equality_calls: equality_calls.clone(),
    });
    trace.lock().unwrap().clear();
    vm.set_model(replacement.clone());

    assert!(Arc::ptr_eq(&vm.model(), &replacement));
    assert_eq!(vm.hint().as_deref(), Some("hint:replacement"));
    assert!(hinter_calls.load(Ordering::SeqCst) > hinter_calls_before);
    assert!(equality_calls.load(Ordering::SeqCst) > equality_calls_before_republish);
    assert_eq!(*trace.lock().unwrap(), vec!["hub:model", "local:model"]);

    let readonly_hub = MessageHub::new();
    let readonly_vm = ReadonlyComponentVm::new(
        "readonly",
        model.clone(),
        readonly_hub.clone(),
        NullDispatcher::new(),
    );
    let readonly_local = Arc::new(Mutex::new(Vec::new()));
    let readonly_local_for_subscription = readonly_local.clone();
    let _readonly_subscription = readonly_vm.property_changed().subscribe(move |name| {
        readonly_local_for_subscription
            .lock()
            .unwrap()
            .push(name.to_string());
    });

    readonly_vm.republish_model();

    assert!(Arc::ptr_eq(&readonly_vm.model(), &model));
    assert_eq!(
        readonly_hub
            .history()
            .iter()
            .filter(|message| matches!(message, Message::PropertyChanged(change) if change.property_name == "model"))
            .count(),
        1
    );
    assert_eq!(*readonly_local.lock().unwrap(), vec!["model"]);

    let wrapped_hub = MessageHub::new();
    let wrapped = ComponentVm::with_model(
        "wrapped",
        model.clone(),
        wrapped_hub.clone(),
        NullDispatcher::new(),
    );
    let forwarding = ForwardingComponentVm::new(wrapped.clone());
    let forwarded_local = Arc::new(Mutex::new(Vec::new()));
    let forwarded_local_for_subscription = forwarded_local.clone();
    let _forwarded_subscription = forwarding.property_changed().subscribe(move |name| {
        forwarded_local_for_subscription
            .lock()
            .unwrap()
            .push(name.to_string());
    });

    forwarding.republish_model();

    assert!(wrapped_hub.history().iter().any(
        |message| matches!(message, Message::PropertyChanged(change) if change.property_name == "model" && change.sender_id == wrapped.id())
    ));
    assert_eq!(*forwarded_local.lock().unwrap(), vec!["model"]);

    let null_vm = ComponentVm::with_model(
        "null",
        model.clone(),
        NullMessageHub::hub(),
        NullDispatcher::new(),
    );
    let null_local = Arc::new(Mutex::new(Vec::new()));
    let null_local_for_subscription = null_local.clone();
    let _null_subscription = null_vm.property_changed().subscribe(move |name| {
        null_local_for_subscription
            .lock()
            .unwrap()
            .push(name.to_string());
    });

    null_vm.republish_model();

    assert_eq!(*null_local.lock().unwrap(), vec!["model"]);

    let disposed_hub = MessageHub::new();
    let disposed_vm = ComponentVm::with_model(
        "disposed",
        model.clone(),
        disposed_hub.clone(),
        NullDispatcher::new(),
    );
    let disposed_local = Arc::new(Mutex::new(Vec::new()));
    let disposed_local_for_subscription = disposed_local.clone();
    let _disposed_subscription = disposed_vm.property_changed().subscribe(move |name| {
        disposed_local_for_subscription
            .lock()
            .unwrap()
            .push(name.to_string());
    });
    disposed_vm.dispose().unwrap();
    let disposed_history_before = disposed_hub.history().len();

    disposed_vm.republish_model();

    assert_eq!(disposed_hub.history().len(), disposed_history_before);
    assert!(disposed_local.lock().unwrap().is_empty());

    let reentrant_hub = MessageHub::new();
    let reentrant_vm = ComponentVm::with_model(
        "reentrant",
        model,
        reentrant_hub.clone(),
        NullDispatcher::new(),
    );
    let reentered = Arc::new(AtomicBool::new(false));
    let reentrant_trace = Arc::new(Mutex::new(Vec::new()));
    let hub_trace = reentrant_trace.clone();
    let reentered_for_hub = reentered.clone();
    let vm_for_hub = reentrant_vm.clone();
    let _reentrant_hub_subscription = reentrant_hub.subscribe(move |message| {
        if !matches!(message, Message::PropertyChanged(change) if change.property_name == "model") {
            return;
        }
        hub_trace.lock().unwrap().push("hub:model");
        if !reentered_for_hub.swap(true, Ordering::SeqCst) {
            vm_for_hub.republish_model();
        }
    });
    let local_trace = reentrant_trace.clone();
    let _reentrant_local_subscription = reentrant_vm.property_changed().subscribe(move |name| {
        if name == "model" {
            local_trace.lock().unwrap().push("local:model");
        }
    });

    reentrant_vm.republish_model();

    assert_eq!(
        *reentrant_trace.lock().unwrap(),
        vec!["hub:model", "local:model", "hub:model", "local:model"]
    );
}
