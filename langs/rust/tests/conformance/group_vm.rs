use vmx::{
    CollectionChangeAction, Command, ConstructionStatus, Message, MessageHub, NullDispatcher,
};

type Child = vmx::ComponentVm<&'static str>;

fn child(name: &'static str) -> Child {
    Child::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

fn collection_actions(hub: &MessageHub) -> Vec<CollectionChangeAction> {
    hub.history()
        .into_iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) => Some(change.action),
            _ => None,
        })
        .collect()
}

/// GRP-001 — Add emits CollectionChanged(action=Add)
#[test]
fn add_emits_collection_changed_add() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());

    group.add(child("a")).unwrap();

    assert_eq!(collection_actions(&hub), vec![CollectionChangeAction::Add]);
}

/// GRP-002 — Group lacks child-navigation and child-selection members
#[test]
fn group_has_own_selection_commands_without_child_selection_state() {
    let group = vmx::GroupVm::<Child>::new("group");
    let select = group.select_command();
    let deselect = group.deselect_command();

    assert!(select.can_execute());
    assert!(!deselect.can_execute());

    select.execute();

    assert!(group.is_selected());
    assert!(!select.can_execute());
    assert!(deselect.can_execute());

    deselect.execute();

    assert!(!group.is_selected());
}

/// GRP-003 — Construct waits until all children reach Constructed
#[test]
fn construct_constructs_all_children() {
    let group = vmx::GroupVm::new("group");
    let a = child("a");
    let b = child("b");
    group.add(a.clone()).unwrap();
    group.add(b.clone()).unwrap();

    group.construct().unwrap();

    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
}

#[test]
fn parent_reaches_constructed_only_after_children() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    let item = Child::with_model("child", "child", hub.clone(), NullDispatcher::new());
    group.add(item.clone()).unwrap();

    group.construct().unwrap();

    let statuses = hub
        .history()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change) => Some((change.sender_id, change.status)),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        statuses,
        vec![
            (group.id(), ConstructionStatus::Constructing),
            (item.id(), ConstructionStatus::Constructing),
            (item.id(), ConstructionStatus::Constructed),
            (group.id(), ConstructionStatus::Constructed),
        ]
    );
}

/// GRP-004 — Destruct waits until all children reach Destructed
#[test]
fn destruct_destructs_all_children() {
    let group = vmx::GroupVm::new("group");
    let a = child("a");
    group.add(a.clone()).unwrap();
    group.construct().unwrap();

    group.destruct().unwrap();

    assert_eq!(a.status(), ConstructionStatus::Destructed);
}

/// GRP-005 — AutoConstructOnAdd(true) auto-constructs late children
#[test]
fn auto_construct_on_add_constructs_late_children() {
    let group = vmx::GroupVm::new("group");
    group.set_auto_construct_on_add(true);
    group.construct().unwrap();
    let item = child("late");

    group.add(item.clone()).unwrap();

    assert_eq!(item.status(), ConstructionStatus::Constructed);
}

/// GRP-006 — BatchUpdate suppresses per-mutation events and emits one Reset
#[test]
fn batch_update_emits_single_reset() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());

    group.batch_update(|| {
        group.add(child("a")).unwrap();
        group.add(child("b")).unwrap();
    });

    assert_eq!(
        collection_actions(&hub),
        vec![CollectionChangeAction::Reset]
    );
}

/// GRP-011 — Group children are not selectable peers
#[test]
fn group_child_remains_non_current_peer() {
    let group = vmx::GroupVm::new("group");
    let item = child("a");
    group.add(item.clone()).unwrap();

    assert_eq!(item.parent_id(), Some(group.id()));
    assert!(!item.is_current());
}
