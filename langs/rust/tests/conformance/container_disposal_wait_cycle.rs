//! A cross-thread container disposal waits for the container's open membership
//! transaction (ADR-0122), unless that wait would close a wait-for cycle. Then
//! it records the intent, and the transaction owner disposes the container
//! when its transaction ends (ADR-0153, ADR-0167, #1058).

use std::sync::mpsc;
use std::sync::{Arc, Barrier, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use vmx::{
    AggregateVm1, ComponentVm, CompositeVm, ConstructionStatus, GroupVm, Message, MessageHub,
    MessageRecorder, NullDispatcher, VmxError, VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

type Child = ComponentVm<&'static str>;

fn child(name: &'static str, hub: &MessageHub) -> Child {
    Child::with_model(name, name, hub.clone(), NullDispatcher::new())
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

fn disposals(recorder: &MessageRecorder, name: &str) -> usize {
    recorder
        .messages()
        .iter()
        .filter(|message| {
            matches!(message, Message::ConstructionStatusChanged(changed)
                if changed.sender_name == name && changed.status == ConstructionStatus::Disposed)
        })
        .count()
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

/// Each thread holds one container's transaction (its child's construct hook
/// runs inside the add) and disposes the other container.
fn opposing_disposals_complete<C: Container>() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let x = C::make("x", &hub);
    let z = C::make("z", &hub);
    let a = child("a", &hub);
    let b = child("b", &hub);
    let barrier = Arc::new(Barrier::new(2));
    a.on_construct({
        let (barrier, z) = (barrier.clone(), z.clone());
        move || {
            barrier.wait();
            z.dispose_container()
        }
    });
    b.on_construct({
        let (barrier, x) = (barrier.clone(), x.clone());
        move || {
            barrier.wait();
            x.dispose_container()
        }
    });

    let first = thread::spawn({
        let (x, a) = (x.clone(), a.clone());
        move || x.add_child(a)
    });
    let second = thread::spawn({
        let (z, b) = (z.clone(), b.clone());
        move || z.add_child(b)
    });
    let deadline = Instant::now() + BOUND;
    let first = join_by(first, deadline, "x.add(a)");
    let second = join_by(second, deadline, "z.add(b)");

    assert_eq!(x.container_status(), ConstructionStatus::Disposed);
    assert_eq!(z.container_status(), ConstructionStatus::Disposed);
    // The disposal that would close the cycle defers to its transaction owner.
    // That owner's add has not admitted its child yet, so the add fails and
    // rolls the child back (ADR-0122). The other add completes, and its
    // container's disposal disposes the admitted child once.
    let (rolled_back, admitted) = match (&first, &second) {
        (Err(VmxError::Disposed), Ok(())) => ((&a, "a"), (&b, "b")),
        (Ok(()), Err(VmxError::Disposed)) => ((&b, "b"), (&a, "a")),
        outcomes => panic!("expected exactly one deferred add, got {outcomes:?}"),
    };
    assert_eq!(rolled_back.0.status(), ConstructionStatus::Destructed);
    assert_eq!(rolled_back.0.parent_id(), None);
    assert_eq!(disposals(&recorder, rolled_back.1), 0);
    assert_eq!(admitted.0.status(), ConstructionStatus::Disposed);
    assert_eq!(disposals(&recorder, admitted.1), 1);
}

/// No wait cycle: `z.dispose()` waits until `z`'s transaction on the other
/// thread ends, then disposes `z`.
fn one_sided_disposal_still_waits<C: Container>() {
    let hub = MessageHub::new();
    let x = C::make("x", &hub);
    let z = C::make("z", &hub);
    let a = child("a", &hub);
    let b = child("b", &hub);
    let order = Arc::new(Mutex::new(Vec::new()));
    let (entered, entered_rx) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    b.on_construct({
        let order = order.clone();
        move || {
            entered.send(()).unwrap();
            // A dropped sender also releases the hook, so a failed
            // assertion below cannot leave this thread blocked.
            let _ = release_rx.recv_timeout(2 * BOUND);
            order.lock().unwrap().push("z transaction ends");
            Ok(())
        }
    });
    a.on_construct({
        let (order, z) = (order.clone(), z.clone());
        move || {
            z.dispose_container()?;
            let status = z.container_status();
            order.lock().unwrap().push("z.dispose() returned");
            assert_eq!(status, ConstructionStatus::Disposed);
            Ok(())
        }
    });

    let holder = thread::spawn({
        let z = z.clone();
        move || z.add_child(b)
    });
    entered_rx.recv_timeout(BOUND).unwrap();
    let disposer = thread::spawn({
        let x = x.clone();
        move || x.add_child(a)
    });
    let disposer_thread = disposer.thread().id();
    let deadline = Instant::now() + BOUND;
    while !vmx::container_wait_registered_for_testing(disposer_thread) {
        assert!(
            !disposer.is_finished(),
            "z.dispose() returned without waiting"
        );
        assert!(Instant::now() < deadline, "z.dispose() never waited");
        thread::sleep(Duration::from_millis(1));
    }
    release.send(()).unwrap();
    let deadline = Instant::now() + BOUND;

    assert_eq!(join_by(holder, deadline, "z.add(b)"), Ok(()));
    assert_eq!(join_by(disposer, deadline, "x.add(a)"), Ok(()));
    assert_eq!(
        *order.lock().unwrap(),
        vec!["z transaction ends", "z.dispose() returned"]
    );
    assert_eq!(z.container_status(), ConstructionStatus::Disposed);
    assert_eq!(x.container_status(), ConstructionStatus::Constructed);
}

#[test]
fn opposing_composite_disposals_inside_transactions_complete() {
    opposing_disposals_complete::<CompositeVm<Child>>();
}

#[test]
fn opposing_group_disposals_inside_transactions_complete() {
    opposing_disposals_complete::<GroupVm<Child>>();
}

#[test]
fn one_sided_composite_disposal_still_waits_for_the_transaction() {
    one_sided_disposal_still_waits::<CompositeVm<Child>>();
}

#[test]
fn one_sided_group_disposal_still_waits_for_the_transaction() {
    one_sided_disposal_still_waits::<GroupVm<Child>>();
}

/// A fixed aggregate's construct holds its membership transaction while each
/// component's construct hook runs.
#[test]
fn opposing_aggregate_disposals_inside_construct_transactions_complete() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let a = child("a", &hub);
    let b = child("b", &hub);
    let x = AggregateVm1::with_services("x", hub.clone(), NullDispatcher::new(), a.clone());
    let z = AggregateVm1::with_services("z", hub.clone(), NullDispatcher::new(), b.clone());
    let barrier = Arc::new(Barrier::new(2));
    a.on_construct({
        let (barrier, z) = (barrier.clone(), z.clone());
        move || {
            barrier.wait();
            z.dispose()
        }
    });
    b.on_construct({
        let (barrier, x) = (barrier.clone(), x.clone());
        move || {
            barrier.wait();
            x.dispose()
        }
    });

    let first = thread::spawn({
        let x = x.clone();
        move || x.construct()
    });
    let second = thread::spawn({
        let z = z.clone();
        move || z.construct()
    });
    let deadline = Instant::now() + BOUND;
    let first = join_by(first, deadline, "x.construct()");
    let second = join_by(second, deadline, "z.construct()");

    assert_eq!(first, Ok(()));
    assert_eq!(second, Ok(()));
    assert_eq!(x.status(), ConstructionStatus::Disposed);
    assert_eq!(z.status(), ConstructionStatus::Disposed);
    assert_eq!(disposals(&recorder, "a"), 1);
    assert_eq!(disposals(&recorder, "b"), 1);
}
