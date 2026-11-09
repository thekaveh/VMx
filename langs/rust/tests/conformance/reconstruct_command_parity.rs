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

/// Asserts that a kept reconstruct command is disabled and inert once its
/// container's last handle dropped (#1483).
fn assert_command_is_inert(hub: &MessageHub, command: &vmx::RelayCommand, container: &str) {
    assert!(
        !command.can_execute(),
        "a {container} command whose container is gone is disabled"
    );
    let messages = recorded(hub, || command.execute());
    assert!(
        messages.is_empty(),
        "a {container} command whose container is gone does nothing: {messages:?}"
    );
}

/// Asserts that `children` report no parent and can join another container.
fn assert_children_are_released(children: &[Child]) {
    let group = vmx::GroupVm::<Child>::new("next-parent");
    for child in children {
        assert_eq!(child.parent_id(), None, "{} has no parent", child.name());
        assert_eq!(group.add(child.clone()), Ok(()));
    }
}

/// Asserts that the command reconstructs `container` and every child while a
/// container handle exists.
fn assert_command_reconstructs(
    hub: &MessageHub,
    command: &vmx::RelayCommand,
    container: usize,
    children: &[Child],
) {
    assert!(command.can_execute());
    let messages = recorded(hub, || command.execute());
    for id in children.iter().map(Child::id).chain([container]) {
        for status in [
            ConstructionStatus::Destructed,
            ConstructionStatus::Constructed,
        ] {
            assert!(
                messages.iter().any(|message| matches!(
                    message,
                    Message::ConstructionStatusChanged(change)
                        if change.sender_id == id && change.status == status
                )),
                "the command reconstructs {id}: {messages:?}"
            );
        }
    }
}

#[test]
fn a_kept_reconstruct_command_is_disabled_once_its_container_drops() {
    let hub = MessageHub::new();

    let one = child("one", &hub);
    let aggregate1 = vmx::AggregateVm1::with_services(
        "aggregate1",
        hub.clone(),
        NullDispatcher::new(),
        one.clone(),
    );
    aggregate1.construct().unwrap();
    let aggregate1_command = aggregate1.reconstruct_command();
    assert_command_reconstructs(
        &hub,
        &aggregate1_command,
        aggregate1.id(),
        std::slice::from_ref(&one),
    );
    drop(aggregate1);

    let six: Vec<Child> = ["s1", "s2", "s3", "s4", "s5", "s6"]
        .into_iter()
        .map(|name| child(name, &hub))
        .collect();
    let aggregate6 = vmx::AggregateVm6::with_services(
        "aggregate6",
        hub.clone(),
        NullDispatcher::new(),
        six[0].clone(),
        six[1].clone(),
        six[2].clone(),
        six[3].clone(),
        six[4].clone(),
        six[5].clone(),
    );
    aggregate6.construct().unwrap();
    let aggregate6_command = aggregate6.reconstruct_command();
    assert_command_reconstructs(&hub, &aggregate6_command, aggregate6.id(), &six);
    drop(aggregate6);

    let composite =
        vmx::CompositeVm::<Child>::with_services("composite", hub.clone(), NullDispatcher::new());
    let composite_child = child("composite-child", &hub);
    composite.add(composite_child.clone()).unwrap();
    composite.construct().unwrap();
    let composite_command = composite.reconstruct_command();
    assert_command_reconstructs(
        &hub,
        &composite_command,
        composite.id(),
        std::slice::from_ref(&composite_child),
    );
    drop(composite);

    let group = vmx::GroupVm::<Child>::with_services("group", hub.clone(), NullDispatcher::new());
    let group_child = child("group-child", &hub);
    group.add(group_child.clone()).unwrap();
    group.construct().unwrap();
    let group_command = group.reconstruct_command();
    assert_command_reconstructs(
        &hub,
        &group_command,
        group.id(),
        std::slice::from_ref(&group_child),
    );
    drop(group);

    assert_command_is_inert(&hub, &aggregate1_command, "AggregateVm1");
    assert_command_is_inert(&hub, &aggregate6_command, "AggregateVm6");
    assert_command_is_inert(&hub, &composite_command, "CompositeVm");
    assert_command_is_inert(&hub, &group_command, "GroupVm");

    assert_children_are_released(&[one]);
    assert_children_are_released(&six);
    assert_children_are_released(&[composite_child, group_child]);
}
