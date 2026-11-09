//! One starter for each child construct (spec/02 §6, spec/06 §5.1, ADR-0218
//! rule 6, #1370). A child added while its container is `Constructing`, before
//! the construct walk takes its snapshot, has two starters: the add and the
//! walk. When the other side starts the child between one side's status read
//! and its `construct()` call, that call fails. The add then leaves the
//! construct to the walk, and the walk joins it. Neither operation fails.

use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, ThreadId};
use std::time::Duration;
use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, GroupVm, LifecycleSettleCallback, MessageHub,
    NullDispatcher, ParentHandle, VmNode, VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

/// The entry report and the release of one thread's gated `construct()`.
type Gate = (Sender<()>, Receiver<()>);

/// A `ComponentVm` whose `construct()` can pause one armed thread before it
/// calls the wrapped VM, so a test can let the other starter go first.
#[derive(Clone)]
struct Gated {
    vm: ComponentVm<i32>,
    hooks: Arc<AtomicUsize>,
    gates: Arc<Mutex<HashMap<ThreadId, Gate>>>,
}

impl Gated {
    /// A child whose first construct hook reports entry and waits for the
    /// returned release, so its construct stays in flight meanwhile.
    fn new() -> (Self, Receiver<()>, Sender<()>) {
        let vm = ComponentVm::with_model("child", 1, MessageHub::new(), NullDispatcher::new());
        let hooks = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&hooks);
        let (entered_tx, entered) = mpsc::channel();
        let (release, release_rx) = mpsc::channel::<()>();
        vm.on_construct(move || {
            if counter.fetch_add(1, Ordering::SeqCst) == 0 {
                let _ = entered_tx.send(());
                let _ = release_rx.recv_timeout(BOUND);
            }
            Ok(())
        });
        let gated = Self {
            vm,
            hooks,
            gates: Arc::default(),
        };
        (gated, entered, release)
    }

    /// Pauses the calling thread once at its next `construct()` entry.
    /// Returns the entry report and the release.
    fn arm(&self) -> (Receiver<()>, Sender<()>) {
        let (reached, reached_rx) = mpsc::channel();
        let (release_tx, release) = mpsc::channel();
        self.gates
            .lock()
            .unwrap()
            .insert(thread::current().id(), (reached, release));
        (reached_rx, release_tx)
    }
}

impl PartialEq for Gated {
    fn eq(&self, other: &Self) -> bool {
        self.vm.id() == other.vm.id()
    }
}

impl VmNode for Gated {
    fn id(&self) -> usize {
        VmNode::id(&self.vm)
    }
    fn construct(&self) -> VmxResult<()> {
        let gate = self.gates.lock().unwrap().remove(&thread::current().id());
        if let Some((reached, release)) = gate {
            let _ = reached.send(());
            let _ = release.recv_timeout(BOUND);
        }
        VmNode::construct(&self.vm)
    }
    fn destruct(&self) -> VmxResult<()> {
        VmNode::destruct(&self.vm)
    }
    fn dispose(&self) -> VmxResult<()> {
        VmNode::dispose(&self.vm)
    }
    fn status(&self) -> ConstructionStatus {
        VmNode::status(&self.vm)
    }
    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.vm.set_parent_id(parent_id);
    }
    fn parent_id(&self) -> Option<usize> {
        VmNode::parent_id(&self.vm)
    }
    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.vm.set_parent_handle(parent);
    }
    fn parent_handle(&self) -> Option<ParentHandle> {
        self.vm.parent_handle()
    }
    fn when_lifecycle_settled(&self, callback: LifecycleSettleCallback) -> bool {
        self.vm.when_lifecycle_settled(callback)
    }
}

/// The container surface these scenarios use, for CompositeVm and GroupVm.
trait Container: Clone + Send + Sync + 'static {
    fn create() -> Self;
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static);
    fn add(&self, child: Gated) -> VmxResult<()>;
    fn construct(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    fn items(&self) -> Vec<Gated>;
}

impl Container for CompositeVm<Gated> {
    fn create() -> Self {
        let vm = CompositeVm::new("composite");
        vm.set_auto_construct_on_add(true);
        vm
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        CompositeVm::on_construct(self, hook);
    }
    fn add(&self, child: Gated) -> VmxResult<()> {
        CompositeVm::add(self, child)
    }
    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }
    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }
    fn items(&self) -> Vec<Gated> {
        CompositeVm::items(self)
    }
}

impl Container for GroupVm<Gated> {
    fn create() -> Self {
        let vm = GroupVm::new("group");
        vm.set_auto_construct_on_add(true);
        vm
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        GroupVm::on_construct(self, hook);
    }
    fn add(&self, child: Gated) -> VmxResult<()> {
        GroupVm::add(self, child)
    }
    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }
    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
    }
    fn items(&self) -> Vec<Gated> {
        GroupVm::items(self)
    }
}

fn recv(receiver: &Receiver<()>, what: &str) {
    receiver
        .recv_timeout(BOUND)
        .unwrap_or_else(|_| panic!("{what} within {BOUND:?}"));
}

/// The race setup: the container's construct hook runs on its own thread and
/// waits, and an add on another thread attaches `child` and pauses at its
/// `construct()` entry. Returns the release of the construct hook, the
/// release of the add, and the two result channels.
struct Race {
    release_hook: Sender<()>,
    release_add: Sender<()>,
    constructed: Receiver<VmxResult<()>>,
    added: Receiver<VmxResult<()>>,
    /// Arms the construct thread's pause at its next `construct()` entry.
    arm_walk: Sender<Sender<(Receiver<()>, Sender<()>)>>,
}

fn race<C: Container>(container: &C, child: &Gated) -> Race {
    let (entered_tx, entered) = mpsc::channel();
    let (release_hook, hook_release) = mpsc::channel::<()>();
    let (arm_walk, arm_requests) = mpsc::channel::<Sender<(Receiver<()>, Sender<()>)>>();
    {
        let child = child.clone();
        container.on_construct(move || {
            let _ = entered_tx.send(());
            let _ = hook_release.recv_timeout(BOUND);
            // The walk starts on this thread right after the hook returns.
            if let Ok(reply) = arm_requests.try_recv() {
                let _ = reply.send(child.arm());
            }
            Ok(())
        });
    }
    let (constructed_tx, constructed) = mpsc::channel();
    {
        let container = container.clone();
        thread::spawn(move || {
            let _ = constructed_tx.send(container.construct());
        });
    }
    recv(&entered, "the construct hook runs");
    assert_eq!(container.status(), ConstructionStatus::Constructing);

    let (handoff_tx, handoff) = mpsc::channel();
    let (added_tx, added) = mpsc::channel();
    {
        let container = container.clone();
        let child = child.clone();
        thread::spawn(move || {
            let _ = handoff_tx.send(child.arm());
            let _ = added_tx.send(container.add(child));
        });
    }
    let (reached, release_add) = handoff.recv_timeout(BOUND).unwrap();
    recv(&reached, "the add pauses at the child's construct");
    assert_eq!(child.status(), ConstructionStatus::Destructed);
    Race {
        release_hook,
        release_add,
        constructed,
        added,
        arm_walk,
    }
}

fn ends_with_one_constructed_member<C: Container>(container: &C, child: &Gated) {
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    assert_eq!(child.status(), ConstructionStatus::Constructed);
    let ids: Vec<usize> = container.items().iter().map(VmNode::id).collect();
    assert_eq!(ids, vec![child.id()]);
    assert!(child.parent_handle().is_some());
    assert_eq!(
        child.hooks.load(Ordering::SeqCst),
        1,
        "the child constructs once"
    );
}

/// Waits until `container` reaches `Constructed`.
fn settles_constructed<C: Container>(container: &C) {
    let deadline = std::time::Instant::now() + BOUND;
    while container.status() != ConstructionStatus::Constructed {
        assert!(
            std::time::Instant::now() < deadline,
            "the container settles Constructed within {BOUND:?}, got {:?}",
            container.status()
        );
        thread::sleep(Duration::from_millis(1));
    }
}

/// The walk starts the child while the add is between its status read and
/// its start call. The add finds the walk's construct in flight, leaves it to
/// the walk and does not wait for it.
fn add_loses_the_start<C: Container>() {
    let container = C::create();
    let (child, hook_entered, release_hook) = Gated::new();
    let race = race(&container, &child);

    let _ = race.release_hook.send(());
    recv(
        &hook_entered,
        "the walk's construct of the child is in flight",
    );
    let _ = race.release_add.send(());
    let added = race.added.recv_timeout(BOUND).expect("the add returns");
    assert_eq!(
        child.status(),
        ConstructionStatus::Constructing,
        "the add returned without waiting for the walk's construct"
    );
    let _ = release_hook.send(());
    let constructed = race
        .constructed
        .recv_timeout(BOUND)
        .expect("the container construct returns");

    assert_eq!(added, Ok(()), "the add does not fail on the walk's start");
    assert_eq!(constructed, Ok(()));
    settles_constructed(&container);
    ends_with_one_constructed_member(&container, &child);
}

/// The add starts the child while the walk is between its status read and
/// its start call. The walk finds the add's construct in flight and joins it.
fn walk_loses_the_start<C: Container>() {
    let container = C::create();
    let (child, hook_entered, release_hook) = Gated::new();
    let race = race(&container, &child);

    let (reply_tx, reply) = mpsc::channel();
    race.arm_walk.send(reply_tx).unwrap();
    let _ = race.release_hook.send(());
    let (walk_reached, release_walk) = reply.recv_timeout(BOUND).unwrap();
    recv(&walk_reached, "the walk pauses at the child's construct");
    let _ = race.release_add.send(());
    recv(
        &hook_entered,
        "the add's construct of the child is in flight",
    );
    let _ = release_walk.send(());
    let constructed = race
        .constructed
        .recv_timeout(BOUND)
        .expect("the container construct returns");
    let _ = release_hook.send(());
    let added = race.added.recv_timeout(BOUND).expect("the add returns");

    assert_eq!(
        constructed,
        Ok(()),
        "the container construct does not fail on the add's start"
    );
    assert_eq!(added, Ok(()));
    settles_constructed(&container);
    ends_with_one_constructed_member(&container, &child);
}

/// A composite add that loses the start to the construct walk succeeds.
#[test]
fn composite_add_leaves_a_construct_the_walk_started() {
    add_loses_the_start::<CompositeVm<Gated>>();
}

/// A group add that loses the start to the construct walk succeeds.
#[test]
fn group_add_leaves_a_construct_the_walk_started() {
    add_loses_the_start::<GroupVm<Gated>>();
}

/// A composite construct walk that loses the start to an add joins it.
#[test]
fn composite_walk_joins_a_construct_the_add_started() {
    walk_loses_the_start::<CompositeVm<Gated>>();
}

/// A group construct walk that loses the start to an add joins it.
#[test]
fn group_walk_joins_a_construct_the_add_started() {
    walk_loses_the_start::<GroupVm<Gated>>();
}
