//! #799 — a container's reconstruct command runs `reconstruct()`, so both
//! publish the same hub messages in the same order.

use vmx::{Command, ConstructionStatus, Message, MessageHub, NullDispatcher};

type Child = vmx::ComponentVm<&'static str>;

fn child(name: &'static str, hub: &MessageHub) -> Child {
    Child::with_model(name, name, hub.clone(), NullDispatcher::new())
}

/// Records the hub messages that `action` publishes.
fn recorded(hub: &MessageHub, action: impl FnOnce()) -> Vec<Message> {
    let recorder = hub.record(1024);
    action();
    assert_eq!(recorder.dropped(), 0, "the recorder kept every message");
    recorder.messages()
}

#[test]
fn composite_reconstruct_command_publishes_what_reconstruct_publishes() {
    let hub = MessageHub::new();
    let composite =
        vmx::CompositeVm::<Child>::with_services("composite", hub.clone(), NullDispatcher::new());
    composite.add(child("first", &hub)).unwrap();
    composite.add(child("second", &hub)).unwrap();
    composite.set_current_selector(|items| items.last().cloned());
    composite.construct().unwrap();
    assert_eq!(
        composite.current().map(|item| item.name()),
        Some("second".into())
    );

    let direct = recorded(&hub, || composite.reconstruct().unwrap());
    let command = recorded(&hub, || composite.reconstruct_command().execute());

    assert!(
        direct.iter().any(|message| matches!(
            message,
            Message::PropertyChanged(change)
                if change.sender_id == composite.id() && change.property_name == "current"
        )),
        "the walk clears and reselects the current child: {direct:?}"
    );
    assert_eq!(command, direct);
    assert_eq!(composite.status(), ConstructionStatus::Constructed);
    assert_eq!(
        composite.current().map(|item| item.name()),
        Some("second".into())
    );
}

#[test]
fn group_reconstruct_command_publishes_what_reconstruct_publishes() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::<Child>::with_services("group", hub.clone(), NullDispatcher::new());
    group.add(child("first", &hub)).unwrap();
    group.add(child("second", &hub)).unwrap();
    group.construct().unwrap();

    let direct = recorded(&hub, || group.reconstruct().unwrap());
    let command = recorded(&hub, || group.reconstruct_command().execute());

    let children = group.items();
    assert!(
        children
            .iter()
            .all(|item| direct.iter().any(|message| matches!(
                message,
                Message::ConstructionStatusChanged(change) if change.sender_id == item.id()
            ))),
        "the walk reaches every child: {direct:?}"
    );
    assert_eq!(command, direct);
    assert_eq!(group.status(), ConstructionStatus::Constructed);
    assert!(children
        .iter()
        .all(|item| item.status() == ConstructionStatus::Constructed));
}

#[test]
fn a_kept_reconstruct_command_does_not_keep_a_dropped_container_as_parent() {
    let hub = MessageHub::new();
    let composite =
        vmx::CompositeVm::<Child>::with_services("composite", hub.clone(), NullDispatcher::new());
    let composite_child = child("composite-child", &hub);
    composite.add(composite_child.clone()).unwrap();
    let composite_command = composite.reconstruct_command();
    drop(composite);
    assert_eq!(composite_child.parent_id(), None);

    let group = vmx::GroupVm::<Child>::with_services("group", hub.clone(), NullDispatcher::new());
    let group_child = child("group-child", &hub);
    group.add(group_child.clone()).unwrap();
    let group_command = group.reconstruct_command();
    drop(group);
    assert_eq!(group_child.parent_id(), None);

    let messages = recorded(&hub, || {
        composite_command.execute();
        group_command.execute();
    });
    assert!(
        messages.is_empty(),
        "a command whose container is gone does nothing"
    );
}
