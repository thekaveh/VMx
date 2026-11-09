//! #1289 — `CompositeVm`, `GroupVm`, `ModeledCompositeVm` and `AggregateVm1`
//! to `AggregateVm6` register members for depth-first disposal with
//! `own_member` (spec/02 §7.1, ADR-0162). A container disposes its children
//! and then its members, before it publishes `Disposed`; during a foreign
//! dispose it publishes `Disposed` first and disposes both after the hook
//! returns (ADR-0179).

use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use vmx::{
    AggregateVm1, AggregateVm2, AggregateVm3, AggregateVm4, AggregateVm5, AggregateVm6,
    ComponentVm, CompositeVm, ConstructionStatus, GroupVm, Message, MessageHub, MessageRecorder,
    ModeledCompositeVm, NullDispatcher, VmxError, VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

fn vm(name: &str, hub: &MessageHub) -> ComponentVm {
    ComponentVm::with_services(name, hub.clone(), NullDispatcher::new())
}

fn disposed_order(recorder: &MessageRecorder) -> Vec<String> {
    recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change)
                if change.status == ConstructionStatus::Disposed =>
            {
                Some(change.sender_name)
            }
            _ => None,
        })
        .collect()
}

#[test]
fn every_container_rejects_itself_as_a_member() {
    let hub = MessageHub::new();
    let composite = CompositeVm::<ComponentVm>::new("composite");
    assert_eq!(
        composite.own_member(&composite),
        Err(VmxError::OwnershipCycle)
    );
    let group = GroupVm::<ComponentVm>::new("group");
    assert_eq!(group.own_member(&group), Err(VmxError::OwnershipCycle));
    let modeled = ModeledCompositeVm::<u8, ComponentVm>::new(
        "modeled",
        MessageHub::new(),
        NullDispatcher::new(),
        Vec::new,
        |_| ComponentVm::new("unused"),
    );
    assert_eq!(modeled.own_member(&modeled), Err(VmxError::OwnershipCycle));

    let a1 = AggregateVm1::new("a1", vm("1", &hub));
    assert_eq!(a1.own_member(&a1), Err(VmxError::OwnershipCycle));
    let a2 = AggregateVm2::new("a2", vm("1", &hub), vm("2", &hub));
    assert_eq!(a2.own_member(&a2), Err(VmxError::OwnershipCycle));
    let a3 = AggregateVm3::new("a3", vm("1", &hub), vm("2", &hub), vm("3", &hub));
    assert_eq!(a3.own_member(&a3), Err(VmxError::OwnershipCycle));
    let a4 = AggregateVm4::new(
        "a4",
        vm("1", &hub),
        vm("2", &hub),
        vm("3", &hub),
        vm("4", &hub),
    );
    assert_eq!(a4.own_member(&a4), Err(VmxError::OwnershipCycle));
    let a5 = AggregateVm5::new(
        "a5",
        vm("1", &hub),
        vm("2", &hub),
        vm("3", &hub),
        vm("4", &hub),
        vm("5", &hub),
    );
    assert_eq!(a5.own_member(&a5), Err(VmxError::OwnershipCycle));
    let a6 = AggregateVm6::new(
        "a6",
        vm("1", &hub),
        vm("2", &hub),
        vm("3", &hub),
        vm("4", &hub),
        vm("5", &hub),
        vm("6", &hub),
    );
    assert_eq!(a6.own_member(&a6), Err(VmxError::OwnershipCycle));
}

/// The containers under test, each with one child.
trait Container: Clone + Send + Sync + 'static {
    fn make(hub: &MessageHub, child: ComponentVm) -> Self;
    fn own_member(&self, member: &ComponentVm) -> VmxResult<()>;
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static);
    fn construct(&self) -> VmxResult<()>;
    fn dispose(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
}

impl Container for CompositeVm<ComponentVm> {
    fn make(hub: &MessageHub, child: ComponentVm) -> Self {
        let composite = CompositeVm::with_services("container", hub.clone(), NullDispatcher::new());
        composite.add(child).unwrap();
        composite
    }
    fn own_member(&self, member: &ComponentVm) -> VmxResult<()> {
        CompositeVm::own_member(self, member)
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        CompositeVm::on_construct(self, hook);
    }
    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        CompositeVm::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }
}

impl Container for GroupVm<ComponentVm> {
    fn make(hub: &MessageHub, child: ComponentVm) -> Self {
        let group = GroupVm::with_services("container", hub.clone(), NullDispatcher::new());
        group.add(child).unwrap();
        group
    }
    fn own_member(&self, member: &ComponentVm) -> VmxResult<()> {
        GroupVm::own_member(self, member)
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        GroupVm::on_construct(self, hook);
    }
    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        GroupVm::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
    }
}

impl Container for AggregateVm1<ComponentVm> {
    fn make(hub: &MessageHub, child: ComponentVm) -> Self {
        AggregateVm1::with_services("container", hub.clone(), NullDispatcher::new(), child)
    }
    fn own_member(&self, member: &ComponentVm) -> VmxResult<()> {
        AggregateVm1::own_member(self, member)
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        AggregateVm1::on_construct(self, hook);
    }
    fn construct(&self) -> VmxResult<()> {
        AggregateVm1::construct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        AggregateVm1::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        AggregateVm1::status(self)
    }
}

/// With no hook running, the child and then the member reach `Disposed`
/// before the container publishes `Disposed` (ADR-0179 rule 1).
fn disposes_children_then_members<C: Container>() {
    let hub = MessageHub::new();
    let child = vm("child", &hub);
    let member = vm("member", &hub);
    let container = C::make(&hub, child.clone());
    container.own_member(&member).unwrap();
    container.construct().unwrap();

    let recorder = hub.record(256);
    container.dispose().unwrap();

    assert_eq!(
        disposed_order(&recorder),
        vec!["child", "member", "container"]
    );
    assert_eq!(member.status(), ConstructionStatus::Disposed);
    assert_eq!(container.dispose(), Ok(()));
    assert_eq!(disposed_order(&recorder).len(), 3, "disposed once");
}

#[test]
fn composite_disposes_its_children_then_its_members() {
    disposes_children_then_members::<CompositeVm<ComponentVm>>();
}

#[test]
fn group_disposes_its_children_then_its_members() {
    disposes_children_then_members::<GroupVm<ComponentVm>>();
}

#[test]
fn aggregate_disposes_its_children_then_its_members() {
    disposes_children_then_members::<AggregateVm1<ComponentVm>>();
}

#[test]
fn modeled_composite_disposes_its_children_then_its_members() {
    let hub = MessageHub::new();
    let child_hub = hub.clone();
    let modeled = ModeledCompositeVm::<&'static str, ComponentVm>::new(
        "container",
        hub.clone(),
        NullDispatcher::new(),
        || vec!["child"],
        move |name| vm(name, &child_hub),
    );
    let member = vm("member", &hub);
    modeled.own_member(&member).unwrap();
    modeled.construct().unwrap();

    let recorder = hub.record(256);
    vmx::VmNode::dispose(&modeled).unwrap();

    assert_eq!(
        disposed_order(&recorder),
        vec!["child", "member", "container"]
    );
}

/// A foreign dispose while the container's construct hook runs: the
/// container publishes `Disposed` first, and after the hook returns it
/// disposes its child and then its member (ADR-0179 rule 2, LIFE-015).
fn foreign_dispose_publishes_disposed_first<C: Container>() {
    let hub = MessageHub::new();
    let child = vm("child", &hub);
    let member = vm("member", &hub);
    let container = C::make(&hub, child.clone());
    container.own_member(&member).unwrap();
    let (entered, entered_rx) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    container.on_construct({
        let release_rx = Mutex::new(release_rx);
        move || {
            entered.send(()).unwrap();
            let _ = release_rx.lock().unwrap().recv_timeout(BOUND);
            Ok(())
        }
    });
    let recorder = hub.record(256);

    let constructor = thread::spawn({
        let container = container.clone();
        move || container.construct()
    });
    entered_rx
        .recv_timeout(BOUND)
        .expect("the construct hook ran");
    let disposer = thread::spawn({
        let container = container.clone();
        move || container.dispose()
    });

    let deadline = Instant::now() + BOUND;
    while disposed_order(&recorder).is_empty() {
        assert!(
            Instant::now() < deadline,
            "the container publishes Disposed"
        );
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(disposed_order(&recorder), vec!["container"]);
    assert_ne!(child.status(), ConstructionStatus::Disposed);
    assert_ne!(member.status(), ConstructionStatus::Disposed);

    release.send(()).unwrap();
    assert_eq!(disposer.join().unwrap(), Ok(()));
    let _ = constructor.join().unwrap();

    assert_eq!(
        disposed_order(&recorder),
        vec!["container", "child", "member"]
    );
    assert_eq!(container.status(), ConstructionStatus::Disposed);
}

#[test]
fn composite_foreign_dispose_disposes_child_then_member_after_the_hook() {
    foreign_dispose_publishes_disposed_first::<CompositeVm<ComponentVm>>();
}

#[test]
fn group_foreign_dispose_disposes_child_then_member_after_the_hook() {
    foreign_dispose_publishes_disposed_first::<GroupVm<ComponentVm>>();
}

#[test]
fn aggregate_foreign_dispose_disposes_child_then_member_after_the_hook() {
    foreign_dispose_publishes_disposed_first::<AggregateVm1<ComponentVm>>();
}

/// The `own_member` result and the late member's status after the call.
type Observed = (VmxResult<()>, ConstructionStatus);

/// A member registered once the container's disposal began is disposed by
/// its registration: from a child's dispose hook during the cascade, and
/// after the disposal finished.
fn late_member_is_disposed_at_registration<C: Container>() {
    let hub = MessageHub::new();
    let child = vm("child", &hub);
    let container = C::make(&hub, child.clone());
    let late = vm("late", &hub);
    let observed: Arc<Mutex<Option<Observed>>> = Arc::default();
    child.on_dispose({
        let container = container.clone();
        let late = late.clone();
        let observed = Arc::clone(&observed);
        move || {
            let result = container.own_member(&late);
            *observed.lock().unwrap() = Some((result, late.status()));
            Ok(())
        }
    });
    container.construct().unwrap();

    container.dispose().unwrap();

    assert_eq!(
        observed.lock().unwrap().take(),
        Some((Ok(()), ConstructionStatus::Disposed)),
        "the late member is disposed during the own_member call"
    );
    let after = vm("after", &hub);
    assert_eq!(container.own_member(&after), Ok(()));
    assert_eq!(after.status(), ConstructionStatus::Disposed);
}

#[test]
fn composite_disposes_a_late_member_at_registration() {
    late_member_is_disposed_at_registration::<CompositeVm<ComponentVm>>();
}

#[test]
fn group_disposes_a_late_member_at_registration() {
    late_member_is_disposed_at_registration::<GroupVm<ComponentVm>>();
}

#[test]
fn aggregate_disposes_a_late_member_at_registration() {
    late_member_is_disposed_at_registration::<AggregateVm1<ComponentVm>>();
}
