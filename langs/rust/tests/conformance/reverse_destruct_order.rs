//! GRP-014 and COMP-046: the opt-in reverse destruct and dispose order of
//! group and composite children (ADR-0161).

use vmx::{
    ChildOrder, Command, ComponentVm, CompositeVm, CompositeVmOptions, ConstructionStatus, GroupVm,
    GroupVmOptions, Message, MessageHub, MessageRecorder, ModeledCompositeVm, NullDispatcher,
    VmNode,
};

type Child = ComponentVm<&'static str>;

const NAMES: [&str; 3] = ["a", "b", "c"];

fn children(hub: &MessageHub) -> Vec<Child> {
    NAMES
        .iter()
        .map(|name| Child::with_model(*name, *name, hub.clone(), NullDispatcher::new()))
        .collect()
}

/// The names of the senders that published `status`, in publication order.
fn senders(recorder: &MessageRecorder, status: ConstructionStatus) -> Vec<String> {
    recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change) if change.status == status => {
                Some(change.sender_name)
            }
            _ => None,
        })
        .collect()
}

fn names(expected: &[&str]) -> Vec<String> {
    expected.iter().map(|name| (*name).to_string()).collect()
}

/// Drives one container through construct, destruct, reconstruct, the
/// reconstruct command and dispose, and checks the child order of each walk.
/// `walk` is the expected destruct and dispose order of the children.
fn assert_walk_orders<V: VmNode>(
    hub: &MessageHub,
    container: &V,
    container_name: &str,
    reconstruct: impl Fn(),
    walk: &[&str],
) {
    let recorder = hub.record(1024);
    container.construct().unwrap();
    assert_eq!(
        senders(&recorder, ConstructionStatus::Constructed),
        names(&["a", "b", "c", container_name]),
        "construct keeps insertion order"
    );

    let recorder = hub.record(1024);
    container.destruct().unwrap();
    let mut expected = walk.to_vec();
    expected.push(container_name);
    assert_eq!(
        senders(&recorder, ConstructionStatus::Destructed),
        names(&expected)
    );

    container.construct().unwrap();
    let recorder = hub.record(1024);
    reconstruct();
    assert_eq!(
        senders(&recorder, ConstructionStatus::Destructed),
        names(&expected),
        "the destruct phase of reconstruct follows the destruct order"
    );
    assert_eq!(
        senders(&recorder, ConstructionStatus::Constructed),
        names(&["a", "b", "c", container_name]),
        "the construct phase of reconstruct keeps insertion order"
    );
    let constructed_at = recorder
        .messages()
        .iter()
        .position(|message| {
            matches!(message, Message::ConstructionStatusChanged(change)
                if change.status == ConstructionStatus::Constructing)
        })
        .unwrap();
    let last_destructed = recorder
        .messages()
        .iter()
        .rposition(|message| {
            matches!(message, Message::ConstructionStatusChanged(change)
                if change.status == ConstructionStatus::Destructed)
        })
        .unwrap();
    assert!(
        last_destructed < constructed_at,
        "destruct before construct"
    );

    let recorder = hub.record(1024);
    container.dispose().unwrap();
    assert_eq!(
        senders(&recorder, ConstructionStatus::Disposed),
        names(&expected),
        "every child is disposed before the container publishes Disposed"
    );
}

/// GRP-014 — with `ChildOrder::Reverse` a group destructs and disposes its
/// children in reverse insertion order; construct keeps insertion order
#[test]
fn group_reverse_destruct_order() {
    let hub = MessageHub::new();
    let members = children(&hub);
    let group = GroupVm::builder()
        .name("group")
        .services(hub.clone(), NullDispatcher::new())
        .children(move || members.clone())
        .destruct_order(ChildOrder::Reverse)
        .build()
        .unwrap();
    let reconstructed = group.clone();
    assert_walk_orders(
        &hub,
        &group,
        "group",
        move || reconstructed.reconstruct().unwrap(),
        &["c", "b", "a"],
    );
}

/// GRP-014 — the group's reconstruct command and `create` options follow the
/// destruct order; the default stays insertion order
#[test]
fn group_reverse_destruct_order_command_options_and_default() {
    let hub = MessageHub::new();
    let group = GroupVm::create(GroupVmOptions {
        name: Some("group".to_string()),
        hint: None,
        hub: hub.clone(),
        dispatcher: NullDispatcher::new(),
        children: Some(children(&hub)),
        auto_construct_on_add: false,
        destruct_order: ChildOrder::Reverse,
    })
    .unwrap();
    let command = group.reconstruct_command();
    assert_walk_orders(
        &hub,
        &group,
        "group",
        move || command.execute(),
        &["c", "b", "a"],
    );

    let hub = MessageHub::new();
    let members = children(&hub);
    let group = GroupVm::builder()
        .name("group")
        .services(hub.clone(), NullDispatcher::new())
        .children(move || members.clone())
        .build()
        .unwrap();
    let reconstructed = group.clone();
    assert_walk_orders(
        &hub,
        &group,
        "group",
        move || reconstructed.reconstruct().unwrap(),
        &["a", "b", "c"],
    );
}

/// COMP-046 — with `ChildOrder::Reverse` a composite clears `current`, then
/// destructs and disposes its children in reverse insertion order; construct
/// keeps insertion order
#[test]
fn composite_reverse_destruct_order() {
    let hub = MessageHub::new();
    let members = children(&hub);
    let composite = CompositeVm::builder()
        .name("composite")
        .services(hub.clone(), NullDispatcher::new())
        .children(move || members.clone())
        .current(|items| items.last().cloned())
        .destruct_order(ChildOrder::Reverse)
        .build()
        .unwrap();
    let reconstructed = composite.clone();
    let observed = composite.clone();
    assert_walk_orders(
        &hub,
        &composite,
        "composite",
        move || {
            reconstructed.reconstruct().unwrap();
            assert_eq!(
                observed.current().map(|child| child.name()),
                Some("c".into())
            );
        },
        &["c", "b", "a"],
    );
}

/// COMP-046 — the composite's reconstruct command, `create` options and the
/// modeled composite builder follow the destruct order; the default stays
/// insertion order
#[test]
fn composite_reverse_destruct_order_command_options_modeled_and_default() {
    let hub = MessageHub::new();
    let composite = CompositeVm::create(CompositeVmOptions {
        name: Some("composite".to_string()),
        hint: None,
        hub: hub.clone(),
        dispatcher: NullDispatcher::new(),
        children: Some(children(&hub)),
        auto_construct_on_add: false,
        destruct_order: ChildOrder::Reverse,
    })
    .unwrap();
    let command = composite.reconstruct_command();
    assert_walk_orders(
        &hub,
        &composite,
        "composite",
        move || command.execute(),
        &["c", "b", "a"],
    );

    let hub = MessageHub::new();
    let child_hub = hub.clone();
    let modeled = ModeledCompositeVm::<&'static str, Child>::builder()
        .name("modeled")
        .services(hub.clone(), NullDispatcher::new())
        .children_models(|| NAMES.to_vec())
        .child_model_to_child_view_model(move |model| {
            Child::with_model(model, model, child_hub.clone(), NullDispatcher::new())
        })
        .destruct_order(ChildOrder::Reverse)
        .build()
        .unwrap();
    let reconstructed = modeled.clone();
    assert_walk_orders(
        &hub,
        &modeled,
        "modeled",
        move || reconstructed.reconstruct().unwrap(),
        &["c", "b", "a"],
    );

    let hub = MessageHub::new();
    let members = children(&hub);
    let composite = CompositeVm::builder()
        .name("composite")
        .services(hub.clone(), NullDispatcher::new())
        .children(move || members.clone())
        .build()
        .unwrap();
    let reconstructed = composite.clone();
    assert_walk_orders(
        &hub,
        &composite,
        "composite",
        move || reconstructed.reconstruct().unwrap(),
        &["a", "b", "c"],
    );
}
