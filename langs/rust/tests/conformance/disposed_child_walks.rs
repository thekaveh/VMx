//! Container walks and the child-transition helper skip a child that was
//! disposed directly (spec/02 §6 and §6.1, ADR-0189).

use std::sync::{Arc, Mutex};

use vmx::{
    AggregateVm2, ComponentVm, CompositeVm, ConstructionStatus, GroupVm, ManualDispatcher,
    MessageHub, NullDispatcher, VmxError, VmxResult,
};

type Child = ComponentVm<&'static str>;

fn child(name: &'static str) -> Child {
    Child::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

/// The lifecycle surface the composite and group checks share.
trait Container {
    fn construct(&self) -> VmxResult<()>;
    fn destruct(&self) -> VmxResult<()>;
    fn reconstruct(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    fn items(&self) -> Vec<Child>;
}

impl Container for CompositeVm<Child> {
    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }
    fn destruct(&self) -> VmxResult<()> {
        CompositeVm::destruct(self)
    }
    fn reconstruct(&self) -> VmxResult<()> {
        CompositeVm::reconstruct(self)
    }
    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }
    fn items(&self) -> Vec<Child> {
        CompositeVm::items(self)
    }
}

impl Container for GroupVm<Child> {
    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }
    fn destruct(&self) -> VmxResult<()> {
        GroupVm::destruct(self)
    }
    fn reconstruct(&self) -> VmxResult<()> {
        GroupVm::reconstruct(self)
    }
    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
    }
    fn items(&self) -> Vec<Child> {
        GroupVm::items(self)
    }
}

fn composite(a: &Child, b: &Child) -> CompositeVm<Child> {
    let composite = CompositeVm::new("box");
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    composite
}

fn group(a: &Child, b: &Child) -> GroupVm<Child> {
    let group = GroupVm::new("box");
    group.add(a.clone()).unwrap();
    group.add(b.clone()).unwrap();
    group
}

fn check_container<C: Container>(make: impl Fn(&Child, &Child) -> C) {
    // Disposed while Constructed: destruct, construct, then reconstruct.
    let (a, b) = (child("a"), child("b"));
    let container = make(&a, &b);
    container.construct().unwrap();
    b.dispose().unwrap();

    assert_eq!(container.destruct(), Ok(()));
    assert_eq!(container.status(), ConstructionStatus::Destructed);
    assert_eq!(a.status(), ConstructionStatus::Destructed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);
    assert!(container.items().contains(&b));

    assert_eq!(container.construct(), Ok(()));
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);

    assert_eq!(container.reconstruct(), Ok(()));
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);

    // Disposed while the container is Destructed.
    let (a, b) = (child("a"), child("b"));
    let container = make(&a, &b);
    container.construct().unwrap();
    container.destruct().unwrap();
    b.dispose().unwrap();

    assert_eq!(container.construct(), Ok(()));
    assert_eq!(container.status(), ConstructionStatus::Constructed);
    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);
    assert!(container.items().contains(&b));
}

/// LIFE-022 — a `CompositeVm` walk skips a child that was disposed directly,
/// keeps it as a member, and still destructs, constructs and reconstructs.
#[test]
fn composite_walks_skip_a_disposed_child() {
    check_container(composite);
}

/// LIFE-022 — the same for a `GroupVm`.
#[test]
fn group_walks_skip_a_disposed_child() {
    check_container(group);
}

/// LIFE-022 — an `AggregateVm2` with a disposed slot destructs, and its next
/// construct replaces both slots from the slot factories; `reconstruct()`
/// from `Constructed` with a disposed slot ends in `Constructed`.
#[test]
fn aggregate_walks_skip_a_disposed_slot() {
    let aggregate = AggregateVm2::builder()
        .name("box")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(|| child("a"))
        .component_2(|| child("b"))
        .build()
        .unwrap();
    aggregate.construct().unwrap();
    let a = aggregate.component_1().unwrap();
    let b = aggregate.component_2().unwrap();
    b.dispose().unwrap();

    assert_eq!(aggregate.destruct(), Ok(()));
    assert_eq!(aggregate.status(), ConstructionStatus::Destructed);
    assert_eq!(a.status(), ConstructionStatus::Destructed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);

    assert_eq!(aggregate.construct(), Ok(()));
    assert_eq!(aggregate.status(), ConstructionStatus::Constructed);
    let next_a = aggregate.component_1().unwrap();
    let next_b = aggregate.component_2().unwrap();
    assert_ne!(next_a.id(), a.id());
    assert_ne!(next_b.id(), b.id());
    assert_eq!(next_a.status(), ConstructionStatus::Constructed);
    assert_eq!(next_b.status(), ConstructionStatus::Constructed);

    next_b.dispose().unwrap();

    assert_eq!(aggregate.reconstruct(), Ok(()));
    assert_eq!(aggregate.status(), ConstructionStatus::Constructed);
    let last_b = aggregate.component_2().unwrap();
    assert_ne!(last_b.id(), next_b.id());
    assert_eq!(last_b.status(), ConstructionStatus::Constructed);
}

/// A leaf view-model that walks its members with the child-transition
/// helper.
struct Leaf {
    component: ComponentVm<()>,
    members: Vec<Child>,
}

impl Leaf {
    fn construct(&self) -> VmxResult<()> {
        self.component.construct_with_children(|walk| {
            for member in &self.members {
                walk.transition(member)?;
            }
            Ok(())
        })
    }

    fn destruct(&self) -> VmxResult<()> {
        self.component.destruct_with_children(|walk| {
            for member in &self.members {
                walk.transition(member)?;
            }
            Ok(())
        })
    }
}

/// LIFE-022 — the child-transition helper skips a disposed member in both
/// walks and the leaf reaches the target status.
#[test]
fn helper_walks_skip_a_disposed_member() {
    let (m1, m2) = (child("m1"), child("m2"));
    let leaf = Leaf {
        component: ComponentVm::with_model("leaf", (), MessageHub::new(), NullDispatcher::new()),
        members: vec![m1.clone(), m2.clone()],
    };
    leaf.construct().unwrap();
    m2.dispose().unwrap();

    assert_eq!(leaf.destruct(), Ok(()));
    assert_eq!(leaf.component.status(), ConstructionStatus::Destructed);
    assert_eq!(m1.status(), ConstructionStatus::Destructed);
    assert_eq!(m2.status(), ConstructionStatus::Disposed);

    assert_eq!(leaf.construct(), Ok(()));
    assert_eq!(leaf.component.status(), ConstructionStatus::Constructed);
    assert_eq!(m1.status(), ConstructionStatus::Constructed);
    assert_eq!(m2.status(), ConstructionStatus::Disposed);
}

/// ADR-0189 rule 1 — a background child that another `dispose()` reaches
/// while the container walk waits for it ends the wait as a success: the
/// walk goes on and the container reaches `Destructed`.
#[test]
fn walk_waiting_on_a_background_child_settles_when_it_is_disposed() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let a = ComponentVm::builder()
        .name("a")
        .model("a")
        .background(true)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let b = ComponentVm::builder()
        .name("b")
        .model("b")
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let composite = CompositeVm::with_services("box", hub.clone(), dispatcher.clone());
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    let errors: Arc<Mutex<Vec<VmxError>>> = Arc::default();
    let sink = Arc::clone(&errors);
    let _errors = composite
        .background_errors()
        .subscribe(move |error| sink.lock().unwrap().push(error.clone()));
    composite.construct().unwrap();
    dispatcher.drain();
    assert_eq!(composite.status(), ConstructionStatus::Constructed);

    composite.destruct().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Destructing);
    assert_eq!(a.status(), ConstructionStatus::Destructing);

    a.dispose().unwrap();
    dispatcher.drain();

    assert_eq!(a.status(), ConstructionStatus::Disposed);
    assert_eq!(b.status(), ConstructionStatus::Destructed);
    assert_eq!(composite.status(), ConstructionStatus::Destructed);
    assert!(errors.lock().unwrap().is_empty());
}
