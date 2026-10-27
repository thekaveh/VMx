use std::sync::{Arc, Mutex};

use vmx::{
    ChildOrder, Command, ComponentVm, ComponentVmOptions, CompositeVm, CompositeVmOptions, GroupVm,
    GroupVmOptions, Message, MessageHub, NullDispatcher, RelayCommand, ViewModelType,
};

type Child = ComponentVm<&'static str>;

fn child(name: &'static str) -> Child {
    Child::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

/// BLD-001 — Setter returns a new builder instance
#[test]
fn setter_returns_new_builder_instance() {
    let b1 = ComponentVm::<&'static str>::builder()
        .model("model")
        .services(MessageHub::new(), NullDispatcher::new());
    let b2 = b1.clone().name("vm");

    // b1 keeps no name; b2 carries the one set on it.
    assert!(matches!(
        b1.build(),
        Err(vmx::VmxError::BuilderValidation(message)) if message.contains("name")
    ));
    assert_eq!(b2.build().unwrap().name(), "vm");
}

/// BLD-002 — Required fields validated on Build
#[test]
fn required_fields_are_validated() {
    let result = ComponentVm::<&'static str>::builder()
        .name("vm")
        .model("model")
        .build();

    // Missing `services(...)`: the diagnostic names the first missing
    // service field (the Rust builder stores hub and dispatcher separately).
    assert!(matches!(
        &result,
        Err(vmx::VmxError::BuilderValidation(message)) if message.contains("hub")
    ));

    let missing_model = ComponentVm::<&'static str>::builder()
        .name("vm")
        .services(MessageHub::new(), NullDispatcher::new())
        .build();
    assert!(matches!(
        &missing_model,
        Err(vmx::VmxError::BuilderValidation(message)) if message.contains("model")
    ));
}

/// BLD-003 — Repeated identical Build calls produce equivalent VMs
#[test]
fn repeated_build_calls_produce_equivalent_distinct_vms() {
    let builder = ComponentVm::<&'static str>::builder()
        .name("vm")
        .hint("hint")
        .model("model")
        .services(MessageHub::new(), NullDispatcher::new());

    let first = builder.clone().build().unwrap();
    let second = builder.build().unwrap();

    assert_eq!(first.name(), second.name());
    assert_eq!(first.hint(), second.hint());
    assert_ne!(first.id(), second.id());
}

/// BLD-004 — Field defaults applied when not set
#[test]
fn field_defaults_are_applied() {
    let vm = ComponentVm::<&'static str>::builder()
        .name("vm")
        .model("model")
        .model_hint(|model| Some(format!("modeled:{model}")))
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .unwrap();

    assert_eq!(vm.hint(), Some(String::new()));
    assert_eq!(vm.parent_id(), None);
    assert_eq!(vm.view_model_type(), ViewModelType::Component);
    assert_eq!(vm.modeled_hint(), Some("modeled:model".to_string()));
}

/// BLD-005 — Additive setters retain prior values across repeated calls
///
/// Insertion order of the accumulated triggers is not observable through the
/// Rust public API: `RelayCommandBuilder` keeps its trigger list private and
/// each trigger raises an indistinguishable eligibility change, so only the
/// cumulative count and per-trigger delivery are asserted. The non-additive
/// overwrite clause is pinned through `action`.
#[test]
fn relay_command_trigger_setter_is_additive() {
    let trigger_a = MessageHub::new();
    let trigger_b = MessageHub::new();
    let builder = RelayCommand::builder()
        .trigger(trigger_a.clone())
        .trigger(trigger_b.clone());
    assert_eq!(builder.trigger_count(), 2);
    let command = builder.build();
    let hits = Arc::new(Mutex::new(0));
    let seen = hits.clone();
    let _subscription = command.can_execute_changed().subscribe(move |_| {
        *seen.lock().unwrap() += 1;
    });

    trigger_a.send(Message::Custom {
        sender_id: 0,
        sender_name: "trigger_a".to_string(),
        name: "a".to_string(),
    });
    trigger_b.send(Message::Custom {
        sender_id: 0,
        sender_name: "trigger_b".to_string(),
        name: "b".to_string(),
    });

    assert_eq!(*hits.lock().unwrap(), 2);

    // Non-additive setter: a repeated `action` overwrites the earlier one.
    let calls = Arc::new(Mutex::new(Vec::new()));
    let first = calls.clone();
    let second = calls.clone();
    let overwritten = RelayCommand::builder()
        .action(move || first.lock().unwrap().push("first"))
        .action(move || second.lock().unwrap().push("second"))
        .build();
    overwritten.execute();
    assert_eq!(*calls.lock().unwrap(), vec!["second"]);
}

/// BLD-006 — Common VM options factories match builder semantics
///
/// The partial-service-pair clause is not representable in Rust: the options
/// structs take non-optional `hub` and `dispatcher` fields, so a partial pair
/// cannot be constructed.
#[test]
fn common_options_factories_match_builder_shape() {
    let composite_child = child("a");
    let component = ComponentVm::create(ComponentVmOptions {
        name: Some("component".to_string()),
        hint: Some("hint".to_string()),
        model: Some("model"),
        view_model_type: ViewModelType::Aggregate,
        background: false,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
    })
    .unwrap();
    let builder_component = ComponentVm::builder()
        .name("component")
        .hint("hint")
        .model("model")
        .view_model_type(ViewModelType::Aggregate)
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .unwrap();
    let composite = CompositeVm::create(CompositeVmOptions {
        name: Some("composite".to_string()),
        hint: None,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
        children: Some(vec![composite_child]),
        auto_construct_on_add: false,
        destruct_order: ChildOrder::Insertion,
    })
    .unwrap();
    let group = GroupVm::create(GroupVmOptions {
        name: Some("group".to_string()),
        hint: None,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
        children: Some(vec![child("b")]),
        auto_construct_on_add: false,
        destruct_order: ChildOrder::Insertion,
    })
    .unwrap();

    assert_eq!(component.name(), "component");
    assert_eq!(component.hint(), Some("hint".to_string()));
    assert_eq!(component.name(), builder_component.name());
    assert_eq!(component.hint(), builder_component.hint());
    assert_eq!(component.model(), builder_component.model());
    assert_eq!(component.view_model_type(), ViewModelType::Aggregate);
    assert_eq!(
        component.view_model_type(),
        builder_component.view_model_type()
    );
    assert_eq!(composite.len(), 1);
    assert_eq!(group.len(), 1);
    assert_eq!(composite.name(), "composite");
    assert_eq!(group.name(), "group");

    // Missing required fields go through the same BuilderValidation path and
    // diagnostic as the fluent builder.
    let options_missing_name = ComponentVm::create(ComponentVmOptions {
        name: None,
        hint: None,
        model: Some("model"),
        view_model_type: ViewModelType::Component,
        background: false,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
    });
    let builder_missing_name = ComponentVm::<&'static str>::builder()
        .model("model")
        .services(MessageHub::new(), NullDispatcher::new())
        .build();
    match (options_missing_name, builder_missing_name) {
        (
            Err(vmx::VmxError::BuilderValidation(options_message)),
            Err(vmx::VmxError::BuilderValidation(builder_message)),
        ) => {
            assert!(options_message.contains("name"));
            assert_eq!(options_message, builder_message);
        }
        _ => panic!("both paths must fail BuilderValidation for a missing name"),
    }
    let options_missing_model = ComponentVm::<&'static str>::create(ComponentVmOptions {
        name: Some("component".to_string()),
        hint: None,
        model: None,
        view_model_type: ViewModelType::Component,
        background: false,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
    });
    assert!(matches!(
        &options_missing_model,
        Err(vmx::VmxError::BuilderValidation(message)) if message.contains("model")
    ));
    let composite_missing_name = CompositeVm::<Child>::create(CompositeVmOptions {
        name: None,
        hint: None,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
        children: Some(Vec::new()),
        auto_construct_on_add: false,
        destruct_order: ChildOrder::Insertion,
    });
    assert!(matches!(
        &composite_missing_name,
        Err(vmx::VmxError::BuilderValidation(message)) if message.contains("name")
    ));
    let group_missing_children = GroupVm::<Child>::create(GroupVmOptions {
        name: Some("group".to_string()),
        hint: None,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
        children: None,
        auto_construct_on_add: false,
        destruct_order: ChildOrder::Insertion,
    });
    assert!(matches!(
        &group_missing_children,
        Err(vmx::VmxError::BuilderValidation(message)) if message.contains("children")
    ));
}

/// The senders of the Destructed messages that `destruct` publishes on `hub`,
/// in publication order (ADR-0161).
fn destruct_walk(hub: &MessageHub, destruct: impl FnOnce()) -> Vec<String> {
    let recorder = hub.record(64);
    destruct();
    recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change)
                if change.status == vmx::ConstructionStatus::Destructed =>
            {
                Some(change.sender_name)
            }
            _ => None,
        })
        .collect()
}

fn shared_children(hub: &MessageHub) -> Vec<Child> {
    ["a", "b", "c"]
        .into_iter()
        .map(|name| Child::with_model(name, name, hub.clone(), NullDispatcher::new()))
        .collect()
}

/// BLD-004 — `destruct_order` defaults to `ChildOrder::Insertion`, and the
/// setter returns a builder whose original keeps the default
#[test]
fn destruct_order_defaults_to_insertion_and_setter_is_immutable() {
    assert_eq!(ChildOrder::default(), ChildOrder::Insertion);

    let hub = MessageHub::new();
    let child_hub = hub.clone();
    let base = GroupVm::builder()
        .name("group")
        .services(hub.clone(), NullDispatcher::new())
        .children(move || shared_children(&child_hub));
    let reverse = base
        .clone()
        .destruct_order(ChildOrder::Reverse)
        .build()
        .unwrap();
    reverse.construct().unwrap();
    assert_eq!(
        destruct_walk(&hub, || reverse.destruct().unwrap()),
        ["c", "b", "a", "group"]
    );
    reverse.dispose().unwrap();

    let default_group = base.build().unwrap();
    default_group.construct().unwrap();
    assert_eq!(
        destruct_walk(&hub, || default_group.destruct().unwrap()),
        ["a", "b", "c", "group"]
    );

    let hub = MessageHub::new();
    let child_hub = hub.clone();
    let base = CompositeVm::builder()
        .name("composite")
        .services(hub.clone(), NullDispatcher::new())
        .children(move || shared_children(&child_hub));
    let reverse = base
        .clone()
        .destruct_order(ChildOrder::Reverse)
        .build()
        .unwrap();
    reverse.construct().unwrap();
    assert_eq!(
        destruct_walk(&hub, || reverse.destruct().unwrap()),
        ["c", "b", "a", "composite"]
    );
    reverse.dispose().unwrap();

    let default_composite = base.build().unwrap();
    default_composite.construct().unwrap();
    assert_eq!(
        destruct_walk(&hub, || default_composite.destruct().unwrap()),
        ["a", "b", "c", "composite"]
    );
}

/// BLD-006 — the `destruct_order` options field matches the builder setter
#[test]
fn destruct_order_options_field_matches_builder() {
    let hub = MessageHub::new();
    let group = GroupVm::create(GroupVmOptions {
        name: Some("group".to_string()),
        hint: None,
        hub: hub.clone(),
        dispatcher: NullDispatcher::new(),
        children: Some(shared_children(&hub)),
        auto_construct_on_add: false,
        destruct_order: ChildOrder::Reverse,
    })
    .unwrap();
    group.construct().unwrap();
    assert_eq!(
        destruct_walk(&hub, || group.destruct().unwrap()),
        ["c", "b", "a", "group"]
    );

    let hub = MessageHub::new();
    let composite = CompositeVm::create(CompositeVmOptions {
        name: Some("composite".to_string()),
        hint: None,
        hub: hub.clone(),
        dispatcher: NullDispatcher::new(),
        children: Some(shared_children(&hub)),
        auto_construct_on_add: false,
        destruct_order: ChildOrder::Insertion,
    })
    .unwrap();
    composite.construct().unwrap();
    assert_eq!(
        destruct_walk(&hub, || composite.destruct().unwrap()),
        ["a", "b", "c", "composite"]
    );
}
