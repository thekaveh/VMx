use vmx::{
    Command, ComponentVm, ConstructionStatus, Message, MessageHub, NullDispatcher,
    ReadonlyComponentVm,
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
