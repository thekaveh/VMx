//! A failed add, insert or replacement that auto-started a background child
//! returns that child to `Destructed` once its construct settles with no
//! parent (spec/06 §4.2, spec/07 §1.1, ADR-0218 rule 7, #1372).

use std::sync::atomic::{AtomicBool, Ordering};
use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, GroupVm, ManualDispatcher, Message, MessageHub,
    Subscription, VmNode, VmxError, VmxResult,
};

type Child = ComponentVm<i32, ManualDispatcher>;

fn child(hub: &MessageHub, dispatcher: &ManualDispatcher, background: bool) -> Child {
    ComponentVm::builder()
        .name("child")
        .model(1)
        .background(background)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap()
}

/// The membership changes these scenarios try, for both containers.
#[derive(Clone, Copy, Debug)]
enum Change {
    Add,
    Insert,
    Replace,
}

/// The container surface these scenarios use.
trait Container: Clone + Send + Sync + 'static {
    fn create(hub: &MessageHub, dispatcher: &ManualDispatcher) -> Self;
    fn add(&self, child: Child) -> VmxResult<()>;
    fn insert(&self, index: usize, child: Child) -> VmxResult<()>;
    fn replace(&self, index: usize, child: Child) -> VmxResult<Child>;
    fn construct(&self) -> VmxResult<()>;
    fn dispose(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    fn len(&self) -> usize;
}

impl Container for CompositeVm<Child, ManualDispatcher> {
    fn create(hub: &MessageHub, dispatcher: &ManualDispatcher) -> Self {
        let vm = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
        vm.set_auto_construct_on_add(true);
        vm
    }
    fn add(&self, child: Child) -> VmxResult<()> {
        CompositeVm::add(self, child)
    }
    fn insert(&self, index: usize, child: Child) -> VmxResult<()> {
        CompositeVm::insert(self, index, child)
    }
    fn replace(&self, index: usize, child: Child) -> VmxResult<Child> {
        CompositeVm::replace(self, index, child)
    }
    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        CompositeVm::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }
    fn len(&self) -> usize {
        CompositeVm::len(self)
    }
}

impl Container for GroupVm<Child, ManualDispatcher> {
    fn create(hub: &MessageHub, dispatcher: &ManualDispatcher) -> Self {
        let vm = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
        vm.set_auto_construct_on_add(true);
        vm
    }
    fn add(&self, child: Child) -> VmxResult<()> {
        GroupVm::add(self, child)
    }
    fn insert(&self, index: usize, child: Child) -> VmxResult<()> {
        GroupVm::insert(self, index, child)
    }
    fn replace(&self, index: usize, child: Child) -> VmxResult<Child> {
        GroupVm::replace(self, index, child)
    }
    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        GroupVm::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
    }
    fn len(&self) -> usize {
        GroupVm::len(self)
    }
}

/// Disposes `container` once, when `child` publishes `Constructing`.
fn dispose_on_constructing<C: Container>(
    hub: &MessageHub,
    container: &C,
    child: &Child,
) -> Subscription {
    let container = container.clone();
    let child_id = child.id();
    let fired = AtomicBool::new(false);
    hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(change) = message {
            if change.sender_id == child_id
                && change.status == ConstructionStatus::Constructing
                && !fired.swap(true, Ordering::SeqCst)
            {
                container.dispose().unwrap();
            }
        }
    })
}

/// A container in the given state: `Constructed`, or `Constructing` while it
/// waits on a background member. Each has one member at index 0 that a
/// replacement can displace.
fn container<C: Container>(
    hub: &MessageHub,
    dispatcher: &ManualDispatcher,
    constructing: bool,
) -> C {
    let container = C::create(hub, dispatcher);
    container.add(child(hub, dispatcher, constructing)).unwrap();
    container.construct().unwrap();
    if constructing {
        assert_eq!(container.status(), ConstructionStatus::Constructing);
    } else {
        dispatcher.drain();
        assert_eq!(container.status(), ConstructionStatus::Constructed);
    }
    container
}

/// Runs `change` with a child that the container auto-starts and whose
/// `Constructing` publication disposes the container. Returns the child
/// after the queued work drained.
fn failed_change<C: Container>(change: Change, constructing: bool, background: bool) -> Child {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let container = container::<C>(&hub, &dispatcher, constructing);
    let c = child(&hub, &dispatcher, background);
    let _dispose = dispose_on_constructing(&hub, &container, &c);

    let result = match change {
        Change::Add => container.add(c.clone()),
        Change::Insert => container.insert(0, c.clone()),
        Change::Replace => container.replace(0, c.clone()).map(|_| ()),
    };

    assert_eq!(
        result,
        Err(VmxError::Disposed),
        "{change:?} fails with the disposal error"
    );
    assert!(c.parent_handle().is_none(), "{change:?} leaves no parent");
    dispatcher.drain();
    assert_eq!(container.status(), ConstructionStatus::Disposed);
    assert_eq!(
        container.len(),
        1,
        "{change:?} keeps only the original member"
    );
    c
}

fn background_child_returns_to_destructed<C: Container>() {
    for constructing in [false, true] {
        for change in [Change::Add, Change::Insert, Change::Replace] {
            let c = failed_change::<C>(change, constructing, true);
            assert_eq!(
                c.status(),
                ConstructionStatus::Destructed,
                "{change:?} while constructing={constructing}: the background child \
                 returns to Destructed once it settles"
            );
            assert!(c.parent_handle().is_none());
        }
    }
}

fn synchronous_child_returns_to_destructed<C: Container>() {
    for constructing in [false, true] {
        for change in [Change::Add, Change::Insert, Change::Replace] {
            let c = failed_change::<C>(change, constructing, false);
            assert_eq!(c.status(), ConstructionStatus::Destructed);
            assert!(c.parent_handle().is_none());
        }
    }
}

/// COMP-054 — a failed composite add, insert or replacement returns a
/// background child it auto-started to `Destructed` once the child settles,
/// with no parent, from `Constructed` and from `Constructing`.
#[test]
fn comp_054_failed_composite_add_returns_background_child_to_destructed() {
    background_child_returns_to_destructed::<CompositeVm<Child, ManualDispatcher>>();
}

/// COMP-054 — a synchronous child in the same steps fails the change and ends
/// `Destructed`, with no parent.
#[test]
fn comp_054_failed_composite_add_returns_synchronous_child_to_destructed() {
    synchronous_child_returns_to_destructed::<CompositeVm<Child, ManualDispatcher>>();
}

/// GRP-017 — a failed group add, insert or replacement returns a background
/// child it auto-started to `Destructed` once the child settles, with no
/// parent, from `Constructed` and from `Constructing`.
#[test]
fn grp_017_failed_group_add_returns_background_child_to_destructed() {
    background_child_returns_to_destructed::<GroupVm<Child, ManualDispatcher>>();
}

/// GRP-017 — a synchronous child in the same steps fails the change and ends
/// `Destructed`, with no parent.
#[test]
fn grp_017_failed_group_add_returns_synchronous_child_to_destructed() {
    synchronous_child_returns_to_destructed::<GroupVm<Child, ManualDispatcher>>();
}

/// A background child that a container adopted before it settled is left
/// alone: the deferred compensation destructs only a child with no parent.
#[test]
fn adopted_background_child_is_not_destructed_after_a_failed_add() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let failing: CompositeVm<Child, ManualDispatcher> = container(&hub, &dispatcher, false);
    let adopter: CompositeVm<Child, ManualDispatcher> =
        CompositeVm::with_services("adopter", hub.clone(), dispatcher.clone());
    let c = child(&hub, &dispatcher, true);
    let _dispose = dispose_on_constructing(&hub, &failing, &c);

    assert_eq!(failing.add(c.clone()), Err(VmxError::Disposed));
    assert_eq!(c.status(), ConstructionStatus::Constructing);
    adopter.add(c.clone()).unwrap();
    dispatcher.drain();

    assert_eq!(c.status(), ConstructionStatus::Constructed);
    assert!(c.parent_handle().is_some());
    assert_eq!(adopter.len(), 1);
}
