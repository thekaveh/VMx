//! Containers publish their collection changes on the hub (spec ch. 01 §1.4,
//! ch. 06 §4–§4.2, ch. 07, ch. 21 §2.4, ADR-0142).
//!
//! Rust's `CompositeVm` and `GroupVm` keep their children in a hub-bound
//! `ObservableList`, so the container's hub is its collection-change channel:
//! there is no separate local stream to order against. These tests therefore
//! assert that each effective mutation delivers exactly one
//! `CollectionChangedMessage` before the mutating call returns, in mutation
//! order, sent by the container, with the positions of chapter 21 §2.4. Rust's
//! additional `PropertyChanged("Count")` message (ADR-0085) is ignored.

use std::sync::{Arc, Mutex};

use vmx::{
    CollectionChangeAction, ConstructionStatus, ForwardingCompositeVm, Message, MessageHub,
    MessageRecorder, NullDispatcher, ParentHandle, Subscription, VmNode, VmxError, VmxResult,
};

type Child = vmx::ComponentVm<&'static str>;
type Composite = vmx::CompositeVm<Child>;
type Group = vmx::GroupVm<Child>;

/// Sender identity, action, old index, and new index of one collection change.
type Change = (usize, CollectionChangeAction, Option<usize>, Option<usize>);

fn child(hub: &MessageHub, name: &'static str) -> Child {
    Child::with_model(name, name, hub.clone(), NullDispatcher::new())
}

fn composite(hub: &MessageHub, name: &str) -> Composite {
    Composite::with_services(name, hub.clone(), NullDispatcher::new())
}

fn group(hub: &MessageHub, name: &str) -> Group {
    Group::with_services(name, hub.clone(), NullDispatcher::new())
}

fn change_of(message: &Message) -> Option<Change> {
    match message {
        Message::CollectionChanged(change) => Some((
            change.sender_id,
            change.action.clone(),
            change.old_index,
            change.new_index,
        )),
        _ => None,
    }
}

fn add(sender: usize, index: usize) -> Change {
    (sender, CollectionChangeAction::Add, None, Some(index))
}

fn remove(sender: usize, index: usize) -> Change {
    (sender, CollectionChangeAction::Remove, Some(index), None)
}

fn replace(sender: usize, index: usize) -> Change {
    (
        sender,
        CollectionChangeAction::Replace,
        Some(index),
        Some(index),
    )
}

fn moved(sender: usize, from: usize, to: usize) -> Change {
    (sender, CollectionChangeAction::Move, Some(from), Some(to))
}

fn reset(sender: usize) -> Change {
    (sender, CollectionChangeAction::Reset, None, None)
}

/// Collection changes in the order the hub delivers them to subscribers.
struct Delivered {
    changes: Arc<Mutex<Vec<Change>>>,
    _subscription: Subscription,
}

impl Delivered {
    fn on(hub: &MessageHub) -> Self {
        let changes = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&changes);
        let subscription = hub.subscribe(move |message| {
            if let Some(change) = change_of(message) {
                sink.lock().unwrap().push(change);
            }
        });
        Self {
            changes,
            _subscription: subscription,
        }
    }

    fn changes(&self) -> Vec<Change> {
        self.changes.lock().unwrap().clone()
    }
}

/// Collection changes in the order the hub accepted them, including any
/// still deferred by a hub transaction.
fn accepted(recorder: &MessageRecorder) -> Vec<Change> {
    recorder.messages().iter().filter_map(change_of).collect()
}

/// Runs one mutation and asserts it delivered exactly `expected` before
/// returning.
fn step(delivered: &Delivered, mutate: impl FnOnce(), expected: &[Change]) {
    let before = delivered.changes().len();
    mutate();
    assert_eq!(&delivered.changes()[before..], expected);
}

/// Records, at each delivery from `sender`, whether `probe` is a member and the
/// container size, so tests can check that delivery sees committed membership.
type MembershipProbe = Arc<Mutex<Vec<(CollectionChangeAction, bool, usize)>>>;

fn probe_membership<F>(
    hub: &MessageHub,
    sender: usize,
    inspect: F,
) -> (MembershipProbe, Subscription)
where
    F: Fn() -> (bool, usize) + Send + Sync + 'static,
{
    let seen: MembershipProbe = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&seen);
    let subscription = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            if change.sender_id == sender {
                let (contains, len) = inspect();
                sink.lock()
                    .unwrap()
                    .push((change.action.clone(), contains, len));
            }
        }
    });
    (seen, subscription)
}

/// A composite node that can nest, used to provoke an ownership cycle.
#[derive(Clone)]
struct Nested(vmx::CompositeVm<Nested>);

impl Nested {
    fn new(hub: &MessageHub, name: &str) -> Self {
        Self(vmx::CompositeVm::with_services(
            name,
            hub.clone(),
            NullDispatcher::new(),
        ))
    }
}

impl PartialEq for Nested {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl VmNode for Nested {
    fn id(&self) -> usize {
        self.0.id()
    }

    fn construct(&self) -> VmxResult<()> {
        self.0.construct()
    }

    fn destruct(&self) -> VmxResult<()> {
        self.0.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        self.0.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.0.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        VmNode::set_parent_id(&self.0, parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.0.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        VmNode::set_parent_handle(&self.0, parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        VmNode::parent_handle(&self.0)
    }
}

/// COMP-042 — each effective composite mutation publishes one hub message sent by the composite
#[test]
fn comp_042_each_composite_mutation_publishes_one_hub_message() {
    let hub = MessageHub::new();
    let parent = composite(&hub, "parent");
    let id = parent.id();
    let [a, b, c, d] = ["a", "b", "c", "d"].map(|name| child(&hub, name));
    let delivered = Delivered::on(&hub);

    // Membership after each step is shown in the trailing comment.
    step(&delivered, || parent.add(a.clone()).unwrap(), &[add(id, 0)]); // [a]
    step(
        &delivered,
        || parent.insert(0, b.clone()).unwrap(),
        &[add(id, 0)],
    ); // [b, a]
    step(
        &delivered,
        || parent.move_item(0, 1).unwrap(),
        &[moved(id, 0, 1)],
    ); // [a, b]
    step(
        &delivered,
        || assert_eq!(parent.replace(0, c.clone()).unwrap(), a),
        &[replace(id, 0)],
    ); // [c, b]
    step(
        &delivered,
        || assert_eq!(parent.remove_at(1).unwrap(), b),
        &[remove(id, 1)],
    ); // [c]
    step(&delivered, || parent.remove(&c).unwrap(), &[remove(id, 0)]); // []
    step(&delivered, || parent.add(d.clone()).unwrap(), &[add(id, 0)]); // [d]
    step(&delivered, || parent.clear(), &[reset(id)]); // []

    assert_eq!(delivered.changes().len(), 8);
    assert!(parent.is_empty());
}

/// COMP-042 — the composite's hub message observes the committed membership
#[test]
fn comp_042_hub_message_observes_committed_membership() {
    let hub = MessageHub::new();
    let parent = composite(&hub, "parent");
    let a = child(&hub, "a");
    let (seen, _subscription) = probe_membership(&hub, parent.id(), {
        let parent = parent.clone();
        let a = a.clone();
        move || (parent.items().contains(&a), parent.len())
    });

    parent.add(a.clone()).unwrap();
    parent.remove(&a).unwrap();

    assert_eq!(
        *seen.lock().unwrap(),
        vec![
            (CollectionChangeAction::Add, true, 1),
            (CollectionChangeAction::Remove, false, 0),
        ]
    );
}

/// COMP-043 — nested composite batches publish nothing inside and one Reset on outermost exit
#[test]
fn comp_043_nested_batch_publishes_one_reset_on_outermost_exit() {
    let hub = MessageHub::new();
    let parent = composite(&hub, "parent");
    let id = parent.id();
    let recorder = hub.record(64);
    let delivered = Delivered::on(&hub);

    parent.batch_update(|| {
        parent.add(child(&hub, "a")).unwrap();
        parent.batch_update(|| {
            parent.add(child(&hub, "b")).unwrap();
            parent.move_item(0, 1).unwrap();
            assert!(delivered.changes().is_empty());
        });
        assert!(
            delivered.changes().is_empty(),
            "an inner batch exit publishes nothing"
        );
    });

    assert_eq!(delivered.changes(), vec![reset(id)]);
    assert_eq!(accepted(&recorder), vec![reset(id)]);
}

/// COMP-043 — an empty batch or one holding only same-index moves publishes nothing
#[test]
fn comp_043_batch_without_mutation_publishes_nothing() {
    let hub = MessageHub::new();
    let parent = composite(&hub, "parent");
    parent.add(child(&hub, "a")).unwrap();
    parent.add(child(&hub, "b")).unwrap();
    let recorder = hub.record(64);

    parent.batch_update(|| {});
    parent.batch_update(|| {
        parent.move_item(0, 0).unwrap();
        parent.batch_update(|| parent.move_item(1, 1).unwrap());
    });

    assert_eq!(accepted(&recorder), vec![]);
}

/// COMP-044 — a transfer publishes the old container's Remove before the new container's Add
#[test]
fn comp_044_transfer_publishes_old_remove_before_new_add() {
    let hub = MessageHub::new();
    let old_parent = composite(&hub, "old");
    let peers = group(&hub, "peers");
    let new_parent = composite(&hub, "new");
    let sibling = child(&hub, "sibling");
    let transferred = child(&hub, "transferred");
    old_parent.add(sibling).unwrap();
    old_parent.add(transferred.clone()).unwrap();
    let delivered = Delivered::on(&hub);

    peers.add(transferred.clone()).unwrap(); // composite -> group
    new_parent.insert(0, transferred.clone()).unwrap(); // group -> composite

    assert_eq!(
        delivered.changes(),
        vec![
            remove(old_parent.id(), 1),
            add(peers.id(), 0),
            remove(peers.id(), 0),
            add(new_parent.id(), 0),
        ]
    );
    assert_eq!(new_parent.items(), vec![transferred]);
}

/// COMP-044 — rejected, rolled-back, and same-index mutations publish nothing
#[test]
fn comp_044_failed_and_no_op_mutations_publish_nothing() {
    let hub = MessageHub::new();
    let parent = composite(&hub, "parent");
    let a = child(&hub, "a");
    parent.add(a.clone()).unwrap();

    let inner = Nested::new(&hub, "inner");
    let outer = Nested::new(&hub, "outer");
    outer.0.add(inner.clone()).unwrap();

    let source = composite(&hub, "source");
    let failing = child(&hub, "failing");
    failing.on_construct(|| Err(VmxError::Other("construct failed".to_string())));
    source.add(failing.clone()).unwrap();
    let destination = composite(&hub, "destination");
    destination.set_auto_construct_on_add(true);
    destination.construct().unwrap();

    let recorder = hub.record(64);

    assert_eq!(parent.add(a.clone()), Err(VmxError::DuplicateChild));
    assert_eq!(inner.0.add(outer.clone()), Err(VmxError::OwnershipCycle));
    assert!(matches!(
        parent.insert(99, child(&hub, "late")),
        Err(VmxError::InvalidArgument(_))
    ));
    assert!(matches!(
        parent.replace(99, child(&hub, "late")),
        Err(VmxError::InvalidArgument(_))
    ));
    assert!(matches!(
        parent.remove_at(99),
        Err(VmxError::InvalidArgument(_))
    ));
    assert!(matches!(
        parent.move_item(0, 99),
        Err(VmxError::InvalidArgument(_))
    ));
    assert_eq!(
        destination.add(failing.clone()),
        Err(VmxError::Other("construct failed".to_string()))
    );
    assert_eq!(parent.move_item(0, 0), Ok(()));
    assert_eq!(parent.remove(&child(&hub, "stranger")), Ok(()));
    destination.clear();

    assert_eq!(accepted(&recorder), vec![]);
    assert_eq!(parent.items(), vec![a]);
    assert_eq!(source.items(), vec![failing]);
    assert!(destination.is_empty());
}

/// COMP-045 — a hub transaction defers composite messages and delivers them in mutation order
#[test]
fn comp_045_hub_transaction_defers_messages_in_mutation_order() {
    let hub = MessageHub::new();
    let parent = composite(&hub, "parent");
    let id = parent.id();
    let delivered = Delivered::on(&hub);

    hub.batch(|| {
        parent.add(child(&hub, "a")).unwrap();
        parent.add(child(&hub, "b")).unwrap();
        parent.move_item(0, 1).unwrap();
        assert!(delivered.changes().is_empty());
    });

    assert_eq!(
        delivered.changes(),
        vec![add(id, 0), add(id, 1), moved(id, 0, 1)]
    );
}

/// COMP-045 — a disposed composite publishes no further collection change
#[test]
fn comp_045_disposed_composite_publishes_nothing() {
    let hub = MessageHub::new();
    let parent = composite(&hub, "parent");
    let a = child(&hub, "a");
    let b = child(&hub, "b");
    parent.add(a.clone()).unwrap();
    parent.add(b.clone()).unwrap();
    parent.dispose().unwrap();
    let recorder = hub.record(64);

    // A disposed composite may reject a mutation; either way it publishes nothing.
    assert_eq!(parent.add(child(&hub, "late")), Err(VmxError::Disposed));
    let _ = parent.insert(0, child(&hub, "late"));
    let _ = parent.replace(0, child(&hub, "late"));
    let _ = parent.move_item(0, 1);
    let _ = parent.remove_at(1);
    let _ = parent.remove(&a);
    parent.batch_update(|| {
        let _ = parent.remove(&b);
    });
    parent.clear();

    assert_eq!(accepted(&recorder), vec![]);
}

/// COMP-045 — a forwarding wrapper publishes each change once, sent by the wrapped composite
#[test]
fn comp_045_forwarding_wrapper_publishes_each_change_once() {
    let hub = MessageHub::new();
    let parent = composite(&hub, "parent");
    let id = parent.id();
    let wrapper = ForwardingCompositeVm::new(parent.clone());
    let a = child(&hub, "a");
    let b = child(&hub, "b");
    let delivered = Delivered::on(&hub);

    wrapper.add(a.clone()).unwrap(); // [a]
    wrapper.insert(0, b.clone()).unwrap(); // [b, a]
    wrapper.move_item(0, 1).unwrap(); // [a, b]
    wrapper.remove(&a).unwrap(); // [b]
    wrapper.batch_update(|| wrapper.clear()); // []

    assert_eq!(
        delivered.changes(),
        vec![
            add(id, 0),
            add(id, 0),
            moved(id, 0, 1),
            remove(id, 0),
            reset(id)
        ]
    );
    assert!(parent.is_empty());
}

/// GRP-012 — each effective group mutation publishes one hub message sent by the group
#[test]
fn grp_012_each_group_mutation_publishes_one_hub_message() {
    let hub = MessageHub::new();
    let peers = group(&hub, "peers");
    let id = peers.id();
    let [a, b, c, d] = ["a", "b", "c", "d"].map(|name| child(&hub, name));
    let delivered = Delivered::on(&hub);

    // Membership after each step is shown in the trailing comment.
    step(&delivered, || peers.add(a.clone()).unwrap(), &[add(id, 0)]); // [a]
    step(
        &delivered,
        || peers.insert(0, b.clone()).unwrap(),
        &[add(id, 0)],
    ); // [b, a]
    step(
        &delivered,
        || peers.move_item(0, 1).unwrap(),
        &[moved(id, 0, 1)],
    ); // [a, b]
    step(&delivered, || peers.move_item(1, 1).unwrap(), &[]); // [a, b]
    step(
        &delivered,
        || assert_eq!(peers.replace(0, c.clone()).unwrap(), a),
        &[replace(id, 0)],
    ); // [c, b]
    step(
        &delivered,
        || assert_eq!(peers.remove_at(0).unwrap(), c),
        &[remove(id, 0)],
    ); // [b]
    step(&delivered, || peers.remove(&b).unwrap(), &[remove(id, 0)]); // []
    step(&delivered, || peers.add(d.clone()).unwrap(), &[add(id, 0)]); // [d]
    step(&delivered, || peers.clear(), &[reset(id)]); // []

    assert_eq!(delivered.changes().len(), 8);
    assert!(peers.is_empty());
}

/// GRP-012 — the group's hub message observes the committed membership
#[test]
fn grp_012_hub_message_observes_committed_membership() {
    let hub = MessageHub::new();
    let peers = group(&hub, "peers");
    let a = child(&hub, "a");
    let (seen, _subscription) = probe_membership(&hub, peers.id(), {
        let peers = peers.clone();
        let a = a.clone();
        move || (peers.items().contains(&a), peers.len())
    });

    peers.add(a.clone()).unwrap();
    peers.remove(&a).unwrap();

    assert_eq!(
        *seen.lock().unwrap(),
        vec![
            (CollectionChangeAction::Add, true, 1),
            (CollectionChangeAction::Remove, false, 0),
        ]
    );
}

/// GRP-012 — group mutations without a collection change, and any after disposal, publish nothing
#[test]
fn grp_012_no_op_and_post_dispose_mutations_publish_nothing() {
    let hub = MessageHub::new();
    let peers = group(&hub, "peers");
    let a = child(&hub, "a");
    let b = child(&hub, "b");
    peers.add(a.clone()).unwrap();
    peers.add(b.clone()).unwrap();
    let recorder = hub.record(64);

    assert_eq!(peers.add(a.clone()), Err(VmxError::DuplicateChild));
    assert!(matches!(
        peers.insert(9, child(&hub, "late")),
        Err(VmxError::InvalidArgument(_))
    ));
    assert!(matches!(
        peers.move_item(0, 9),
        Err(VmxError::InvalidArgument(_))
    ));
    assert_eq!(peers.move_item(1, 1), Ok(()));
    assert_eq!(peers.remove(&child(&hub, "stranger")), Ok(()));
    assert_eq!(accepted(&recorder), vec![]);

    peers.dispose().unwrap();
    // A disposed group may reject a mutation; either way it publishes nothing.
    assert_eq!(peers.add(child(&hub, "late")), Err(VmxError::Disposed));
    let _ = peers.insert(0, child(&hub, "late"));
    let _ = peers.replace(0, child(&hub, "late"));
    let _ = peers.move_item(0, 1);
    let _ = peers.remove_at(1);
    let _ = peers.remove(&a);
    peers.batch_update(|| {
        let _ = peers.remove(&b);
    });
    peers.clear();

    assert_eq!(accepted(&recorder), vec![]);
}

/// GRP-013 — nested group batches publish one Reset on outermost exit; empty batches publish nothing
#[test]
fn grp_013_nested_group_batch_publishes_one_reset() {
    let hub = MessageHub::new();
    let peers = group(&hub, "peers");
    let id = peers.id();
    let delivered = Delivered::on(&hub);

    peers.batch_update(|| {});
    peers.batch_update(|| peers.batch_update(|| {}));
    assert!(delivered.changes().is_empty());

    peers.batch_update(|| {
        peers.add(child(&hub, "a")).unwrap();
        peers.batch_update(|| {
            peers.add(child(&hub, "b")).unwrap();
            assert!(delivered.changes().is_empty());
        });
        assert!(
            delivered.changes().is_empty(),
            "an inner batch exit publishes nothing"
        );
    });
    assert_eq!(delivered.changes(), vec![reset(id)]);

    peers.batch_update(|| peers.move_item(1, 1).unwrap());
    assert_eq!(delivered.changes(), vec![reset(id)]);
}
