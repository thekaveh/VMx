use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use vmx::{
    CollectionChangeAction, ConstructionStatus, Message, MessageHub, NullDispatcher,
    SelectableVmCollection, VmCollection, VmNode, VmxError,
};

type Child = vmx::ComponentVm<&'static str>;

fn child(name: &'static str) -> Child {
    Child::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

fn move_events(hub: &MessageHub) -> Vec<vmx::CollectionChangedMessage> {
    hub.history()
        .into_iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) if change.action == CollectionChangeAction::Move => {
                Some(change)
            }
            _ => None,
        })
        .collect()
}

fn accepts_collection<C: VmCollection<Child>>(collection: &C) -> usize {
    collection.len()
}

fn accepts_selectable<C: SelectableVmCollection<Child>>(collection: &C) -> Option<Child> {
    collection.current()
}

/// COL-032 — composite and group share VmCollection; selection is a separate capability.
#[test]
fn shared_contract_separates_selection() {
    let composite = vmx::CompositeVm::<Child>::new("composite");
    let group = vmx::GroupVm::<Child>::new("group");

    assert_eq!(accepts_collection(&composite), 0);
    assert_eq!(accepts_collection(&group), 0);
    assert_eq!(accepts_selectable(&composite), None);
}

/// COL-033 — forward move emits one Move event with both indices.
#[test]
fn forward_move_emits_one_move_event() {
    let hub = MessageHub::new();
    let composite =
        vmx::CompositeVm::with_services("composite", hub.clone(), NullDispatcher::new());
    let (a, b, c) = (child("a"), child("b"), child("c"));
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    composite.add(c.clone()).unwrap();

    composite.move_item(0, 2).unwrap();

    assert_eq!(composite.items(), vec![b, c, a.clone()]);
    let events = move_events(&hub);
    assert_eq!(events.len(), 1);
    assert_eq!(
        (events[0].old_index, events[0].new_index),
        (Some(0), Some(2))
    );
}

/// COL-034 — backward move works for GroupVm through the shared contract.
#[test]
fn backward_move_works_for_group() {
    let hub = MessageHub::new();
    let group = vmx::GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    let (a, b, c) = (child("a"), child("b"), child("c"));
    group.add(a.clone()).unwrap();
    group.add(b.clone()).unwrap();
    group.add(c.clone()).unwrap();

    group.move_item(2, 0).unwrap();

    assert_eq!(group.items(), vec![c, a, b]);
    let events = move_events(&hub);
    assert_eq!(
        (events[0].old_index, events[0].new_index),
        (Some(2), Some(0))
    );
}

/// COL-035 — same-index move is a true no-op.
#[test]
fn same_index_move_is_true_no_op() {
    let hub = MessageHub::new();
    let composite =
        vmx::CompositeVm::with_services("composite", hub.clone(), NullDispatcher::new());
    let (a, b, c) = (child("a"), child("b"), child("c"));
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    composite.add(c.clone()).unwrap();
    let before = hub.history().len();

    composite.batch_update(|| composite.move_item(1, 1).unwrap());

    assert_eq!(composite.items(), vec![a, b, c]);
    assert_eq!(hub.history().len(), before);
}

/// COL-036 — invalid bounds are rejected atomically.
#[test]
fn invalid_bounds_are_atomic() {
    let hub = MessageHub::new();
    let composite =
        vmx::CompositeVm::with_services("composite", hub.clone(), NullDispatcher::new());
    let (a, b, c) = (child("a"), child("b"), child("c"));
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    composite.add(c.clone()).unwrap();
    let before = hub.history().len();

    assert!(matches!(
        composite.move_item(3, 0),
        Err(VmxError::InvalidArgument(_))
    ));
    assert!(matches!(
        composite.move_item(0, 3),
        Err(VmxError::InvalidArgument(_))
    ));
    assert_eq!(composite.items(), vec![a, b, c]);
    assert_eq!(hub.history().len(), before);
}

/// COL-037 — move preserves identity, parent, lifecycle, and current selection.
#[test]
fn move_preserves_identity_parent_lifecycle_and_current() {
    let composite = vmx::CompositeVm::new("composite");
    let (a, b, c) = (child("a"), child("b"), child("c"));
    composite.add(a.clone()).unwrap();
    composite.add(b).unwrap();
    composite.add(c).unwrap();
    composite.construct().unwrap();
    composite.select_component(&a).unwrap();
    let parent = a.parent_id();

    composite.move_item(0, 2).unwrap();

    assert_eq!(composite.get(2), Some(a.clone()));
    assert_eq!(composite.current(), Some(a.clone()));
    assert!(a.is_current());
    assert_eq!(a.parent_id(), parent);
    assert_eq!(a.status(), ConstructionStatus::Constructed);
}

/// COL-038 — a move inside batchUpdate collapses to one Reset.
#[test]
fn batched_move_collapses_to_reset() {
    let hub = MessageHub::new();
    let composite =
        vmx::CompositeVm::with_services("composite", hub.clone(), NullDispatcher::new());
    composite.add(child("a")).unwrap();
    composite.add(child("b")).unwrap();
    composite.add(child("c")).unwrap();
    let before = hub.history().len();

    composite.batch_update(|| composite.move_item(0, 2).unwrap());

    let changes: Vec<_> = hub.history()[before..]
        .iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) => Some(change.action.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(changes, vec![CollectionChangeAction::Reset]);
}

/// COL-039 — moving an auto-constructed child never constructs it again.
#[test]
fn move_does_not_reconstruct_auto_constructed_child() {
    let composite = vmx::CompositeVm::new("composite");
    composite.set_auto_construct_on_add(true);
    composite.construct().unwrap();
    let moved = child("moved");
    let constructs = Arc::new(AtomicUsize::new(0));
    let observed = constructs.clone();
    moved.on_construct(move || {
        observed.fetch_add(1, Ordering::SeqCst);
        Ok(())
    });
    composite.add(moved.clone()).unwrap();
    composite.add(child("other")).unwrap();

    composite.move_item(0, 1).unwrap();

    assert_eq!(composite.get(1), Some(moved));
    assert_eq!(constructs.load(Ordering::SeqCst), 1);
}
