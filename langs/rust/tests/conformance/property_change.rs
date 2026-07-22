use std::sync::{Arc, Mutex};
use vmx::{ComponentVm, Message, MessageHub, NullDispatcher, PropertyChangedMessage};

#[derive(Clone, PartialEq, Debug)]
struct TestModel {
    id: u32,
    name: &'static str,
}

fn property_messages(hub: &MessageHub) -> Arc<Mutex<Vec<PropertyChangedMessage>>> {
    let messages = Arc::new(Mutex::new(Vec::new()));
    let messages_clone = messages.clone();
    let _subscription = hub.subscribe(move |message| {
        if let Message::PropertyChanged(property) = message {
            messages_clone.lock().unwrap().push(property.clone());
        }
    });
    std::mem::forget(_subscription);
    messages
}

/// PROP-001 — Setting a property to a different value publishes PropertyChangedMessage
#[test]
fn setting_different_model_publishes_property_changed() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model(
        "vm1",
        TestModel {
            id: 1,
            name: "Alice",
        },
        hub.clone(),
        NullDispatcher::new(),
    );
    let messages = property_messages(&hub);

    vm.set_model(TestModel { id: 2, name: "Bob" });

    let model_messages = messages
        .lock()
        .unwrap()
        .iter()
        .filter(|message| message.property_name == "model")
        .cloned()
        .collect::<Vec<_>>();
    assert_eq!(model_messages.len(), 1);
    assert_eq!(model_messages[0].sender_id, vm.id());
}

/// PROP-002 — Setting a property to the same value does NOT publish
#[test]
fn setting_same_model_does_not_publish_property_changed() {
    let hub = MessageHub::new();
    let model = TestModel {
        id: 1,
        name: "Alice",
    };
    let vm = ComponentVm::with_model("vm1", model.clone(), hub.clone(), NullDispatcher::new());
    let messages = property_messages(&hub);

    vm.set_model(model);

    assert!(messages.lock().unwrap().is_empty());
}

/// PROP-003 — Sender identity equals the VM instance
#[test]
fn property_changed_sender_id_matches_vm_id() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model(
        "vm1",
        TestModel {
            id: 1,
            name: "Alice",
        },
        hub.clone(),
        NullDispatcher::new(),
    );
    let messages = property_messages(&hub);

    vm.set_model(TestModel { id: 2, name: "Bob" });

    assert_eq!(messages.lock().unwrap()[0].sender_id, vm.id());
}

/// PROP-004 — PropertyName equals the property's name and SenderName equals the VM's name
#[test]
fn property_changed_property_name_matches_model() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_model(
        "vm1",
        TestModel {
            id: 1,
            name: "Alice",
        },
        hub.clone(),
        NullDispatcher::new(),
    );
    let messages = property_messages(&hub);

    vm.set_model(TestModel { id: 2, name: "Bob" });

    let messages = messages.lock().unwrap();
    assert_eq!(messages[0].property_name, "model");
    assert_eq!(messages[0].sender_name, "vm1");
    assert_eq!(
        Message::PropertyChanged(messages[0].clone()).sender_name(),
        "vm1"
    );
}
