use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

use vmx::{
    CollectionChangeAction, Command, ConstructionStatus, Dispatcher, ImmediateDispatcher,
    ManualDispatcher, Message, MessageHub, NullDispatcher, VmNode, VmxError,
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

#[test]
fn composite_exposes_parent_delegating_disposable_baseline_commands() {
    let composite = vmx::CompositeVm::<Child>::new("composite");
    composite.add(child("leaf")).unwrap();
    let parent = vmx::CompositeVm::new("parent");
    parent.add(composite.clone()).unwrap();
    parent.construct().unwrap();
    let commands = [
        composite.select_command(),
        composite.deselect_command(),
        composite.select_next_command(),
        composite.select_previous_command(),
        composite.reconstruct_command(),
    ];

    commands[0].execute();
    assert!(parent.current() == Some(composite.clone()));
    commands[1].execute();
    assert!(parent.current().is_none());
    commands[4].execute();
    assert!(composite.is_constructed());

    composite.dispose().unwrap();
    assert!(commands.iter().all(|command| !command.can_execute()));
}

/// COMP-001 — Add emits CollectionChanged(action=Add)
#[test]
fn add_emits_collection_changed_add() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());

    composite.add(child("a")).unwrap();

    assert_eq!(collection_actions(&hub), vec![CollectionChangeAction::Add]);
}

/// COMP-002 — Remove emits CollectionChanged(action=Remove)
#[test]
fn remove_emits_collection_changed_remove() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());
    let item = child("a");
    composite.add(item.clone()).unwrap();

    composite.remove(&item).unwrap();

    assert!(collection_actions(&hub).contains(&CollectionChangeAction::Remove));
    assert_eq!(item.parent_id(), None);
}

/// COMP-003 — select_component sets Current
#[test]
fn select_component_sets_current_and_child_current_flag() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");
    composite.add(item.clone()).unwrap();
    item.construct().unwrap();

    composite.select_component(&item).unwrap();

    assert_eq!(composite.current(), Some(item.clone()));
    assert!(item.is_current());
}

/// COMP-004 — Construct waits until all children reach Constructed
#[test]
fn construct_constructs_all_children() {
    let composite = vmx::CompositeVm::new("root");
    let a = child("a");
    let b = child("b");
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();

    composite.construct().unwrap();

    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
}

#[test]
fn parent_reaches_constructed_only_after_children() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());
    let item = Child::with_model("child", "child", hub.clone(), NullDispatcher::new());
    composite.add(item.clone()).unwrap();

    composite.construct().unwrap();

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
            (composite.id(), ConstructionStatus::Constructing),
            (item.id(), ConstructionStatus::Constructing),
            (item.id(), ConstructionStatus::Constructed),
            (composite.id(), ConstructionStatus::Constructed),
        ]
    );
}

/// COMP-005 — Destruct waits until all children reach Destructed
#[test]
fn destruct_clears_current_and_destructs_children() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");
    composite.add(item.clone()).unwrap();
    composite.construct().unwrap();
    composite.select_component(&item).unwrap();

    composite.destruct().unwrap();

    assert_eq!(composite.current(), None);
    assert_eq!(item.status(), ConstructionStatus::Destructed);
    assert!(!item.is_current());
}

/// COMP-006 — IsCurrent change on the previously-Current child dispatches on foreground
#[test]
fn previous_current_change_can_be_observed_on_foreground_dispatcher() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let composite = vmx::CompositeVm::<Child, ManualDispatcher>::with_services(
        "root",
        hub.clone(),
        dispatcher.clone(),
    );
    let a = Child::with_model("a", "a", hub.clone(), NullDispatcher::new());
    let b = Child::with_model("b", "b", hub.clone(), NullDispatcher::new());
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    composite.construct().unwrap();
    composite.select_component(&a).unwrap();

    let observed = Arc::new(Mutex::new(0));
    let observed_inner = observed.clone();
    let observer_dispatcher = dispatcher.clone();
    let a_id = a.id();
    let _subscription = hub.subscribe(move |message| {
        if matches!(
            message,
            Message::PropertyChanged(change)
                if change.sender_id == a_id && change.property_name == "is_current"
        ) {
            let observed_inner = observed_inner.clone();
            observer_dispatcher.dispatch(Box::new(move || *observed_inner.lock().unwrap() += 1));
        }
    });

    composite.select_component(&b).unwrap();

    assert_eq!(*observed.lock().unwrap(), 0);
    dispatcher.drain();
    assert_eq!(*observed.lock().unwrap(), 1);
}

/// COMP-007 — Modeled composite maps model factory output to children
#[test]
fn modeled_composite_maps_model_factory_output_to_children() {
    let composite =
        vmx::ModeledCompositeVm::<i32, vmx::ComponentVm<i32>, NullDispatcher>::builder()
            .name("modeled")
            .services(MessageHub::new(), NullDispatcher::new())
            .children_models(|| vec![1, 2])
            .child_model_to_child_view_model(|model| {
                vmx::ComponentVm::with_model(
                    format!("child-{model}"),
                    model,
                    MessageHub::new(),
                    NullDispatcher::new(),
                )
            })
            .build()
            .unwrap();

    composite.construct().unwrap();

    assert_eq!(composite.len(), 2);
    assert_eq!(composite.get(0).unwrap().model(), 1);
    assert_eq!(composite.get(1).unwrap().model(), 2);
}

/// COMP-008 — can_select_component returns false for non-children
#[test]
fn can_select_component_false_for_non_child() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("outside");
    item.construct().unwrap();

    assert!(!composite.can_select_component(&item));
}

/// COMP-009 — Current setter raises when assigned a non-child
#[test]
fn set_current_rejects_non_child() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("outside");

    let result = composite.set_current(Some(item));

    assert_eq!(result, Err(VmxError::NonChild));
    assert_eq!(composite.current(), None);
}

/// COMP-010 — AsyncSelection dispatches Current change via foreground scheduler
#[test]
fn async_selection_dispatches_current_change_via_foreground() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let composite = vmx::CompositeVm::<Child, ManualDispatcher>::with_services(
        "root",
        hub.clone(),
        dispatcher.clone(),
    );
    composite.set_async_selection(true);
    let item = child("a");
    composite.add(item.clone()).unwrap();
    item.construct().unwrap();
    let observed = Arc::new(Mutex::new(0));
    let observed_inner = observed.clone();
    let observer_dispatcher = dispatcher.clone();
    let composite_id = composite.id();
    let _subscription = hub.subscribe(move |message| {
        if matches!(
            message,
            Message::PropertyChanged(change)
                if change.sender_id == composite_id && change.property_name == "current"
        ) {
            let observed_inner = observed_inner.clone();
            observer_dispatcher.dispatch(Box::new(move || *observed_inner.lock().unwrap() += 1));
        }
    });

    composite.select_component(&item).unwrap();

    assert_eq!(composite.current(), None);
    assert_eq!(*observed.lock().unwrap(), 0);
    dispatcher.drain();
    assert_eq!(composite.current(), Some(item));
    assert_eq!(*observed.lock().unwrap(), 1);
}

#[test]
fn async_selection_with_inline_dispatchers_completes_without_deadlock() {
    let null = vmx::CompositeVm::new("null");
    let null_child = child("null-child");
    null.add(null_child.clone()).unwrap();
    null_child.construct().unwrap();
    null.set_async_selection(true);
    null.select_component(&null_child).unwrap();
    assert_eq!(null.current(), Some(null_child));

    let immediate = vmx::CompositeVm::<Child, ImmediateDispatcher>::with_services(
        "immediate",
        MessageHub::new(),
        ImmediateDispatcher::new(),
    );
    let immediate_child = child("immediate-child");
    immediate.add(immediate_child.clone()).unwrap();
    immediate_child.construct().unwrap();
    immediate.set_async_selection(true);
    immediate.select_component(&immediate_child).unwrap();
    assert_eq!(immediate.current(), Some(immediate_child));
}

#[test]
fn queued_async_selection_revalidates_membership_before_assignment() {
    let dispatcher = ManualDispatcher::new();
    let composite = vmx::CompositeVm::<Child, ManualDispatcher>::with_services(
        "async-membership",
        MessageHub::new(),
        dispatcher.clone(),
    );
    let item = child("queued-child");
    composite.add(item.clone()).unwrap();
    item.construct().unwrap();
    composite.set_async_selection(true);

    composite.select_component(&item).unwrap();
    composite.remove(&item).unwrap();
    dispatcher.drain();

    assert_eq!(composite.current(), None);
    assert!(!item.is_current());
}

/// COMP-011 — deselect_component raises when vm is not Current
#[test]
fn deselect_component_rejects_non_current_child() {
    let composite = vmx::CompositeVm::new("root");
    let a = child("a");
    let b = child("b");
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    a.construct().unwrap();
    b.construct().unwrap();
    composite.select_component(&a).unwrap();

    let result = composite.deselect_component(&b);

    assert_eq!(result, Err(VmxError::NotCurrent));
    assert_eq!(composite.current(), Some(a));
}

/// COMP-012 — AutoConstructOnAdd(true) auto-constructs late children
#[test]
fn auto_construct_on_add_constructs_late_child_before_event() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());
    composite.set_auto_construct_on_add(true);
    composite.construct().unwrap();
    let item = child("late");

    composite.add(item.clone()).unwrap();

    assert_eq!(item.status(), ConstructionStatus::Constructed);
    assert_eq!(
        collection_actions(&hub).last(),
        Some(&CollectionChangeAction::Add)
    );
}

#[derive(Clone)]
enum OwnershipNode {
    Composite(vmx::CompositeVm<OwnershipNode>),
}

impl PartialEq for OwnershipNode {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl VmNode for OwnershipNode {
    fn id(&self) -> usize {
        match self {
            Self::Composite(vm) => vm.id(),
        }
    }

    fn construct(&self) -> vmx::VmxResult<()> {
        match self {
            Self::Composite(vm) => vm.construct(),
        }
    }

    fn destruct(&self) -> vmx::VmxResult<()> {
        match self {
            Self::Composite(vm) => vm.destruct(),
        }
    }

    fn dispose(&self) -> vmx::VmxResult<()> {
        match self {
            Self::Composite(vm) => vm.dispose(),
        }
    }

    fn status(&self) -> ConstructionStatus {
        match self {
            Self::Composite(vm) => vm.status(),
        }
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        match self {
            Self::Composite(vm) => vm.set_parent_id(parent_id),
        }
    }

    fn parent_id(&self) -> Option<usize> {
        match self {
            Self::Composite(vm) => vm.parent_id(),
        }
    }

    fn set_parent_handle(&self, parent: Option<vmx::ParentHandle>) {
        match self {
            Self::Composite(vm) => vm.set_parent_handle(parent),
        }
    }

    fn parent_handle(&self) -> Option<vmx::ParentHandle> {
        match self {
            Self::Composite(vm) => vm.parent_handle(),
        }
    }
}

#[derive(Clone)]
struct ValueEqualNode {
    inner: Child,
}

impl ValueEqualNode {
    fn new(name: &'static str) -> Self {
        Self { inner: child(name) }
    }
}

impl PartialEq for ValueEqualNode {
    fn eq(&self, other: &Self) -> bool {
        self.inner.model() == other.inner.model()
    }
}

impl VmNode for ValueEqualNode {
    fn id(&self) -> usize {
        self.inner.id()
    }

    fn construct(&self) -> vmx::VmxResult<()> {
        self.inner.construct()
    }

    fn destruct(&self) -> vmx::VmxResult<()> {
        self.inner.destruct()
    }

    fn dispose(&self) -> vmx::VmxResult<()> {
        self.inner.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        VmNode::set_parent_id(&self.inner, parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        VmNode::parent_id(&self.inner)
    }

    fn set_parent_handle(&self, parent: Option<vmx::ParentHandle>) {
        VmNode::set_parent_handle(&self.inner, parent);
    }

    fn parent_handle(&self) -> Option<vmx::ParentHandle> {
        VmNode::parent_handle(&self.inner)
    }

    fn set_current_flag(&self, is_current: bool) {
        VmNode::set_current_flag(&self.inner, is_current);
    }

    fn is_current(&self) -> bool {
        VmNode::is_current(&self.inner)
    }
}

/// COMP-039 — VM membership uses `VmNode::id`, not arbitrary `PartialEq` value equality.
#[test]
fn membership_uses_node_identity_when_partial_eq_is_value_based() {
    let child = ValueEqualNode::new("same");
    let foreign = ValueEqualNode::new("same");
    let composite = vmx::CompositeVm::new("composite");
    composite.add(child.clone()).unwrap();
    child.construct().unwrap();

    assert!(!composite.can_select_component(&foreign));
    assert_eq!(
        composite.set_current(Some(foreign.clone())),
        Err(VmxError::NonChild)
    );
    assert_eq!(composite.remove(&foreign), Err(VmxError::NonChild));
    assert_eq!(composite.items()[0].id(), child.id());

    let filtered = vmx::FilteredCompositeVm::new(composite.clone(), |_| true);
    assert_eq!(filtered.set_current(Some(foreign)), Err(VmxError::NonChild));

    let group_child = ValueEqualNode::new("group-same");
    let group_foreign = ValueEqualNode::new("group-same");
    let group = vmx::GroupVm::new("group");
    group.add(group_child.clone()).unwrap();

    assert_eq!(group.remove(&group_foreign), Err(VmxError::NonChild));
    assert_eq!(group.items()[0].id(), group_child.id());
}

/// COMP-038 — Adding an owned child transfers it between composite/group parents.
#[test]
fn adding_owned_child_transfers_membership() {
    let item = child("owned");
    let old_parent = vmx::CompositeVm::new("old");
    let destination = vmx::GroupVm::new("destination");
    old_parent.add(item.clone()).unwrap();

    destination.add(item.clone()).unwrap();

    assert!(old_parent.is_empty());
    assert_eq!(destination.items(), vec![item.clone()]);
    assert_eq!(item.parent_id(), Some(destination.id()));
}

/// COMP-039 — Duplicate ownership and ancestor cycles are rejected.
#[test]
fn duplicate_and_cycle_are_rejected() {
    let item = child("duplicate");
    let parent = vmx::CompositeVm::new("parent");
    parent.add(item.clone()).unwrap();
    assert_eq!(parent.add(item), Err(VmxError::DuplicateChild));

    let ancestor = vmx::CompositeVm::<OwnershipNode>::new("ancestor");
    let descendant = vmx::CompositeVm::<OwnershipNode>::new("descendant");
    ancestor
        .add(OwnershipNode::Composite(descendant.clone()))
        .unwrap();

    assert_eq!(
        descendant.add(OwnershipNode::Composite(ancestor.clone())),
        Err(VmxError::OwnershipCycle)
    );
    assert_eq!(ancestor.len(), 1);
    assert!(descendant.is_empty());
}

#[test]
fn builder_population_rejects_duplicate_identity_in_composite_and_group() {
    let item = child("duplicate-factory");
    let composite = vmx::CompositeVm::<Child>::builder()
        .name("composite")
        .services(MessageHub::new(), NullDispatcher::new())
        .children({
            let item = item.clone();
            move || vec![item.clone(), item.clone()]
        })
        .build();
    assert!(matches!(composite, Err(VmxError::DuplicateChild)));

    let group = vmx::GroupVm::<Child>::builder()
        .name("group")
        .services(MessageHub::new(), NullDispatcher::new())
        .children({
            let item = item.clone();
            move || vec![item.clone(), item.clone()]
        })
        .build();
    assert!(matches!(group, Err(VmxError::DuplicateChild)));
    assert_eq!(item.parent_id(), None);
}

#[test]
fn auto_construct_hook_cannot_reparent_before_admission_commits() {
    let source = vmx::CompositeVm::new("source");
    let destination = vmx::GroupVm::new("destination");
    source.set_auto_construct_on_add(true);
    source.construct().unwrap();
    let item = child("reentrant");
    let nested_item = item.clone();
    let nested_destination = destination.clone();
    item.on_construct(move || nested_destination.add(nested_item.clone()));

    assert_eq!(
        source.add(item.clone()),
        Err(VmxError::OwnershipTransactionInProgress)
    );
    assert!(source.is_empty());
    assert!(destination.is_empty());
    assert_eq!(item.parent_id(), None);
}

#[test]
fn auto_construct_hook_cannot_mutate_destination_membership() {
    let destination = vmx::GroupVm::new("destination");
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();
    let candidate = child("candidate");
    let nested = child("nested");
    let destination_from_hook = destination.clone();
    let nested_from_hook = nested.clone();
    candidate.on_construct(move || destination_from_hook.add(nested_from_hook.clone()));

    assert_eq!(
        destination.add(candidate.clone()),
        Err(VmxError::OwnershipTransactionInProgress)
    );
    assert!(destination.is_empty());
    assert_eq!(candidate.parent_id(), None);
    assert_eq!(nested.parent_id(), None);
}

#[test]
fn auto_construct_hook_disposal_aborts_destination_admission() {
    let composite = vmx::CompositeVm::new("composite");
    composite.set_auto_construct_on_add(true);
    composite.construct().unwrap();
    let composite_child = child("composite-child");
    let composite_from_hook = composite.clone();
    let composite_hook_called = Arc::new(AtomicBool::new(false));
    let composite_hook_flag = Arc::clone(&composite_hook_called);
    composite_child.on_construct(move || {
        composite_hook_flag.store(true, Ordering::SeqCst);
        composite_from_hook.dispose()
    });

    let group = vmx::GroupVm::new("group");
    group.set_auto_construct_on_add(true);
    group.construct().unwrap();
    let group_child = child("group-child");
    let group_from_hook = group.clone();
    group_child.on_construct(move || group_from_hook.dispose());

    let composite_result = composite.add(composite_child.clone());
    assert!(composite_hook_called.load(Ordering::SeqCst));
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
    assert_eq!(composite_result, Err(VmxError::Disposed));
    assert_eq!(group.add(group_child.clone()), Err(VmxError::Disposed));
    assert!(composite.is_empty());
    assert!(group.is_empty());
    assert_eq!(composite_child.parent_id(), None);
    assert_eq!(group_child.parent_id(), None);
}

#[test]
fn replacement_hook_cannot_remove_candidate_during_rollback() {
    let destination = vmx::CompositeVm::new("destination");
    let old = child("old");
    destination.add(old.clone()).unwrap();
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();

    let candidate = child("candidate");
    let destination_from_hook = destination.clone();
    let candidate_from_hook = candidate.clone();
    candidate.on_construct(move || destination_from_hook.remove(&candidate_from_hook));

    assert_eq!(
        destination.replace(0, candidate.clone()),
        Err(VmxError::OwnershipTransactionInProgress)
    );
    assert_eq!(destination.items(), vec![old.clone()]);
    assert_eq!(old.parent_id(), Some(destination.id()));
    assert_eq!(candidate.parent_id(), None);
}

#[test]
fn transfer_hook_cannot_mutate_old_parent_before_rollback() {
    let old_parent = vmx::CompositeVm::new("old-parent");
    let before = child("before");
    let candidate = child("candidate");
    let after = child("after");
    old_parent.add(before.clone()).unwrap();
    old_parent.add(candidate.clone()).unwrap();
    old_parent.add(after.clone()).unwrap();
    old_parent.set_current(Some(candidate.clone())).unwrap();

    let destination = vmx::GroupVm::new("destination");
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();
    let nested = child("nested");
    let old_parent_from_hook = old_parent.clone();
    let nested_from_hook = nested.clone();
    candidate.on_construct(move || old_parent_from_hook.add(nested_from_hook.clone()));

    assert_eq!(
        destination.add(candidate.clone()),
        Err(VmxError::OwnershipTransactionInProgress)
    );
    assert_eq!(old_parent.items(), vec![before, candidate.clone(), after]);
    assert_eq!(old_parent.current(), Some(candidate));
    assert_eq!(nested.parent_id(), None);
    assert!(destination.is_empty());
}

/// COMP-040 — A failed destination attach restores exact old membership/current state.
#[test]
fn failed_attach_rolls_back_old_parent_state() {
    let item = child("rollback");
    item.on_construct(|| Err(VmxError::Other("boom".to_string())));
    let old_parent = vmx::CompositeVm::new("old");
    old_parent.add(item.clone()).unwrap();
    old_parent.set_current(Some(item.clone())).unwrap();
    let destination = vmx::CompositeVm::new("destination");
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();

    assert_eq!(
        destination.add(item.clone()),
        Err(VmxError::Other("boom".to_string()))
    );

    assert_eq!(old_parent.items(), vec![item.clone()]);
    assert_eq!(old_parent.current(), Some(item));
    assert!(destination.is_empty());
}

/// COMP-040 — old-parent disposal waits until successful transfer commit.
#[test]
fn old_composite_disposal_is_deferred_until_transfer_commit() {
    let item = child("deferred-success");
    let old_parent = vmx::CompositeVm::new("old");
    old_parent.add(item.clone()).unwrap();
    let destination = vmx::GroupVm::new("destination");
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();
    let old_from_hook = old_parent.clone();
    item.on_construct(move || old_from_hook.dispose());

    destination.add(item.clone()).unwrap();

    assert_eq!(old_parent.status(), ConstructionStatus::Disposed);
    assert!(old_parent.is_empty());
    assert_eq!(destination.items(), vec![item.clone()]);
    assert_eq!(item.status(), ConstructionStatus::Constructed);
    assert_eq!(item.parent_id(), Some(destination.id()));
}

/// COMP-040 — rollback restores membership before deferred old-parent disposal.
#[test]
fn failed_transfer_rolls_back_before_deferred_old_group_disposal() {
    let item = child("deferred-failure");
    let old_parent = vmx::GroupVm::new("old");
    old_parent.add(item.clone()).unwrap();
    let destination = vmx::CompositeVm::new("destination");
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();
    let old_from_hook = old_parent.clone();
    item.on_construct(move || {
        old_from_hook.dispose()?;
        Err(VmxError::Other("boom".to_string()))
    });

    assert_eq!(
        destination.add(item.clone()),
        Err(VmxError::Other("boom".to_string()))
    );

    assert_eq!(old_parent.status(), ConstructionStatus::Disposed);
    assert_eq!(old_parent.items(), vec![item.clone()]);
    assert!(destination.is_empty());
    assert_eq!(item.status(), ConstructionStatus::Disposed);
    assert_eq!(item.parent_id(), Some(old_parent.id()));
}

/// Regression — destination disposal after successful auto-construction rolls lifecycle back.
#[test]
fn destination_disposal_after_auto_construct_destructs_detached_children() {
    let composite_child = child("composite-child");
    let composite = vmx::CompositeVm::new("composite");
    composite.set_auto_construct_on_add(true);
    composite.construct().unwrap();
    let composite_from_hook = composite.clone();
    composite_child.on_construct(move || composite_from_hook.dispose());

    assert_eq!(
        composite.add(composite_child.clone()),
        Err(VmxError::Disposed)
    );
    assert!(composite.is_empty());
    assert_eq!(composite_child.status(), ConstructionStatus::Destructed);
    assert_eq!(composite.status(), ConstructionStatus::Disposed);

    let group_child = child("group-child");
    let group = vmx::GroupVm::new("group");
    group.set_auto_construct_on_add(true);
    group.construct().unwrap();
    let group_from_hook = group.clone();
    group_child.on_construct(move || group_from_hook.dispose());

    assert_eq!(group.add(group_child.clone()), Err(VmxError::Disposed));
    assert!(group.is_empty());
    assert_eq!(group_child.status(), ConstructionStatus::Destructed);
    assert_eq!(group.status(), ConstructionStatus::Disposed);
}

/// COMP-040 — factory population rolls back if a successful construct disposes its destination.
#[test]
fn population_disposal_rolls_back_constructed_child() {
    let item = child("population-child");
    let mapped_item = item.clone();
    let destination = vmx::ModeledCompositeVm::new(
        "destination",
        MessageHub::new(),
        NullDispatcher::new(),
        || vec![1],
        move |_| mapped_item.clone(),
    );
    let destination_from_hook = destination.clone();
    item.on_construct(move || destination_from_hook.dispose());

    assert_eq!(destination.construct(), Err(VmxError::Disposed));
    assert!(
        destination.items().is_empty(),
        "len={}, child={:?}, destination={:?}, parent={:?}",
        destination.items().len(),
        item.status(),
        destination.status(),
        item.parent_id()
    );
    assert_eq!(item.status(), ConstructionStatus::Destructed);
    assert_eq!(destination.status(), ConstructionStatus::Disposed);
}

/// COMP-040 — replacement rollback precedes deferred composite/group disposal.
#[test]
fn replacement_disposal_restores_old_child_before_terminal_cascade() {
    let old = child("old");
    let candidate = child("candidate");
    let composite = vmx::CompositeVm::new("composite");
    composite.add(old.clone()).unwrap();
    composite.set_auto_construct_on_add(true);
    composite.construct().unwrap();
    let composite_from_hook = composite.clone();
    candidate.on_construct(move || composite_from_hook.dispose());

    assert_eq!(
        composite.replace(0, candidate.clone()),
        Err(VmxError::Disposed)
    );
    assert!(composite.items() == vec![old.clone()]);
    assert_eq!(old.status(), ConstructionStatus::Disposed);
    assert_eq!(candidate.status(), ConstructionStatus::Destructed);
    assert_eq!(candidate.parent_id(), None);

    let group_old = child("group-old");
    let group_candidate = child("group-candidate");
    let group = vmx::GroupVm::new("group");
    group.add(group_old.clone()).unwrap();
    group.set_auto_construct_on_add(true);
    group.construct().unwrap();
    let group_from_hook = group.clone();
    group_candidate.on_construct(move || group_from_hook.dispose());

    assert_eq!(
        group.replace(0, group_candidate.clone()),
        Err(VmxError::Disposed)
    );
    assert!(group.items() == vec![group_old.clone()]);
    assert_eq!(group_old.status(), ConstructionStatus::Disposed);
    assert_eq!(group_candidate.status(), ConstructionStatus::Destructed);
    assert_eq!(group_candidate.parent_id(), None);
}

/// COMP-040 — deferred disposal failure follows committed transfer events.
#[test]
fn deferred_disposal_failure_follows_committed_transfer_events() {
    let item = child("moving");
    let failing_sibling = child("failing-sibling");
    failing_sibling.on_dispose(|| Err(VmxError::Other("dispose failure".to_string())));
    let old_hub = MessageHub::new();
    let old_parent = vmx::GroupVm::with_services("old", old_hub.clone(), NullDispatcher::new());
    old_parent.add(item.clone()).unwrap();
    old_parent.add(failing_sibling.clone()).unwrap();
    let destination_hub = MessageHub::new();
    let destination = vmx::CompositeVm::with_services(
        "destination",
        destination_hub.clone(),
        NullDispatcher::new(),
    );
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();
    let old_from_hook = old_parent.clone();
    item.on_construct(move || old_from_hook.dispose());

    assert_eq!(
        destination.add(item.clone()),
        Err(VmxError::Other("dispose failure".to_string()))
    );

    assert_eq!(
        collection_actions(&old_hub),
        vec![
            CollectionChangeAction::Add,
            CollectionChangeAction::Add,
            CollectionChangeAction::Remove,
        ]
    );
    assert_eq!(
        collection_actions(&destination_hub),
        vec![CollectionChangeAction::Add]
    );
    assert_eq!(old_parent.status(), ConstructionStatus::Disposed);
    assert_eq!(failing_sibling.status(), ConstructionStatus::Disposed);
    assert_eq!(destination.items(), vec![item.clone()]);
    assert_eq!(item.parent_id(), Some(destination.id()));
}

/// COMP-040 — attachment failure precedes deferred disposal failure.
#[test]
fn attachment_failure_precedes_deferred_disposal_failure() {
    let item = child("moving");
    item.on_dispose(|| Err(VmxError::Other("dispose failure".to_string())));
    let old_parent = vmx::GroupVm::new("old");
    old_parent.add(item.clone()).unwrap();
    let destination = vmx::CompositeVm::new("destination");
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();
    let old_from_hook = old_parent.clone();
    item.on_construct(move || {
        old_from_hook.dispose()?;
        Err(VmxError::Other("attachment failure".to_string()))
    });

    assert_eq!(
        destination.add(item.clone()),
        Err(VmxError::Other("attachment failure".to_string()))
    );

    assert_eq!(old_parent.status(), ConstructionStatus::Disposed);
    assert_eq!(item.status(), ConstructionStatus::Disposed);
    assert_eq!(old_parent.items(), vec![item.clone()]);
    assert!(destination.is_empty());
}

/// COMP-040 — late disposal failure cannot make committed population retry.
#[test]
fn late_disposal_failure_does_not_retry_committed_population() {
    let item = child("moving");
    let failing_sibling = child("failing-sibling");
    failing_sibling.on_dispose(|| Err(VmxError::Other("dispose failure".to_string())));
    let old_hub = MessageHub::new();
    let old_parent = vmx::GroupVm::with_services("old", old_hub.clone(), NullDispatcher::new());
    old_parent.add(item.clone()).unwrap();
    old_parent.add(failing_sibling).unwrap();
    let old_from_hook = old_parent.clone();
    item.on_construct(move || old_from_hook.dispose());
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_from_factory = Arc::clone(&calls);
    let mapped_item = item.clone();
    let destination_hub = MessageHub::new();
    let destination = vmx::ModeledCompositeVm::<i32, Child, NullDispatcher>::new(
        "destination",
        destination_hub.clone(),
        NullDispatcher::new(),
        move || {
            calls_from_factory.fetch_add(1, Ordering::SeqCst);
            vec![1]
        },
        move |_| mapped_item.clone(),
    );

    assert_eq!(
        destination.construct(),
        Err(VmxError::Other("dispose failure".to_string()))
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(destination.items(), vec![item.clone()]);
    assert!(collection_actions(&old_hub).contains(&CollectionChangeAction::Remove));
    assert!(collection_actions(&destination_hub).contains(&CollectionChangeAction::Add));

    destination.construct().unwrap();

    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(destination.status(), ConstructionStatus::Constructed);
}

/// COMP-040 — foreign-thread disposal waits for transfer commit.
#[test]
fn concurrent_old_parent_disposal_waits_for_transfer_commit() {
    let item = child("concurrent-disposal");
    let old_parent = vmx::GroupVm::new("old");
    old_parent.add(item.clone()).unwrap();
    let destination = vmx::CompositeVm::new("destination");
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();
    let (hook_entered_tx, hook_entered_rx) = mpsc::channel();
    let (release_hook_tx, release_hook_rx) = mpsc::channel();
    let release_hook_rx = Arc::new(Mutex::new(release_hook_rx));
    item.on_construct(move || {
        hook_entered_tx.send(()).unwrap();
        release_hook_rx
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
        Ok(())
    });

    let transfer_destination = destination.clone();
    let transfer_item = item.clone();
    let transfer = std::thread::spawn(move || transfer_destination.add(transfer_item));
    hook_entered_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    let (dispose_started_tx, dispose_started_rx) = mpsc::channel();
    let (dispose_done_tx, dispose_done_rx) = mpsc::channel();
    let dispose_parent = old_parent.clone();
    let disposal = std::thread::spawn(move || {
        dispose_started_tx.send(()).unwrap();
        let result = dispose_parent.dispose();
        dispose_done_tx.send(result).unwrap();
    });
    dispose_started_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    assert!(dispose_done_rx
        .recv_timeout(Duration::from_millis(50))
        .is_err());

    release_hook_tx.send(()).unwrap();
    transfer.join().unwrap().unwrap();
    dispose_done_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap()
        .unwrap();
    disposal.join().unwrap();
    assert_eq!(old_parent.status(), ConstructionStatus::Disposed);
    assert!(old_parent.is_empty());
    assert_eq!(destination.items(), vec![item.clone()]);
    assert_eq!(item.status(), ConstructionStatus::Constructed);
}

/// COMP-040 — Lazy population rolls back earlier transfers and remains retryable.
#[test]
fn failed_population_rolls_back_as_one_transaction() {
    let old_hub = MessageHub::new();
    let destination_hub = MessageHub::new();
    let first = Child::with_model("first", "first", MessageHub::new(), NullDispatcher::new());
    let failing = Child::with_model(
        "failing",
        "failing",
        MessageHub::new(),
        NullDispatcher::new(),
    );
    let fail = Arc::new(AtomicBool::new(true));
    let fail_hook = Arc::clone(&fail);
    failing.on_construct(move || {
        if fail_hook.load(Ordering::SeqCst) {
            Err(VmxError::Other("boom".to_string()))
        } else {
            Ok(())
        }
    });
    let old_parent =
        vmx::CompositeVm::with_services("bulk-old", old_hub.clone(), NullDispatcher::new());
    old_parent.add(first.clone()).unwrap();
    let first_for_mapper = first.clone();
    let failing_for_mapper = failing.clone();
    let destination = vmx::ModeledCompositeVm::<i32, Child, NullDispatcher>::new(
        "bulk-destination",
        destination_hub.clone(),
        NullDispatcher::new(),
        || vec![1, 2],
        move |model| {
            if model == 1 {
                first_for_mapper.clone()
            } else {
                failing_for_mapper.clone()
            }
        },
    );

    assert_eq!(
        destination.construct(),
        Err(VmxError::Other("boom".to_string()))
    );

    assert_eq!(old_parent.items(), vec![first.clone()]);
    assert_eq!(first.status(), ConstructionStatus::Destructed);
    assert!(destination.is_empty());
    assert!(!collection_actions(&old_hub).contains(&CollectionChangeAction::Remove));
    assert!(!collection_actions(&destination_hub).contains(&CollectionChangeAction::Add));

    fail.store(false, Ordering::SeqCst);
    destination.construct().unwrap();
    assert!(old_parent.is_empty());
    assert_eq!(destination.len(), 2);
}

#[test]
fn failed_population_surfaces_lifecycle_compensation_failure() {
    let first = child("first");
    first.on_destruct(|| Err(VmxError::Other("compensation failed".to_string())));
    let failing = child("failing");
    failing.on_construct(|| Err(VmxError::Other("construction failed".to_string())));
    let first_for_mapper = first.clone();
    let failing_for_mapper = failing.clone();
    let destination = vmx::ModeledCompositeVm::<i32, Child, NullDispatcher>::new(
        "destination",
        MessageHub::new(),
        NullDispatcher::new(),
        || vec![1, 2],
        move |model| {
            if model == 1 {
                first_for_mapper.clone()
            } else {
                failing_for_mapper.clone()
            }
        },
    );

    assert_eq!(
        destination.construct(),
        Err(VmxError::Other("compensation failed".to_string()))
    );
    assert_eq!(first.status(), ConstructionStatus::Constructed);
    assert!(destination.is_empty());
}

/// COMP-041 — Successful transfer publishes old remove before destination add.
#[test]
fn transfer_publishes_remove_before_add() {
    let old_hub = MessageHub::new();
    let destination_hub = MessageHub::new();
    let old_parent = vmx::GroupVm::with_services("old", old_hub.clone(), NullDispatcher::new());
    let destination = vmx::CompositeVm::with_services(
        "destination",
        destination_hub.clone(),
        NullDispatcher::new(),
    );
    let item = child("ordered");
    old_parent.add(item.clone()).unwrap();
    let order = Arc::new(Mutex::new(Vec::new()));
    let old_order = Arc::clone(&order);
    let _old_subscription = old_hub.subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(change) if change.action == CollectionChangeAction::Remove)
        {
            old_order.lock().unwrap().push("remove");
        }
    });
    let destination_order = Arc::clone(&order);
    let _destination_subscription = destination_hub.subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(change) if change.action == CollectionChangeAction::Add)
        {
            destination_order.lock().unwrap().push("add");
        }
    });

    destination.add(item).unwrap();

    assert_eq!(*order.lock().unwrap(), vec!["remove", "add"]);
}

/// COMP-041 — A throwing old-current callback cannot suppress committed events.
#[test]
fn transfer_finishes_publication_before_resuming_old_current_panic() {
    let old_hub = MessageHub::new();
    let destination_hub = MessageHub::new();
    let old_parent = vmx::CompositeVm::with_services("old", old_hub.clone(), NullDispatcher::new());
    let destination = vmx::CompositeVm::with_services(
        "destination",
        destination_hub.clone(),
        NullDispatcher::new(),
    );
    let item = child("ordered");
    old_parent.add(item.clone()).unwrap();
    old_parent.set_current(Some(item.clone())).unwrap();
    old_parent.on_current_changed(|_| panic!("old current callback failed"));

    let order = Arc::new(Mutex::new(Vec::new()));
    let old_order = Arc::clone(&order);
    let _old_subscription = old_hub.subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(change) if change.action == CollectionChangeAction::Remove)
        {
            old_order.lock().unwrap().push("remove");
        }
    });
    let destination_order = Arc::clone(&order);
    let _destination_subscription = destination_hub.subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(change) if change.action == CollectionChangeAction::Add)
        {
            destination_order.lock().unwrap().push("add");
        }
    });

    let outcome = catch_unwind(AssertUnwindSafe(|| destination.add(item.clone())));

    assert!(outcome.is_err());
    assert!(old_parent.is_empty());
    assert!(old_parent.current().is_none());
    assert_eq!(destination.items(), vec![item]);
    assert_eq!(*order.lock().unwrap(), vec!["remove", "add"]);
}

/// COMP-041 — Group destinations also finish transfer publication before panic.
#[test]
fn transfer_to_group_finishes_publication_before_resuming_old_current_panic() {
    let old_hub = MessageHub::new();
    let destination_hub = MessageHub::new();
    let old_parent = vmx::CompositeVm::with_services("old", old_hub.clone(), NullDispatcher::new());
    let destination = vmx::GroupVm::with_services(
        "destination",
        destination_hub.clone(),
        NullDispatcher::new(),
    );
    let item = child("ordered");
    old_parent.add(item.clone()).unwrap();
    old_parent.set_current(Some(item.clone())).unwrap();
    old_parent.on_current_changed(|_| panic!("old current callback failed"));

    let order = Arc::new(Mutex::new(Vec::new()));
    let old_order = Arc::clone(&order);
    let _old_subscription = old_hub.subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(change) if change.action == CollectionChangeAction::Remove)
        {
            old_order.lock().unwrap().push("remove");
        }
    });
    let destination_order = Arc::clone(&order);
    let _destination_subscription = destination_hub.subscribe(move |message| {
        if matches!(message, Message::CollectionChanged(change) if change.action == CollectionChangeAction::Add)
        {
            destination_order.lock().unwrap().push("add");
        }
    });

    let outcome = catch_unwind(AssertUnwindSafe(|| destination.add(item.clone())));

    assert!(outcome.is_err());
    assert!(old_parent.is_empty());
    assert_eq!(destination.items(), vec![item]);
    assert_eq!(*order.lock().unwrap(), vec!["remove", "add"]);
}

/// COMP-041 — Transfer callbacks may replace themselves without deadlocking.
#[test]
fn transfer_old_current_callback_can_replace_itself() {
    let old_parent = vmx::CompositeVm::new("old");
    let destination = vmx::CompositeVm::new("destination");
    let item = child("replace-callback");
    old_parent.add(item.clone()).unwrap();
    old_parent.set_current(Some(item.clone())).unwrap();
    let callback_parent = old_parent.clone();
    old_parent.on_current_changed(move |_| callback_parent.on_current_changed(|_| {}));

    let (sender, receiver) = mpsc::channel();
    let destination_for_transfer = destination.clone();
    std::thread::spawn(move || {
        let _ = sender.send(destination_for_transfer.add(item));
    });

    assert_eq!(receiver.recv_timeout(Duration::from_secs(1)), Ok(Ok(())));
    assert!(old_parent.is_empty());
    assert_eq!(destination.len(), 1);
}

/// COMP-013 — BatchUpdate suppresses per-mutation events and emits one Reset
#[test]
fn batch_update_emits_single_reset() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());

    composite.batch_update(|| {
        composite.add(child("a")).unwrap();
        composite.add(child("b")).unwrap();
    });

    assert_eq!(
        collection_actions(&hub),
        vec![CollectionChangeAction::Reset]
    );
}

/// COMP-025 — `Current(selector)` builder hook drives initial selection during construct
#[test]
fn current_selector_builder_hook_drives_initial_selection_during_construct() {
    let hub = MessageHub::new();
    let children = vec![child("a"), child("b"), child("c")];
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_inner = calls.clone();
    let composite = vmx::CompositeVm::<Child>::builder()
        .name("root")
        .services(hub, NullDispatcher::new())
        .children({
            let children = children.clone();
            move || children.clone()
        })
        .current(move |items| {
            calls_inner.fetch_add(1, Ordering::SeqCst);
            assert!(items
                .iter()
                .all(|item| item.status() == ConstructionStatus::Constructed));
            items.get(1).cloned()
        })
        .build()
        .unwrap();

    composite.construct().unwrap();

    assert_eq!(composite.current(), Some(children[1].clone()));
    assert_eq!(calls.load(Ordering::SeqCst), 1);

    let hub = MessageHub::new();
    let null_selector = vmx::CompositeVm::<Child>::builder()
        .name("root")
        .services(hub.clone(), NullDispatcher::new())
        .children(|| vec![child("a")])
        .current(|_| None)
        .build()
        .unwrap();

    null_selector.construct().unwrap();

    assert_eq!(null_selector.current(), None);
    assert!(!hub.history().iter().any(|message| matches!(
        message,
        Message::PropertyChanged(change) if change.property_name == "current"
    )));
}

/// COMP-026 — OnCurrentChanged(callback) fires synchronously after each Current change
#[test]
fn on_current_changed_fires_after_current_changes() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");
    composite.add(item.clone()).unwrap();
    item.construct().unwrap();
    let observed = Arc::new(Mutex::new(Vec::new()));
    let seen = observed.clone();
    composite.on_current_changed(move |current| {
        seen.lock()
            .unwrap()
            .push(current.map(|vm| vm.name()).unwrap_or_default());
    });

    composite.select_component(&item).unwrap();
    composite.deselect_component(&item).unwrap();

    assert_eq!(
        observed.lock().unwrap().clone(),
        vec!["a".to_string(), String::new()]
    );
}

/// COMP-026 — a current-change callback may dispose the same composite.
#[test]
fn current_change_callback_can_dispose_the_composite_without_deadlocking() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");
    composite.add(item.clone()).unwrap();
    item.construct().unwrap();
    let callback_composite = composite.clone();
    let callback_status = Arc::new(Mutex::new(None));
    let seen_status = Arc::clone(&callback_status);
    composite.on_current_changed(move |current| {
        *seen_status.lock().unwrap() = current.map(|child| child.status());
        callback_composite.dispose().unwrap();
    });

    let worker_composite = composite.clone();
    let (completed, completion) = mpsc::channel();
    std::thread::spawn(move || {
        completed
            .send(worker_composite.set_current(Some(item)))
            .unwrap();
    });

    assert_eq!(
        completion
            .recv_timeout(Duration::from_secs(1))
            .expect("re-entrant disposal must not deadlock current assignment"),
        Ok(())
    );
    assert_eq!(
        *callback_status.lock().unwrap(),
        Some(ConstructionStatus::Constructed)
    );
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
}

#[test]
fn dispatched_current_change_callback_can_dispose_without_deadlocking() {
    let composite =
        vmx::CompositeVm::with_services("root", MessageHub::new(), ImmediateDispatcher::new());
    let item = child("a");
    composite.add(item.clone()).unwrap();
    composite.set_async_selection(true);
    let callback_composite = composite.clone();
    composite.on_current_changed(move |_| callback_composite.dispose().unwrap());

    let worker_composite = composite.clone();
    let (completed, completion) = mpsc::channel();
    std::thread::spawn(move || {
        completed
            .send(worker_composite.set_current(Some(item)))
            .unwrap();
    });

    assert_eq!(
        completion
            .recv_timeout(Duration::from_secs(1))
            .expect("re-entrant disposal must not deadlock dispatched current assignment"),
        Ok(())
    );
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
}

/// COMP-027 — Adding a child sets its Parent; removing clears it
#[test]
fn add_and_remove_manage_child_parent() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");

    composite.add(item.clone()).unwrap();
    assert_eq!(item.parent_id(), Some(composite.id()));
    item.construct().unwrap();
    assert!(item.can_select());
    item.select();
    assert_eq!(composite.current(), Some(item.clone()));
    assert!(item.is_current());
    item.deselect();
    assert_eq!(composite.current(), None);

    composite.remove(&item).unwrap();
    assert_eq!(item.parent_id(), None);
    assert!(!item.can_select());
    item.select();
    assert_eq!(composite.current(), None);
}
