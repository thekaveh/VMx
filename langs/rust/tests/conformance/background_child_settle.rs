//! Containers stay transient until background children settle (spec/02 §6).

use std::sync::{mpsc, Arc, Mutex};
use vmx::{
    AggregateVm1, AggregateVm3, ComponentVm, CompositeVm, ConstructionStatus, GroupVm,
    LifecycleSettleCallback, ManualDispatcher, Message, MessageHub, ParentHandle, Subscription,
    VmNode, VmxError, VmxResult,
};

type Child = ComponentVm<i32, ManualDispatcher>;
type Log = Arc<Mutex<Vec<(usize, ConstructionStatus)>>>;

fn background_child(hub: &MessageHub, dispatcher: &ManualDispatcher, name: &str) -> Child {
    ComponentVm::builder()
        .name(name)
        .model(1)
        .background(true)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap()
}

fn failing_child(hub: &MessageHub, dispatcher: &ManualDispatcher, name: &str) -> Child {
    ComponentVm::builder()
        .name(name)
        .model(1)
        .background(true)
        .on_construct(|| Err(VmxError::Other("child construct failed".to_string())))
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap()
}

fn record(hub: &MessageHub) -> (Log, Subscription) {
    let log: Log = Arc::default();
    let sink = Arc::clone(&log);
    let subscription = hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(change) = message {
            sink.lock().unwrap().push((change.sender_id, change.status));
        }
    });
    (log, subscription)
}

fn position(log: &Log, id: usize, status: ConstructionStatus) -> usize {
    log.lock()
        .unwrap()
        .iter()
        .position(|entry| *entry == (id, status))
        .unwrap_or_else(|| panic!("{id} never published {status:?}"))
}

/// LIFE-014 — a composite with background children completes construct and
/// destruct only after every child settles, and publishes its terminal
/// status after theirs.
#[test]
fn composite_waits_for_background_children() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let first = background_child(&hub, &dispatcher, "first");
    let second = background_child(&hub, &dispatcher, "second");
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(first.clone()).unwrap();
    composite.add(second.clone()).unwrap();
    let (log, _subscription) = record(&hub);

    composite.construct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Constructing);
    dispatcher.drain_background();
    dispatcher.drain_foreground();
    assert_eq!(first.status(), ConstructionStatus::Constructed);
    assert_eq!(composite.status(), ConstructionStatus::Constructing);
    dispatcher.drain();
    assert_eq!(second.status(), ConstructionStatus::Constructed);
    assert_eq!(composite.status(), ConstructionStatus::Constructed);
    let done = position(&log, composite.id(), ConstructionStatus::Constructed);
    assert!(position(&log, first.id(), ConstructionStatus::Constructed) < done);
    assert!(position(&log, second.id(), ConstructionStatus::Constructed) < done);

    composite.destruct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Destructing);
    dispatcher.drain();
    assert_eq!(first.status(), ConstructionStatus::Destructed);
    assert_eq!(second.status(), ConstructionStatus::Destructed);
    assert_eq!(composite.status(), ConstructionStatus::Destructed);
    let done = position(&log, composite.id(), ConstructionStatus::Destructed);
    assert!(position(&log, second.id(), ConstructionStatus::Destructed) < done);
}

/// LIFE-014 — a background child that fails rolls the composite back and the
/// failure reaches the composite's background error stream.
#[test]
fn failing_background_child_rolls_composite_back() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let bad = failing_child(&hub, &dispatcher, "bad");
    let later = background_child(&hub, &dispatcher, "later");
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(bad.clone()).unwrap();
    composite.add(later.clone()).unwrap();
    let (errors_send, errors) = mpsc::channel();
    let _errors = composite.background_errors().subscribe(move |error| {
        errors_send.send(error).unwrap();
    });
    let (log, _subscription) = record(&hub);

    composite.construct().unwrap();
    dispatcher.drain();

    assert_eq!(bad.status(), ConstructionStatus::Destructed);
    assert_eq!(later.status(), ConstructionStatus::Destructed);
    assert_eq!(composite.status(), ConstructionStatus::Destructed);
    assert!(matches!(errors.try_recv(), Ok(VmxError::Other(_))));
    assert!(!log
        .lock()
        .unwrap()
        .contains(&(composite.id(), ConstructionStatus::Constructed)));
    assert!(!matches!(
        composite.construct(),
        Err(VmxError::ConcurrentOperation)
    ));
}

/// LIFE-014 — disposing a composite while it waits for a background child
/// publishes no stray terminal status.
#[test]
fn dispose_while_waiting_publishes_no_terminal_status() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite
        .add(background_child(&hub, &dispatcher, "c"))
        .unwrap();
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    group.add(background_child(&hub, &dispatcher, "g")).unwrap();
    let aggregate = AggregateVm1::with_services(
        "aggregate",
        hub.clone(),
        dispatcher.clone(),
        background_child(&hub, &dispatcher, "a"),
    );
    let (log, _subscription) = record(&hub);

    composite.construct().unwrap();
    group.construct().unwrap();
    aggregate.construct().unwrap();
    composite.dispose().unwrap();
    group.dispose().unwrap();
    aggregate.dispose().unwrap();
    dispatcher.drain();

    for id in [composite.id(), group.id(), aggregate.id()] {
        let entries: Vec<_> = log
            .lock()
            .unwrap()
            .iter()
            .filter(|(sender, _)| *sender == id)
            .map(|(_, status)| *status)
            .collect();
        assert_eq!(
            entries,
            vec![
                ConstructionStatus::Constructing,
                ConstructionStatus::Disposed
            ]
        );
    }
}

/// LIFE-014 — a group completes only after its background child settles.
#[test]
fn group_waits_for_background_child() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = background_child(&hub, &dispatcher, "child");
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    group.add(child.clone()).unwrap();

    group.construct().unwrap();
    assert_eq!(group.status(), ConstructionStatus::Constructing);
    dispatcher.drain();
    assert_eq!(child.status(), ConstructionStatus::Constructed);
    assert_eq!(group.status(), ConstructionStatus::Constructed);

    group.destruct().unwrap();
    assert_eq!(group.status(), ConstructionStatus::Destructing);
    dispatcher.drain();
    assert_eq!(group.status(), ConstructionStatus::Destructed);

    let bad = failing_child(&hub, &dispatcher, "bad");
    let failing = GroupVm::with_services("failing", hub.clone(), dispatcher.clone());
    failing.add(bad).unwrap();
    failing.construct().unwrap();
    dispatcher.drain();
    assert_eq!(failing.status(), ConstructionStatus::Destructed);
}

/// LIFE-014 — aggregates of arity 1 and 3 wait for background components and
/// roll back when one fails.
#[test]
fn aggregates_wait_for_background_components() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let only = background_child(&hub, &dispatcher, "only");
    let single =
        AggregateVm1::with_services("single", hub.clone(), dispatcher.clone(), only.clone());
    single.construct().unwrap();
    assert_eq!(single.status(), ConstructionStatus::Constructing);
    dispatcher.drain();
    assert_eq!(only.status(), ConstructionStatus::Constructed);
    assert_eq!(single.status(), ConstructionStatus::Constructed);
    single.destruct().unwrap();
    assert_eq!(single.status(), ConstructionStatus::Destructing);
    dispatcher.drain();
    assert_eq!(single.status(), ConstructionStatus::Destructed);

    let (a, b, c) = (
        background_child(&hub, &dispatcher, "a"),
        background_child(&hub, &dispatcher, "b"),
        background_child(&hub, &dispatcher, "c"),
    );
    let triple = AggregateVm3::with_services(
        "triple",
        hub.clone(),
        dispatcher.clone(),
        a.clone(),
        b.clone(),
        c.clone(),
    );
    triple.construct().unwrap();
    dispatcher.drain_background();
    dispatcher.drain_foreground();
    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(triple.status(), ConstructionStatus::Constructing);
    dispatcher.drain();
    assert_eq!(c.status(), ConstructionStatus::Constructed);
    assert_eq!(triple.status(), ConstructionStatus::Constructed);

    let bad = failing_child(&hub, &dispatcher, "bad");
    let failing = AggregateVm1::with_services("failing", hub.clone(), dispatcher.clone(), bad);
    failing.construct().unwrap();
    dispatcher.drain();
    assert_eq!(failing.status(), ConstructionStatus::Destructed);
}

/// LIFE-014 — a nested container holds its parent transient, and reconstruct
/// completes once the deferred destruct settles.
#[test]
fn nested_containers_and_reconstruct_wait_for_background_leaves() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let leaf = background_child(&hub, &dispatcher, "leaf");
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    group.add(leaf.clone()).unwrap();
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(group.clone()).unwrap();

    composite.construct().unwrap();
    assert_eq!(group.status(), ConstructionStatus::Constructing);
    assert_eq!(composite.status(), ConstructionStatus::Constructing);
    dispatcher.drain();
    assert_eq!(leaf.status(), ConstructionStatus::Constructed);
    assert_eq!(group.status(), ConstructionStatus::Constructed);
    assert_eq!(composite.status(), ConstructionStatus::Constructed);

    composite.reconstruct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Destructing);
    dispatcher.drain();
    assert_eq!(leaf.status(), ConstructionStatus::Constructed);
    assert_eq!(composite.status(), ConstructionStatus::Constructed);
}

/// A user-written wrapper node; `forward_settle` selects whether it forwards
/// the settle hook or only the required trait methods.
#[derive(Clone)]
struct Wrapper {
    inner: Child,
    forward_settle: bool,
}

impl PartialEq for Wrapper {
    fn eq(&self, other: &Self) -> bool {
        self.inner.id() == other.inner.id()
    }
}

impl VmNode for Wrapper {
    fn id(&self) -> usize {
        self.inner.id()
    }
    fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }
    fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }
    fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
    }
    fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }
    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.set_parent_id(parent_id);
    }
    fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }
    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner.set_parent_handle(parent);
    }
    fn parent_handle(&self) -> Option<ParentHandle> {
        self.inner.parent_handle()
    }
    fn when_lifecycle_settled(&self, callback: LifecycleSettleCallback) -> bool {
        self.forward_settle && self.inner.when_lifecycle_settled(callback)
    }
}

/// LIFE-014 — a third-party node that does not forward the settle hook is
/// accepted while its background transition is in flight instead of failing
/// the container.
#[test]
fn wrapper_without_settle_hook_does_not_fail_container() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = Wrapper {
        inner: background_child(&hub, &dispatcher, "wrapped"),
        forward_settle: false,
    };
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(child.clone()).unwrap();

    composite.construct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Constructed);
    dispatcher.drain();
    assert_eq!(child.status(), ConstructionStatus::Constructed);
    assert_eq!(composite.status(), ConstructionStatus::Constructed);

    composite.destruct().unwrap();
    dispatcher.drain();
    assert_eq!(child.status(), ConstructionStatus::Destructed);
    assert_eq!(composite.status(), ConstructionStatus::Destructed);
}

/// LIFE-014 — a wrapper that forwards the settle hook holds the container
/// transient until the wrapped background child settles.
#[test]
fn wrapper_forwarding_settle_hook_makes_container_wait() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = Wrapper {
        inner: background_child(&hub, &dispatcher, "wrapped"),
        forward_settle: true,
    };
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(child.clone()).unwrap();

    composite.construct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Constructing);
    dispatcher.drain();
    assert_eq!(child.status(), ConstructionStatus::Constructed);
    assert_eq!(composite.status(), ConstructionStatus::Constructed);
}

/// LIFE-008 — reconstruct during another transition is a concurrent operation
#[test]
fn reconstruct_during_a_transition_reports_a_concurrent_operation() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = background_child(&hub, &dispatcher, "child");

    child.construct().unwrap();
    assert_eq!(child.status(), ConstructionStatus::Constructing);
    assert_eq!(child.reconstruct(), Err(VmxError::ConcurrentOperation));

    dispatcher.drain();
    child.dispose().unwrap();
    assert_eq!(child.reconstruct(), Err(VmxError::Disposed));
}

/// LIFE-008 — the Reconstructable trait reconstructs only from Constructed
#[test]
fn reconstructable_trait_does_nothing_outside_constructed() {
    use vmx::Reconstructable;
    let hub = MessageHub::new();
    let child = ComponentVm::builder()
        .name("leaf")
        .model(1)
        .services(hub, vmx::NullDispatcher::new())
        .build()
        .unwrap();

    Reconstructable::reconstruct(&child);

    assert_eq!(child.status(), ConstructionStatus::Destructed);
}

/// A background node whose transition fails and settles on another thread
/// before `when_lifecycle_settled` returns, i.e. while the container's own
/// lifecycle action is still running.
#[derive(Clone)]
struct EarlyFailure {
    id: usize,
    status: Arc<Mutex<ConstructionStatus>>,
    parent: Arc<Mutex<Option<usize>>>,
    handle: Arc<Mutex<Option<ParentHandle>>>,
    constructs: Arc<Mutex<usize>>,
}

impl EarlyFailure {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(1 << 40);
        Self {
            id: NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst),
            status: Arc::new(Mutex::new(ConstructionStatus::Destructed)),
            parent: Arc::default(),
            handle: Arc::default(),
            constructs: Arc::default(),
        }
    }
}

impl PartialEq for EarlyFailure {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl VmNode for EarlyFailure {
    fn id(&self) -> usize {
        self.id
    }
    fn construct(&self) -> VmxResult<()> {
        *self.constructs.lock().unwrap() += 1;
        *self.status.lock().unwrap() = ConstructionStatus::Constructing;
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
        let status = Arc::clone(&self.status);
        std::thread::spawn(move || {
            *status.lock().unwrap() = ConstructionStatus::Destructed;
            callback();
        })
        .join()
        .unwrap();
        true
    }
}

fn container_statuses(log: &Log, id: usize) -> Vec<ConstructionStatus> {
    log.lock()
        .unwrap()
        .iter()
        .filter(|(sender, _)| *sender == id)
        .map(|(_, status)| *status)
        .collect()
}

/// LIFE-014 — a background child that fails before the composite's own
/// construct action returns rolls the composite back exactly once, as a
/// failure after the action returns does: one terminal Destructed, no
/// Constructed, the failure on the background error stream, and no later
/// child constructed.
#[test]
fn child_failing_during_composite_action_rolls_back_once() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let bad = EarlyFailure::new();
    let later = EarlyFailure::new();
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(bad.clone()).unwrap();
    composite.add(later.clone()).unwrap();
    let (errors_send, errors) = mpsc::channel();
    let _errors = composite.background_errors().subscribe(move |error| {
        errors_send.send(error).unwrap();
    });
    let (log, _subscription) = record(&hub);

    composite.construct().unwrap();
    dispatcher.drain();

    assert_eq!(bad.status(), ConstructionStatus::Destructed);
    assert_eq!(*later.constructs.lock().unwrap(), 0);
    assert_eq!(composite.status(), ConstructionStatus::Destructed);
    assert_eq!(
        container_statuses(&log, composite.id()),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Destructed
        ]
    );
    assert!(matches!(errors.try_recv(), Ok(VmxError::Other(_))));
    assert!(errors.try_recv().is_err());
    assert!(!matches!(
        composite.construct(),
        Err(VmxError::ConcurrentOperation)
    ));
}

/// LIFE-014 — an aggregate whose component fails before the aggregate's own
/// construct action returns rolls back exactly once and reports the failure
/// on its background error stream.
#[test]
fn component_failing_during_aggregate_action_rolls_back_once() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let bad = EarlyFailure::new();
    let aggregate = AggregateVm1::with_services("aggregate", hub.clone(), dispatcher, bad.clone());
    let (errors_send, errors) = mpsc::channel();
    let _errors = aggregate.background_errors().subscribe(move |error| {
        errors_send.send(error).unwrap();
    });
    let (log, _subscription) = record(&hub);

    aggregate.construct().unwrap();

    assert_eq!(bad.status(), ConstructionStatus::Destructed);
    assert_eq!(aggregate.status(), ConstructionStatus::Destructed);
    assert_eq!(
        container_statuses(&log, aggregate.id()),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Destructed
        ]
    );
    assert!(matches!(errors.try_recv(), Ok(VmxError::Other(_))));
    assert!(errors.try_recv().is_err());
}

/// Bound for the deadlock regressions below: a hang fails the test instead of
/// stalling the suite.
const SETTLE_BOUND: std::time::Duration = std::time::Duration::from_secs(5);

/// LIFE-014 — when a failing background child settles after the last
/// composite handle is gone, the settle drops the queued continuation outside
/// the hub lock, so the hub stays usable from another thread.
#[test]
fn dropped_composite_settling_a_failing_child_leaves_the_hub_usable() {
    let hub = MessageHub::new();
    let dispatcher = vmx::DefaultDispatcher::new();
    let child = ComponentVm::builder()
        .name("slow-failure")
        .model(1)
        .background(true)
        .on_construct(|| {
            std::thread::sleep(std::time::Duration::from_millis(100));
            Err(VmxError::Other("child construct failed".to_string()))
        })
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher);
    composite.add(child).unwrap();

    composite.construct().unwrap();
    drop(composite);
    std::thread::sleep(std::time::Duration::from_millis(600));

    let (sent, done) = mpsc::channel();
    std::thread::spawn(move || {
        hub.send(Message::Custom {
            sender_id: 0,
            sender_name: "probe".to_string(),
            name: "probe".to_string(),
        });
        let _ = sent.send(());
    });
    done.recv_timeout(SETTLE_BOUND)
        .expect("hub.send blocked: the settle dropped the composite under the hub lock");
}

/// LIFE-014 — a child removed while its construct step is queued, whose last
/// handle the queue then owns, drops outside the hub lock when a background
/// sibling fails and the composite rolls back.
#[test]
fn removed_queued_child_drops_outside_the_hub_lock_when_a_sibling_fails() {
    let (finished, done) = mpsc::channel();
    std::thread::spawn(move || {
        let hub = MessageHub::new();
        let dispatcher = ManualDispatcher::new();
        let bad = failing_child(&hub, &dispatcher, "bad");
        let queued = background_child(&hub, &dispatcher, "queued");
        let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
        composite.add(bad).unwrap();
        composite.add(queued.clone()).unwrap();

        composite.construct().unwrap();
        composite.remove(&queued).unwrap();
        drop(queued);
        dispatcher.drain();
        let _ = finished.send(composite.status());
    });
    let status = done
        .recv_timeout(SETTLE_BOUND)
        .expect("drain blocked: a queued child dropped under the hub lock");
    assert_eq!(status, ConstructionStatus::Destructed);
}
