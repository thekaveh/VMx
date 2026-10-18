//! Auto-construct-on-add while a container is Constructing (spec/02 §6): the
//! construct walk joins a child added during it, and the container completes
//! only when that child is Constructed.

use std::sync::{mpsc, Arc, Mutex};
use vmx::{
    CompositeVm, ConstructionStatus, GroupVm, LifecycleErrorStream, LifecycleSettleCallback,
    Message, MessageHub, NullDispatcher, ParentHandle, Subscription, VmNode, VmxResult,
};

/// A node whose construct either completes at once (foreground) or stays
/// Constructing until the test settles it (background).
#[derive(Clone)]
struct Node {
    id: usize,
    background: bool,
    status: Arc<Mutex<ConstructionStatus>>,
    constructs: Arc<Mutex<usize>>,
    settle: Arc<Mutex<Option<LifecycleSettleCallback>>>,
    parent: Arc<Mutex<Option<usize>>>,
    handle: Arc<Mutex<Option<ParentHandle>>>,
}

impl Node {
    fn new(background: bool) -> Self {
        static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(1 << 41);
        Self {
            id: NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst),
            background,
            status: Arc::new(Mutex::new(ConstructionStatus::Destructed)),
            constructs: Arc::default(),
            settle: Arc::default(),
            parent: Arc::default(),
            handle: Arc::default(),
        }
    }

    fn constructs(&self) -> usize {
        *self.constructs.lock().unwrap()
    }

    /// Settles a background construct at `status` and notifies the container.
    fn finish(&self, status: ConstructionStatus) {
        *self.status.lock().unwrap() = status;
        let callback = self.settle.lock().unwrap().take();
        if let Some(callback) = callback {
            callback();
        }
    }
}

impl PartialEq for Node {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl VmNode for Node {
    fn id(&self) -> usize {
        self.id
    }
    fn construct(&self) -> VmxResult<()> {
        *self.constructs.lock().unwrap() += 1;
        *self.status.lock().unwrap() = if self.background {
            ConstructionStatus::Constructing
        } else {
            ConstructionStatus::Constructed
        };
        Ok(())
    }
    fn destruct(&self) -> VmxResult<()> {
        *self.status.lock().unwrap() = ConstructionStatus::Destructed;
        Ok(())
    }
    fn dispose(&self) -> VmxResult<()> {
        *self.status.lock().unwrap() = ConstructionStatus::Disposed;
        Ok(())
    }
    fn status(&self) -> ConstructionStatus {
        *self.status.lock().unwrap()
    }
    fn set_parent_id(&self, parent_id: Option<usize>) {
        *self.parent.lock().unwrap() = parent_id;
    }
    fn parent_id(&self) -> Option<usize> {
        *self.parent.lock().unwrap()
    }
    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        *self.handle.lock().unwrap() = parent;
    }
    fn parent_handle(&self) -> Option<ParentHandle> {
        self.handle.lock().unwrap().clone()
    }
    fn when_lifecycle_settled(&self, callback: LifecycleSettleCallback) -> bool {
        if self.status() != ConstructionStatus::Constructing {
            return false;
        }
        *self.settle.lock().unwrap() = Some(callback);
        true
    }
}

/// The container surface these scenarios use, for CompositeVm and GroupVm.
trait Container {
    fn create(hub: &MessageHub, auto_construct: bool) -> Self;
    fn id(&self) -> usize;
    fn add(&self, node: Node) -> VmxResult<()>;
    fn construct(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    fn background_errors(&self) -> LifecycleErrorStream;
}

impl Container for CompositeVm<Node> {
    fn create(hub: &MessageHub, auto_construct: bool) -> Self {
        let vm = CompositeVm::with_services("composite", hub.clone(), NullDispatcher::new());
        vm.set_auto_construct_on_add(auto_construct);
        vm
    }
    fn id(&self) -> usize {
        VmNode::id(self)
    }
    fn add(&self, node: Node) -> VmxResult<()> {
        CompositeVm::add(self, node)
    }
    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }
    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }
    fn background_errors(&self) -> LifecycleErrorStream {
        CompositeVm::background_errors(self)
    }
}

impl Container for GroupVm<Node> {
    fn create(hub: &MessageHub, auto_construct: bool) -> Self {
        let vm = GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
        vm.set_auto_construct_on_add(auto_construct);
        vm
    }
    fn id(&self) -> usize {
        VmNode::id(self)
    }
    fn add(&self, node: Node) -> VmxResult<()> {
        GroupVm::add(self, node)
    }
    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }
    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
    }
    fn background_errors(&self) -> LifecycleErrorStream {
        GroupVm::background_errors(self)
    }
}

type Log = Arc<Mutex<Vec<ConstructionStatus>>>;

fn record(hub: &MessageHub, id: usize) -> (Log, Subscription) {
    let log: Log = Arc::default();
    let sink = Arc::clone(&log);
    let subscription = hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(change) = message {
            if change.sender_id == id {
                sink.lock().unwrap().push(change.status);
            }
        }
    });
    (log, subscription)
}

/// A container with auto-construct set as given, constructing while it waits
/// on one background child.
fn constructing<C: Container>(auto_construct: bool) -> (MessageHub, C, Node, Log, Subscription) {
    let hub = MessageHub::new();
    let container = C::create(&hub, auto_construct);
    let anchor = Node::new(true);
    container.add(anchor.clone()).unwrap();
    let (log, subscription) = record(&hub, container.id());
    container.construct().unwrap();
    assert_eq!(container.status(), ConstructionStatus::Constructing);
    (hub, container, anchor, log, subscription)
}

fn foreground_late_child_is_constructed<C: Container>() {
    let (_hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let late = Node::new(false);
    container.add(late.clone()).unwrap();
    assert_eq!(late.status(), ConstructionStatus::Constructed);

    anchor.finish(ConstructionStatus::Constructed);

    assert_eq!(late.constructs(), 1);
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed
        ]
    );
}

fn background_late_child_keeps_container_constructing<C: Container>() {
    let (_hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let late = Node::new(true);
    container.add(late.clone()).unwrap();
    assert_eq!(late.status(), ConstructionStatus::Constructing);

    anchor.finish(ConstructionStatus::Constructed);
    assert_eq!(container.status(), ConstructionStatus::Constructing);

    late.finish(ConstructionStatus::Constructed);
    assert_eq!(late.constructs(), 1);
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed
        ]
    );
}

fn failing_late_child_rolls_back_once<C: Container>() {
    let (_hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let (errors_send, errors) = mpsc::channel();
    let _errors = container.background_errors().subscribe(move |error| {
        errors_send.send(error).unwrap();
    });
    let late = Node::new(true);
    container.add(late.clone()).unwrap();

    anchor.finish(ConstructionStatus::Constructed);
    late.finish(ConstructionStatus::Destructed);

    assert_eq!(late.constructs(), 1);
    assert_eq!(container.status(), ConstructionStatus::Destructed);
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Destructed
        ]
    );
    assert!(errors.try_recv().is_ok());
    assert!(errors.try_recv().is_err());
}

fn auto_construct_off_leaves_late_child_alone<C: Container>() {
    let (_hub, container, anchor, log, _subscription) = constructing::<C>(false);
    let late = Node::new(false);
    container.add(late.clone()).unwrap();

    anchor.finish(ConstructionStatus::Constructed);

    assert_eq!(late.constructs(), 0);
    assert_eq!(late.status(), ConstructionStatus::Destructed);
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed
        ]
    );
}

/// LIFE-014 — a foreground child added to a Constructing composite is
/// constructed at once and the composite then completes.
#[test]
fn composite_constructs_foreground_child_added_while_constructing() {
    foreground_late_child_is_constructed::<CompositeVm<Node>>();
}

/// LIFE-014 — a background child added to a Constructing composite holds it
/// Constructing until that child settles; the child is joined, not restarted.
#[test]
fn composite_waits_for_background_child_added_while_constructing() {
    background_late_child_keeps_container_constructing::<CompositeVm<Node>>();
}

/// LIFE-014 — a child added to a Constructing composite that fails rolls the
/// composite back once and reports the failure.
#[test]
fn composite_rolls_back_once_when_late_child_fails() {
    failing_late_child_rolls_back_once::<CompositeVm<Node>>();
}

/// LIFE-014 — without auto-construct-on-add a child added to a Constructing
/// composite is neither constructed nor awaited.
#[test]
fn composite_without_auto_construct_ignores_late_child() {
    auto_construct_off_leaves_late_child_alone::<CompositeVm<Node>>();
}

/// LIFE-014 — a foreground child added to a Constructing group is constructed
/// at once and the group then completes.
#[test]
fn group_constructs_foreground_child_added_while_constructing() {
    foreground_late_child_is_constructed::<GroupVm<Node>>();
}

/// LIFE-014 — a background child added to a Constructing group holds it
/// Constructing until that child settles; the child is joined, not restarted.
#[test]
fn group_waits_for_background_child_added_while_constructing() {
    background_late_child_keeps_container_constructing::<GroupVm<Node>>();
}

/// LIFE-014 — a child added to a Constructing group that fails rolls the
/// group back once and reports the failure.
#[test]
fn group_rolls_back_once_when_late_child_fails() {
    failing_late_child_rolls_back_once::<GroupVm<Node>>();
}

/// LIFE-014 — without auto-construct-on-add a child added to a Constructing
/// group is neither constructed nor awaited.
#[test]
fn group_without_auto_construct_ignores_late_child() {
    auto_construct_off_leaves_late_child_alone::<GroupVm<Node>>();
}
