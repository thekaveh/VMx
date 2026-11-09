//! #1255 — the children factory of the `CompositeVm` and `GroupVm` builders
//! runs on the first `construct()`, not in `build()` (spec/06 §1, spec/07 §3,
//! ADR-0204).

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use vmx::{ComponentVm, CompositeVm, ConstructionStatus, GroupVm, MessageHub, NullDispatcher};

fn child(name: &str) -> ComponentVm {
    ComponentVm::with_services(name, MessageHub::new(), NullDispatcher::new())
}

/// A factory that counts its calls and returns the same children each time.
fn counting_factory(
    children: Vec<ComponentVm>,
) -> (
    Arc<AtomicUsize>,
    impl Fn() -> Vec<ComponentVm> + Send + Sync,
) {
    let calls = Arc::new(AtomicUsize::new(0));
    let counted = Arc::clone(&calls);
    (calls, move || {
        counted.fetch_add(1, Ordering::SeqCst);
        children.clone()
    })
}

#[test]
fn composite_builder_runs_the_children_factory_on_the_first_construct() {
    let (a, b) = (child("a"), child("b"));
    let (calls, factory) = counting_factory(vec![a.clone(), b.clone()]);
    let composite = CompositeVm::<ComponentVm>::builder()
        .name("composite")
        .services(MessageHub::new(), NullDispatcher::new())
        .children(factory)
        .build()
        .unwrap();

    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(composite.len(), 0);
    assert_eq!(a.parent_id(), None);

    composite.construct().unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(composite.items(), vec![a.clone(), b.clone()]);
    assert_eq!(a.parent_id(), Some(composite.id()));
    assert_eq!(a.status(), ConstructionStatus::Constructed);

    composite.reconstruct().unwrap();
    composite.destruct().unwrap();
    composite.construct().unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1, "the factory runs once");
    assert_eq!(composite.len(), 2);
}

#[test]
fn group_builder_runs_the_children_factory_on_the_first_construct() {
    let (a, b) = (child("a"), child("b"));
    let (calls, factory) = counting_factory(vec![a.clone(), b.clone()]);
    let group = GroupVm::<ComponentVm>::builder()
        .name("group")
        .services(MessageHub::new(), NullDispatcher::new())
        .children(factory)
        .build()
        .unwrap();

    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(group.len(), 0);
    assert_eq!(a.parent_id(), None);

    group.construct().unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(group.items(), vec![a.clone(), b.clone()]);
    assert_eq!(a.parent_id(), Some(group.id()));
    assert_eq!(a.status(), ConstructionStatus::Constructed);

    group.reconstruct().unwrap();
    group.destruct().unwrap();
    group.construct().unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1, "the factory runs once");
    assert_eq!(group.len(), 2);
}

#[test]
fn a_refused_population_keeps_the_factory_for_the_next_construct() {
    let a = child("a");
    let duplicate = Arc::new(AtomicUsize::new(1));
    let composite = CompositeVm::<ComponentVm>::builder()
        .name("composite")
        .services(MessageHub::new(), NullDispatcher::new())
        .children({
            let a = a.clone();
            let duplicate = Arc::clone(&duplicate);
            move || {
                if duplicate.swap(0, Ordering::SeqCst) == 1 {
                    vec![a.clone(), a.clone()]
                } else {
                    vec![a.clone()]
                }
            }
        })
        .build()
        .unwrap();

    assert_eq!(composite.construct(), Err(vmx::VmxError::DuplicateChild));
    assert_eq!(composite.len(), 0);
    assert_eq!(a.parent_id(), None);
    composite.construct().unwrap();
    assert_eq!(composite.items(), vec![a.clone()]);
}

#[test]
fn a_disposed_built_container_never_runs_the_factory() {
    let (calls, factory) = counting_factory(vec![child("a")]);
    let group = GroupVm::<ComponentVm>::builder()
        .name("group")
        .services(MessageHub::new(), NullDispatcher::new())
        .children(factory)
        .build()
        .unwrap();
    group.dispose().unwrap();

    assert!(group.construct().is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(group.len(), 0);
}
