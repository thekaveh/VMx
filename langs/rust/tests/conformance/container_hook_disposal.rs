//! A container's child cascade runs at the same admitted-hook boundary as its
//! own disposal (LIFE-015, #1062). A foreign `dispose()` disposes no child
//! while the container's admitted construct hook runs. With no hook running,
//! the children are still disposed before the container publishes `Disposed`
//! (LIFE-013).

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use vmx::{
    AggregateVm2, ComponentVm, CompositeVm, ConstructionStatus, GroupVm, Message, MessageHub,
    MessageRecorder, NullDispatcher, VmxError, VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

type Log = Arc<Mutex<Vec<String>>>;

fn push(log: &Log, entry: impl Into<String>) {
    log.lock().unwrap().push(entry.into());
}

fn entries(log: &Log) -> Vec<String> {
    log.lock().unwrap().clone()
}

/// A child that logs `cleanup:<name>` from its dispose hook.
fn child(name: &'static str, hub: &MessageHub, log: &Log) -> ComponentVm {
    let vm = ComponentVm::with_services(name, hub.clone(), NullDispatcher::new());
    let log = Arc::clone(log);
    vm.on_dispose(move || {
        push(&log, format!("cleanup:{name}"));
        Ok(())
    });
    vm
}

fn statuses_of(recorder: &MessageRecorder, status: ConstructionStatus) -> Vec<String> {
    recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(changed) if changed.status == status => {
                Some(changed.sender_name)
            }
            _ => None,
        })
        .collect()
}

/// The three container kinds under test.
trait Container: Clone + Send + Sync + 'static {
    fn make(hub: &MessageHub, children: Vec<ComponentVm>) -> Self;
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static);
    fn construct(&self) -> VmxResult<()>;
    fn dispose(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
}

impl Container for CompositeVm<ComponentVm> {
    fn make(hub: &MessageHub, children: Vec<ComponentVm>) -> Self {
        let composite = CompositeVm::with_services("container", hub.clone(), NullDispatcher::new());
        for child in children {
            composite.add(child).unwrap();
        }
        composite
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
    fn make(hub: &MessageHub, children: Vec<ComponentVm>) -> Self {
        let group = GroupVm::with_services("container", hub.clone(), NullDispatcher::new());
        for child in children {
            group.add(child).unwrap();
        }
        group
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

impl Container for AggregateVm2<ComponentVm, ComponentVm> {
    fn make(hub: &MessageHub, children: Vec<ComponentVm>) -> Self {
        let mut children = children.into_iter();
        AggregateVm2::with_services(
            "container",
            hub.clone(),
            NullDispatcher::new(),
            children.next().unwrap(),
            children.next().unwrap(),
        )
    }
    fn on_construct(&self, hook: impl FnMut() -> VmxResult<()> + Send + 'static) {
        AggregateVm2::on_construct(self, hook);
    }
    fn construct(&self) -> VmxResult<()> {
        AggregateVm2::construct(self)
    }
    fn dispose(&self) -> VmxResult<()> {
        AggregateVm2::dispose(self)
    }
    fn status(&self) -> ConstructionStatus {
        AggregateVm2::status(self)
    }
}

/// A foreign `dispose()` while the container's construct hook blocks: no child
/// is disposed until the hook returns, and nothing publishes `Constructed`.
fn child_cascade_waits_for_the_admitted_hook<C: Container>() {
    let hub = MessageHub::new();
    let recorder = hub.record(256);
    let log: Log = Arc::default();
    let c1 = child("c1", &hub, &log);
    let c2 = child("c2", &hub, &log);
    let container = C::make(&hub, vec![c1.clone(), c2.clone()]);
    let (entered, entered_rx) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    container.on_construct({
        let log = Arc::clone(&log);
        let release_rx = Mutex::new(release_rx);
        move || {
            push(&log, "hook-enter");
            entered.send(()).unwrap();
            let _ = release_rx.lock().unwrap().recv_timeout(BOUND);
            push(&log, "hook-exit");
            Ok(())
        }
    });

    let constructor = thread::spawn({
        let container = container.clone();
        move || container.construct()
    });
    entered_rx
        .recv_timeout(BOUND)
        .expect("the construct hook ran");
    let (disposed, disposed_rx) = mpsc::channel();
    let disposer = thread::spawn({
        let container = container.clone();
        move || disposed.send(container.dispose()).unwrap()
    });

    assert!(
        disposed_rx
            .recv_timeout(Duration::from_millis(200))
            .is_err(),
        "the foreign dispose waits for the hook"
    );
    assert_ne!(c1.status(), ConstructionStatus::Disposed);
    assert_ne!(c2.status(), ConstructionStatus::Disposed);
    assert!(
        entries(&log)
            .iter()
            .all(|entry| !entry.starts_with("cleanup:")),
        "no child cleanup while the hook runs: {:?}",
        entries(&log)
    );
    release.send(()).unwrap();
    assert_eq!(disposed_rx.recv_timeout(BOUND).unwrap(), Ok(()));
    let _ = constructor.join().unwrap();
    disposer.join().unwrap();

    let log = entries(&log);
    let hook_exit = log.iter().position(|entry| entry == "hook-exit").unwrap();
    for name in ["c1", "c2"] {
        let cleanups: Vec<_> = log
            .iter()
            .enumerate()
            .filter(|(_, entry)| *entry == &format!("cleanup:{name}"))
            .collect();
        assert_eq!(cleanups.len(), 1, "{name} is disposed once: {log:?}");
        assert!(
            cleanups[0].0 > hook_exit,
            "{name} is disposed after the hook: {log:?}"
        );
    }
    assert_eq!(container.status(), ConstructionStatus::Disposed);
    assert_eq!(c1.status(), ConstructionStatus::Disposed);
    assert_eq!(c2.status(), ConstructionStatus::Disposed);
    assert_eq!(
        statuses_of(&recorder, ConstructionStatus::Constructed),
        Vec::<String>::new()
    );
    assert_eq!(container.dispose(), Ok(()));
}

/// LIFE-015 — a foreign `CompositeVm` dispose waits for the admitted construct
/// hook before its child cascade (#1062).
#[test]
fn composite_child_cascade_waits_for_the_admitted_construct_hook() {
    child_cascade_waits_for_the_admitted_hook::<CompositeVm<ComponentVm>>();
}

/// LIFE-015 — the same for `GroupVm` (#1062).
#[test]
fn group_child_cascade_waits_for_the_admitted_construct_hook() {
    child_cascade_waits_for_the_admitted_hook::<GroupVm<ComponentVm>>();
}

/// LIFE-015 — the same for a fixed aggregate (#1062).
#[test]
fn aggregate_child_cascade_waits_for_the_admitted_construct_hook() {
    child_cascade_waits_for_the_admitted_hook::<AggregateVm2<ComponentVm, ComponentVm>>();
}

/// LIFE-015 — opposing container hooks that dispose each other's container
/// finish without deadlock, and each child cascade follows its own hook.
#[test]
fn opposing_container_hooks_defer_the_child_cascade() {
    let hub = MessageHub::new();
    let log: Log = Arc::default();
    let rendezvous = Arc::new(Barrier::new(2));
    let containers: Arc<Mutex<Vec<CompositeVm<ComponentVm>>>> = Arc::default();
    let built: Vec<CompositeVm<ComponentVm>> = (0..2)
        .map(|index| {
            let names: [&'static str; 2] = if index == 0 {
                ["a1", "a2"]
            } else {
                ["b1", "b2"]
            };
            let composite = CompositeVm::<ComponentVm>::make(
                &hub,
                names.iter().map(|name| child(name, &hub, &log)).collect(),
            );
            let (rendezvous, containers, log) = (
                Arc::clone(&rendezvous),
                Arc::clone(&containers),
                Arc::clone(&log),
            );
            composite.on_construct(move || {
                rendezvous.wait();
                let other = containers.lock().unwrap()[1 - index].clone();
                other.dispose()?;
                push(&log, format!("hook-exit:{index}"));
                Ok(())
            });
            composite
        })
        .collect();
    *containers.lock().unwrap() = built.clone();
    let (done, done_rx) = mpsc::channel();
    let threads: Vec<_> = built
        .iter()
        .cloned()
        .map(|composite| {
            let done = done.clone();
            thread::spawn(move || done.send(composite.construct()).unwrap())
        })
        .collect();

    for _ in 0..2 {
        assert_eq!(done_rx.recv_timeout(BOUND).expect("no deadlock"), Ok(()));
    }
    for thread in threads {
        thread.join().unwrap();
    }
    containers.lock().unwrap().clear();
    let log = entries(&log);
    for (index, names) in [(0, ["a1", "a2"]), (1, ["b1", "b2"])] {
        let hook_exit = log
            .iter()
            .position(|entry| entry == &format!("hook-exit:{index}"))
            .unwrap();
        for name in names {
            let cleanup = log
                .iter()
                .position(|entry| entry == &format!("cleanup:{name}"))
                .unwrap_or_else(|| panic!("{name} is disposed: {log:?}"));
            assert!(
                cleanup > hook_exit,
                "{name} follows its container's hook: {log:?}"
            );
        }
    }
    assert!(built
        .iter()
        .all(|c| c.status() == ConstructionStatus::Disposed));
}

/// LIFE-015 — a `dispose()` from the container's own hook disposes the
/// children at once; only the terminal cleanup waits for the hook.
#[test]
fn same_thread_container_dispose_inside_its_hook_cascades_at_once() {
    let hub = MessageHub::new();
    let log: Log = Arc::default();
    let composite = CompositeVm::<ComponentVm>::make(
        &hub,
        vec![child("c1", &hub, &log), child("c2", &hub, &log)],
    );
    composite.on_construct({
        let (composite, log) = (composite.clone(), Arc::clone(&log));
        move || {
            push(&log, "hook-enter");
            composite.dispose()?;
            push(&log, "dispose-returned");
            push(&log, "hook-exit");
            Ok(())
        }
    });

    assert_eq!(composite.construct(), Ok(()));

    assert_eq!(
        entries(&log),
        vec![
            "hook-enter",
            "cleanup:c1",
            "cleanup:c2",
            "dispose-returned",
            "hook-exit"
        ]
    );
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
}

/// LIFE-013 — a child whose dispose hook disposes its container again does not
/// make the container publish `Disposed` before its remaining children.
fn reentrant_dispose_keeps_the_container_last<C: Container>() {
    let hub = MessageHub::new();
    let recorder = hub.record(256);
    let log: Log = Arc::default();
    let c1 = child("c1", &hub, &log);
    let c2 = child("c2", &hub, &log);
    let container = C::make(&hub, vec![c1.clone(), c2]);
    let slot: Arc<Mutex<Option<C>>> = Arc::new(Mutex::new(Some(container.clone())));
    c1.on_dispose({
        let slot = Arc::clone(&slot);
        move || {
            let container = slot.lock().unwrap().clone();
            if let Some(container) = container {
                container.dispose()?;
            }
            Ok(())
        }
    });

    assert_eq!(container.dispose(), Ok(()));
    slot.lock().unwrap().take();

    assert_eq!(
        statuses_of(&recorder, ConstructionStatus::Disposed),
        vec!["c1", "c2", "container"]
    );
}

/// LIFE-013 — the re-entrant case for `CompositeVm` (#1062).
#[test]
fn composite_reentrant_dispose_during_its_cascade_keeps_it_last() {
    reentrant_dispose_keeps_the_container_last::<CompositeVm<ComponentVm>>();
}

/// LIFE-013 — the re-entrant case for `GroupVm` (#1062).
#[test]
fn group_reentrant_dispose_during_its_cascade_keeps_it_last() {
    reentrant_dispose_keeps_the_container_last::<GroupVm<ComponentVm>>();
}

/// LIFE-015 — a foreign `dispose()` arrives while the post-hook child walk
/// waits in a child's construct hook. The walk starts no further child, and
/// the composite runs no selector. Neither the composite nor `c2` publishes
/// `Constructed`.
#[test]
fn foreign_dispose_during_the_post_hook_walk_starts_no_further_child() {
    let hub = MessageHub::new();
    let recorder = hub.record(256);
    let log: Log = Arc::default();
    let c1 = child("c1", &hub, &log);
    let c2 = child("c2", &hub, &log);
    let (entered, entered_rx) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    c1.on_construct({
        let release_rx = Mutex::new(release_rx);
        move || {
            entered.send(()).unwrap();
            let _ = release_rx.lock().unwrap().recv_timeout(BOUND);
            Ok(())
        }
    });
    let c2_constructs = Arc::new(AtomicUsize::new(0));
    c2.on_construct({
        let c2_constructs = Arc::clone(&c2_constructs);
        move || {
            c2_constructs.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    });
    let selector_runs = Arc::new(AtomicUsize::new(0));
    let composite = CompositeVm::<ComponentVm>::builder()
        .name("container")
        .services(hub.clone(), NullDispatcher::new())
        .children({
            let (c1, c2) = (c1.clone(), c2.clone());
            move || vec![c1.clone(), c2.clone()]
        })
        .current({
            let selector_runs = Arc::clone(&selector_runs);
            move |items: Vec<ComponentVm>| {
                selector_runs.fetch_add(1, Ordering::SeqCst);
                items.into_iter().next()
            }
        })
        .build()
        .unwrap();

    let constructor = thread::spawn({
        let composite = composite.clone();
        move || composite.construct()
    });
    entered_rx
        .recv_timeout(BOUND)
        .expect("c1's construct hook ran");
    let disposer = thread::spawn({
        let composite = composite.clone();
        move || composite.dispose()
    });
    let deadline = Instant::now() + BOUND;
    while composite.status() != ConstructionStatus::Disposed && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
    release.send(()).unwrap();
    assert_eq!(constructor.join().unwrap(), Ok(()));
    assert_eq!(disposer.join().unwrap(), Ok(()));

    assert_eq!(c2_constructs.load(Ordering::SeqCst), 0);
    assert_eq!(selector_runs.load(Ordering::SeqCst), 0);
    assert!(!statuses_of(&recorder, ConstructionStatus::Constructing).contains(&"c2".to_string()));
    // c1's own construct was admitted before the dispose, so only c1 may
    // publish `Constructed`.
    assert_eq!(
        statuses_of(&recorder, ConstructionStatus::Constructed)
            .into_iter()
            .filter(|name| name != "c1")
            .collect::<Vec<_>>(),
        Vec::<String>::new()
    );
    assert_eq!(c1.status(), ConstructionStatus::Disposed);
    assert_eq!(c2.status(), ConstructionStatus::Disposed);
}

/// LIFE-015 — no hook of the container is admitted while its child cascade
/// runs. A `construct()` from a child's dispose hook fails with
/// `VmxError::Disposed` and publishes nothing.
#[test]
fn no_container_hook_is_admitted_during_its_child_cascade() {
    let hub = MessageHub::new();
    let recorder = hub.record(256);
    let log: Log = Arc::default();
    let c1 = child("c1", &hub, &log);
    let composite = CompositeVm::<ComponentVm>::make(&hub, vec![c1.clone()]);
    let hook_runs = Arc::new(AtomicUsize::new(0));
    composite.on_construct({
        let hook_runs = Arc::clone(&hook_runs);
        move || {
            hook_runs.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    });
    let slot = Arc::new(Mutex::new(Some(composite.clone())));
    let attempt: Arc<Mutex<Option<VmxResult<()>>>> = Arc::default();
    c1.on_dispose({
        let (slot, attempt) = (Arc::clone(&slot), Arc::clone(&attempt));
        move || {
            let composite = slot.lock().unwrap().clone();
            if let Some(composite) = composite {
                *attempt.lock().unwrap() = Some(composite.construct());
            }
            Ok(())
        }
    });

    assert_eq!(composite.dispose(), Ok(()));
    slot.lock().unwrap().take();

    assert_eq!(*attempt.lock().unwrap(), Some(Err(VmxError::Disposed)));
    assert_eq!(hook_runs.load(Ordering::SeqCst), 0);
    assert_eq!(
        statuses_of(&recorder, ConstructionStatus::Constructing),
        Vec::<String>::new()
    );
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
}

/// LIFE-015 — a component disposed during its own child walk starts no
/// further member and does not run the walk's `then` step.
#[test]
fn a_disposed_component_walk_skips_later_members_and_then() {
    let hub = MessageHub::new();
    let parent = ComponentVm::with_services("parent", hub.clone(), NullDispatcher::new());
    let first = ComponentVm::with_services("first", hub.clone(), NullDispatcher::new());
    let second = ComponentVm::with_services("second", hub, NullDispatcher::new());
    first.on_construct({
        let parent = parent.clone();
        move || parent.dispose()
    });
    let second_constructs = Arc::new(AtomicUsize::new(0));
    second.on_construct({
        let second_constructs = Arc::clone(&second_constructs);
        move || {
            second_constructs.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    });
    let then_runs = Arc::new(AtomicUsize::new(0));

    let result = parent.construct_with_children(|walk| {
        walk.transition(&first)?;
        walk.transition(&second)?;
        let then_runs = Arc::clone(&then_runs);
        walk.then(move || {
            then_runs.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
    });

    assert_eq!(result, Ok(()));
    assert_eq!(second_constructs.load(Ordering::SeqCst), 0);
    assert_eq!(then_runs.load(Ordering::SeqCst), 0);
    assert_eq!(parent.status(), ConstructionStatus::Disposed);
}
