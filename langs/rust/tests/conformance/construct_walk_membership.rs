//! The construct walk of a composite or group counts members only
//! (spec/06 §5.1, spec/07 §4, ADR-0186, #1313). The walk checks membership
//! before it starts or joins a child, and again after the child settles. A
//! child that a removal or a failed add takes out of the container does not
//! roll the container back.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use vmx::{
    CompositeVm, ConstructionStatus, GroupVm, LifecycleErrorStream, LifecycleSettleCallback,
    Message, MessageHub, NullDispatcher, ParentHandle, Subscription, ValueSubscription, VmNode,
    VmxError, VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

/// A node whose construct completes at once (foreground) or stays
/// Constructing until the test settles it (background). A failing
/// foreground node fails its construct and stays Destructed. A node with a
/// construct gate reports entry and waits for release inside `construct()`.
#[derive(Clone)]
struct Node {
    id: usize,
    background: bool,
    fails: bool,
    status: Arc<Mutex<ConstructionStatus>>,
    constructs: Arc<AtomicUsize>,
    settle: Arc<Mutex<Option<LifecycleSettleCallback>>>,
    parent: Arc<Mutex<Option<usize>>>,
    handle: Arc<Mutex<Option<ParentHandle>>>,
    gate: Arc<Mutex<Option<ConstructGate>>>,
}

/// The entry report and the release of a gated `construct()`.
type ConstructGate = (Sender<()>, Receiver<()>);

impl Node {
    fn new(background: bool, fails: bool) -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(1 << 43);
        Self {
            id: NEXT.fetch_add(1, Ordering::SeqCst),
            background,
            fails,
            status: Arc::new(Mutex::new(ConstructionStatus::Destructed)),
            constructs: Arc::default(),
            settle: Arc::default(),
            parent: Arc::default(),
            handle: Arc::default(),
            gate: Arc::default(),
        }
    }

    /// A background node; the test settles it with [`Node::finish`].
    fn background() -> Self {
        Self::new(true, false)
    }

    /// A foreground node whose construct fails and leaves it Destructed.
    fn failing() -> Self {
        Self::new(false, true)
    }

    /// Makes the next `construct()` report entry, then wait for release.
    fn gate_construct(&self) -> (Receiver<()>, Sender<()>) {
        let (entered_tx, entered) = mpsc::channel();
        let (release, release_rx) = mpsc::channel();
        *self.gate.lock().unwrap() = Some((entered_tx, release_rx));
        (entered, release)
    }

    fn constructs(&self) -> usize {
        self.constructs.load(Ordering::SeqCst)
    }

    /// Settles a background construct at `status` and notifies the waiter.
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
        let gate = self.gate.lock().unwrap().take();
        if let Some((entered, release)) = gate {
            let _ = entered.send(());
            let _ = release.recv_timeout(BOUND);
        }
        self.constructs.fetch_add(1, Ordering::SeqCst);
        if self.fails {
            *self.status.lock().unwrap() = ConstructionStatus::Destructed;
            return Err(VmxError::Other("child construct failed".to_string()));
        }
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
trait Container: Clone + Send + Sync + 'static {
    fn create(hub: &MessageHub) -> Self;
    fn id(&self) -> usize;
    fn add(&self, node: Node) -> VmxResult<()>;
    fn remove(&self, node: &Node) -> VmxResult<()>;
    fn items(&self) -> Vec<Node>;
    fn construct(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    fn background_errors(&self) -> LifecycleErrorStream;
}

impl Container for CompositeVm<Node> {
    fn create(hub: &MessageHub) -> Self {
        let vm = CompositeVm::with_services("composite", hub.clone(), NullDispatcher::new());
        vm.set_auto_construct_on_add(true);
        vm
    }
    fn id(&self) -> usize {
        VmNode::id(self)
    }
    fn add(&self, node: Node) -> VmxResult<()> {
        CompositeVm::add(self, node)
    }
    fn remove(&self, node: &Node) -> VmxResult<()> {
        CompositeVm::remove(self, node)
    }
    fn items(&self) -> Vec<Node> {
        CompositeVm::items(self)
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
    fn create(hub: &MessageHub) -> Self {
        let vm = GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
        vm.set_auto_construct_on_add(true);
        vm
    }
    fn id(&self) -> usize {
        VmNode::id(self)
    }
    fn add(&self, node: Node) -> VmxResult<()> {
        GroupVm::add(self, node)
    }
    fn remove(&self, node: &Node) -> VmxResult<()> {
        GroupVm::remove(self, node)
    }
    fn items(&self) -> Vec<Node> {
        GroupVm::items(self)
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

/// A container under test with its status log and background-error log.
struct Scenario<C> {
    container: C,
    log: Arc<Mutex<Vec<ConstructionStatus>>>,
    errors: Arc<Mutex<Vec<VmxError>>>,
    _subscriptions: (Subscription, ValueSubscription),
}

impl<C: Container> Scenario<C> {
    fn new() -> Self {
        let hub = MessageHub::new();
        let container = C::create(&hub);
        let id = container.id();
        let log: Arc<Mutex<Vec<ConstructionStatus>>> = Arc::default();
        let sink = Arc::clone(&log);
        let statuses = hub.subscribe(move |message| {
            if let Message::ConstructionStatusChanged(change) = message {
                if change.sender_id == id {
                    sink.lock().unwrap().push(change.status);
                }
            }
        });
        let errors: Arc<Mutex<Vec<VmxError>>> = Arc::default();
        let error_sink = Arc::clone(&errors);
        let failures = container
            .background_errors()
            .subscribe(move |error| error_sink.lock().unwrap().push(error));
        Self {
            container,
            log,
            errors,
            _subscriptions: (statuses, failures),
        }
    }

    fn contains(&self, node: &Node) -> bool {
        self.container.items().iter().any(|item| item.id == node.id)
    }

    /// The container reached Constructed once, with no rollback and no
    /// background error.
    fn assert_constructed(&self) {
        assert_eq!(self.container.status(), ConstructionStatus::Constructed);
        assert_eq!(
            *self.log.lock().unwrap(),
            vec![
                ConstructionStatus::Constructing,
                ConstructionStatus::Constructed
            ]
        );
        assert!(
            self.errors.lock().unwrap().is_empty(),
            "a removed child reports no background error for the container"
        );
    }
}

/// Joins `handle`, failing instead of hanging when it does not return in
/// time.
fn join_bounded<T>(handle: JoinHandle<T>, what: &str) -> T {
    let deadline = Instant::now() + BOUND;
    while !handle.is_finished() {
        assert!(Instant::now() < deadline, "{what} did not return: deadlock");
        thread::sleep(Duration::from_millis(1));
    }
    handle.join().unwrap()
}

/// Case 1: a snapshot child removed before the walk reaches it is never
/// started.
fn snapshot_child_removed_before_the_walk_reaches_it<C: Container>() {
    let scenario = Scenario::<C>::new();
    let anchor = Node::background();
    let skipped = Node::failing();
    scenario.container.add(anchor.clone()).unwrap();
    scenario.container.add(skipped.clone()).unwrap();

    assert_eq!(scenario.container.construct(), Ok(()));
    assert_eq!(
        scenario.container.status(),
        ConstructionStatus::Constructing
    );
    scenario.container.remove(&skipped).unwrap();
    anchor.finish(ConstructionStatus::Constructed);

    assert_eq!(skipped.constructs(), 0, "the walk never starts it");
    assert_eq!(skipped.status(), ConstructionStatus::Destructed);
    assert!(!scenario.contains(&skipped));
    scenario.assert_constructed();
}

/// Case 2: a snapshot child removed while the walk waits on it does not
/// change the container when it fails.
fn snapshot_child_removed_while_the_walk_waits_on_it<C: Container>() {
    let scenario = Scenario::<C>::new();
    let awaited = Node::background();
    scenario.container.add(awaited.clone()).unwrap();

    assert_eq!(scenario.container.construct(), Ok(()));
    assert_eq!(awaited.status(), ConstructionStatus::Constructing);
    scenario.container.remove(&awaited).unwrap();
    assert_eq!(
        scenario.container.status(),
        ConstructionStatus::Constructing,
        "the walk keeps waiting on a removed child"
    );
    awaited.finish(ConstructionStatus::Destructed);

    assert_eq!(awaited.constructs(), 1);
    assert_eq!(awaited.status(), ConstructionStatus::Destructed);
    assert!(!scenario.contains(&awaited));
    scenario.assert_constructed();
}

/// Case 3: a late child, started by its add while the container is
/// Constructing, removed while the walk waits on it.
fn late_child_removed_while_the_walk_waits_on_it<C: Container>() {
    let scenario = Scenario::<C>::new();
    let anchor = Node::background();
    scenario.container.add(anchor.clone()).unwrap();
    assert_eq!(scenario.container.construct(), Ok(()));
    let late = Node::background();
    scenario.container.add(late.clone()).unwrap();
    assert_eq!(late.status(), ConstructionStatus::Constructing);

    // The walk passes the anchor and joins the late child.
    anchor.finish(ConstructionStatus::Constructed);
    assert_eq!(
        scenario.container.status(),
        ConstructionStatus::Constructing
    );
    scenario.container.remove(&late).unwrap();
    late.finish(ConstructionStatus::Destructed);

    assert_eq!(late.constructs(), 1);
    assert_eq!(late.status(), ConstructionStatus::Destructed);
    assert!(!scenario.contains(&late));
    scenario.assert_constructed();
}

/// Case 4: a late child removed before the walk reaches it.
fn late_child_removed_before_the_walk_reaches_it<C: Container>() {
    let scenario = Scenario::<C>::new();
    let anchor = Node::background();
    scenario.container.add(anchor.clone()).unwrap();
    assert_eq!(scenario.container.construct(), Ok(()));
    let late = Node::background();
    scenario.container.add(late.clone()).unwrap();
    assert_eq!(late.status(), ConstructionStatus::Constructing);

    scenario.container.remove(&late).unwrap();
    late.finish(ConstructionStatus::Destructed);
    anchor.finish(ConstructionStatus::Constructed);

    assert_eq!(late.constructs(), 1);
    assert_eq!(late.status(), ConstructionStatus::Destructed);
    assert!(!scenario.contains(&late));
    scenario.assert_constructed();
}

/// A late child whose own construct fails during its add, while the walk
/// waits for that add's attempt: the add fails and is undone, and the
/// container still reaches Constructed.
fn late_child_failing_its_add_is_undone_and_container_constructs<C: Container>() {
    let scenario = Scenario::<C>::new();
    let anchor = Node::background();
    scenario.container.add(anchor.clone()).unwrap();
    assert_eq!(scenario.container.construct(), Ok(()));
    let late = Node::failing();
    let (entered, release) = late.gate_construct();
    let adder = {
        let container = scenario.container.clone();
        let late = late.clone();
        thread::spawn(move || container.add(late))
    };
    entered
        .recv_timeout(BOUND)
        .expect("the add starts the late child");
    // The walk passes the anchor and waits for the add's attempt.
    let settler = {
        let anchor = anchor.clone();
        thread::spawn(move || anchor.finish(ConstructionStatus::Constructed))
    };
    join_bounded(settler, "settling the anchor");
    assert_eq!(
        scenario.container.status(),
        ConstructionStatus::Constructing
    );
    release.send(()).unwrap();
    let added = join_bounded(adder, "the failing add");

    assert!(added.is_err(), "the add's own construct failed: {added:?}");
    assert!(!scenario.contains(&late), "the failed add is undone");
    assert_eq!(late.parent_handle().map(|_| ()), None);
    assert_eq!(late.constructs(), 1);
    assert_eq!(late.status(), ConstructionStatus::Destructed);
    scenario.assert_constructed();
}

/// COMP-047 — a snapshot child removed before the composite's walk reaches it
/// is never started, and the composite reaches Constructed.
#[test]
fn composite_walk_skips_snapshot_child_removed_before_it_reaches_it() {
    snapshot_child_removed_before_the_walk_reaches_it::<CompositeVm<Node>>();
}

/// COMP-047 — a snapshot child removed while the composite's walk waits on it
/// is ignored when it fails, and the composite reaches Constructed.
#[test]
fn composite_walk_ignores_snapshot_child_removed_while_it_waits() {
    snapshot_child_removed_while_the_walk_waits_on_it::<CompositeVm<Node>>();
}

/// COMP-047 — a late child removed while the composite's walk waits on it is
/// ignored when it fails, and the composite reaches Constructed.
#[test]
fn composite_walk_ignores_late_child_removed_while_it_waits() {
    late_child_removed_while_the_walk_waits_on_it::<CompositeVm<Node>>();
}

/// COMP-047 — a late child removed before the composite's walk reaches it is
/// skipped, and the composite reaches Constructed.
#[test]
fn composite_walk_skips_late_child_removed_before_it_reaches_it() {
    late_child_removed_before_the_walk_reaches_it::<CompositeVm<Node>>();
}

/// COMP-047 — a late child whose own add fails makes that add fail and be
/// undone, and the composite still reaches Constructed.
#[test]
fn composite_failed_late_add_is_undone_and_composite_constructs() {
    late_child_failing_its_add_is_undone_and_container_constructs::<CompositeVm<Node>>();
}

/// GRP-015 — a snapshot child removed before the group's walk reaches it is
/// never started, and the group reaches Constructed.
#[test]
fn group_walk_skips_snapshot_child_removed_before_it_reaches_it() {
    snapshot_child_removed_before_the_walk_reaches_it::<GroupVm<Node>>();
}

/// GRP-015 — a snapshot child removed while the group's walk waits on it is
/// ignored when it fails, and the group reaches Constructed.
#[test]
fn group_walk_ignores_snapshot_child_removed_while_it_waits() {
    snapshot_child_removed_while_the_walk_waits_on_it::<GroupVm<Node>>();
}

/// GRP-015 — a late child removed while the group's walk waits on it is
/// ignored when it fails, and the group reaches Constructed.
#[test]
fn group_walk_ignores_late_child_removed_while_it_waits() {
    late_child_removed_while_the_walk_waits_on_it::<GroupVm<Node>>();
}

/// GRP-015 — a late child removed before the group's walk reaches it is
/// skipped, and the group reaches Constructed.
#[test]
fn group_walk_skips_late_child_removed_before_it_reaches_it() {
    late_child_removed_before_the_walk_reaches_it::<GroupVm<Node>>();
}

/// GRP-015 — a late child whose own add fails makes that add fail and be
/// undone, and the group still reaches Constructed.
#[test]
fn group_failed_late_add_is_undone_and_group_constructs() {
    late_child_failing_its_add_is_undone_and_container_constructs::<GroupVm<Node>>();
}
