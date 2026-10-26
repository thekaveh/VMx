//! Containers stay transient until background children settle (spec/02 §6).

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use vmx::{
    AggregateVm1, AggregateVm2, AggregateVm3, ComponentVm, CompositeVm, ConstructionStatus,
    GroupVm, LifecycleSettleCallback, ManualDispatcher, Message, MessageHub, ParentHandle,
    Subscription, VmNode, VmxError, VmxResult,
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

/// LIFE-014 — when a failing background child's settle releases the last
/// composite handle (a hub subscriber drops it on the composite's rollback),
/// the settle drops the composite outside the hub lock, so the hub stays
/// usable from another thread and the tree is freed.
#[test]
fn dropped_composite_settling_a_failing_child_leaves_the_hub_usable() {
    let hub = MessageHub::new();
    let dispatcher = vmx::DefaultDispatcher::new();
    let child_dropped = Arc::new(AtomicBool::new(false));
    let child = ComponentVm::builder()
        .name("slow-failure")
        .model(Arc::new(DropSentinel(Arc::clone(&child_dropped))))
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
    let composite_id = composite.id();
    // The subscriber owns the last composite handle and drops it while the
    // settle publishes the composite's rollback, so the settle path releases
    // the composite's last reference.
    let slot = Arc::new(Mutex::new(None));
    let (released_send, released) = mpsc::channel();
    let _release = {
        let slot = Arc::clone(&slot);
        hub.subscribe(move |message| {
            if let Message::ConstructionStatusChanged(change) = message {
                if change.sender_id == composite_id
                    && change.status == ConstructionStatus::Destructed
                {
                    let held = slot.lock().unwrap().take();
                    if held.is_some() {
                        drop(held);
                        let _ = released_send.send(());
                    }
                }
            }
        })
    };

    composite.construct().unwrap();
    *slot.lock().unwrap() = Some(composite);
    released
        .recv_timeout(SETTLE_BOUND)
        .expect("the settle never published the composite's rollback");

    let (sent, done) = mpsc::channel();
    let probe_hub = hub.clone();
    std::thread::spawn(move || {
        probe_hub.send(Message::Custom {
            sender_id: 0,
            sender_name: "probe".to_string(),
            name: "probe".to_string(),
        });
        let _ = sent.send(());
    });
    done.recv_timeout(SETTLE_BOUND)
        .expect("hub.send blocked: the settle dropped the composite under the hub lock");
    let deadline = std::time::Instant::now() + SETTLE_BOUND;
    while !child_dropped.load(Ordering::SeqCst) {
        assert!(
            std::time::Instant::now() < deadline,
            "the composite released by its settle leaked its child"
        );
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
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

/// Disposes an awaited background child whose `on_dispose` hook panics (or
/// fails) while its container waits, then lets the container settle.
fn dispose_awaited_child_with_hook<C: VmNode>(
    container: &C,
    child: &Child,
    dispatcher: &ManualDispatcher,
    panics: bool,
) {
    if panics {
        child.on_dispose(|| panic!("dispose hook panicked"));
    } else {
        child.on_dispose(|| Err(VmxError::Other("dispose hook failed".to_string())));
    }
    container.construct().unwrap();
    assert_eq!(container.status(), ConstructionStatus::Constructing);
    let disposal = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| child.dispose()));
    // #738: the panic still reaches the caller of `dispose()`.
    assert_eq!(disposal.is_err(), panics);
    dispatcher.drain();
}

/// #738 — a panicking `on_dispose` hook on an awaited background child still
/// releases the container's settle waiters, as a failing hook does.
#[test]
fn panicking_dispose_hook_on_an_awaited_child_settles_the_composite() {
    for panics in [false, true] {
        let hub = MessageHub::new();
        let dispatcher = ManualDispatcher::new();
        let child = background_child(&hub, &dispatcher, "child");
        let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
        composite.add(child.clone()).unwrap();

        dispose_awaited_child_with_hook(&composite, &child, &dispatcher, panics);

        assert_eq!(
            composite.status(),
            ConstructionStatus::Destructed,
            "panics: {panics}"
        );
        // A later construct and destruct run normally, without
        // `ConcurrentOperation`, once the disposed child is removed.
        composite.remove(&child).unwrap();
        composite.construct().unwrap();
        dispatcher.drain();
        assert_eq!(composite.status(), ConstructionStatus::Constructed);
        composite.destruct().unwrap();
        dispatcher.drain();
        assert_eq!(composite.status(), ConstructionStatus::Destructed);
    }
}

/// #738 — the same regression for a `GroupVm`.
#[test]
fn panicking_dispose_hook_on_an_awaited_child_settles_the_group() {
    for panics in [false, true] {
        let hub = MessageHub::new();
        let dispatcher = ManualDispatcher::new();
        let child = background_child(&hub, &dispatcher, "child");
        let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
        group.add(child.clone()).unwrap();

        dispose_awaited_child_with_hook(&group, &child, &dispatcher, panics);

        assert_eq!(
            group.status(),
            ConstructionStatus::Destructed,
            "panics: {panics}"
        );
        // A later construct and destruct run normally, without
        // `ConcurrentOperation`, once the disposed child is removed.
        group.remove(&child).unwrap();
        group.construct().unwrap();
        dispatcher.drain();
        assert_eq!(group.status(), ConstructionStatus::Constructed);
        group.destruct().unwrap();
        dispatcher.drain();
        assert_eq!(group.status(), ConstructionStatus::Destructed);
    }
}

/// Constructs `node`, reconstructs it through the `Reconstructable` trait
/// and drains the dispatcher; the node must end `Constructed` (#748).
fn reconstruct_through_the_trait<N: VmNode>(node: &N, dispatcher: &ManualDispatcher) {
    use vmx::Reconstructable;
    node.construct().unwrap();
    dispatcher.drain();
    assert_eq!(node.status(), ConstructionStatus::Constructed);

    Reconstructable::reconstruct(node);
    dispatcher.drain();

    assert_eq!(node.status(), ConstructionStatus::Constructed);
}

/// #748 — the trait reconstruct of a background node waits for its deferred
/// destruct, then constructs again.
#[test]
fn reconstructable_trait_rebuilds_a_background_component() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let vm = background_child(&hub, &dispatcher, "background");
    reconstruct_through_the_trait(&vm, &dispatcher);
}

/// #748 — the same for a composite with a background child.
#[test]
fn reconstructable_trait_rebuilds_a_composite_with_a_background_child() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite
        .add(background_child(&hub, &dispatcher, "c"))
        .unwrap();
    reconstruct_through_the_trait(&composite, &dispatcher);
}

/// #748 — the same for a group with a background child.
#[test]
fn reconstructable_trait_rebuilds_a_group_with_a_background_child() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    group.add(background_child(&hub, &dispatcher, "g")).unwrap();
    reconstruct_through_the_trait(&group, &dispatcher);
}

/// #748 — the same for an aggregate with a background component.
#[test]
fn reconstructable_trait_rebuilds_an_aggregate_with_a_background_component() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let aggregate = AggregateVm1::with_services(
        "aggregate",
        hub.clone(),
        dispatcher.clone(),
        background_child(&hub, &dispatcher, "a"),
    );
    reconstruct_through_the_trait(&aggregate, &dispatcher);
}

/// #748 — a synchronous component still reconstructs through the trait.
#[test]
fn reconstructable_trait_rebuilds_a_synchronous_component() {
    use vmx::Reconstructable;
    let child = ComponentVm::builder()
        .name("leaf")
        .model(1)
        .services(MessageHub::new(), vmx::NullDispatcher::new())
        .build()
        .unwrap();
    child.construct().unwrap();

    Reconstructable::reconstruct(&child);

    assert_eq!(child.status(), ConstructionStatus::Constructed);
}

/// A dispatcher that runs each action inline until it is set to discard;
/// then it drops every action, so a background child it serves never settles.
#[derive(Clone)]
struct DiscardingDispatcher {
    discard: Arc<AtomicBool>,
}

impl DiscardingDispatcher {
    fn discarding() -> Self {
        Self {
            discard: Arc::new(AtomicBool::new(true)),
        }
    }

    fn inline() -> Self {
        Self {
            discard: Arc::new(AtomicBool::new(false)),
        }
    }

    fn start_discarding(&self) {
        self.discard.store(true, Ordering::SeqCst);
    }
}

impl vmx::Dispatcher for DiscardingDispatcher {
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>) {
        if !self.discard.load(Ordering::SeqCst) {
            action();
        }
    }

    fn dispatch_background(&self, action: Box<dyn FnOnce() + Send>) {
        self.dispatch(action);
    }
}

/// Sets its flag when the last model handle drops.
struct DropSentinel(Arc<AtomicBool>);

impl Drop for DropSentinel {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

impl PartialEq for DropSentinel {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }
}

type Tracked = ComponentVm<Arc<DropSentinel>, DiscardingDispatcher>;

/// A component whose model sets the returned flag when it drops.
fn tracked_child(
    hub: &MessageHub,
    dispatcher: &DiscardingDispatcher,
    name: &str,
    background: bool,
) -> (Tracked, Arc<AtomicBool>) {
    let dropped = Arc::new(AtomicBool::new(false));
    let child = ComponentVm::builder()
        .name(name)
        .model(Arc::new(DropSentinel(Arc::clone(&dropped))))
        .background(background)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    (child, dropped)
}

/// A background child and a leaf child, each with a drop sentinel.
struct TrackedTree {
    background: Tracked,
    leaf: Tracked,
    background_dropped: Arc<AtomicBool>,
    leaf_dropped: Arc<AtomicBool>,
}

impl TrackedTree {
    fn new(hub: &MessageHub, dispatcher: &DiscardingDispatcher) -> Self {
        let (background, background_dropped) = tracked_child(hub, dispatcher, "background", true);
        let (leaf, leaf_dropped) = tracked_child(hub, dispatcher, "leaf", false);
        Self {
            background,
            leaf,
            background_dropped,
            leaf_dropped,
        }
    }
}

/// Asserts that both children of a dropped container were freed.
fn assert_tree_dropped(leaf: &AtomicBool, background: &AtomicBool) {
    assert!(
        leaf.load(Ordering::SeqCst),
        "the waiting container leaked its leaf child"
    );
    assert!(
        background.load(Ordering::SeqCst),
        "the waiting container leaked its background child"
    );
}

/// A composite over `tree` that also runs a selector after its children.
fn tracked_composite(
    hub: &MessageHub,
    dispatcher: &DiscardingDispatcher,
    tree: TrackedTree,
) -> (
    CompositeVm<Tracked, DiscardingDispatcher>,
    Arc<AtomicBool>,
    Arc<AtomicBool>,
) {
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.set_current_selector(|items| items.into_iter().last());
    composite.add(tree.background).unwrap();
    composite.add(tree.leaf).unwrap();
    (composite, tree.leaf_dropped, tree.background_dropped)
}

fn tracked_group(
    hub: &MessageHub,
    dispatcher: &DiscardingDispatcher,
    tree: TrackedTree,
) -> (
    GroupVm<Tracked, DiscardingDispatcher>,
    Arc<AtomicBool>,
    Arc<AtomicBool>,
) {
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    group.add(tree.background).unwrap();
    group.add(tree.leaf).unwrap();
    (group, tree.leaf_dropped, tree.background_dropped)
}

type TrackedAggregate = AggregateVm2<Tracked, Tracked, DiscardingDispatcher>;

fn tracked_aggregate(
    hub: &MessageHub,
    dispatcher: &DiscardingDispatcher,
    tree: TrackedTree,
) -> (TrackedAggregate, Arc<AtomicBool>, Arc<AtomicBool>) {
    let aggregate = AggregateVm2::with_services(
        "aggregate",
        hub.clone(),
        dispatcher.clone(),
        tree.background,
        tree.leaf,
    );
    (aggregate, tree.leaf_dropped, tree.background_dropped)
}

/// #750 — a composite waiting for a background child that never settles
/// frees its tree when its last handle drops without `dispose()`.
#[test]
fn composite_waiting_on_an_unsettled_child_frees_its_tree() {
    let hub = MessageHub::new();
    let dispatcher = DiscardingDispatcher::discarding();
    let tree = TrackedTree::new(&hub, &dispatcher);
    let (composite, leaf_dropped, background_dropped) = tracked_composite(&hub, &dispatcher, tree);

    composite.construct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Constructing);
    drop(composite);

    assert_tree_dropped(&leaf_dropped, &background_dropped);
}

/// #750 — a group waiting for a background child that never settles frees
/// its tree when its last handle drops without `dispose()`.
#[test]
fn group_waiting_on_an_unsettled_child_frees_its_tree() {
    let hub = MessageHub::new();
    let dispatcher = DiscardingDispatcher::discarding();
    let tree = TrackedTree::new(&hub, &dispatcher);
    let (group, leaf_dropped, background_dropped) = tracked_group(&hub, &dispatcher, tree);

    group.construct().unwrap();
    assert_eq!(group.status(), ConstructionStatus::Constructing);
    drop(group);

    assert_tree_dropped(&leaf_dropped, &background_dropped);
}

/// #750 — an aggregate waiting for a background component that never
/// settles frees its tree when its last handle drops without `dispose()`.
#[test]
fn aggregate_waiting_on_an_unsettled_component_frees_its_tree() {
    let hub = MessageHub::new();
    let dispatcher = DiscardingDispatcher::discarding();
    let tree = TrackedTree::new(&hub, &dispatcher);
    let (aggregate, leaf_dropped, background_dropped) = tracked_aggregate(&hub, &dispatcher, tree);

    aggregate.construct().unwrap();
    assert_eq!(aggregate.status(), ConstructionStatus::Constructing);
    drop(aggregate);

    assert_tree_dropped(&leaf_dropped, &background_dropped);
}

/// #750 — a composite whose reconstruct waits for a background child's
/// destruct that never settles frees its tree when its last handle drops.
#[test]
fn composite_reconstruct_waiting_on_an_unsettled_child_frees_its_tree() {
    let hub = MessageHub::new();
    let dispatcher = DiscardingDispatcher::inline();
    let tree = TrackedTree::new(&hub, &dispatcher);
    let (composite, leaf_dropped, background_dropped) = tracked_composite(&hub, &dispatcher, tree);
    composite.construct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Constructed);

    dispatcher.start_discarding();
    composite.reconstruct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Destructing);
    drop(composite);

    assert_tree_dropped(&leaf_dropped, &background_dropped);
}

/// #750 — the composite's reconstruct command, waiting the same way, frees
/// the tree when the composite's last handle drops.
#[test]
fn composite_reconstruct_command_waiting_on_an_unsettled_child_frees_its_tree() {
    let hub = MessageHub::new();
    let dispatcher = DiscardingDispatcher::inline();
    let tree = TrackedTree::new(&hub, &dispatcher);
    let (composite, leaf_dropped, background_dropped) = tracked_composite(&hub, &dispatcher, tree);
    composite.construct().unwrap();

    dispatcher.start_discarding();
    vmx::Command::execute(&composite.reconstruct_command());
    assert_eq!(composite.status(), ConstructionStatus::Destructing);
    drop(composite);

    assert_tree_dropped(&leaf_dropped, &background_dropped);
}

/// #750 — a group whose reconstruct waits for a background child's destruct
/// that never settles frees its tree when its last handle drops.
#[test]
fn group_reconstruct_waiting_on_an_unsettled_child_frees_its_tree() {
    let hub = MessageHub::new();
    let dispatcher = DiscardingDispatcher::inline();
    let tree = TrackedTree::new(&hub, &dispatcher);
    let (group, leaf_dropped, background_dropped) = tracked_group(&hub, &dispatcher, tree);
    group.construct().unwrap();
    assert_eq!(group.status(), ConstructionStatus::Constructed);

    dispatcher.start_discarding();
    group.reconstruct().unwrap();
    assert_eq!(group.status(), ConstructionStatus::Destructing);
    drop(group);

    assert_tree_dropped(&leaf_dropped, &background_dropped);
}

/// #750 — the group's reconstruct command, waiting the same way, frees the
/// tree when the group's last handle drops.
#[test]
fn group_reconstruct_command_waiting_on_an_unsettled_child_frees_its_tree() {
    let hub = MessageHub::new();
    let dispatcher = DiscardingDispatcher::inline();
    let tree = TrackedTree::new(&hub, &dispatcher);
    let (group, leaf_dropped, background_dropped) = tracked_group(&hub, &dispatcher, tree);
    group.construct().unwrap();

    dispatcher.start_discarding();
    vmx::Command::execute(&group.reconstruct_command());
    assert_eq!(group.status(), ConstructionStatus::Destructing);
    drop(group);

    assert_tree_dropped(&leaf_dropped, &background_dropped);
}

/// #750 — an aggregate whose reconstruct waits for a background component's
/// destruct that never settles frees its tree when its last handle drops.
#[test]
fn aggregate_reconstruct_waiting_on_an_unsettled_component_frees_its_tree() {
    let hub = MessageHub::new();
    let dispatcher = DiscardingDispatcher::inline();
    let tree = TrackedTree::new(&hub, &dispatcher);
    let (aggregate, leaf_dropped, background_dropped) = tracked_aggregate(&hub, &dispatcher, tree);
    aggregate.construct().unwrap();
    assert_eq!(aggregate.status(), ConstructionStatus::Constructed);

    dispatcher.start_discarding();
    aggregate.reconstruct().unwrap();
    assert_eq!(aggregate.status(), ConstructionStatus::Destructing);
    drop(aggregate);

    assert_tree_dropped(&leaf_dropped, &background_dropped);
}

/// #750 — a composite dropped while it waits abandons its transition: the
/// background child still settles later, and nothing panics or blocks.
#[test]
fn dropped_waiting_composite_lets_its_child_settle_alone() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = background_child(&hub, &dispatcher, "child");
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(child.clone()).unwrap();
    composite.construct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Constructing);

    drop(composite);
    dispatcher.drain();

    assert_eq!(child.status(), ConstructionStatus::Constructed);
}

/// #750 — an aggregate whose user keeps only one of its commands across a
/// deferred `reconstruct()` still completes the reconstruct: the command
/// keeps the aggregate's core alive, so the transition must not be abandoned.
#[test]
fn aggregate_reconstruct_completes_while_only_a_command_is_held() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let aggregate = AggregateVm2::with_services(
        "aggregate",
        hub.clone(),
        dispatcher.clone(),
        background_child(&hub, &dispatcher, "background"),
        background_child(&hub, &dispatcher, "other"),
    );
    aggregate.construct().unwrap();
    dispatcher.drain();
    assert_eq!(aggregate.status(), ConstructionStatus::Constructed);
    let id = aggregate.id();
    let (log, _subscription) = record(&hub);

    let command = aggregate.select_command();
    aggregate.reconstruct().unwrap();
    assert_eq!(aggregate.status(), ConstructionStatus::Destructing);
    drop(aggregate);
    dispatcher.drain();

    assert_eq!(
        container_statuses(&log, id),
        vec![
            ConstructionStatus::Destructing,
            ConstructionStatus::Destructed,
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed,
        ]
    );
    drop(command);
}
