use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use vmx::{
    AggregateVm1, AggregateVm2, AggregateVm3, AggregateVm4, AggregateVm5, AggregateVm6,
    AsyncResourceVm, Command, ComponentVm, CompositeVm, ConstructionStatus, FilteredCompositeVm,
    FormVm, ForwardingComponentVm, ForwardingCompositeVm, GroupVm, HierarchicalVm, Message,
    MessageHub, ModeledCompositeVm, NullDispatcher, NullMessageHub, ReadonlyComponentVm, TreeNode,
    ViewModelType, VmNode,
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
    let parent = vmx::CompositeVm::new("parent");

    fn require_component_traits<T: VmNode + TreeNode>(_: &T) {}

    require_component_traits(&vm);
    assert_eq!(vm.name(), "readonly");
    assert_eq!(vm.hint(), None);
    assert_eq!(vm.model(), 7);
    assert_eq!(vm.status(), ConstructionStatus::Destructed);

    parent.add(vm.clone()).unwrap();
    vm.construct().unwrap();
    assert!(vm.is_constructed());
    let select = vm.select_command();
    assert!(select.can_execute());
    select.execute();
    assert!(vm.is_current());
    assert_eq!(parent.current(), Some(vm.clone()));
    assert!(!select.can_execute());
}

#[test]
fn component_variants_expose_their_view_model_type() {
    let component = ComponentVm::new("component");
    let readonly =
        ReadonlyComponentVm::new("readonly", 1, MessageHub::new(), NullDispatcher::new());
    let tagged = ComponentVm::builder()
        .name("tagged")
        .model(())
        .view_model_type(ViewModelType::Aggregate)
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .unwrap();
    let forwarding = ForwardingComponentVm::new(tagged.clone());
    let nested_forwarding = ForwardingComponentVm::wrap(forwarding.clone());
    let twice_nested_forwarding = ForwardingComponentVm::wrap(nested_forwarding.clone());

    assert_eq!(component.view_model_type(), ViewModelType::Component);
    assert_eq!(readonly.view_model_type(), ViewModelType::ReadOnlyComponent);
    assert_eq!(tagged.view_model_type(), ViewModelType::Aggregate);
    assert_eq!(
        forwarding.view_model_type(),
        tagged.view_model_type(),
        "forwarding must delegate the wrapped type"
    );
    assert_eq!(
        nested_forwarding.view_model_type(),
        tagged.view_model_type(),
        "nested forwarding must delegate through two layers"
    );
    assert_eq!(
        twice_nested_forwarding.view_model_type(),
        tagged.view_model_type(),
        "nested forwarding must delegate through three layers"
    );
}

#[test]
fn every_component_vm_family_exposes_its_canonical_view_model_type() {
    let group = GroupVm::<ComponentVm>::new("group");
    let composite = CompositeVm::<ComponentVm>::new("composite");
    let modeled = ModeledCompositeVm::new(
        "modeled",
        MessageHub::new(),
        NullDispatcher::new(),
        Vec::<i32>::new,
        |model| ComponentVm::with_model("child", model, MessageHub::new(), NullDispatcher::new()),
    );
    let filtered = FilteredCompositeVm::new(composite.clone(), |_| true);
    let forwarding = ForwardingCompositeVm::new(composite.clone());
    let hierarchy = HierarchicalVm::new("hierarchy", 1);
    let form = FormVm::new("form", 1);
    let resource = AsyncResourceVm::new("resource", |_| Ok::<_, vmx::VmxError>(1));

    assert_eq!(group.view_model_type(), ViewModelType::Group);
    assert_eq!(composite.view_model_type(), ViewModelType::Composite);
    assert_eq!(modeled.view_model_type(), ViewModelType::Composite);
    assert_eq!(filtered.view_model_type(), ViewModelType::Composite);
    assert_eq!(forwarding.view_model_type(), ViewModelType::Composite);
    assert_eq!(hierarchy.view_model_type(), ViewModelType::Component);
    assert_eq!(form.view_model_type(), ViewModelType::Component);
    assert_eq!(resource.view_model_type(), ViewModelType::Component);

    assert_eq!(
        AggregateVm1::new("a1", ComponentVm::new("a1c1")).view_model_type(),
        ViewModelType::Aggregate
    );
    assert_eq!(
        AggregateVm2::new("a2", ComponentVm::new("a2c1"), ComponentVm::new("a2c2"))
            .view_model_type(),
        ViewModelType::Aggregate
    );
    assert_eq!(
        AggregateVm3::new(
            "a3",
            ComponentVm::new("a3c1"),
            ComponentVm::new("a3c2"),
            ComponentVm::new("a3c3")
        )
        .view_model_type(),
        ViewModelType::Aggregate
    );
    assert_eq!(
        AggregateVm4::new(
            "a4",
            ComponentVm::new("a4c1"),
            ComponentVm::new("a4c2"),
            ComponentVm::new("a4c3"),
            ComponentVm::new("a4c4")
        )
        .view_model_type(),
        ViewModelType::Aggregate
    );
    assert_eq!(
        AggregateVm5::new(
            "a5",
            ComponentVm::new("a5c1"),
            ComponentVm::new("a5c2"),
            ComponentVm::new("a5c3"),
            ComponentVm::new("a5c4"),
            ComponentVm::new("a5c5")
        )
        .view_model_type(),
        ViewModelType::Aggregate
    );
    assert_eq!(
        AggregateVm6::new(
            "a6",
            ComponentVm::new("a6c1"),
            ComponentVm::new("a6c2"),
            ComponentVm::new("a6c3"),
            ComponentVm::new("a6c4"),
            ComponentVm::new("a6c5"),
            ComponentVm::new("a6c6")
        )
        .view_model_type(),
        ViewModelType::Aggregate
    );
}

#[test]
fn component_disposal_tears_down_all_retained_baseline_commands() {
    let vm = ComponentVm::new("component");
    let commands = [
        vm.select_command(),
        vm.deselect_command(),
        vm.select_next_command(),
        vm.select_previous_command(),
        vm.reconstruct_command(),
    ];
    let deliveries = Arc::new(AtomicUsize::new(0));
    let subscriptions = commands
        .iter()
        .map(|command| {
            let deliveries = Arc::clone(&deliveries);
            command.can_execute_changed().subscribe(move |_| {
                deliveries.fetch_add(1, Ordering::SeqCst);
            })
        })
        .collect::<Vec<_>>();

    vm.dispose().unwrap();
    let at_disposal = deliveries.load(Ordering::SeqCst);
    for command in &commands {
        assert!(!command.can_execute());
        command.raise_can_execute_changed();
    }

    assert_eq!(deliveries.load(Ordering::SeqCst), at_disposal);
    drop(subscriptions);
}

/// CVM-004 — ModeledHint recomputes when Model changes
#[test]
fn modeled_hint_recomputes_when_model_changes() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model("vm", 7, hub.clone(), NullDispatcher::new())
        .with_model_hint(|model| Some(format!("hint:{model}")));

    vm.set_model(8);

    assert_eq!(vm.hint(), None);
    assert_eq!(vm.modeled_hint(), Some("hint:8".to_string()));
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
        completed.send(vm.modeled_hint()).unwrap();
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
    let vm = ComponentVm::builder()
        .name("orig")
        .hint("fixed")
        .model(())
        .model_hint(|_| Some("modeled".to_string()))
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .unwrap();

    vm.construct().unwrap();

    assert_eq!(vm.name(), "orig");
    assert_eq!(vm.hint(), Some("fixed".to_string()));
    assert_eq!(vm.modeled_hint(), Some("modeled".to_string()));
}

/// CVM-006 — SelectCommand can_execute reflects selection state
#[test]
fn select_command_can_execute_reflects_selection_state() {
    let composite = vmx::CompositeVm::new("root");
    let vm = ComponentVm::new("vm");
    let command = vm.select_command();

    assert!(!vm.can_select());
    assert!(!command.can_execute());
    command.execute();
    assert!(!vm.is_current());

    composite.add(vm.clone()).unwrap();
    vm.construct().unwrap();

    assert!(vm.can_select());
    assert!(command.can_execute());
    command.execute();
    assert_eq!(composite.current(), Some(vm.clone()));
    assert!(vm.is_current());
    assert!(!command.can_execute());
}

#[test]
fn baseline_selection_commands_delegate_and_keep_stable_identity() {
    let composite = vmx::CompositeVm::new("root");
    let vm = ComponentVm::new("vm");
    composite.add(vm.clone()).unwrap();
    vm.construct().unwrap();

    let select = vm.select_command();
    let observed = Arc::new(Mutex::new(0));
    let seen = Arc::clone(&observed);
    let _subscription = select.can_execute_changed().subscribe(move |_| {
        *seen.lock().unwrap() += 1;
    });
    vm.destruct().unwrap();
    vm.construct().unwrap();
    assert_eq!(*observed.lock().unwrap(), 4);

    assert!(!vm.can_deselect());
    vm.select();
    assert!(vm.can_deselect());
    assert!(vm.deselect_command().can_execute());
    vm.deselect_command().execute();
    assert_eq!(composite.current(), None);

    assert!(!vm.select_next_command().can_execute());
    assert!(!vm.select_previous_command().can_execute());
    vm.reconstruct_command().execute();
    assert_eq!(vm.status(), ConstructionStatus::Constructed);
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
    let hint_before = vm.modeled_hint();
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
    assert_eq!(vm.modeled_hint(), hint_before);
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
    assert_eq!(vm.modeled_hint().as_deref(), Some("hint:replacement"));
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
