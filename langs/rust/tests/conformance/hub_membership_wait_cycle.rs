//! Hub, hook-owner and container membership waits share one wait-for graph
//! (spec/03 §4.1, ADR-0172, #1158). A cross-thread container disposal and the
//! owner of that container's transaction can wait for each other through a hub
//! drain or an admitted hook, in either order. The wait that closes the cycle
//! is refused, so neither thread hangs: a disposal records deferred terminal
//! intent (chapter 06 §4.2, ADR-0153, ADR-0167), a hub send enqueues for the
//! active drain (ADR-0119), and a foreign `dispose()` defers terminal cleanup
//! to the hook (ADR-0126).
//!
//! The threads are ordered by observed wait registrations, not by sleeps.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle, ThreadId};
use std::time::{Duration, Instant};
use vmx::{
    container_wait_registered_for_testing, wait_registered_for_testing, AggregateVm1, ComponentVm,
    CompositeVm, ConstructionStatus, GroupVm, Message, MessageHub, NullDispatcher, VmxError,
    VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

type Child = ComponentVm<&'static str>;

fn child(name: &'static str, hub: &MessageHub) -> Child {
    Child::with_model(name, name, hub.clone(), NullDispatcher::new())
}

fn go() -> Message {
    Message::Custom {
        sender_id: 0,
        sender_name: "test".into(),
        name: "go".into(),
    }
}

fn is_go(message: &Message) -> bool {
    matches!(message, Message::Custom { name, .. } if name == "go")
}

/// Polls `condition` until it holds or the bound passes. Returns whether it
/// held, so a hook or subscriber never panics inside the library.
fn eventually(condition: impl Fn() -> bool) -> bool {
    let deadline = Instant::now() + BOUND;
    while !condition() {
        if Instant::now() >= deadline {
            return false;
        }
        thread::sleep(Duration::from_millis(1));
    }
    true
}

/// Joins `handle`, failing instead of hanging when it does not return by
/// `deadline`.
fn join_by<T>(handle: JoinHandle<T>, deadline: Instant, what: &str) -> T {
    while !handle.is_finished() {
        assert!(Instant::now() < deadline, "{what} did not return: deadlock");
        thread::sleep(Duration::from_millis(1));
    }
    handle.join().unwrap()
}

/// A thread id that a test publishes once the thread is spawned.
#[derive(Clone, Default)]
struct Slot(Arc<Mutex<Option<ThreadId>>>);

impl Slot {
    fn set(&self, id: ThreadId) {
        *self.0.lock().unwrap() = Some(id);
    }

    fn get(&self) -> ThreadId {
        loop {
            if let Some(id) = *self.0.lock().unwrap() {
                return id;
            }
            thread::yield_now();
        }
    }
}

#[derive(Clone, Default)]
struct Flag(Arc<AtomicBool>);

impl Flag {
    fn raise(&self) {
        self.0.store(true, Ordering::SeqCst);
    }

    fn is_raised(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
}

/// The two container kinds under test, built with auto-construct-on-add and
/// constructed.
trait Container: Clone + Send + Sync + 'static {
    fn make(name: &'static str, hub: &MessageHub) -> Self;
    fn add_child(&self, child: Child) -> VmxResult<()>;
    fn dispose_container(&self) -> VmxResult<()>;
    fn container_status(&self) -> ConstructionStatus;
}

impl Container for CompositeVm<Child> {
    fn make(name: &'static str, hub: &MessageHub) -> Self {
        let composite = CompositeVm::with_services(name, hub.clone(), NullDispatcher::new());
        composite.set_auto_construct_on_add(true);
        composite.construct().unwrap();
        composite
    }
    fn add_child(&self, child: Child) -> VmxResult<()> {
        self.add(child)
    }
    fn dispose_container(&self) -> VmxResult<()> {
        self.dispose()
    }
    fn container_status(&self) -> ConstructionStatus {
        self.status()
    }
}

impl Container for GroupVm<Child> {
    fn make(name: &'static str, hub: &MessageHub) -> Self {
        let group = GroupVm::with_services(name, hub.clone(), NullDispatcher::new());
        group.set_auto_construct_on_add(true);
        group.construct().unwrap();
        group
    }
    fn add_child(&self, child: Child) -> VmxResult<()> {
        self.add(child)
    }
    fn dispose_container(&self) -> VmxResult<()> {
        self.dispose()
    }
    fn container_status(&self) -> ConstructionStatus {
        self.status()
    }
}

/// Reproduction 1. Thread B drains the hub, and its subscriber disposes the
/// container. Thread A adds `x`, so A's transaction publishes `x`'s status on
/// the hub that B drains.
///
/// With `disposal_waits_first`, B's disposal waits for A's transaction, and
/// A's status publication then closes the cycle. Otherwise A's publication
/// waits for B's drain, and B's disposal closes it.
fn a_hub_drain_and_a_container_disposal_do_not_deadlock<C: Container>(
    disposal_waits_first: bool,
    dispose_other: bool,
) {
    let hub = MessageHub::new();
    let container = C::make("c", &hub);
    let other = C::make("other", &hub);
    let x = child("x", &hub);
    let (a_slot, b_slot) = (Slot::default(), Slot::default());
    let (draining, send_now) = (Flag::default(), Flag::default());
    let disposal = Arc::new(Mutex::new(None));
    let _subscription = hub.subscribe({
        let target = if dispose_other {
            other.clone()
        } else {
            container.clone()
        };
        let (a_slot, draining, disposal) = (a_slot.clone(), draining.clone(), disposal.clone());
        move |message| {
            if !is_go(message) {
                return;
            }
            draining.raise();
            if !disposal_waits_first && !dispose_other {
                let a = a_slot.get();
                eventually(|| wait_registered_for_testing(a));
            }
            *disposal.lock().unwrap() = Some(target.dispose_container());
        }
    });
    if disposal_waits_first {
        x.on_construct({
            let (b_slot, send_now) = (b_slot.clone(), send_now.clone());
            move || {
                send_now.raise();
                let b = b_slot.get();
                if eventually(|| container_wait_registered_for_testing(b)) {
                    Ok(())
                } else {
                    Err(VmxError::Other("the disposal never waited".into()))
                }
            }
        });
    }

    let b = thread::spawn({
        let (hub, send_now) = (hub.clone(), send_now.clone());
        move || {
            if disposal_waits_first {
                assert!(eventually(|| send_now.is_raised()));
            }
            hub.send(go());
        }
    });
    b_slot.set(b.thread().id());
    let a = thread::spawn({
        let (container, x) = (container.clone(), x.clone());
        move || {
            if !disposal_waits_first {
                assert!(eventually(|| draining.is_raised()));
            }
            container.add_child(x)
        }
    });
    a_slot.set(a.thread().id());
    let deadline = Instant::now() + BOUND;
    let added = join_by(a, deadline, "container.add(x)");
    join_by(b, deadline, "the drain");

    assert_eq!(*disposal.lock().unwrap(), Some(Ok(())));
    if dispose_other {
        assert_eq!(added, Ok(()));
        assert_eq!(other.container_status(), ConstructionStatus::Disposed);
        assert_eq!(
            container.container_status(),
            ConstructionStatus::Constructed
        );
        assert_eq!(x.status(), ConstructionStatus::Constructed);
        return;
    }
    assert_eq!(container.container_status(), ConstructionStatus::Disposed);
    match added {
        Ok(()) => assert_eq!(x.status(), ConstructionStatus::Disposed),
        Err(VmxError::Disposed) => {
            assert_eq!(x.status(), ConstructionStatus::Destructed);
            assert_eq!(x.parent_id(), None);
        }
        other => panic!("unexpected add result {other:?}"),
    }
}

#[test]
fn a_group_disposal_and_a_hub_drain_wait_do_not_deadlock() {
    a_hub_drain_and_a_container_disposal_do_not_deadlock::<GroupVm<Child>>(false, false);
}

#[test]
fn a_group_disposal_that_waits_first_and_a_hub_publication_do_not_deadlock() {
    a_hub_drain_and_a_container_disposal_do_not_deadlock::<GroupVm<Child>>(true, false);
}

#[test]
fn a_composite_disposal_and_a_hub_drain_wait_do_not_deadlock() {
    a_hub_drain_and_a_container_disposal_do_not_deadlock::<CompositeVm<Child>>(false, false);
}

#[test]
fn a_composite_disposal_that_waits_first_and_a_hub_publication_do_not_deadlock() {
    a_hub_drain_and_a_container_disposal_do_not_deadlock::<CompositeVm<Child>>(true, false);
}

/// Control: B disposes another container, so no cycle forms and the add
/// completes.
#[test]
fn disposing_another_container_from_the_drain_leaves_the_add_intact() {
    a_hub_drain_and_a_container_disposal_do_not_deadlock::<GroupVm<Child>>(false, true);
    a_hub_drain_and_a_container_disposal_do_not_deadlock::<CompositeVm<Child>>(false, true);
}

/// Reproduction 2. Thread A runs `v`'s construct hook, which disposes `g`.
/// Thread B adds `x` to `g`, and `x`'s construct hook, inside B's transaction,
/// disposes `v`, whose hook A owns.
///
/// With `disposal_waits_first`, A's `g.dispose()` waits for B's transaction,
/// and B's `v.dispose()` then closes the cycle. Otherwise B's `v.dispose()`
/// waits for A's hook, and A's `g.dispose()` closes it.
fn a_hook_owner_wait_and_a_container_disposal_do_not_deadlock(disposal_waits_first: bool) {
    let hub = MessageHub::new();
    let g = <GroupVm<Child> as Container>::make("g", &hub);
    let v = child("v", &hub);
    let x = child("x", &hub);
    let (a_slot, b_slot) = (Slot::default(), Slot::default());
    let (v_hook_running, x_hook_running) = (Flag::default(), Flag::default());
    let disposals = Arc::new(Mutex::new(Vec::new()));
    v.on_construct({
        let (g, b_slot, disposals) = (g.clone(), b_slot.clone(), disposals.clone());
        let (v_hook_running, x_hook_running) = (v_hook_running.clone(), x_hook_running.clone());
        move || {
            v_hook_running.raise();
            eventually(|| x_hook_running.is_raised());
            if !disposal_waits_first {
                let b = b_slot.get();
                eventually(|| wait_registered_for_testing(b));
            }
            let result = g.dispose();
            disposals.lock().unwrap().push(("g", result.clone()));
            result
        }
    });
    x.on_construct({
        let (v, a_slot, disposals) = (v.clone(), a_slot.clone(), disposals.clone());
        move || {
            x_hook_running.raise();
            if disposal_waits_first {
                let a = a_slot.get();
                eventually(|| container_wait_registered_for_testing(a));
            }
            let result = v.dispose();
            disposals.lock().unwrap().push(("v", result.clone()));
            result
        }
    });

    let a = thread::spawn({
        let v = v.clone();
        move || v.construct()
    });
    a_slot.set(a.thread().id());
    let b = thread::spawn({
        let (g, x) = (g.clone(), x.clone());
        move || {
            assert!(eventually(|| v_hook_running.is_raised()));
            g.add(x)
        }
    });
    b_slot.set(b.thread().id());
    let deadline = Instant::now() + BOUND;
    let _ = join_by(a, deadline, "v.construct()");
    let _ = join_by(b, deadline, "g.add(x)");

    let mut disposals = disposals.lock().unwrap().clone();
    disposals.sort_by_key(|(name, _)| *name);
    assert_eq!(disposals, vec![("g", Ok(())), ("v", Ok(()))]);
    assert_eq!(g.status(), ConstructionStatus::Disposed);
    assert_eq!(v.status(), ConstructionStatus::Disposed);
}

#[test]
fn a_hook_owner_wait_and_a_group_disposal_do_not_deadlock() {
    a_hook_owner_wait_and_a_container_disposal_do_not_deadlock(false);
}

#[test]
fn a_group_disposal_that_waits_first_and_a_hook_owner_wait_do_not_deadlock() {
    a_hook_owner_wait_and_a_container_disposal_do_not_deadlock(true);
}

/// Reproduction 3. Thread A constructs a fixed aggregate, so its child's
/// status publication runs inside the aggregate's membership transaction.
/// Thread B drains the hub, and its subscriber disposes the aggregate.
fn a_hub_drain_and_an_aggregate_disposal_do_not_deadlock(disposal_waits_first: bool) {
    let hub = MessageHub::new();
    let a_child = child("a", &hub);
    let aggregate =
        AggregateVm1::with_services("x", hub.clone(), NullDispatcher::new(), a_child.clone());
    let (a_slot, b_slot) = (Slot::default(), Slot::default());
    let (send_now, draining) = (Flag::default(), Flag::default());
    let disposal = Arc::new(Mutex::new(None));
    let _subscription = hub.subscribe({
        let (aggregate, a_slot) = (aggregate.clone(), a_slot.clone());
        let (draining, disposal) = (draining.clone(), disposal.clone());
        move |message| {
            if !is_go(message) {
                return;
            }
            draining.raise();
            if !disposal_waits_first {
                let a = a_slot.get();
                eventually(|| wait_registered_for_testing(a));
            }
            *disposal.lock().unwrap() = Some(aggregate.dispose());
        }
    });
    a_child.on_construct({
        let (b_slot, send_now) = (b_slot.clone(), send_now.clone());
        move || {
            send_now.raise();
            let ordered = if disposal_waits_first {
                let b = b_slot.get();
                eventually(|| container_wait_registered_for_testing(b))
            } else {
                eventually(|| draining.is_raised())
            };
            if ordered {
                Ok(())
            } else {
                Err(VmxError::Other("the threads never met".into()))
            }
        }
    });

    let b = thread::spawn({
        let hub = hub.clone();
        move || {
            assert!(eventually(|| send_now.is_raised()));
            hub.send(go());
        }
    });
    b_slot.set(b.thread().id());
    let a = thread::spawn({
        let aggregate = aggregate.clone();
        move || aggregate.construct()
    });
    a_slot.set(a.thread().id());
    let deadline = Instant::now() + BOUND;
    let constructed = join_by(a, deadline, "aggregate.construct()");
    join_by(b, deadline, "the drain");

    assert_eq!(constructed, Ok(()));
    assert_eq!(*disposal.lock().unwrap(), Some(Ok(())));
    assert_eq!(aggregate.status(), ConstructionStatus::Disposed);
}

#[test]
fn a_hub_drain_wait_and_an_aggregate_disposal_do_not_deadlock() {
    a_hub_drain_and_an_aggregate_disposal_do_not_deadlock(false);
}

#[test]
fn an_aggregate_disposal_that_waits_first_and_a_hub_publication_do_not_deadlock() {
    a_hub_drain_and_an_aggregate_disposal_do_not_deadlock(true);
}
