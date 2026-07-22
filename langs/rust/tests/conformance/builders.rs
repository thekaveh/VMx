use std::sync::{Arc, Mutex};

use vmx::{
    ComponentVm, ComponentVmOptions, CompositeVm, CompositeVmOptions, GroupVm, GroupVmOptions,
    Message, MessageHub, NullDispatcher, RelayCommand,
};

type Child = ComponentVm<&'static str>;

fn child(name: &'static str) -> Child {
    Child::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

/// BLD-001 — Setter returns a new builder instance
#[test]
fn setter_returns_new_builder_instance() {
    let b1 = ComponentVm::<&'static str>::builder();
    let b2 = b1.clone().name("vm");

    assert!(format!("{:p}", &b1) != format!("{:p}", &b2));
}

/// BLD-002 — Required fields validated on Build
#[test]
fn required_fields_are_validated() {
    let result = ComponentVm::<&'static str>::builder()
        .name("vm")
        .model("model")
        .build();

    assert!(matches!(result, Err(vmx::VmxError::BuilderValidation(_))));
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
    assert_eq!(vm.modeled_hint(), Some("modeled:model".to_string()));
}

/// BLD-005 — Additive setters retain prior values across repeated calls
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
}

/// BLD-006 — Common VM options factories match builder semantics
#[test]
fn common_options_factories_match_builder_shape() {
    let composite_child = child("a");
    let component = ComponentVm::create(ComponentVmOptions {
        name: Some("component".to_string()),
        hint: Some("hint".to_string()),
        model: Some("model"),
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
    })
    .unwrap();
    let composite = CompositeVm::create(CompositeVmOptions {
        name: Some("composite".to_string()),
        hint: None,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
        children: Some(vec![composite_child]),
        auto_construct_on_add: false,
    })
    .unwrap();
    let group = GroupVm::create(GroupVmOptions {
        name: Some("group".to_string()),
        hint: None,
        hub: MessageHub::new(),
        dispatcher: NullDispatcher::new(),
        children: Some(vec![child("b")]),
        auto_construct_on_add: false,
    })
    .unwrap();

    assert_eq!(component.name(), "component");
    assert_eq!(component.hint(), Some("hint".to_string()));
    assert_eq!(composite.len(), 1);
    assert_eq!(group.len(), 1);
}
