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

/// GRP-002 — Group keeps baseline self-selection commands without child selection.
#[test]
fn group_has_complete_baseline_commands_without_child_selection_state() {
    let group = vmx::GroupVm::<Child>::new("group");
    let parent = vmx::CompositeVm::new("parent");
    parent.add(group.clone()).unwrap();
    parent.construct().unwrap();
    let select = group.select_command();
    let deselect = group.deselect_command();
    let next = group.select_next_command();
    let previous = group.select_previous_command();
    let reconstruct = group.reconstruct_command();

    assert!(select.can_execute());
    assert!(!deselect.can_execute());
    assert!(!next.can_execute());
    assert!(!previous.can_execute());
    assert!(reconstruct.can_execute());

    select.execute();

    assert!(parent.current() == Some(group.clone()));
    assert!(group.is_current());
    assert!(!select.can_execute());
    assert!(deselect.can_execute());

    deselect.execute();

    assert!(parent.current().is_none());
    assert!(!group.is_current());

    group.dispose().unwrap();
    for command in [select, deselect, next, previous, reconstruct] {
        assert!(!command.can_execute());
        command.execute();
    }
    assert!(parent.current().is_none());
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

// Membership edits beyond `add` (#362 coverage review). These assert observable
// outcomes: order, collection events, returned values, errors, and which
// children the group's disposal reaches.

fn names(group: &vmx::GroupVm<Child>) -> Vec<&'static str> {
    group.items().iter().map(|item| item.model()).collect()
}

#[test]
fn insert_places_the_child_and_emits_add() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    group.add(child("a")).unwrap();
    group.add(child("c")).unwrap();

    group.insert(1, child("b")).unwrap();

    assert_eq!(names(&group), vec!["a", "b", "c"]);
    assert_eq!(
        collection_actions(&hub),
        vec![CollectionChangeAction::Add; 3]
    );
}

#[test]
fn insert_out_of_range_changes_nothing() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    group.add(child("a")).unwrap();

    let error = group.insert(5, child("late")).unwrap_err();

    assert!(matches!(error, vmx::VmxError::InvalidArgument(_)));
    assert_eq!(names(&group), vec!["a"]);
    assert_eq!(collection_actions(&hub), vec![CollectionChangeAction::Add]);
}

#[test]
fn insert_into_a_constructed_group_constructs_the_child_when_auto_construct_is_on() {
    let group = vmx::GroupVm::<Child>::new("group");
    group.set_auto_construct_on_add(true);
    group.construct().unwrap();
    let late = child("late");

    group.insert(0, late.clone()).unwrap();

    assert_eq!(late.status(), ConstructionStatus::Constructed);
}

#[test]
fn insert_into_a_disposed_group_is_rejected_and_leaves_the_child_free() {
    let group = vmx::GroupVm::<Child>::new("group");
    group.dispose().unwrap();
    let orphan = child("orphan");

    assert!(matches!(
        group.insert(0, orphan.clone()),
        Err(vmx::VmxError::Disposed)
    ));

    let other = vmx::GroupVm::<Child>::new("other");
    other.add(orphan.clone()).unwrap();
    other.dispose().unwrap();
    assert_eq!(orphan.status(), ConstructionStatus::Disposed);
}

#[test]
fn remove_detaches_the_member_and_emits_remove() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    let (a, b) = (child("a"), child("b"));
    group.add(a.clone()).unwrap();
    group.add(b.clone()).unwrap();
    group.construct().unwrap();

    group.remove(&a).unwrap();
    group.dispose().unwrap();

    assert_eq!(
        collection_actions(&hub),
        vec![
            CollectionChangeAction::Add,
            CollectionChangeAction::Add,
            CollectionChangeAction::Remove
        ]
    );
    // The removed child is no longer the group's to dispose; the member is.
    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);
}

#[test]
fn removing_a_non_member_is_a_silent_no_op() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    group.add(child("a")).unwrap();

    group.remove(&child("stranger")).unwrap();

    assert_eq!(names(&group), vec!["a"]);
    assert_eq!(collection_actions(&hub), vec![CollectionChangeAction::Add]);
}

#[test]
fn remove_at_returns_the_child_and_rejects_a_bad_index() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    group.add(child("a")).unwrap();
    group.add(child("b")).unwrap();

    let removed = group.remove_at(0).unwrap();
    let error = group.remove_at(4).unwrap_err();

    assert_eq!(removed.model(), "a");
    assert!(matches!(error, vmx::VmxError::InvalidArgument(_)));
    assert_eq!(names(&group), vec!["b"]);
    assert_eq!(
        collection_actions(&hub),
        vec![
            CollectionChangeAction::Add,
            CollectionChangeAction::Add,
            CollectionChangeAction::Remove
        ]
    );
    group.dispose().unwrap();
    assert_ne!(removed.status(), ConstructionStatus::Disposed);
}

#[test]
fn clear_releases_every_child_and_emits_one_reset() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    let (a, b) = (child("a"), child("b"));
    group.add(a.clone()).unwrap();
    group.add(b.clone()).unwrap();

    group.clear();
    group.clear(); // already empty: no second reset
    group.dispose().unwrap();

    assert!(group.is_empty());
    assert_eq!(
        collection_actions(&hub),
        vec![
            CollectionChangeAction::Add,
            CollectionChangeAction::Add,
            CollectionChangeAction::Reset
        ]
    );
    assert_ne!(a.status(), ConstructionStatus::Disposed);
    assert_ne!(b.status(), ConstructionStatus::Disposed);
}
