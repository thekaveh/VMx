//! A leaf component's member cascade runs at the same admitted-hook boundary
//! as its own disposal (spec/02 §7.1, LIFE-015, #1164). A foreign
//! `dispose()` disposes no member while the leaf's admitted hook runs: the
//! leaf publishes `Disposed` first, and the members follow once the hook
//! returns. With no hook running, the members are still disposed before the
//! leaf publishes `Disposed` (LIFE-018).

use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::thread;
use std::time::Duration;
use vmx::{
    ComponentVm, ConstructionStatus, ManualDispatcher, Message, MessageHub, MessageRecorder,
    NullDispatcher, VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);
/// How long a test lets a foreign `dispose()` run before it checks that the
/// dispose still waits for the hook.
const SETTLE: Duration = Duration::from_millis(200);

type Log = Arc<Mutex<Vec<String>>>;

fn push(log: &Log, entry: impl Into<String>) {
    log.lock().unwrap().push(entry.into());
}

fn entries(log: &Log) -> Vec<String> {
    log.lock().unwrap().clone()
}

/// A member that logs `cleanup:<name>` from its dispose hook.
fn member(name: &'static str, hub: &MessageHub, log: &Log) -> ComponentVm {
    let vm = ComponentVm::with_services(name, hub.clone(), NullDispatcher::new());
    let log = Arc::clone(log);
    vm.on_dispose(move || {
        push(&log, format!("cleanup:{name}"));
        Ok(())
    });
    vm
}

/// The `(sender id, status)` pairs of every status publication.
fn publications(recorder: &MessageRecorder) -> Vec<(usize, ConstructionStatus)> {
    recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(changed) => {
                Some((changed.sender_id, changed.status))
            }
            _ => None,
        })
        .collect()
}

/// A hook that logs its entry and exit, reports its entry, and blocks until
/// released or until [`BOUND`] passes.
fn blocking_hook(
    log: &Log,
    entered: mpsc::Sender<()>,
    release: mpsc::Receiver<()>,
) -> impl FnMut() -> VmxResult<()> + Send + 'static {
    let log = Arc::clone(log);
    let release = Mutex::new(release);
    move || {
        push(&log, "hook-enter");
        entered.send(()).unwrap();
        let _ = release.lock().unwrap().recv_timeout(BOUND);
        push(&log, "hook-exit");
        Ok(())
    }
}

/// The path that runs the leaf's blocking hook.
#[derive(Clone, Copy, Debug)]
enum HookPath {
    Construct,
    Destruct,
    ReconstructConstructPhase,
    BackgroundConstruct,
}

/// A foreign `dispose()` while the leaf's hook blocks on another thread:
/// the member is not disposed until the hook returns, the leaf publishes
/// `Disposed` before the member does, and nothing follows the leaf's
/// `Disposed`.
fn member_cascade_waits_for_the_admitted_hook(path: HookPath) {
    let hub = MessageHub::new();
    let log: Log = Arc::default();
    let dispatcher = ManualDispatcher::new();
    let (entered, entered_rx) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    let hook = blocking_hook(&log, entered, release_rx);
    let builder = ComponentVm::builder()
        .name("owner")
        .model(())
        .background(matches!(path, HookPath::BackgroundConstruct))
        .services(hub.clone(), dispatcher.clone());
    let owner = match path {
        HookPath::Destruct => builder.on_destruct(hook),
        _ => builder.on_construct(hook),
    }
    .build()
    .unwrap();
    let m1 = member("m1", &hub, &log);
    owner.own_member(&m1).unwrap();
    let recorder = hub.record(256);

    let runner = match path {
        HookPath::Construct => thread::spawn({
            let owner = owner.clone();
            move || owner.construct()
        }),
        HookPath::Destruct => {
            owner.construct().unwrap();
            thread::spawn({
                let owner = owner.clone();
                move || owner.destruct()
            })
        }
        HookPath::ReconstructConstructPhase => {
            // The first construct runs the blocking hook too: release it at
            // once, so only the reconstruct's construct phase blocks.
            let first = thread::spawn({
                let owner = owner.clone();
                move || owner.construct()
            });
            entered_rx.recv_timeout(BOUND).unwrap();
            release.send(()).unwrap();
            first.join().unwrap().unwrap();
            log.lock().unwrap().clear();
            recorder.clear();
            thread::spawn({
                let owner = owner.clone();
                move || owner.reconstruct()
            })
        }
        HookPath::BackgroundConstruct => {
            owner.construct().unwrap();
            thread::spawn({
                let dispatcher = dispatcher.clone();
                move || {
                    dispatcher.drain_background();
                    Ok(())
                }
            })
        }
    };
    entered_rx
        .recv_timeout(BOUND)
        .expect("the blocking hook ran");
    let (disposed, disposed_rx) = mpsc::channel();
    let disposer = thread::spawn({
        let owner = owner.clone();
        move || disposed.send(owner.dispose()).unwrap()
    });

    assert!(
        disposed_rx.recv_timeout(SETTLE).is_err(),
        "{path:?}: the foreign dispose waits for the hook"
    );
    assert_ne!(m1.status(), ConstructionStatus::Disposed, "{path:?}");
    assert!(
        entries(&log).iter().all(|entry| entry != "cleanup:m1"),
        "{path:?}: no member cleanup while the hook runs: {:?}",
        entries(&log)
    );
    release.send(()).unwrap();
    assert_eq!(disposed_rx.recv_timeout(BOUND).unwrap(), Ok(()), "{path:?}");
    assert_eq!(runner.join().unwrap(), Ok(()), "{path:?}");
    disposer.join().unwrap();
    dispatcher.drain();

    let log = entries(&log);
    let hook_exit = log.iter().position(|entry| entry == "hook-exit").unwrap();
    let cleanups: Vec<_> = log
        .iter()
        .enumerate()
        .filter(|(_, entry)| *entry == "cleanup:m1")
        .collect();
    assert_eq!(cleanups.len(), 1, "{path:?}: m1 is disposed once: {log:?}");
    assert!(
        cleanups[0].0 > hook_exit,
        "{path:?}: m1 is disposed after the hook: {log:?}"
    );
    let published = publications(&recorder);
    let owner_disposed = published
        .iter()
        .position(|entry| *entry == (owner.id(), ConstructionStatus::Disposed))
        .expect("the owner published Disposed");
    let member_disposed = published
        .iter()
        .position(|entry| *entry == (m1.id(), ConstructionStatus::Disposed))
        .expect("m1 published Disposed");
    assert!(
        owner_disposed < member_disposed,
        "{path:?}: the owner publishes Disposed first: {published:?}"
    );
    assert!(
        published[owner_disposed + 1..]
            .iter()
            .all(|(id, _)| *id != owner.id()),
        "{path:?}: nothing follows the owner's Disposed: {published:?}"
    );
    assert_eq!(owner.status(), ConstructionStatus::Disposed);
    assert_eq!(m1.status(), ConstructionStatus::Disposed);
    assert_eq!(owner.dispose(), Ok(()));
}

/// LIFE-015 — a foreign dispose during a leaf's blocking `on_construct`
/// disposes its member only after the hook returns (#1164).
#[test]
fn leaf_member_cascade_waits_for_the_admitted_construct_hook() {
    member_cascade_waits_for_the_admitted_hook(HookPath::Construct);
}

/// LIFE-015 — the same for a blocking `on_destruct`.
#[test]
fn leaf_member_cascade_waits_for_the_admitted_destruct_hook() {
    member_cascade_waits_for_the_admitted_hook(HookPath::Destruct);
}

/// LIFE-015 — the same for the construct phase of `reconstruct()`.
#[test]
fn leaf_member_cascade_waits_for_the_reconstruct_construct_hook() {
    member_cascade_waits_for_the_admitted_hook(HookPath::ReconstructConstructPhase);
}

/// LIFE-015 — the same for a background `on_construct` that a
/// `ManualDispatcher` drain runs on another thread.
#[test]
fn leaf_member_cascade_waits_for_the_admitted_background_hook() {
    member_cascade_waits_for_the_admitted_hook(HookPath::BackgroundConstruct);
}

/// LIFE-021 — a `reconstruct()` whose destruct phase ended before another
/// thread started the member cascade starts no construct phase. A
/// `Destructed` subscriber opens the window; the member's dispose hook holds
/// the cascade open while the reconstruct continues.
#[test]
fn reconstruct_starts_no_construct_phase_after_the_member_cascade_starts() {
    let hub = MessageHub::new();
    let log: Log = Arc::default();
    let (constructing, constructing_rx) = mpsc::channel::<()>();
    let owner = ComponentVm::builder()
        .name("owner")
        .model(())
        .on_construct({
            let log = Arc::clone(&log);
            let constructing = Mutex::new(constructing);
            move || {
                push(&log, "construct-hook");
                let _ = constructing.lock().unwrap().send(());
                Ok(())
            }
        })
        .services(hub.clone(), NullDispatcher::new())
        .build()
        .unwrap();
    owner.construct().unwrap();
    log.lock().unwrap().clear();
    // The member uses its own hub: the owner's hub is busy delivering
    // `Destructed` while the member is disposed.
    let member_hub = MessageHub::new();
    let m1 = ComponentVm::with_services("m1", member_hub, NullDispatcher::new());
    let (go, go_rx) = mpsc::channel::<()>();
    m1.on_dispose({
        let log = Arc::clone(&log);
        let go = Mutex::new(go);
        let constructing_rx = Mutex::new(constructing_rx);
        move || {
            push(&log, "cleanup:m1");
            go.lock().unwrap().send(()).unwrap();
            // Hold the cascade open while the reconstruct goes on; a
            // construct hook that runs ends the hold at once.
            let _ = constructing_rx
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_millis(300));
            Ok(())
        }
    });
    owner.own_member(&m1).unwrap();
    let recorder = hub.record(256);
    let (disposed, disposed_rx) = mpsc::channel();
    let go_rx = Mutex::new(go_rx);
    let subscription = hub.subscribe({
        let owner = owner.clone();
        let owner_id = owner.id();
        let disposed = Mutex::new(Some(disposed));
        move |message| {
            if let Message::ConstructionStatusChanged(changed) = message {
                if changed.sender_id == owner_id && changed.status == ConstructionStatus::Destructed
                {
                    let Some(disposed) = disposed.lock().unwrap().take() else {
                        return;
                    };
                    let owner = owner.clone();
                    thread::spawn(move || disposed.send(owner.dispose()).unwrap());
                    let _ = go_rx.lock().unwrap().recv_timeout(BOUND);
                }
            }
        }
    });

    assert_eq!(owner.reconstruct(), Ok(()));
    assert_eq!(disposed_rx.recv_timeout(BOUND).unwrap(), Ok(()));
    subscription.dispose();

    assert_eq!(entries(&log), vec!["cleanup:m1"], "no construct hook");
    let owner_statuses: Vec<_> = publications(&recorder)
        .into_iter()
        .filter(|(id, _)| *id == owner.id())
        .map(|(_, status)| status)
        .collect();
    assert_eq!(
        owner_statuses,
        vec![
            ConstructionStatus::Destructing,
            ConstructionStatus::Destructed,
            ConstructionStatus::Disposed
        ]
    );
    assert_eq!(owner.status(), ConstructionStatus::Disposed);
    assert_eq!(m1.status(), ConstructionStatus::Disposed);
}

/// LIFE-015 — two leaves whose construct hooks dispose each other, each with
/// one member, finish without deadlock; each member follows its owner's
/// hook.
#[test]
fn opposing_leaf_hooks_defer_the_member_cascade() {
    let hub = MessageHub::new();
    let log: Log = Arc::default();
    let rendezvous = Arc::new(Barrier::new(2));
    let owners: Arc<Mutex<Vec<ComponentVm>>> = Arc::default();
    let built: Vec<ComponentVm> = (0..2)
        .map(|index| {
            let owner = ComponentVm::with_services(
                format!("owner{index}"),
                hub.clone(),
                NullDispatcher::new(),
            );
            owner
                .own_member(&member(["a1", "b1"][index], &hub, &log))
                .unwrap();
            let (rendezvous, owners, log) = (
                Arc::clone(&rendezvous),
                Arc::clone(&owners),
                Arc::clone(&log),
            );
            owner.on_construct(move || {
                rendezvous.wait();
                let other = owners.lock().unwrap()[1 - index].clone();
                other.dispose()?;
                push(&log, format!("hook-exit:{index}"));
                Ok(())
            });
            owner
        })
        .collect();
    *owners.lock().unwrap() = built.clone();
    let (done, done_rx) = mpsc::channel();
    let threads: Vec<_> = built
        .iter()
        .cloned()
        .map(|owner| {
            let done = done.clone();
            thread::spawn(move || done.send(owner.construct()).unwrap())
        })
        .collect();

    for _ in 0..2 {
        assert_eq!(done_rx.recv_timeout(BOUND).expect("no deadlock"), Ok(()));
    }
    for thread in threads {
        thread.join().unwrap();
    }
    owners.lock().unwrap().clear();
    let log = entries(&log);
    for (index, name) in [(0, "a1"), (1, "b1")] {
        let hook_exit = log
            .iter()
            .position(|entry| entry == &format!("hook-exit:{index}"))
            .unwrap();
        let cleanups: Vec<_> = log
            .iter()
            .enumerate()
            .filter(|(_, entry)| *entry == &format!("cleanup:{name}"))
            .collect();
        assert_eq!(cleanups.len(), 1, "{name} is disposed once: {log:?}");
        assert!(
            cleanups[0].0 > hook_exit,
            "{name} follows its owner's hook: {log:?}"
        );
    }
    assert!(built
        .iter()
        .all(|owner| owner.status() == ConstructionStatus::Disposed));
}

/// LIFE-018 — with no hook running, the member is still disposed before the
/// leaf publishes `Disposed`, and a re-entrant `dispose()` from the member's
/// dispose hook returns `Ok(())` at once.
#[test]
fn inline_member_cascade_still_precedes_the_leaf_disposed() {
    let hub = MessageHub::new();
    let owner = ComponentVm::with_services("owner", hub.clone(), NullDispatcher::new());
    let m1 = ComponentVm::with_services("m1", hub.clone(), NullDispatcher::new());
    let reentrant: Arc<Mutex<Option<VmxResult<()>>>> = Arc::default();
    m1.on_dispose({
        let (owner, reentrant) = (owner.clone(), Arc::clone(&reentrant));
        move || {
            *reentrant.lock().unwrap() = Some(owner.dispose());
            Ok(())
        }
    });
    owner.own_member(&m1).unwrap();
    let recorder = hub.record(256);

    assert_eq!(owner.dispose(), Ok(()));

    assert_eq!(*reentrant.lock().unwrap(), Some(Ok(())));
    assert_eq!(
        publications(&recorder),
        vec![
            (m1.id(), ConstructionStatus::Disposed),
            (owner.id(), ConstructionStatus::Disposed)
        ]
    );
}
