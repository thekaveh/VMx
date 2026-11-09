//! #1255 — the children factory of the `CompositeVm` and `GroupVm` builders
//! runs on the first `construct()`, not in `build()` (spec/06 §1, spec/07 §3,
//! ADR-0204).

use std::panic::{self, AssertUnwindSafe};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;
use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, GroupVm, Message, MessageHub, NullDispatcher,
    VmxError,
};

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

/// Builds a composite or a group with `factory` as its children factory on
/// `hub`, so one test body covers both containers.
macro_rules! built {
    (CompositeVm, $hub:expr, $factory:expr) => {
        CompositeVm::<ComponentVm>::builder()
            .name("container")
            .services($hub, NullDispatcher::new())
            .children($factory)
            .build()
            .unwrap()
    };
    (GroupVm, $hub:expr, $factory:expr) => {
        GroupVm::<ComponentVm>::builder()
            .name("container")
            .services($hub, NullDispatcher::new())
            .children($factory)
            .build()
            .unwrap()
    };
}

/// A construct that starts while the factory runs is a concurrent operation:
/// it fails and leaves the first construct to populate and construct the
/// children (spec/02 §6, LIFE-008).
macro_rules! concurrent_construct_test {
    ($name:ident, $container:ident) => {
        #[test]
        fn $name() {
            let a = child("a");
            let (entered_tx, entered_rx) = mpsc::channel::<()>();
            let (release_tx, release_rx) = mpsc::channel::<()>();
            let entered_tx = Mutex::new(entered_tx);
            let release_rx = Mutex::new(release_rx);
            let container = built!($container, MessageHub::new(), {
                let a = a.clone();
                move || {
                    lock(&entered_tx).send(()).unwrap();
                    lock(&release_rx).recv().unwrap();
                    vec![a.clone()]
                }
            });

            let first = thread::spawn({
                let container = container.clone();
                move || container.construct()
            });
            entered_rx.recv_timeout(Duration::from_secs(10)).unwrap();
            assert_eq!(
                container.construct(),
                Err(VmxError::InvalidLifecycleTransition {
                    from: ConstructionStatus::Constructing,
                    operation: "construct",
                })
            );
            assert_eq!(container.status(), ConstructionStatus::Constructing);
            release_tx.send(()).unwrap();
            first.join().unwrap().unwrap();

            assert_eq!(container.status(), ConstructionStatus::Constructed);
            assert_eq!(container.items(), vec![a.clone()]);
            assert_eq!(a.status(), ConstructionStatus::Constructed);
        }
    };
}

concurrent_construct_test!(
    a_composite_construct_during_its_population_is_concurrent,
    CompositeVm
);
concurrent_construct_test!(
    a_group_construct_during_its_population_is_concurrent,
    GroupVm
);

/// A refused population is a failed construct, as in C# and TypeScript: the
/// container publishes Constructing and then rolls back to Destructed.
macro_rules! refused_population_test {
    ($name:ident, $container:ident) => {
        #[test]
        fn $name() {
            let a = child("a");
            let hub = MessageHub::new();
            let recorder = hub.record(64);
            let container = built!($container, hub, {
                let a = a.clone();
                move || vec![a.clone(), a.clone()]
            });

            assert_eq!(container.construct(), Err(VmxError::DuplicateChild));
            assert_eq!(container.status(), ConstructionStatus::Destructed);
            assert_eq!(container.len(), 0);
            let statuses = recorder
                .messages()
                .into_iter()
                .filter_map(|message| match message {
                    Message::ConstructionStatusChanged(change)
                        if change.sender_id == container.id() =>
                    {
                        Some(change.status)
                    }
                    _ => None,
                })
                .collect::<Vec<_>>();
            assert_eq!(
                statuses,
                vec![
                    ConstructionStatus::Constructing,
                    ConstructionStatus::Destructed
                ]
            );
        }
    };
}

refused_population_test!(a_refused_composite_population_rolls_back, CompositeVm);
refused_population_test!(a_refused_group_population_rolls_back, GroupVm);

/// The population runs after the construct hook, as in C# and TypeScript, so
/// the hook of the first construct sees no children.
macro_rules! hook_order_test {
    ($name:ident, $container:ident) => {
        #[test]
        fn $name() {
            let a = child("a");
            let container = built!($container, MessageHub::new(), {
                let a = a.clone();
                move || vec![a.clone()]
            });
            let parent_in_hook = Arc::new(Mutex::new(Vec::new()));
            container.on_construct({
                let a = a.clone();
                let parent_in_hook = Arc::clone(&parent_in_hook);
                move || {
                    lock(&parent_in_hook).push(a.parent_id());
                    Ok(())
                }
            });

            container.construct().unwrap();
            container.reconstruct().unwrap();
            assert_eq!(*lock(&parent_in_hook), vec![None, Some(container.id())]);
        }
    };
}

hook_order_test!(a_composite_populates_after_its_construct_hook, CompositeVm);
hook_order_test!(a_group_populates_after_its_construct_hook, GroupVm);

/// A factory that panics leaves its slot filled, so the next construct calls
/// it again.
macro_rules! panicking_factory_test {
    ($name:ident, $container:ident) => {
        #[test]
        fn $name() {
            let a = child("a");
            let panics = Arc::new(AtomicUsize::new(1));
            let container = built!($container, MessageHub::new(), {
                let a = a.clone();
                let panics = Arc::clone(&panics);
                move || {
                    if panics.swap(0, Ordering::SeqCst) == 1 {
                        panic!("factory panic");
                    }
                    vec![a.clone()]
                }
            });

            let unwound = panic::catch_unwind(AssertUnwindSafe(|| container.construct()));
            assert!(unwound.is_err());
            assert_eq!(container.status(), ConstructionStatus::Destructed);
            assert_eq!(container.len(), 0);

            container.construct().unwrap();
            assert_eq!(container.items(), vec![a.clone()]);
            assert_eq!(a.status(), ConstructionStatus::Constructed);
        }
    };
}

panicking_factory_test!(a_panicking_composite_factory_runs_again, CompositeVm);
panicking_factory_test!(a_panicking_group_factory_runs_again, GroupVm);

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}
