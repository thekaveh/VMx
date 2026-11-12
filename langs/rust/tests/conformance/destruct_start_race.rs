//! One starter for each child destruct (spec/02 §6, ADR-0218 rule 6, ADR-0227).
//! A container destruct walk reads a child as `Constructed` and then starts the
//! child's destruct. Another thread can start that destruct between the read
//! and the walk's call. The call then fails as an invalid transition from
//! `Destructing`. The walk joins the destruct instead of failing, so the
//! container destruct succeeds. A destruct that finishes before the walk checks
//! the refusal is joined too. A joined destruct that is still in flight when
//! the walk registers its join, and then fails, returns `Ok` from the call. The
//! walk rolls the container back to `Constructed` and reports the failure on
//! `background_errors()` (ADR-0227 §3). A failure the walk learns of before its
//! call returns is returned from the call as the settle error. A refusal from
//! `Disposed`, the inline dispose cascade, is not joined (LIFE-021). The
//! `ComponentVm` leaf walk follows the same rules. A failed settle check that
//! the walk's action outlives, and a dispose during a joined destruct, have
//! tests of their own (ADR-0227 §2.8, §4).

use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, ThreadId};
use std::time::{Duration, Instant};
use vmx::{
    AggregateVm1, AggregateVm2, AggregateVm3, AggregateVm4, AggregateVm5, AggregateVm6,
    ComponentVm, CompositeVm, ConstructionStatus, GroupVm, LifecycleSettleCallback, MessageHub,
    NullDispatcher, ParentHandle, VmNode, VmxError, VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

/// Where an armed thread pauses inside the child's `destruct()`.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Point {
    /// Before the call, so the walk has already read the child's status.
    Entry,
    /// After a refused call, before its error returns to the walk.
    Refusal,
    /// Before the walk registers to wait on the child's settle. The walk has
    /// read the child in flight, so the child can settle before the wait is
    /// registered.
    Register,
    /// After the walk registers to wait on the child's settle. The walk is
    /// then parked on a join that is still in flight.
    Settle,
    /// In the leaf walk's action, after its step registered the join and
    /// before the action ends, so the action is still running.
    Hold,
    /// In the settle check of a destruct another thread started, after its
    /// child settled. The check reads the child's status at this point.
    Check,
    /// On a disposing thread, before it disposes the child whose destruct is
    /// in flight.
    Dispose,
}

/// The point, the entry report and the release of one armed pause.
type Pause = (Point, Sender<()>, Receiver<()>);

/// A `ComponentVm` whose first destruct hook holds the child in
/// `Destructing` until released. Its `destruct()` also pauses an armed thread
/// at a chosen point.
#[derive(Clone)]
struct Gated {
    vm: ComponentVm<i32>,
    destructs: Arc<AtomicUsize>,
    pauses: Arc<Mutex<HashMap<ThreadId, Vec<Pause>>>>,
}

impl Gated {
    /// A child whose first destruct reports entry and waits for the returned
    /// release. Its destruct stays in flight meanwhile.
    fn new() -> (Self, Receiver<()>, Sender<()>) {
        Self::holding(false)
    }

    /// As [`Gated::new`], but the held destruct fails once it is released.
    fn failing() -> (Self, Receiver<()>, Sender<()>) {
        Self::holding(true)
    }

    fn holding(fails: bool) -> (Self, Receiver<()>, Sender<()>) {
        let vm = ComponentVm::with_model("child", 1, MessageHub::new(), NullDispatcher::new());
        let destructs = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&destructs);
        let (entered_tx, entered) = mpsc::channel();
        let (release, release_rx) = mpsc::channel::<()>();
        vm.on_destruct(move || {
            if counter.fetch_add(1, Ordering::SeqCst) == 0 {
                let _ = entered_tx.send(());
                let _ = release_rx.recv_timeout(BOUND);
                if fails {
                    return Err(VmxError::Other("destruct hook failed".to_string()));
                }
            }
            Ok(())
        });
        let gated = Self {
            vm,
            destructs,
            pauses: Arc::default(),
        };
        (gated, entered, release)
    }

    /// Arms the calling thread to pause once at `point` of its next
    /// `destruct()`. Returns the entry report and the release of that pause.
    fn arm(&self, point: Point) -> (Receiver<()>, Sender<()>) {
        let (reached, reached_rx) = mpsc::channel();
        let (release_tx, release) = mpsc::channel();
        self.pauses
            .lock()
            .unwrap()
            .entry(thread::current().id())
            .or_default()
            .push((point, reached, release));
        (reached_rx, release_tx)
    }

    /// Pauses the calling thread at `point` when it is armed there.
    fn pause(&self, point: Point) {
        let id = thread::current().id();
        let armed = {
            let mut pauses = self.pauses.lock().unwrap();
            pauses.get_mut(&id).and_then(|armed| {
                let index = armed.iter().position(|(at, _, _)| *at == point)?;
                Some(armed.remove(index))
            })
        };
        if let Some((_, reached, release)) = armed {
            let _ = reached.send(());
            let _ = release.recv_timeout(BOUND);
        }
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
        VmNode::construct(&self.vm)
    }
    fn destruct(&self) -> VmxResult<()> {
        self.pause(Point::Entry);
        let result = VmNode::destruct(&self.vm);
        if result.is_err() {
            self.pause(Point::Refusal);
        }
        result
    }
    fn dispose(&self) -> VmxResult<()> {
        self.pause(Point::Dispose);
        VmNode::dispose(&self.vm)
    }
    fn status(&self) -> ConstructionStatus {
        self.pause(Point::Check);
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
        self.pause(Point::Register);
        let registered = self.vm.when_lifecycle_settled(callback);
        self.pause(Point::Settle);
        registered
    }
}

/// The container surface these scenarios use. The child is in the first slot.
trait Container: Clone + Send + Sync + 'static {
    /// A container that holds `child` and is not yet constructed.
    fn holding(child: Gated) -> Self;
    fn construct(&self) -> VmxResult<()>;
    fn destruct(&self) -> VmxResult<()>;
    fn dispose(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    fn background_errors(&self) -> vmx::LifecycleErrorStream;
}

impl Container for CompositeVm<Gated> {
    fn holding(child: Gated) -> Self {
        let vm = CompositeVm::new("composite");
        vm.add(child).expect("the child is added");
        vm
    }
    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }
    fn destruct(&self) -> VmxResult<()> {
        CompositeVm::destruct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        CompositeVm::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }
    fn background_errors(&self) -> vmx::LifecycleErrorStream {
        CompositeVm::background_errors(self)
    }
}

impl Container for GroupVm<Gated> {
    fn holding(child: Gated) -> Self {
        let vm = GroupVm::new("group");
        vm.add(child).expect("the child is added");
        vm
    }
    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }
    fn destruct(&self) -> VmxResult<()> {
        GroupVm::destruct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        GroupVm::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
    }
    fn background_errors(&self) -> vmx::LifecycleErrorStream {
        GroupVm::background_errors(self)
    }
}

impl Container for AggregateVm1<Gated> {
    fn holding(child: Gated) -> Self {
        AggregateVm1::new("aggregate", child)
    }
    fn construct(&self) -> VmxResult<()> {
        AggregateVm1::construct(self)
    }
    fn destruct(&self) -> VmxResult<()> {
        AggregateVm1::destruct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        AggregateVm1::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        AggregateVm1::status(self)
    }
    fn background_errors(&self) -> vmx::LifecycleErrorStream {
        AggregateVm1::background_errors(self)
    }
}

/// Implements `Container` for a fixed-arity aggregate. The other slots hold
/// plain children whose destruct never waits, because their gates are dropped.
macro_rules! aggregate_container {
    ($ty:ident, $($extra:ident),+) => {
        impl Container for $ty<Gated $(, aggregate_container!(@ty $extra))+> {
            fn holding(child: Gated) -> Self {
                $ty::new("aggregate", child $(, aggregate_container!(@child $extra))+)
            }
            fn construct(&self) -> VmxResult<()> {
                $ty::construct(self)
            }
            fn destruct(&self) -> VmxResult<()> {
                $ty::destruct(self)
            }
            fn dispose(&self) -> VmxResult<()> {
                $ty::dispose(self)
            }
            fn status(&self) -> ConstructionStatus {
                $ty::status(self)
            }
            fn background_errors(&self) -> vmx::LifecycleErrorStream {
                $ty::background_errors(self)
            }
        }
    };
    (@ty $_extra:ident) => { Gated };
    (@child $_extra:ident) => { Gated::new().0 };
}

aggregate_container!(AggregateVm2, second);
aggregate_container!(AggregateVm3, second, third);
aggregate_container!(AggregateVm4, second, third, fourth);
aggregate_container!(AggregateVm5, second, third, fourth, fifth);
aggregate_container!(AggregateVm6, second, third, fourth, fifth, sixth);

/// A `ComponentVm` leaf that walks its one child through `ChildTransitions` in
/// its construct and destruct hooks. The leaf walk is the consumer surface of
/// the shared helper (ADR-0227 §2).
#[derive(Clone)]
struct Leaf {
    vm: ComponentVm<()>,
    child: Gated,
}

impl Container for Leaf {
    fn holding(child: Gated) -> Self {
        let vm = ComponentVm::with_model("leaf", (), MessageHub::new(), NullDispatcher::new());
        Self { vm, child }
    }
    fn construct(&self) -> VmxResult<()> {
        let child = self.child.clone();
        self.vm
            .construct_with_children(move |walk| walk.transition(&child))
    }
    fn destruct(&self) -> VmxResult<()> {
        let child = self.child.clone();
        self.vm.destruct_with_children(move |walk| {
            walk.transition(&child)?;
            // Still inside the walk's action. A pause here, once the step
            // has registered its join, keeps the action running (Hold).
            child.pause(Point::Hold);
            Ok(())
        })
    }
    fn dispose(&self) -> VmxResult<()> {
        self.vm.dispose()
    }
    fn status(&self) -> ConstructionStatus {
        self.vm.status()
    }
    fn background_errors(&self) -> vmx::LifecycleErrorStream {
        self.vm.background_errors()
    }
}

fn recv(receiver: &Receiver<()>, what: &str) {
    receiver
        .recv_timeout(BOUND)
        .unwrap_or_else(|_| panic!("{what} within {BOUND:?}"));
}

/// Builds `C` around `child` and constructs it, so the child is `Constructed`.
fn built<C: Container>(child: &Gated) -> C {
    let container = C::holding(child.clone());
    container.construct().expect("the container constructs");
    assert_eq!(child.status(), ConstructionStatus::Constructed);
    container
}

/// Starts `child`'s destruct on a thread of its own, the other starter.
fn start_other_destruct(child: &Gated) -> Receiver<VmxResult<()>> {
    let (done_tx, done) = mpsc::channel();
    let other = child.clone();
    thread::spawn(move || {
        let _ = done_tx.send(VmNode::destruct(&other));
    });
    done
}

/// As [`start_other_destruct`], and the other starter's thread is armed to
/// pause at the child's status read in the settle check of its own destruct.
/// Returns the destruct's result, the pause report and the release of the pause.
fn start_other_destruct_held_in_check(
    child: &Gated,
) -> (Receiver<VmxResult<()>>, Receiver<()>, Sender<()>) {
    let (done_tx, done) = mpsc::channel();
    let (armed_tx, armed) = mpsc::channel();
    let other = child.clone();
    thread::spawn(move || {
        let _ = armed_tx.send(other.arm(Point::Check));
        let _ = done_tx.send(VmNode::destruct(&other));
    });
    let (reached, release) = armed.recv_timeout(BOUND).expect("the other starter arms");
    (done, reached, release)
}

fn ends_destructed<C: Container>(container: &C, child: &Gated) {
    // A joined walk can finish on its own dispatcher after the other destruct
    // returns, so the container is awaited, up to the bound.
    let deadline = Instant::now() + BOUND;
    while container.status() != ConstructionStatus::Destructed && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(container.status(), ConstructionStatus::Destructed);
    assert_eq!(child.status(), ConstructionStatus::Destructed);
    assert_eq!(
        child.destructs.load(Ordering::SeqCst),
        1,
        "the child destructs once"
    );
}

/// The walk reads the child `Constructed` and pauses before its call. Another
/// thread then starts the child's destruct, and the destruct is still in flight
/// when the walk's call is refused. The walk joins that destruct.
fn walk_joins_a_destruct_in_flight_after_its_read<C: Container>() {
    let (child, other_entered, release_other) = Gated::new();
    let container = built::<C>(&child);

    let (armed_tx, armed) = mpsc::channel();
    let (walk_tx, walk) = mpsc::channel();
    {
        let (container, child) = (container.clone(), child.clone());
        thread::spawn(move || {
            let _ = armed_tx.send((
                child.arm(Point::Entry),
                child.arm(Point::Refusal),
                child.arm(Point::Settle),
            ));
            let _ = walk_tx.send(container.destruct());
        });
    }
    let ((read, release_read), (refused, release_refused), (joined, release_joined)) =
        armed.recv_timeout(BOUND).expect("the walk arms");
    recv(&read, "the walk pauses before its destruct call");
    assert_eq!(child.status(), ConstructionStatus::Constructed);

    let other = start_other_destruct(&child);
    recv(&other_entered, "the other starter's destruct is in flight");
    let _ = release_read.send(());
    // The walk's call is refused while the other destruct is held.
    recv(&refused, "the walk's call is refused");
    let _ = release_refused.send(());
    // The walk has checked the status and registered its join while the
    // other destruct is still held, so the join is in flight.
    recv(&joined, "the walk joins the destruct in flight");
    let _ = release_joined.send(());
    let _ = release_other.send(());

    assert_eq!(
        other
            .recv_timeout(BOUND)
            .expect("the other destruct returns"),
        Ok(())
    );
    assert_eq!(
        walk.recv_timeout(BOUND)
            .expect("the container destruct returns"),
        Ok(()),
        "the walk joins the destruct in flight instead of failing"
    );
    ends_destructed(&container, &child);
}

/// The walk's call is refused while another destruct is in flight. That
/// destruct finishes before the walk checks the refusal. The walk joins the
/// finished destruct and does not fail.
fn walk_joins_a_destruct_that_finished_after_its_refusal<C: Container>() {
    let (child, other_entered, release_other) = Gated::new();
    let container = built::<C>(&child);

    let other = start_other_destruct(&child);
    recv(&other_entered, "the other starter's destruct is in flight");

    let (armed_tx, armed) = mpsc::channel();
    let (walk_tx, walk) = mpsc::channel();
    {
        let (container, child) = (container.clone(), child.clone());
        thread::spawn(move || {
            let _ = armed_tx.send(child.arm(Point::Refusal));
            let _ = walk_tx.send(container.destruct());
        });
    }
    let (walk_reached, release_walk) = armed.recv_timeout(BOUND).expect("the walk arms");
    recv(&walk_reached, "the walk's call is refused");

    let _ = release_other.send(());
    assert_eq!(
        other
            .recv_timeout(BOUND)
            .expect("the other destruct returns"),
        Ok(())
    );
    assert_eq!(child.status(), ConstructionStatus::Destructed);
    let _ = release_walk.send(());

    assert_eq!(
        walk.recv_timeout(BOUND)
            .expect("the container destruct returns"),
        Ok(()),
        "the walk joins the finished destruct instead of failing"
    );
    ends_destructed(&container, &child);
}

/// Collects the errors one container reports on `background_errors()`.
fn collect_errors(
    stream: vmx::LifecycleErrorStream,
) -> (mpsc::Receiver<VmxError>, vmx::ValueSubscription) {
    let (send, receive) = mpsc::channel();
    let subscription = stream.subscribe(move |error| {
        let _ = send.send(error);
    });
    (receive, subscription)
}

/// The walk reads the child `Constructed` and pauses before its call. Another
/// thread starts the child's destruct, and that destruct fails once released.
/// The walk joins it. The walk returns `Ok` and the container rolls back to
/// `Constructed`. The failure reaches `background_errors()`, as a background
/// child's failure does (ADR-0227 §3). The walk did not start the failing
/// destruct, so its call has no synchronous error to return.
fn walk_joins_a_destruct_that_fails_and_reports_it_in_background<C: Container>() {
    let (child, other_entered, release_other) = Gated::failing();
    let container = built::<C>(&child);
    let (errors, _subscription) = collect_errors(container.background_errors());

    let (armed_tx, armed) = mpsc::channel();
    let (walk_tx, walk) = mpsc::channel();
    {
        let (container, child) = (container.clone(), child.clone());
        thread::spawn(move || {
            let _ = armed_tx.send((
                child.arm(Point::Entry),
                child.arm(Point::Refusal),
                child.arm(Point::Settle),
            ));
            let _ = walk_tx.send(container.destruct());
        });
    }
    let ((read, release_read), (refused, release_refused), (joined, release_joined)) =
        armed.recv_timeout(BOUND).expect("the walk arms");
    recv(&read, "the walk pauses before its destruct call");

    let other = start_other_destruct(&child);
    recv(&other_entered, "the other starter's destruct is in flight");
    let _ = release_read.send(());
    recv(&refused, "the walk's call is refused");
    let _ = release_refused.send(());
    // The walk has registered its join while the other destruct is held, so
    // the join is in flight when the destruct fails.
    recv(&joined, "the walk joins the destruct in flight");
    let _ = release_joined.send(());
    let _ = release_other.send(());

    assert_eq!(
        other
            .recv_timeout(BOUND)
            .expect("the other destruct returns"),
        Err(VmxError::Other("destruct hook failed".to_string())),
        "the other starter's destruct fails"
    );
    assert_eq!(
        walk.recv_timeout(BOUND)
            .expect("the container destruct returns"),
        Ok(()),
        "the walk joins the failed destruct and returns Ok"
    );
    // The rollback is published before its report, and a leaf walk resumes on
    // its own dispatcher. So the report is the sync point: the container is
    // Constructed once it arrives. The report names the child's settle, not
    // the hook's own error.
    match errors
        .recv_timeout(BOUND)
        .expect("the failure is reported on background_errors()")
    {
        VmxError::Other(message) => assert!(
            message.ends_with("settled at Constructed instead of Destructed"),
            "the container reports the child's settle: {message}"
        ),
        other => panic!("unexpected background error: {other:?}"),
    }
    assert_eq!(child.status(), ConstructionStatus::Constructed);
    assert_eq!(container.status(), ConstructionStatus::Constructed);
}

/// The walk reads the child `Constructed` and pauses before its call. Another
/// thread starts the child's destruct, and that destruct is held in flight
/// when the walk's call is refused. The walk joins it, then pauses before it
/// registers its wait. The destruct fails and the child settles `Constructed`
/// before the registration. The walk learns of the failure at once, so the
/// call returns the settle error as `Err` (ADR-0227 §3).
fn walk_joins_a_destruct_that_fails_before_its_wait_registers<C: Container>() {
    let (child, other_entered, release_other) = Gated::failing();
    let container = built::<C>(&child);

    let (armed_tx, armed) = mpsc::channel();
    let (walk_tx, walk) = mpsc::channel();
    {
        let (container, child) = (container.clone(), child.clone());
        thread::spawn(move || {
            let _ = armed_tx.send((
                child.arm(Point::Entry),
                child.arm(Point::Refusal),
                child.arm(Point::Register),
            ));
            let _ = walk_tx.send(container.destruct());
        });
    }
    let ((read, release_read), (refused, release_refused), (registering, release_registering)) =
        armed.recv_timeout(BOUND).expect("the walk arms");
    recv(&read, "the walk pauses before its destruct call");

    let other = start_other_destruct(&child);
    recv(&other_entered, "the other starter's destruct is in flight");
    let _ = release_read.send(());
    recv(&refused, "the walk's call is refused");
    let _ = release_refused.send(());
    recv(
        &registering,
        "the walk joins the destruct and pauses before its wait registers",
    );
    let _ = release_other.send(());
    assert_eq!(
        other
            .recv_timeout(BOUND)
            .expect("the other destruct returns"),
        Err(VmxError::Other("destruct hook failed".to_string())),
        "the other starter's destruct fails"
    );
    assert_eq!(child.status(), ConstructionStatus::Constructed);
    let _ = release_registering.send(());

    match walk
        .recv_timeout(BOUND)
        .expect("the container destruct returns")
    {
        Err(VmxError::Other(message)) => assert!(
            message.ends_with("settled at Constructed instead of Destructed"),
            "the call returns the child's settle error: {message}"
        ),
        other => panic!("the call returns the settle error, not {other:?}"),
    }
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    assert_eq!(child.status(), ConstructionStatus::Constructed);
}

#[test]
fn composite_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<CompositeVm<Gated>>();
}

#[test]
fn group_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<GroupVm<Gated>>();
}

#[test]
fn aggregate1_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<AggregateVm1<Gated>>();
}

#[test]
fn aggregate2_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<AggregateVm2<Gated, Gated>>();
}

#[test]
fn aggregate3_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<AggregateVm3<Gated, Gated, Gated>>();
}

#[test]
fn aggregate4_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<AggregateVm4<Gated, Gated, Gated, Gated>>();
}

#[test]
fn aggregate5_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<AggregateVm5<Gated, Gated, Gated, Gated, Gated>>(
    );
}

#[test]
fn aggregate6_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<
        AggregateVm6<Gated, Gated, Gated, Gated, Gated, Gated>,
    >();
}

#[test]
fn composite_walk_joins_a_destruct_that_finished_after_its_refusal() {
    walk_joins_a_destruct_that_finished_after_its_refusal::<CompositeVm<Gated>>();
}

#[test]
fn group_walk_joins_a_destruct_that_finished_after_its_refusal() {
    walk_joins_a_destruct_that_finished_after_its_refusal::<GroupVm<Gated>>();
}

#[test]
fn aggregate1_walk_joins_a_destruct_that_finished_after_its_refusal() {
    walk_joins_a_destruct_that_finished_after_its_refusal::<AggregateVm1<Gated>>();
}

#[test]
fn aggregate2_walk_joins_a_destruct_that_finished_after_its_refusal() {
    walk_joins_a_destruct_that_finished_after_its_refusal::<AggregateVm2<Gated, Gated>>();
}

#[test]
fn aggregate3_walk_joins_a_destruct_that_finished_after_its_refusal() {
    walk_joins_a_destruct_that_finished_after_its_refusal::<AggregateVm3<Gated, Gated, Gated>>();
}

#[test]
fn aggregate4_walk_joins_a_destruct_that_finished_after_its_refusal() {
    walk_joins_a_destruct_that_finished_after_its_refusal::<AggregateVm4<Gated, Gated, Gated, Gated>>(
    );
}

#[test]
fn aggregate5_walk_joins_a_destruct_that_finished_after_its_refusal() {
    walk_joins_a_destruct_that_finished_after_its_refusal::<
        AggregateVm5<Gated, Gated, Gated, Gated, Gated>,
    >();
}

#[test]
fn aggregate6_walk_joins_a_destruct_that_finished_after_its_refusal() {
    walk_joins_a_destruct_that_finished_after_its_refusal::<
        AggregateVm6<Gated, Gated, Gated, Gated, Gated, Gated>,
    >();
}

#[test]
fn composite_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<CompositeVm<Gated>>();
}

#[test]
fn group_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<GroupVm<Gated>>();
}

#[test]
fn aggregate1_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<AggregateVm1<Gated>>();
}

#[test]
fn aggregate2_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<AggregateVm2<Gated, Gated>>();
}

#[test]
fn aggregate3_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<
        AggregateVm3<Gated, Gated, Gated>,
    >();
}

#[test]
fn aggregate4_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<
        AggregateVm4<Gated, Gated, Gated, Gated>,
    >();
}

#[test]
fn aggregate5_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<
        AggregateVm5<Gated, Gated, Gated, Gated, Gated>,
    >();
}

#[test]
fn aggregate6_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<
        AggregateVm6<Gated, Gated, Gated, Gated, Gated, Gated>,
    >();
}

#[test]
fn composite_walk_joins_a_destruct_that_fails_before_its_wait_registers() {
    walk_joins_a_destruct_that_fails_before_its_wait_registers::<CompositeVm<Gated>>();
}

#[test]
fn group_walk_joins_a_destruct_that_fails_before_its_wait_registers() {
    walk_joins_a_destruct_that_fails_before_its_wait_registers::<GroupVm<Gated>>();
}

#[test]
fn aggregate1_walk_joins_a_destruct_that_fails_before_its_wait_registers() {
    walk_joins_a_destruct_that_fails_before_its_wait_registers::<AggregateVm1<Gated>>();
}

#[test]
fn leaf_walk_joins_a_destruct_that_fails_before_its_wait_registers() {
    walk_joins_a_destruct_that_fails_before_its_wait_registers::<Leaf>();
}

#[test]
fn leaf_walk_joins_a_destruct_in_flight_after_its_read() {
    walk_joins_a_destruct_in_flight_after_its_read::<Leaf>();
}

/// The leaf walk checks the child's status before it calls `destruct()`, so
/// it reaches a refused call only after reading the child `Constructed`. The
/// walk pauses before that call, and another thread starts the child's
/// destruct. The walk's call is refused. The other destruct then finishes
/// before the walk checks the refusal, and the walk joins the finished destruct.
#[test]
fn leaf_walk_joins_a_destruct_that_finished_after_its_refusal() {
    let (child, other_entered, release_other) = Gated::new();
    let leaf = Leaf::holding(child.clone());
    leaf.construct().expect("the leaf constructs");
    assert_eq!(child.status(), ConstructionStatus::Constructed);

    let (armed_tx, armed) = mpsc::channel();
    let (walk_tx, walk) = mpsc::channel();
    {
        let (leaf, child) = (leaf.clone(), child.clone());
        thread::spawn(move || {
            let entry = child.arm(Point::Entry);
            let refusal = child.arm(Point::Refusal);
            let _ = armed_tx.send((entry, refusal));
            let _ = walk_tx.send(leaf.destruct());
        });
    }
    let ((entry_reached, release_entry), (refusal_reached, release_refusal)) =
        armed.recv_timeout(BOUND).expect("the walk arms");
    recv(&entry_reached, "the walk pauses before its destruct call");
    assert_eq!(child.status(), ConstructionStatus::Constructed);

    let other = start_other_destruct(&child);
    recv(&other_entered, "the other starter's destruct is in flight");
    let _ = release_entry.send(());
    recv(&refusal_reached, "the walk's call is refused");

    let _ = release_other.send(());
    assert_eq!(
        other
            .recv_timeout(BOUND)
            .expect("the other destruct returns"),
        Ok(())
    );
    assert_eq!(child.status(), ConstructionStatus::Destructed);
    let _ = release_refusal.send(());

    assert_eq!(
        walk.recv_timeout(BOUND).expect("the leaf destruct returns"),
        Ok(()),
        "the walk joins the finished destruct instead of failing"
    );
    ends_destructed(&leaf, &child);
}

#[test]
fn leaf_walk_joins_a_destruct_that_fails_and_reports_it_in_background() {
    walk_joins_a_destruct_that_fails_and_reports_it_in_background::<Leaf>();
}

/// The leaf walk joins a destruct another thread started, and that destruct
/// fails. The walk's action is held after its step registers the join, so the
/// action is still running when the failure settles the child. The settle
/// check runs on the other thread and is held at its child status read, with
/// the wait still marked. The action then ends during the check. The wait
/// keeps the walk from publishing `Destructed` over the `Constructed` child.
/// The check's failure rolls the leaf back and is reported on
/// `background_errors()` (ADR-0227 §2.8, §3). Without the §2.8 fix the leaf
/// publishes `Destructed` and the failure is lost.
#[test]
fn leaf_walk_action_ending_during_a_failed_settle_check_rolls_back() {
    let (child, other_entered, release_other) = Gated::failing();
    let leaf = built::<Leaf>(&child);
    let (errors, _subscription) = collect_errors(leaf.background_errors());

    let (armed_tx, armed) = mpsc::channel();
    let (walk_tx, walk) = mpsc::channel();
    {
        let (leaf, child) = (leaf.clone(), child.clone());
        thread::spawn(move || {
            let _ = armed_tx.send((
                child.arm(Point::Entry),
                child.arm(Point::Refusal),
                child.arm(Point::Hold),
            ));
            let _ = walk_tx.send(leaf.destruct());
        });
    }
    let ((read, release_read), (refused, release_refused), (held, release_held)) =
        armed.recv_timeout(BOUND).expect("the walk arms");
    recv(&read, "the walk pauses before its destruct call");
    assert_eq!(child.status(), ConstructionStatus::Constructed);

    let (other, check_held, release_check) = start_other_destruct_held_in_check(&child);
    recv(&other_entered, "the other starter's destruct is in flight");
    let _ = release_read.send(());
    recv(&refused, "the walk's call is refused");
    let _ = release_refused.send(());
    recv(&held, "the walk joins the destruct, and its action holds");
    // The failed destruct settles while the walk's action still runs, so the
    // settle check starts on the other thread and is held there.
    let _ = release_other.send(());
    recv(&check_held, "the failed destruct's settle check is held");

    // The walk's action ends while the check is held.
    let _ = release_held.send(());
    assert_eq!(
        walk.recv_timeout(BOUND).expect("the leaf destruct returns"),
        Ok(()),
        "the walk joins the destruct and returns Ok"
    );
    assert_eq!(
        leaf.status(),
        ConstructionStatus::Destructing,
        "the leaf waits for the check, so it does not publish Destructed"
    );

    let _ = release_check.send(());
    assert_eq!(
        other
            .recv_timeout(BOUND)
            .expect("the other destruct returns"),
        Err(VmxError::Other("destruct hook failed".to_string())),
        "the other starter's destruct fails"
    );
    match errors
        .recv_timeout(BOUND)
        .expect("the failed check is reported on background_errors()")
    {
        VmxError::Other(message) => assert!(
            message.ends_with("settled at Constructed instead of Destructed"),
            "the leaf reports the child's settle: {message}"
        ),
        other => panic!("unexpected background error: {other:?}"),
    }
    assert_eq!(leaf.status(), ConstructionStatus::Constructed);
    assert_eq!(child.status(), ConstructionStatus::Constructed);
}

/// Disposes `container` while a destruct it joined is in flight. The walk
/// joins the destruct and returns `Ok`. A thread then disposes the container,
/// and its dispose is held at the child's dispose, after the container has
/// abandoned its settle wait. The in-flight destruct then completes. The
/// container ends `Disposed`, the child ends `Disposed`, and no rollback is
/// reported, so the abandoned join does not publish a terminal status.
fn dispose_during_a_joined_destruct<C: Container>() {
    let (child, other_entered, release_other) = Gated::new();
    let container = built::<C>(&child);
    let (errors, _subscription) = collect_errors(container.background_errors());

    let (armed_tx, armed) = mpsc::channel();
    let (walk_tx, walk) = mpsc::channel();
    {
        let (container, child) = (container.clone(), child.clone());
        thread::spawn(move || {
            let _ = armed_tx.send((
                child.arm(Point::Entry),
                child.arm(Point::Refusal),
                child.arm(Point::Settle),
            ));
            let _ = walk_tx.send(container.destruct());
        });
    }
    let ((read, release_read), (refused, release_refused), (joined, release_joined)) =
        armed.recv_timeout(BOUND).expect("the walk arms");
    recv(&read, "the walk pauses before its destruct call");

    let other = start_other_destruct(&child);
    recv(&other_entered, "the other starter's destruct is in flight");
    let _ = release_read.send(());
    recv(&refused, "the walk's call is refused");
    let _ = release_refused.send(());
    recv(&joined, "the walk joins the destruct in flight");
    let _ = release_joined.send(());
    assert_eq!(
        walk.recv_timeout(BOUND)
            .expect("the container destruct returns"),
        Ok(()),
        "the walk joins the destruct in flight instead of failing"
    );

    // The dispose thread pauses before it disposes the child, which is still
    // Destructing. The container has abandoned its wait by then.
    let (disposed_tx, disposed) = mpsc::channel();
    let (armed_tx, armed) = mpsc::channel();
    {
        let (container, child) = (container.clone(), child.clone());
        thread::spawn(move || {
            let _ = armed_tx.send(child.arm(Point::Dispose));
            let _ = disposed_tx.send(container.dispose());
        });
    }
    let (dispose_reached, release_dispose) = armed.recv_timeout(BOUND).expect("the dispose arms");
    recv(
        &dispose_reached,
        "the dispose reaches the child while its destruct is in flight",
    );
    assert_eq!(child.status(), ConstructionStatus::Destructing);
    let _ = release_dispose.send(());
    let _ = release_other.send(());

    assert_eq!(
        other
            .recv_timeout(BOUND)
            .expect("the other destruct returns"),
        Ok(())
    );
    assert_eq!(
        disposed
            .recv_timeout(BOUND)
            .expect("the container dispose returns"),
        Ok(())
    );
    assert_eq!(container.status(), ConstructionStatus::Disposed);
    assert_eq!(child.status(), ConstructionStatus::Disposed);
    assert_eq!(
        child.destructs.load(Ordering::SeqCst),
        1,
        "the child destructs once"
    );
    assert!(
        errors.try_recv().is_err(),
        "the abandoned join reports no rollback after the container is disposed"
    );
}

#[test]
fn composite_dispose_during_a_joined_destruct_ends_disposed() {
    dispose_during_a_joined_destruct::<CompositeVm<Gated>>();
}

#[test]
fn group_dispose_during_a_joined_destruct_ends_disposed() {
    dispose_during_a_joined_destruct::<GroupVm<Gated>>();
}

#[test]
fn aggregate1_dispose_during_a_joined_destruct_ends_disposed() {
    dispose_during_a_joined_destruct::<AggregateVm1<Gated>>();
}

/// A child composite that holds one grandchild. The grandchild's dispose hook
/// runs the walk under test, so the walk reaches the child while the child is
/// in its inline dispose cascade (spec/02 §7.2).
fn cascade_child() -> (CompositeVm<ComponentVm<i32>>, ComponentVm<i32>) {
    let grandchild: ComponentVm<i32> =
        ComponentVm::with_model("grandchild", 1, MessageHub::new(), NullDispatcher::new());
    let child = CompositeVm::new("child");
    child
        .add(grandchild.clone())
        .expect("the grandchild is added");
    (child, grandchild)
}

/// Disposes `child` and runs `walk` from the grandchild's dispose hook, so
/// `walk` runs during the child's cascade. Returns what `walk` returned. The
/// child reads `Destructed` during the cascade and refuses a destruct from
/// `Disposed`, a refusal the walk must not join (LIFE-021).
fn walk_during_cascade(
    child: &CompositeVm<ComponentVm<i32>>,
    grandchild: &ComponentVm<i32>,
    walk: impl Fn() -> VmxResult<()> + Send + 'static,
) -> VmxResult<()> {
    child.destruct().expect("the child destructs first");
    let (result_tx, result) = mpsc::channel();
    grandchild.on_dispose(move || {
        let _ = result_tx.send(walk());
        Ok(())
    });
    child.dispose().expect("the child disposes");
    result
        .recv_timeout(BOUND)
        .expect("the grandchild's dispose ran the walk")
}

#[test]
fn composite_destruct_refuses_a_child_in_its_inline_dispose_cascade() {
    let (child, grandchild) = cascade_child();
    let outer = CompositeVm::new("outer");
    outer.add(child.clone()).expect("the child is added");
    outer.construct().expect("the outer constructs");

    let walked = outer.clone();
    let walk = walk_during_cascade(&child, &grandchild, move || walked.destruct());
    assert_eq!(
        walk,
        Err(VmxError::InvalidLifecycleTransition {
            from: ConstructionStatus::Disposed,
            operation: "destruct",
        }),
        "the cascade refusal stays an error and is not joined"
    );
    assert_eq!(outer.status(), ConstructionStatus::Constructed);
    assert_eq!(child.status(), ConstructionStatus::Disposed);
}

#[test]
fn group_destruct_refuses_a_child_in_its_inline_dispose_cascade() {
    let (child, grandchild) = cascade_child();
    let outer = GroupVm::new("outer");
    outer.add(child.clone()).expect("the child is added");
    outer.construct().expect("the outer constructs");

    let walked = outer.clone();
    let walk = walk_during_cascade(&child, &grandchild, move || walked.destruct());
    assert_eq!(
        walk,
        Err(VmxError::InvalidLifecycleTransition {
            from: ConstructionStatus::Disposed,
            operation: "destruct",
        }),
        "the cascade refusal stays an error and is not joined"
    );
    assert_eq!(outer.status(), ConstructionStatus::Constructed);
    assert_eq!(child.status(), ConstructionStatus::Disposed);
}
