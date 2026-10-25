//! Auto-construct-on-add while a container is Constructing (spec/02 §6): the
//! construct walk joins a child added during it, and the container completes
//! only when that child is Constructed.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::RecvTimeoutError;
use std::sync::{mpsc, Arc, Mutex};
use std::thread::ThreadId;
use std::time::Duration;
use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, GroupVm, LifecycleErrorStream,
    LifecycleSettleCallback, ManualDispatcher, Message, MessageHub, NullDispatcher, ParentHandle,
    Subscription, VmNode, VmxResult,
};

/// Runs `body` on a worker and fails if it does not finish in time, so a
/// deadlock regression fails the test instead of hanging the suite. A worker
/// panic is reported as a panic, with its message, not as a deadlock.
fn within_timeout<R: Send + 'static>(what: &str, body: impl FnOnce() -> R + Send + 'static) -> R {
    let (tx, rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let _ = tx.send(body());
    });
    match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(value) => value,
        Err(RecvTimeoutError::Timeout) => panic!("{what} deadlocked"),
        Err(RecvTimeoutError::Disconnected) => {
            let message = match worker.join() {
                Ok(()) => "worker exited without a result".to_string(),
                Err(payload) => payload
                    .downcast_ref::<&str>()
                    .map(|text| (*text).to_string())
                    .or_else(|| payload.downcast_ref::<String>().cloned())
                    .unwrap_or_else(|| "non-string panic payload".to_string()),
            };
            panic!("{what} worker panicked: {message}")
        }
    }
}

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
    fails: bool,
    pause: Arc<Mutex<Option<Pause>>>,
}

/// Where an add pauses a node it attached, before the node is started.
#[derive(Clone, Copy, PartialEq)]
enum PauseAt {
    /// The add reads the attached node's status to decide whether to start it.
    Status,
    /// The add calls `construct()`, before the node leaves Destructed.
    Construct,
    /// Inside `construct()`, while the node is Constructing (in flight).
    InFlight,
    /// The add reads the attached node's id inside its membership gate.
    Id,
}

/// A one-shot pause of one thread: it reports `reached`, then waits for
/// `release`. Every wait is bounded, so a regression fails instead of hanging.
struct Pause {
    at: PauseAt,
    thread: ThreadId,
    reached: mpsc::Sender<()>,
    release: mpsc::Receiver<()>,
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
            fails: false,
            pause: Arc::default(),
        }
    }

    /// A foreground node whose construct fails and leaves it Destructed.
    fn failing() -> Self {
        Self {
            fails: true,
            ..Self::new(false)
        }
    }

    /// Pauses the calling thread once at `at` while the node is attached.
    fn pause_this_thread_at(&self, at: PauseAt) -> (mpsc::Receiver<()>, mpsc::Sender<()>) {
        let (reached, reached_rx) = mpsc::channel();
        let (release_tx, release) = mpsc::channel();
        *self.pause.lock().unwrap() = Some(Pause {
            at,
            thread: std::thread::current().id(),
            reached,
            release,
        });
        (reached_rx, release_tx)
    }

    fn pauses_this_thread_at(&self, at: PauseAt) -> bool {
        self.pause
            .lock()
            .unwrap()
            .as_ref()
            .is_some_and(|pause| pause.at == at && pause.thread == std::thread::current().id())
    }

    fn maybe_pause(&self, at: PauseAt) {
        if self.handle.lock().unwrap().is_none() {
            return;
        }
        let pause = {
            let mut slot = self.pause.lock().unwrap();
            match slot.as_ref() {
                Some(pause) if pause.at == at && pause.thread == std::thread::current().id() => {
                    slot.take()
                }
                _ => None,
            }
        };
        if let Some(pause) = pause {
            let _ = pause.reached.send(());
            let _ = pause.release.recv_timeout(Duration::from_secs(5));
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
        self.maybe_pause(PauseAt::Id);
        self.id
    }
    fn construct(&self) -> VmxResult<()> {
        self.maybe_pause(PauseAt::Construct);
        *self.constructs.lock().unwrap() += 1;
        if self.fails {
            *self.status.lock().unwrap() = ConstructionStatus::Destructed;
            return Err(vmx::VmxError::Other("late child failed".to_string()));
        }
        if self.pauses_this_thread_at(PauseAt::InFlight) {
            *self.status.lock().unwrap() = ConstructionStatus::Constructing;
            self.maybe_pause(PauseAt::InFlight);
            self.finish(ConstructionStatus::Constructed);
            return Ok(());
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
        self.maybe_pause(PauseAt::Status);
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
    fn set_auto_construct_on_add(&self, enabled: bool);
    fn len(&self) -> usize;
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
    fn set_auto_construct_on_add(&self, enabled: bool) {
        CompositeVm::set_auto_construct_on_add(self, enabled);
    }
    fn len(&self) -> usize {
        CompositeVm::len(self)
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
    fn set_auto_construct_on_add(&self, enabled: bool) {
        GroupVm::set_auto_construct_on_add(self, enabled);
    }
    fn len(&self) -> usize {
        GroupVm::len(self)
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

type Leaf = ComponentVm<i32, ManualDispatcher>;

/// Statuses `id` published on `hub`, in order.
fn statuses(
    log: &Arc<Mutex<Vec<(usize, ConstructionStatus)>>>,
    id: usize,
) -> Vec<ConstructionStatus> {
    log.lock()
        .unwrap()
        .iter()
        .filter(|(sender, _)| *sender == id)
        .map(|(_, status)| *status)
        .collect()
}

/// Adds a real background `ComponentVm` from the container's construct hook,
/// i.e. while it is Constructing but before its walk takes the snapshot, and
/// checks the walk joins that already-started child instead of restarting it.
macro_rules! child_added_by_construct_hook_is_joined {
    ($container:ident) => {{
        let hub = MessageHub::new();
        let dispatcher = ManualDispatcher::new();
        let container: $container<Leaf, ManualDispatcher> =
            $container::with_services("container", hub.clone(), dispatcher.clone());
        container.set_auto_construct_on_add(true);
        let child: Leaf = ComponentVm::builder()
            .name("child")
            .model(1)
            .background(true)
            .services(hub.clone(), dispatcher.clone())
            .build()
            .unwrap();
        let target = container.clone();
        let added = child.clone();
        container.on_construct(move || target.add(added.clone()));
        let log: Arc<Mutex<Vec<(usize, ConstructionStatus)>>> = Arc::default();
        let sink = Arc::clone(&log);
        let _subscription = hub.subscribe(move |message| {
            if let Message::ConstructionStatusChanged(change) = message {
                sink.lock().unwrap().push((change.sender_id, change.status));
            }
        });

        assert_eq!(container.construct(), Ok(()));
        assert_eq!(container.status(), ConstructionStatus::Constructing);
        assert_eq!(child.status(), ConstructionStatus::Constructing);
        dispatcher.drain();

        assert_eq!(child.status(), ConstructionStatus::Constructed);
        assert_eq!(container.status(), ConstructionStatus::Constructed);
        assert_eq!(
            statuses(&log, child.id()),
            vec![
                ConstructionStatus::Constructing,
                ConstructionStatus::Constructed
            ]
        );
        assert_eq!(
            statuses(&log, container.id()),
            vec![
                ConstructionStatus::Constructing,
                ConstructionStatus::Constructed
            ]
        );
        container.on_construct(|| Ok(()));
    }};
}

/// LIFE-014 — a background child that a composite's construct hook adds with
/// auto-construct-on-add is joined by the walk, not constructed a second time.
#[test]
fn composite_joins_child_added_by_its_construct_hook() {
    child_added_by_construct_hook_is_joined!(CompositeVm);
}

/// LIFE-014 — a background child that a group's construct hook adds with
/// auto-construct-on-add is joined by the walk, not constructed a second time.
#[test]
fn group_joins_child_added_by_its_construct_hook() {
    child_added_by_construct_hook_is_joined!(GroupVm);
}

/// Calls `reconstruct()` on a Constructed container whose construct hook adds
/// a real background `ComponentVm`, and checks the reconstruct walk joins that
/// already-started child: its construct hook runs once, while the container
/// is still Constructing in that walk, and the container then completes.
macro_rules! reconstruct_joins_child_added_by_construct_hook {
    ($container:ident) => {{
        let hub = MessageHub::new();
        let dispatcher = ManualDispatcher::new();
        let container: $container<Leaf, ManualDispatcher> =
            $container::with_services("container", hub.clone(), dispatcher.clone());
        container.set_auto_construct_on_add(true);
        container.construct().unwrap();
        assert_eq!(container.status(), ConstructionStatus::Constructed);

        let hook_seen: Arc<Mutex<Vec<ConstructionStatus>>> = Arc::default();
        let seen = Arc::clone(&hook_seen);
        let observed = container.clone();
        let child: Leaf = ComponentVm::builder()
            .name("child")
            .model(1)
            .background(true)
            .on_construct(move || {
                seen.lock().unwrap().push(observed.status());
                Ok(())
            })
            .services(hub.clone(), dispatcher.clone())
            .build()
            .unwrap();
        let target = container.clone();
        let added = child.clone();
        container.on_construct(move || target.add(added.clone()));
        let log: Arc<Mutex<Vec<(usize, ConstructionStatus)>>> = Arc::default();
        let sink = Arc::clone(&log);
        let _subscription = hub.subscribe(move |message| {
            if let Message::ConstructionStatusChanged(change) = message {
                sink.lock().unwrap().push((change.sender_id, change.status));
            }
        });

        let result = within_timeout("reconstruct", {
            let container = container.clone();
            move || container.reconstruct()
        });
        assert_eq!(result, Ok(()));
        assert_eq!(container.status(), ConstructionStatus::Constructing);
        assert_eq!(child.status(), ConstructionStatus::Constructing);
        assert!(hook_seen.lock().unwrap().is_empty());
        within_timeout("drain", {
            let dispatcher = dispatcher.clone();
            move || dispatcher.drain()
        });

        assert_eq!(
            *hook_seen.lock().unwrap(),
            vec![ConstructionStatus::Constructing]
        );
        assert_eq!(child.status(), ConstructionStatus::Constructed);
        assert_eq!(container.status(), ConstructionStatus::Constructed);
        assert_eq!(
            statuses(&log, child.id()),
            vec![
                ConstructionStatus::Constructing,
                ConstructionStatus::Constructed
            ]
        );
        assert_eq!(
            statuses(&log, container.id()),
            vec![
                ConstructionStatus::Destructing,
                ConstructionStatus::Destructed,
                ConstructionStatus::Constructing,
                ConstructionStatus::Constructed
            ]
        );
        container.on_construct(|| Ok(()));
        child.on_construct(|| Ok(()));
    }};
}

/// A composite's reconstruct walk joins the background child its construct
/// hook adds and does not construct it a second time.
#[test]
fn composite_reconstruct_joins_child_added_by_its_construct_hook() {
    reconstruct_joins_child_added_by_construct_hook!(CompositeVm);
}

/// A group's reconstruct walk joins the background child its construct hook
/// adds and does not construct it a second time.
#[test]
fn group_reconstruct_joins_child_added_by_its_construct_hook() {
    reconstruct_joins_child_added_by_construct_hook!(GroupVm);
}

type Foreground = ComponentVm<i32>;

/// Where a child is added from during the synchronous construct walk.
#[derive(Clone, Copy)]
enum AddFrom {
    /// The construct hook of a member the walk constructs.
    ChildHook,
    /// A hub subscriber that sees that member's Constructed status.
    HubSubscriber,
}

/// Adds a child to a container from inside its synchronous construct walk,
/// with auto-construct-on-add, and checks `construct()` returns, the added
/// child is constructed exactly once, and the container completes.
macro_rules! child_added_during_the_walk_is_constructed_once {
    ($container:ident, $from:expr) => {{
        let hub = MessageHub::new();
        let container: $container<Foreground> =
            $container::with_services("container", hub.clone(), NullDispatcher::new());
        container.set_auto_construct_on_add(true);
        let first = Foreground::with_model("first", 1, hub.clone(), NullDispatcher::new());
        container.add(first.clone()).unwrap();
        let late = Foreground::with_model("late", 2, hub.clone(), NullDispatcher::new());
        let constructs = Arc::new(AtomicUsize::new(0));
        let count = Arc::clone(&constructs);
        late.on_construct(move || {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        });
        // The container status and add result each time the child is added.
        let adds: Arc<Mutex<Vec<(ConstructionStatus, bool)>>> = Arc::default();
        let record_add = Arc::clone(&adds);
        let target = container.clone();
        let added = late.clone();
        let add = move || {
            let status = target.status();
            let result = target.add(added.clone());
            record_add.lock().unwrap().push((status, result.is_ok()));
        };
        let _subscription = match $from {
            AddFrom::ChildHook => {
                first.on_construct(move || {
                    add();
                    Ok(())
                });
                None
            }
            AddFrom::HubSubscriber => {
                let first_id = first.id();
                Some(hub.subscribe(move |message| {
                    if let Message::ConstructionStatusChanged(change) = message {
                        if change.sender_id == first_id
                            && change.status == ConstructionStatus::Constructed
                        {
                            add();
                        }
                    }
                }))
            }
        };

        let result = within_timeout("construct with an add during the walk", {
            let container = container.clone();
            move || container.construct()
        });

        assert_eq!(result, Ok(()));
        assert_eq!(
            *adds.lock().unwrap(),
            vec![(ConstructionStatus::Constructing, true)]
        );
        assert_eq!(container.len(), 2);
        assert_eq!(constructs.load(Ordering::SeqCst), 1);
        assert_eq!(late.status(), ConstructionStatus::Constructed);
        assert_eq!(container.status(), ConstructionStatus::Constructed);
        first.on_construct(|| Ok(()));
    }};
}

/// A child that a composite member's construct hook adds during the
/// composite's construct walk is constructed once and the walk returns.
#[test]
fn composite_constructs_once_a_child_added_by_a_child_construct_hook() {
    child_added_during_the_walk_is_constructed_once!(CompositeVm, AddFrom::ChildHook);
}

/// A child that a hub subscriber adds during the composite's construct walk
/// is constructed once and the walk returns.
#[test]
fn composite_constructs_once_a_child_added_by_a_hub_subscriber() {
    child_added_during_the_walk_is_constructed_once!(CompositeVm, AddFrom::HubSubscriber);
}

/// A child that a group member's construct hook adds during the group's
/// construct walk is constructed once and the walk returns.
#[test]
fn group_constructs_once_a_child_added_by_a_child_construct_hook() {
    child_added_during_the_walk_is_constructed_once!(GroupVm, AddFrom::ChildHook);
}

/// A child that a hub subscriber adds during the group's construct walk is
/// constructed once and the walk returns.
#[test]
fn group_constructs_once_a_child_added_by_a_hub_subscriber() {
    child_added_during_the_walk_is_constructed_once!(GroupVm, AddFrom::HubSubscriber);
}

/// Adds a background child from a hub subscriber that sees the container's
/// own Constructed status, i.e. once the walk has ended, and checks the child
/// is constructed but not awaited: the container registers no settle callback
/// on it and publishes no further status while the child is Constructing.
fn background_child_added_after_the_walk_is_not_awaited<C>()
where
    C: Container + Clone + Send + Sync + 'static,
{
    let (hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let late = Node::new(true);
    let adds: Arc<Mutex<Vec<(ConstructionStatus, bool)>>> = Arc::default();
    let record_add = Arc::clone(&adds);
    let target = container.clone();
    let added = late.clone();
    let container_id = container.id();
    let _late_add = hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(change) = message {
            if change.sender_id == container_id && change.status == ConstructionStatus::Constructed
            {
                let status = target.status();
                let result = target.add(added.clone());
                record_add.lock().unwrap().push((status, result.is_ok()));
            }
        }
    });

    within_timeout("settle with an add after the walk", {
        let anchor = anchor.clone();
        move || anchor.finish(ConstructionStatus::Constructed)
    });

    assert_eq!(
        *adds.lock().unwrap(),
        vec![(ConstructionStatus::Constructed, true)]
    );
    assert_eq!(late.constructs(), 1);
    assert_eq!(late.status(), ConstructionStatus::Constructing);
    assert!(late.settle.lock().unwrap().is_none());
    assert_eq!(container.status(), ConstructionStatus::Constructed);

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

/// A background child added to a composite once its construct walk has
/// ended is constructed, and the composite does not wait for it.
#[test]
fn composite_does_not_wait_for_background_child_added_after_the_walk() {
    background_child_added_after_the_walk_is_not_awaited::<CompositeVm<Node>>();
}

/// A background child added to a group once its construct walk has ended is
/// constructed, and the group does not wait for it.
#[test]
fn group_does_not_wait_for_background_child_added_after_the_walk() {
    background_child_added_after_the_walk_is_not_awaited::<GroupVm<Node>>();
}

/// The late node's status and construct count each time the container
/// publishes Constructed.
type AtConstructed = Arc<Mutex<Vec<(ConstructionStatus, usize)>>>;

fn watch_constructed(
    hub: &MessageHub,
    container_id: usize,
    late: &Node,
) -> (AtConstructed, Subscription) {
    let seen: AtConstructed = Arc::default();
    let sink = Arc::clone(&seen);
    let late = late.clone();
    let subscription = hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(change) = message {
            if change.sender_id == container_id && change.status == ConstructionStatus::Constructed
            {
                sink.lock()
                    .unwrap()
                    .push((*late.status.lock().unwrap(), late.constructs()));
            }
        }
    });
    (seen, subscription)
}

/// Adds `late` from another thread that pauses at `at`, after the add
/// attached the node (Destructed, or Constructing at `InFlight`), and settles the
/// original child while the add is paused, so the construct walk pulls `late`
/// in that gap. Returns the add's result. Every wait is bounded.
fn add_paused_while_walk_pulls<C>(
    container: &C,
    anchor: &Node,
    late: &Node,
    at: PauseAt,
    while_paused: impl FnOnce(),
) -> VmxResult<()>
where
    C: Container + Clone + Send + Sync + 'static,
{
    let (handoff_tx, handoff) = mpsc::channel();
    let (result_tx, result) = mpsc::channel();
    let adder = {
        let container = container.clone();
        let late = late.clone();
        std::thread::spawn(move || {
            let _ = handoff_tx.send(late.pause_this_thread_at(at));
            let _ = result_tx.send(container.add(late));
        })
    };
    let (reached, release) = handoff
        .recv_timeout(Duration::from_secs(5))
        .expect("the adder thread arms its pause");
    reached
        .recv_timeout(Duration::from_secs(5))
        .expect("the add pauses after it attached the node");
    assert_eq!(container.status(), ConstructionStatus::Constructing);
    let expected = if at == PauseAt::InFlight {
        ConstructionStatus::Constructing
    } else {
        ConstructionStatus::Destructed
    };
    assert_eq!(*late.status.lock().unwrap(), expected);

    within_timeout("settle the original child", {
        let anchor = anchor.clone();
        move || anchor.finish(ConstructionStatus::Constructed)
    });
    while_paused();
    let _ = release.send(());
    let added = result
        .recv_timeout(Duration::from_secs(5))
        .expect("the paused add completes");
    adder.join().unwrap();
    added
}

fn constructed_after_late(log: &Log, at_constructed: &AtConstructed) {
    assert_eq!(
        *at_constructed.lock().unwrap(),
        vec![(ConstructionStatus::Constructed, 1)],
        "the container publishes Constructed only after the late child"
    );
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed
        ]
    );
}

fn walk_waits_for_add_to_start_late_child<C>()
where
    C: Container + Clone + Send + Sync + 'static,
{
    let (hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let late = Node::new(false);
    let (at_constructed, _watch) = watch_constructed(&hub, container.id(), &late);
    let observer = container.clone();
    let while_paused = Arc::new(Mutex::new(None));
    let seen = Arc::clone(&while_paused);

    // The add pauses after it attached the Destructed child, before it
    // starts it; the walk pulls the child first.
    let added =
        add_paused_while_walk_pulls(&container, &anchor, &late, PauseAt::Status, move || {
            *seen.lock().unwrap() = Some(observer.status());
        });

    assert_eq!(
        *while_paused.lock().unwrap(),
        Some(ConstructionStatus::Constructing),
        "the walk waits for the add instead of failing on the unstarted child"
    );
    assert_eq!(added, Ok(()));
    assert_eq!(late.constructs(), 1);
    assert_eq!(late.status(), ConstructionStatus::Constructed);
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    constructed_after_late(&log, &at_constructed);
}

fn walk_joins_late_child_its_add_is_constructing<C>()
where
    C: Container + Clone + Send + Sync + 'static,
{
    let (hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let late = Node::new(false);
    let (at_constructed, _watch) = watch_constructed(&hub, container.id(), &late);
    let observer = container.clone();
    let while_paused = Arc::new(Mutex::new(None));
    let seen = Arc::clone(&while_paused);

    // The add starts the child first and pauses inside its construct, with
    // the child Constructing, while the walk pulls it.
    let added =
        add_paused_while_walk_pulls(&container, &anchor, &late, PauseAt::InFlight, move || {
            *seen.lock().unwrap() = Some(observer.status());
        });

    assert_eq!(
        *while_paused.lock().unwrap(),
        Some(ConstructionStatus::Constructing)
    );
    assert_eq!(added, Ok(()));
    assert_eq!(late.constructs(), 1);
    assert_eq!(late.status(), ConstructionStatus::Constructed);
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    constructed_after_late(&log, &at_constructed);
}

fn late_child_failing_its_add_construct_fails_add_and_rolls_back<C>()
where
    C: Container + Clone + Send + Sync + 'static,
{
    let (_hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let late = Node::failing();

    let added = add_paused_while_walk_pulls(&container, &anchor, &late, PauseAt::Status, || {});

    assert!(added.is_err(), "the add's own construct failed: {added:?}");
    assert_eq!(container.len(), 1, "the failed add is undone");
    assert_eq!(late.parent_handle().map(|_| ()), None);
    assert_eq!(late.constructs(), 1);
    assert_eq!(late.status(), ConstructionStatus::Destructed);
    assert_eq!(container.status(), ConstructionStatus::Destructed);
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Destructed
        ]
    );
}

fn walk_waits_for_late_child_its_add_is_still_attaching<C>()
where
    C: Container + Clone + Send + Sync + 'static,
{
    let (hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let late = Node::new(false);
    let (at_constructed, _watch) = watch_constructed(&hub, container.id(), &late);
    let (handoff_tx, handoff) = mpsc::channel();
    let (result_tx, result) = mpsc::channel();
    let adder = {
        let container = container.clone();
        let late = late.clone();
        std::thread::spawn(move || {
            let _ = handoff_tx.send(late.pause_this_thread_at(PauseAt::Id));
            let _ = result_tx.send(container.add(late));
        })
    };
    let (reached, release) = handoff
        .recv_timeout(Duration::from_secs(5))
        .expect("the adder thread arms its pause");
    // The add pauses inside its membership gate, with the child already a
    // member and the Destructed child not started.
    reached
        .recv_timeout(Duration::from_secs(5))
        .expect("the add pauses inside its gated attach");
    assert_eq!(container.status(), ConstructionStatus::Constructing);
    assert_eq!(*late.status.lock().unwrap(), ConstructionStatus::Destructed);

    let (settled_tx, settled) = mpsc::channel();
    let settler = {
        let anchor = anchor.clone();
        std::thread::spawn(move || {
            anchor.finish(ConstructionStatus::Constructed);
            let _ = settled_tx.send(());
        })
    };
    // A walk that scans members outside the gate finishes while the add is
    // paused. A walk that scans under the gate waits for the add, so only
    // this bound releases the add; the outcome does not depend on it.
    let settled_while_paused = settled.recv_timeout(Duration::from_secs(1)).is_ok();
    let _ = release.send(());
    let added = result
        .recv_timeout(Duration::from_secs(5))
        .expect("the paused add completes");
    adder.join().unwrap();
    if !settled_while_paused {
        settled
            .recv_timeout(Duration::from_secs(5))
            .expect("the walk completes once the add released the gate");
    }
    settler.join().unwrap();

    assert_eq!(added, Ok(()));
    assert_eq!(late.constructs(), 1);
    assert_eq!(late.status(), ConstructionStatus::Constructed);
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    constructed_after_late(&log, &at_constructed);
}

fn auto_construct_turned_on_during_walk_skips_unstarted_child<C: Container>() {
    let (_hub, container, anchor, log, _subscription) = constructing::<C>(false);
    let late = Node::new(false);
    container.add(late.clone()).unwrap();
    container.set_auto_construct_on_add(true);

    within_timeout("settle the original child", {
        let anchor = anchor.clone();
        move || anchor.finish(ConstructionStatus::Constructed)
    });

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

fn failed_late_child_rolls_back_after_auto_construct_turned_off<C: Container>() {
    let (_hub, container, anchor, log, _subscription) = constructing::<C>(true);
    let late = Node::new(true);
    container.add(late.clone()).unwrap();
    assert_eq!(late.status(), ConstructionStatus::Constructing);
    late.finish(ConstructionStatus::Destructed);
    container.set_auto_construct_on_add(false);

    within_timeout("settle the original child", {
        let anchor = anchor.clone();
        move || anchor.finish(ConstructionStatus::Constructed)
    });

    assert_eq!(late.constructs(), 1);
    assert_eq!(container.status(), ConstructionStatus::Destructed);
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Destructed
        ]
    );
}

fn auto_construct_turned_off_during_walk_ignores_later_child<C: Container>() {
    let (_hub, container, anchor, log, _subscription) = constructing::<C>(true);
    container.set_auto_construct_on_add(false);
    let late = Node::new(false);
    container.add(late.clone()).unwrap();
    assert_eq!(late.status(), ConstructionStatus::Destructed);

    within_timeout("settle the original child", {
        let anchor = anchor.clone();
        move || anchor.finish(ConstructionStatus::Constructed)
    });

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

/// A composite's construct walk that pulls a child whose cross-thread add
/// attached it but has not started it waits for that add, then joins the
/// child.
#[test]
fn composite_walk_waits_for_add_to_start_late_child() {
    walk_waits_for_add_to_start_late_child::<CompositeVm<Node>>();
}

/// A group's construct walk that pulls a child whose cross-thread add
/// attached it but has not started it waits for that add, then joins the
/// child.
#[test]
fn group_walk_waits_for_add_to_start_late_child() {
    walk_waits_for_add_to_start_late_child::<GroupVm<Node>>();
}

/// A composite's construct walk that pulls a child its add is still
/// constructing joins that child.
#[test]
fn composite_walk_joins_late_child_its_add_is_constructing() {
    walk_joins_late_child_its_add_is_constructing::<CompositeVm<Node>>();
}

/// A group's construct walk that pulls a child its add is still constructing
/// joins that child.
#[test]
fn group_walk_joins_late_child_its_add_is_constructing() {
    walk_joins_late_child_its_add_is_constructing::<GroupVm<Node>>();
}

/// A late child whose add-started construct fails while a composite's walk
/// waits on it fails the add, which is undone, and rolls the composite back.
#[test]
fn composite_late_child_failing_its_add_construct_fails_add_and_rolls_back() {
    late_child_failing_its_add_construct_fails_add_and_rolls_back::<CompositeVm<Node>>();
}

/// A late child whose add-started construct fails while a group's walk waits
/// on it fails the add, which is undone, and rolls the group back.
#[test]
fn group_late_child_failing_its_add_construct_fails_add_and_rolls_back() {
    late_child_failing_its_add_construct_fails_add_and_rolls_back::<GroupVm<Node>>();
}

/// A child added while auto-construct-on-add was off is not awaited by a
/// composite's walk after the flag turns on mid-walk.
#[test]
fn composite_skips_unstarted_child_after_auto_construct_turned_on_during_walk() {
    auto_construct_turned_on_during_walk_skips_unstarted_child::<CompositeVm<Node>>();
}

/// A child added while auto-construct-on-add was off is not awaited by a
/// group's walk after the flag turns on mid-walk.
#[test]
fn group_skips_unstarted_child_after_auto_construct_turned_on_during_walk() {
    auto_construct_turned_on_during_walk_skips_unstarted_child::<GroupVm<Node>>();
}

/// A late child whose add-started construct failed still rolls a composite
/// back after auto-construct-on-add is turned off.
#[test]
fn composite_failed_late_child_rolls_back_after_auto_construct_turned_off() {
    failed_late_child_rolls_back_after_auto_construct_turned_off::<CompositeVm<Node>>();
}

/// A late child whose add-started construct failed still rolls a group back
/// after auto-construct-on-add is turned off.
#[test]
fn group_failed_late_child_rolls_back_after_auto_construct_turned_off() {
    failed_late_child_rolls_back_after_auto_construct_turned_off::<GroupVm<Node>>();
}

/// After `set_auto_construct_on_add(false)` during a composite's construct
/// walk, a child added later is neither constructed nor awaited, and the
/// composite completes.
#[test]
fn composite_ignores_child_added_after_auto_construct_turned_off_during_walk() {
    auto_construct_turned_off_during_walk_ignores_later_child::<CompositeVm<Node>>();
}

/// After `set_auto_construct_on_add(false)` during a group's construct walk,
/// a child added later is neither constructed nor awaited, and the group
/// completes.
#[test]
fn group_ignores_child_added_after_auto_construct_turned_off_during_walk() {
    auto_construct_turned_off_during_walk_ignores_later_child::<GroupVm<Node>>();
}

/// A composite's construct walk does not complete past a child whose
/// cross-thread add is still inside its gated attach.
#[test]
fn composite_walk_waits_for_late_child_its_add_is_still_attaching() {
    walk_waits_for_late_child_its_add_is_still_attaching::<CompositeVm<Node>>();
}

/// A group's construct walk does not complete past a child whose
/// cross-thread add is still inside its gated attach.
#[test]
fn group_walk_waits_for_late_child_its_add_is_still_attaching() {
    walk_waits_for_late_child_its_add_is_still_attaching::<GroupVm<Node>>();
}
