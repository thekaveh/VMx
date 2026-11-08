//! A lifecycle call during the inline dispose cascade (spec/02 §7.2,
//! ADR-0175, LIFE-021).
//!
//! A `construct()`, `destruct()`, or `reconstruct()` call that starts during
//! the cascade returns `VmxError::Disposed` and publishes nothing. The check
//! runs before the idempotent no-op and the legality check. Once the cascade
//! has started, no status other than `Disposed` commits. A leaf's member
//! cascade follows the same rules as a container's child cascade.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use vmx::{
    AggregateVm1, ComponentVm, CompositeVm, ConstructionStatus, GroupVm, ManualDispatcher, Message,
    MessageHub, MessageRecorder, NullDispatcher, VmxError, VmxResult,
};

type Call = Arc<Mutex<Option<Box<dyn Fn() -> VmxResult<()> + Send>>>>;
type Attempt = Arc<Mutex<Option<VmxResult<()>>>>;

/// The statuses that `sender_id` published, in order.
fn statuses(recorder: &MessageRecorder, sender_id: usize) -> Vec<ConstructionStatus> {
    recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(changed) if changed.sender_id == sender_id => {
                Some(changed.status)
            }
            _ => None,
        })
        .collect()
}

/// A child whose dispose hook runs `call` once and records its result.
fn calling_child(name: &str, hub: &MessageHub, call: &Call, attempt: &Attempt) -> ComponentVm {
    let child = ComponentVm::with_services(name, hub.clone(), NullDispatcher::new());
    let (call, attempt) = (Arc::clone(call), Arc::clone(attempt));
    child.on_dispose(move || {
        if let Some(call) = call.lock().unwrap().take() {
            *attempt.lock().unwrap() = Some(call());
        }
        Ok(())
    });
    child
}

/// A hook that counts its runs in `runs`.
fn counting_hook(runs: &Arc<AtomicUsize>) -> impl FnMut() -> VmxResult<()> + Send + 'static {
    let runs = Arc::clone(runs);
    move || {
        runs.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

/// The lifecycle call that the child's dispose hook makes.
#[derive(Clone, Copy, Debug)]
enum Op {
    Construct,
    Destruct,
    Reconstruct,
}

/// A container kind under test, with counters for its own hooks and for
/// its slot factory.
trait Container: Clone + Send + Sync + 'static {
    /// Builds the container around one child made by `make_child`.
    fn make(hub: &MessageHub, make_child: Arc<dyn Fn() -> ComponentVm + Send + Sync>) -> Self;
    /// The container's child, once it exists.
    fn child(&self) -> ComponentVm;
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static);
    fn on_destruct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static);
    fn id(&self) -> usize;
    fn construct(&self) -> VmxResult<()>;
    fn destruct(&self) -> VmxResult<()>;
    fn reconstruct(&self) -> VmxResult<()>;
    fn dispose(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    /// Whether the child exists only after a first construct (an aggregate).
    const LAZY: bool = false;
}

impl Container for CompositeVm<ComponentVm> {
    fn make(hub: &MessageHub, make_child: Arc<dyn Fn() -> ComponentVm + Send + Sync>) -> Self {
        let composite = CompositeVm::with_services("box", hub.clone(), NullDispatcher::new());
        composite.add(make_child()).unwrap();
        composite
    }
    fn child(&self) -> ComponentVm {
        self.items()[0].clone()
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        CompositeVm::on_construct(self, hook);
    }
    fn on_destruct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        CompositeVm::on_destruct(self, hook);
    }
    fn id(&self) -> usize {
        CompositeVm::id(self)
    }
    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }
    fn destruct(&self) -> VmxResult<()> {
        CompositeVm::destruct(self)
    }
    fn reconstruct(&self) -> VmxResult<()> {
        CompositeVm::reconstruct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        CompositeVm::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }
}

impl Container for GroupVm<ComponentVm> {
    fn make(hub: &MessageHub, make_child: Arc<dyn Fn() -> ComponentVm + Send + Sync>) -> Self {
        let group = GroupVm::with_services("box", hub.clone(), NullDispatcher::new());
        group.add(make_child()).unwrap();
        group
    }
    fn child(&self) -> ComponentVm {
        self.items()[0].clone()
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        GroupVm::on_construct(self, hook);
    }
    fn on_destruct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        GroupVm::on_destruct(self, hook);
    }
    fn id(&self) -> usize {
        GroupVm::id(self)
    }
    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }
    fn destruct(&self) -> VmxResult<()> {
        GroupVm::destruct(self)
    }
    fn reconstruct(&self) -> VmxResult<()> {
        GroupVm::reconstruct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        GroupVm::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
    }
}

impl Container for AggregateVm1<ComponentVm> {
    const LAZY: bool = true;

    fn make(hub: &MessageHub, make_child: Arc<dyn Fn() -> ComponentVm + Send + Sync>) -> Self {
        AggregateVm1::builder()
            .name("box")
            .services(hub.clone(), NullDispatcher::new())
            .component_1(move || make_child())
            .build()
            .unwrap()
    }
    fn child(&self) -> ComponentVm {
        self.component_1().expect("the slot exists")
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        AggregateVm1::on_construct(self, hook);
    }
    fn on_destruct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        AggregateVm1::on_destruct(self, hook);
    }
    fn id(&self) -> usize {
        AggregateVm1::id(self)
    }
    fn construct(&self) -> VmxResult<()> {
        AggregateVm1::construct(self)
    }
    fn destruct(&self) -> VmxResult<()> {
        AggregateVm1::destruct(self)
    }
    fn reconstruct(&self) -> VmxResult<()> {
        AggregateVm1::reconstruct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        AggregateVm1::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        AggregateVm1::status(self)
    }
}

/// Puts `container` in `initial`, then disposes it while `c1`'s dispose hook
/// calls `op` on it. The call fails with `VmxError::Disposed`, runs no
/// container hook and no factory, and the container publishes only
/// `Disposed`.
fn call_during_child_cascade<C: Container>(initial: ConstructionStatus, op: Op) {
    let hub = MessageHub::new();
    let call: Call = Arc::default();
    let attempt: Attempt = Arc::default();
    let factory_runs = Arc::new(AtomicUsize::new(0));
    let make_child: Arc<dyn Fn() -> ComponentVm + Send + Sync> = {
        let (hub, call, attempt) = (hub.clone(), Arc::clone(&call), Arc::clone(&attempt));
        let factory_runs = Arc::clone(&factory_runs);
        Arc::new(move || {
            factory_runs.fetch_add(1, Ordering::SeqCst);
            calling_child("c1", &hub, &call, &attempt)
        })
    };
    let container = C::make(&hub, make_child);
    let hook_runs = Arc::new(AtomicUsize::new(0));
    container.on_construct(counting_hook(&hook_runs));
    container.on_destruct(counting_hook(&hook_runs));
    if C::LAZY || initial == ConstructionStatus::Constructed {
        container.construct().unwrap();
    }
    if initial == ConstructionStatus::Destructed && container.status() != initial {
        container.destruct().unwrap();
    }
    assert_eq!(container.status(), initial);
    let c1 = container.child();
    let hooks_before = hook_runs.load(Ordering::SeqCst);
    let factory_before = factory_runs.load(Ordering::SeqCst);
    let recorder = hub.record(256);
    *call.lock().unwrap() = Some({
        let container = container.clone();
        Box::new(move || match op {
            Op::Construct => container.construct(),
            Op::Destruct => container.destruct(),
            Op::Reconstruct => container.reconstruct(),
        })
    });

    assert_eq!(container.dispose(), Ok(()));

    assert_eq!(
        attempt.lock().unwrap().take(),
        Some(Err(VmxError::Disposed)),
        "{op:?} from {initial:?} during the child cascade"
    );
    assert_eq!(hook_runs.load(Ordering::SeqCst), hooks_before, "no hook");
    assert_eq!(
        factory_runs.load(Ordering::SeqCst),
        factory_before,
        "no factory"
    );
    assert_eq!(
        statuses(&recorder, container.id()),
        vec![ConstructionStatus::Disposed]
    );
    assert_eq!(container.status(), ConstructionStatus::Disposed);
    assert_eq!(c1.status(), ConstructionStatus::Disposed);
    assert_eq!(
        statuses(&recorder, c1.id()),
        vec![ConstructionStatus::Disposed]
    );
}

/// Every call the container cascade refuses: the two from the catalog
/// (`construct()` while Destructed, `destruct()` while Constructed), the
/// idempotent calls and `reconstruct()` from either settled status.
fn every_call_during_child_cascade<C: Container>() {
    use ConstructionStatus::{Constructed, Destructed};
    for (initial, op) in [
        (Destructed, Op::Construct),
        (Constructed, Op::Destruct),
        (Constructed, Op::Construct),
        (Constructed, Op::Reconstruct),
        (Destructed, Op::Destruct),
        (Destructed, Op::Reconstruct),
    ] {
        call_during_child_cascade::<C>(initial, op);
    }
}

/// LIFE-021 — a lifecycle call on a `CompositeVm` from its child's dispose
/// hook fails with `VmxError::Disposed` and publishes nothing.
#[test]
fn composite_refuses_lifecycle_calls_during_its_child_cascade() {
    every_call_during_child_cascade::<CompositeVm<ComponentVm>>();
}

/// LIFE-021 — the same for `GroupVm`.
#[test]
fn group_refuses_lifecycle_calls_during_its_child_cascade() {
    every_call_during_child_cascade::<GroupVm<ComponentVm>>();
}

/// LIFE-021 — the same for `AggregateVm1`; its slot factory does not run
/// again.
#[test]
fn aggregate_refuses_lifecycle_calls_during_its_slot_cascade() {
    every_call_during_child_cascade::<AggregateVm1<ComponentVm>>();
}

/// A leaf with one member whose dispose hook runs `call` on the leaf.
struct Leaf<D: vmx::Dispatcher> {
    leaf: ComponentVm<(), D>,
    member: ComponentVm,
    hook_runs: Arc<AtomicUsize>,
    call: Call,
    attempt: Attempt,
}

fn leaf_with_member<D: vmx::Dispatcher>(
    hub: &MessageHub,
    dispatcher: D,
    background: bool,
) -> Leaf<D> {
    let hook_runs = Arc::new(AtomicUsize::new(0));
    let leaf = ComponentVm::builder()
        .name("leaf")
        .model(())
        .background(background)
        .on_construct(counting_hook(&hook_runs))
        .on_destruct(counting_hook(&hook_runs))
        .services(hub.clone(), dispatcher)
        .build()
        .unwrap();
    let call: Call = Arc::default();
    let attempt: Attempt = Arc::default();
    let member = calling_child("member", hub, &call, &attempt);
    leaf.own_member(&member).unwrap();
    Leaf {
        leaf,
        member,
        hook_runs,
        call,
        attempt,
    }
}

/// Disposes a leaf while its member's dispose hook calls `op` on it.
fn call_during_member_cascade(background: bool, initial: ConstructionStatus, op: Op) {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let Leaf {
        leaf,
        member,
        hook_runs,
        call,
        attempt,
    } = leaf_with_member(&hub, dispatcher.clone(), background);
    if initial == ConstructionStatus::Constructed {
        leaf.construct().unwrap();
        dispatcher.drain();
    }
    assert_eq!(leaf.status(), initial);
    let hooks_before = hook_runs.load(Ordering::SeqCst);
    let recorder = hub.record(256);
    *call.lock().unwrap() = Some({
        let leaf = leaf.clone();
        Box::new(move || match op {
            Op::Construct => leaf.construct(),
            Op::Destruct => leaf.destruct(),
            Op::Reconstruct => leaf.reconstruct(),
        })
    });

    assert_eq!(leaf.dispose(), Ok(()));
    dispatcher.drain();

    assert_eq!(
        attempt.lock().unwrap().take(),
        Some(Err(VmxError::Disposed)),
        "{op:?} from {initial:?} during the member cascade (background: {background})"
    );
    assert_eq!(
        hook_runs.load(Ordering::SeqCst),
        hooks_before,
        "no leaf hook"
    );
    assert_eq!(
        statuses(&recorder, leaf.id()),
        vec![ConstructionStatus::Disposed]
    );
    assert_eq!(leaf.status(), ConstructionStatus::Disposed);
    assert_eq!(member.status(), ConstructionStatus::Disposed);
}

/// LIFE-021 — a lifecycle call on a leaf from its member's dispose hook
/// fails with `VmxError::Disposed`, runs no leaf hook, and the leaf
/// publishes only `Disposed`; with and without `background(true)`.
#[test]
fn leaf_refuses_lifecycle_calls_during_its_member_cascade() {
    use ConstructionStatus::{Constructed, Destructed};
    for background in [false, true] {
        for (initial, op) in [
            (Destructed, Op::Construct),
            (Constructed, Op::Destruct),
            (Constructed, Op::Reconstruct),
            (Constructed, Op::Construct),
            (Destructed, Op::Destruct),
        ] {
            call_during_member_cascade(background, initial, op);
        }
    }
}

/// LIFE-021 — a background leaf whose construct hook ran and whose
/// `Constructed` commit is queued on the foreground publishes no
/// `Constructed` when the member's dispose hook drains that queue.
#[test]
fn queued_background_commit_drained_in_the_member_cascade_publishes_nothing() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let Leaf {
        leaf,
        member,
        hook_runs,
        call,
        ..
    } = leaf_with_member(&hub, dispatcher.clone(), true);
    let recorder = hub.record(256);
    leaf.construct().unwrap();
    dispatcher.drain_background();
    assert_eq!(hook_runs.load(Ordering::SeqCst), 1, "the hook ran");
    assert_eq!(
        dispatcher.foreground_queued_len(),
        1,
        "the commit is queued"
    );
    *call.lock().unwrap() = Some({
        let dispatcher = dispatcher.clone();
        Box::new(move || {
            dispatcher.drain_foreground();
            Ok(())
        })
    });

    assert_eq!(leaf.dispose(), Ok(()));

    assert_eq!(
        statuses(&recorder, leaf.id()),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Disposed
        ]
    );
    assert_eq!(leaf.status(), ConstructionStatus::Disposed);
    assert_eq!(member.status(), ConstructionStatus::Disposed);
}

/// LIFE-021 — a background construct whose hook has not run yet runs no
/// hook and publishes no `Constructed` when the member's dispose hook
/// drains the dispatcher.
#[test]
fn queued_background_hook_drained_in_the_member_cascade_does_not_run() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let Leaf {
        leaf,
        member,
        hook_runs,
        call,
        ..
    } = leaf_with_member(&hub, dispatcher.clone(), true);
    let recorder = hub.record(256);
    leaf.construct().unwrap();
    assert_eq!(dispatcher.background_queued_len(), 1, "the hook is queued");
    *call.lock().unwrap() = Some({
        let dispatcher = dispatcher.clone();
        Box::new(move || {
            dispatcher.drain();
            Ok(())
        })
    });

    assert_eq!(leaf.dispose(), Ok(()));
    dispatcher.drain();

    assert_eq!(hook_runs.load(Ordering::SeqCst), 0, "no hook");
    assert_eq!(
        statuses(&recorder, leaf.id()),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Disposed
        ]
    );
    assert_eq!(leaf.status(), ConstructionStatus::Disposed);
    assert_eq!(member.status(), ConstructionStatus::Disposed);
}
