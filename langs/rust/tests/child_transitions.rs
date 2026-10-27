//! Public-API tests for `ChildTransitions` and `ComponentVm::own_member`
//! (spec/02 §6.1 and §7.1, ADR-0162), written as a consumer crate would.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};
use vmx::{
    ComponentVm, ConstructionStatus, GroupVm, LifecycleSettleCallback, ManualDispatcher, Message,
    MessageHub, ParentHandle, Subscription, VmNode, VmxError, VmxResult,
};

type Member = ComponentVm<i32, ManualDispatcher>;
type Core = ComponentVm<(), ManualDispatcher>;

fn member(hub: &MessageHub, dispatcher: &ManualDispatcher, name: &str, background: bool) -> Member {
    ComponentVm::builder()
        .name(name)
        .model(0)
        .background(background)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap()
}

type Log = Arc<Mutex<Vec<(usize, ConstructionStatus)>>>;

fn record(hub: &MessageHub) -> (Log, Subscription) {
    let log = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&log);
    let subscription = hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(change) = message {
            sink.lock().unwrap().push((change.sender_id, change.status));
        }
    });
    (log, subscription)
}

/// A consumer view-model type: it composes a `ComponentVm`, owns two members,
/// and forwards `VmNode` so a container can hold it.
#[derive(Clone)]
struct Editor {
    component: Core,
    header: Member,
    body: Member,
}

impl PartialEq for Editor {
    fn eq(&self, other: &Self) -> bool {
        self.component == other.component
    }
}

impl Editor {
    fn new(hub: &MessageHub, dispatcher: &ManualDispatcher, background: bool) -> Self {
        let editor = Self {
            component: Core::with_services("editor", hub.clone(), dispatcher.clone()),
            header: member(hub, dispatcher, "header", background),
            body: member(hub, dispatcher, "body", background),
        };
        editor.component.own_member(&editor.header).unwrap();
        editor.component.own_member(&editor.body).unwrap();
        editor
    }

    fn reconstruct(&self) -> VmxResult<()> {
        let (header, body) = (self.header.clone(), self.body.clone());
        self.component.reconstruct_with_children(
            |walk| {
                walk.transition(&self.body)?;
                walk.transition(&self.header)
            },
            move |walk| {
                walk.transition(&header)?;
                walk.transition(&body)
            },
        )
    }
}

impl VmNode for Editor {
    fn id(&self) -> usize {
        self.component.id()
    }

    fn construct(&self) -> VmxResult<()> {
        self.component.construct_with_children(|walk| {
            walk.transition(&self.header)?;
            walk.transition(&self.body)
        })
    }

    fn destruct(&self) -> VmxResult<()> {
        self.component.destruct_with_children(|walk| {
            walk.transition(&self.body)?;
            walk.transition(&self.header)
        })
    }

    fn dispose(&self) -> VmxResult<()> {
        self.component.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.component.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        VmNode::set_parent_id(&self.component, parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        VmNode::parent_id(&self.component)
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        VmNode::set_parent_handle(&self.component, parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        VmNode::parent_handle(&self.component)
    }

    fn when_lifecycle_settled(&self, callback: LifecycleSettleCallback) -> bool {
        VmNode::when_lifecycle_settled(&self.component, callback)
    }
}

#[test]
fn consumer_type_inside_a_group_walks_and_disposes_its_members() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let editor = Editor::new(&hub, &dispatcher, true);
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    group.add(editor.clone()).unwrap();

    group.construct().unwrap();
    assert_eq!(group.status(), ConstructionStatus::Constructing);
    assert_eq!(editor.status(), ConstructionStatus::Constructing);
    dispatcher.drain();
    assert_eq!(editor.header.status(), ConstructionStatus::Constructed);
    assert_eq!(editor.body.status(), ConstructionStatus::Constructed);
    assert_eq!(group.status(), ConstructionStatus::Constructed);

    let (log, _subscription) = record(&hub);
    group.dispose().unwrap();
    let disposed: Vec<usize> = log
        .lock()
        .unwrap()
        .iter()
        .filter(|(_, status)| *status == ConstructionStatus::Disposed)
        .map(|(id, _)| *id)
        .collect();
    assert_eq!(
        disposed,
        vec![
            editor.header.id(),
            editor.body.id(),
            editor.id(),
            group.id()
        ]
    );
}

#[test]
fn reconstruct_with_children_waits_for_a_background_destruct() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let editor = Editor::new(&hub, &dispatcher, true);
    editor.construct().unwrap();
    dispatcher.drain();
    assert_eq!(editor.status(), ConstructionStatus::Constructed);
    let (log, _subscription) = record(&hub);

    editor.reconstruct().unwrap();
    assert_eq!(editor.status(), ConstructionStatus::Destructing);
    assert_eq!(editor.body.status(), ConstructionStatus::Destructing);
    dispatcher.drain();

    use ConstructionStatus::{Constructed, Constructing, Destructed, Destructing};
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            (editor.id(), Destructing),
            (editor.body.id(), Destructing),
            (editor.body.id(), Destructed),
            (editor.header.id(), Destructing),
            (editor.header.id(), Destructed),
            (editor.id(), Destructed),
            (editor.id(), Constructing),
            (editor.header.id(), Constructing),
            (editor.header.id(), Constructed),
            (editor.body.id(), Constructing),
            (editor.body.id(), Constructed),
            (editor.id(), Constructed),
        ]
    );
}

#[test]
fn reconstruct_runs_the_hooks_and_admits_like_reconstruct() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let editor = Editor::new(&hub, &dispatcher, false);
    let hooks = Arc::new(Mutex::new(Vec::new()));
    let (on_construct, on_destruct) = (Arc::clone(&hooks), Arc::clone(&hooks));
    editor.component.on_construct(move || {
        on_construct.lock().unwrap().push("construct");
        Ok(())
    });
    editor.component.on_destruct(move || {
        on_destruct.lock().unwrap().push("destruct");
        Ok(())
    });

    assert!(matches!(
        editor.reconstruct(),
        Err(VmxError::InvalidLifecycleTransition { .. })
    ));
    editor.construct().unwrap();
    editor.reconstruct().unwrap();

    assert_eq!(
        *hooks.lock().unwrap(),
        vec!["construct", "destruct", "construct"]
    );
    assert_eq!(editor.header.status(), ConstructionStatus::Constructed);
    editor.component.dispose().unwrap();
    assert_eq!(editor.reconstruct(), Err(VmxError::Disposed));
}

#[test]
fn deferred_reconstruct_construct_failure_reaches_background_errors() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let editor = Editor::new(&hub, &dispatcher, true);
    editor.construct().unwrap();
    dispatcher.drain();
    let (errors_send, errors) = mpsc::channel();
    let _errors = editor
        .component
        .background_errors()
        .subscribe(move |error| {
            errors_send.send(error).unwrap();
        });

    editor
        .component
        .reconstruct_with_children(
            |walk| walk.transition(&editor.header),
            |walk| walk.then(|| Err(VmxError::Other("after failed".to_string()))),
        )
        .unwrap();
    dispatcher.drain();

    assert_eq!(editor.status(), ConstructionStatus::Destructed);
    assert_eq!(
        errors.try_recv(),
        Ok(VmxError::Other("after failed".to_string()))
    );
}

#[test]
fn walk_joins_a_child_already_destructing() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let destructs = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&destructs);
    let child: Member = ComponentVm::builder()
        .name("child")
        .model(0)
        .background(true)
        .on_destruct(move || {
            counter.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let parent = Core::with_services("parent", hub.clone(), dispatcher.clone());
    parent
        .construct_with_children(|walk| walk.transition(&child))
        .unwrap();
    dispatcher.drain();
    child.destruct().unwrap();
    assert_eq!(child.status(), ConstructionStatus::Destructing);

    parent
        .destruct_with_children(|walk| walk.transition(&child))
        .unwrap();
    assert_eq!(parent.status(), ConstructionStatus::Destructing);
    dispatcher.drain();

    assert_eq!(destructs.load(Ordering::SeqCst), 1);
    assert_eq!(child.status(), ConstructionStatus::Destructed);
    assert_eq!(parent.status(), ConstructionStatus::Destructed);
}

#[test]
fn walk_skips_children_at_target_and_does_not_run_for_a_constructed_parent() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let constructs = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&constructs);
    let child: Member = ComponentVm::builder()
        .name("child")
        .model(0)
        .on_construct(move || {
            counter.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    child.construct().unwrap();
    let parent = Core::with_services("parent", hub, dispatcher);

    parent
        .construct_with_children(|walk| walk.transition(&child))
        .unwrap();
    assert_eq!(constructs.load(Ordering::SeqCst), 1);
    assert_eq!(parent.status(), ConstructionStatus::Constructed);

    let mut ran = false;
    parent
        .construct_with_children(|_| {
            ran = true;
            Ok(())
        })
        .unwrap();
    assert!(!ran);
}

#[test]
fn a_swallowed_step_failure_still_fails_the_walk_and_starts_no_later_child() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let bad: Member = ComponentVm::builder()
        .name("bad")
        .model(0)
        .on_construct(|| Err(VmxError::Other("bad".to_string())))
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let later = member(&hub, &dispatcher, "later", false);
    let parent = Core::with_services("parent", hub, dispatcher);

    let result = parent.construct_with_children(|walk| {
        let _ = walk.transition(&bad);
        assert_eq!(
            walk.transition(&later),
            Err(VmxError::Other("bad".to_string()))
        );
        Ok(())
    });

    assert_eq!(result, Err(VmxError::Other("bad".to_string())));
    assert_eq!(parent.status(), ConstructionStatus::Destructed);
    assert_eq!(later.status(), ConstructionStatus::Destructed);
}

#[test]
fn a_failing_then_rolls_the_parent_back() {
    let parent = ComponentVm::new("parent");
    let result = parent.construct_with_children(|walk| {
        walk.then(|| Err(VmxError::Other("after failed".to_string())))
    });
    assert_eq!(result, Err(VmxError::Other("after failed".to_string())));
    assert_eq!(parent.status(), ConstructionStatus::Destructed);

    parent.construct().unwrap();
    let result = parent.destruct_with_children(|walk| {
        walk.then(|| Err(VmxError::Other("after failed".to_string())))
    });
    assert_eq!(result, Err(VmxError::Other("after failed".to_string())));
    assert_eq!(parent.status(), ConstructionStatus::Constructed);
}

#[test]
fn own_member_after_disposed_disposes_now_and_returns_its_failure() {
    let parent = ComponentVm::new("parent");
    parent.dispose().unwrap();
    let late = ComponentVm::new("late");
    late.on_dispose(|| Err(VmxError::Other("late dispose failed".to_string())));

    assert_eq!(
        parent.own_member(&late),
        Err(VmxError::Other("late dispose failed".to_string()))
    );
    assert_eq!(late.status(), ConstructionStatus::Disposed);
}

#[test]
fn own_member_rejects_the_component_itself() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let editor = Editor::new(&hub, &dispatcher, false);

    assert_eq!(
        editor.component.own_member(&editor.component.clone()),
        Err(VmxError::OwnershipCycle)
    );
    assert_eq!(
        editor.component.own_member(&editor.clone()),
        Err(VmxError::OwnershipCycle)
    );
    editor.component.dispose().unwrap();
    assert_eq!(editor.status(), ConstructionStatus::Disposed);
}

#[test]
fn dispose_keeps_the_first_member_failure_and_clones_share_members() {
    let first = ComponentVm::new("first");
    first.on_dispose(|| Err(VmxError::Other("first".to_string())));
    let second = ComponentVm::new("second");
    second.on_dispose(|| Err(VmxError::Other("second".to_string())));
    let parent = ComponentVm::new("parent");
    parent.own_member(&first).unwrap();
    parent.clone().own_member(&second).unwrap();
    parent.own_member(&first).unwrap();

    assert_eq!(
        parent.clone().dispose(),
        Err(VmxError::Other("first".to_string()))
    );
    assert_eq!(first.status(), ConstructionStatus::Disposed);
    assert_eq!(second.status(), ConstructionStatus::Disposed);
    assert_eq!(parent.status(), ConstructionStatus::Disposed);
    assert_eq!(parent.dispose(), Ok(()));
}

#[test]
fn reentrant_dispose_from_a_member_is_a_no_op() {
    let hub = MessageHub::new();
    let parent = ComponentVm::with_services("parent", hub.clone(), ManualDispatcher::new());
    let first = ComponentVm::with_services("first", hub.clone(), ManualDispatcher::new());
    let second = ComponentVm::with_services("second", hub.clone(), ManualDispatcher::new());
    let observed = Arc::new(Mutex::new(None));
    {
        let parent = parent.clone();
        let observed = Arc::clone(&observed);
        first.on_dispose(move || {
            let result = parent.dispose();
            *observed.lock().unwrap() = Some((result, parent.status()));
            Ok(())
        });
    }
    parent.own_member(&first).unwrap();
    parent.own_member(&second).unwrap();
    let (log, _subscription) = record(&hub);

    parent.dispose().unwrap();

    assert_eq!(
        *observed.lock().unwrap(),
        Some((Ok(()), ConstructionStatus::Destructed))
    );
    let disposed: Vec<usize> = log
        .lock()
        .unwrap()
        .iter()
        .filter(|(_, status)| *status == ConstructionStatus::Disposed)
        .map(|(id, _)| *id)
        .collect();
    assert_eq!(disposed, vec![first.id(), second.id(), parent.id()]);
}

#[test]
fn members_are_not_children() {
    let parent = ComponentVm::new("parent");
    let member = ComponentVm::new("member");
    parent.own_member(&member).unwrap();
    parent.construct().unwrap();

    assert_eq!(member.parent_id(), None);
    assert_eq!(member.status(), ConstructionStatus::Destructed);
}

/// While the member cascade runs, a dispose from another thread returns at
/// once without waiting; the first dispose still publishes the parent's
/// Disposed only after its members.
#[test]
fn a_concurrent_dispose_returns_at_once_and_the_parent_still_disposes_last() {
    let hub = MessageHub::new();
    let parent = ComponentVm::with_services("parent", hub.clone(), ManualDispatcher::new());
    let slow = ComponentVm::with_services("slow", hub.clone(), ManualDispatcher::new());
    let next = ComponentVm::with_services("next", hub.clone(), ManualDispatcher::new());
    let (started_send, started) = mpsc::channel();
    let (release_send, release) = mpsc::channel::<()>();
    let release = Mutex::new(release);
    slow.on_dispose(move || {
        started_send.send(()).unwrap();
        release.lock().unwrap().recv().unwrap();
        Ok(())
    });
    parent.own_member(&slow).unwrap();
    parent.own_member(&next).unwrap();
    let (log, _subscription) = record(&hub);

    let first = {
        let parent = parent.clone();
        std::thread::spawn(move || parent.dispose())
    };
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let (second_send, second) = mpsc::channel();
    {
        let parent = parent.clone();
        std::thread::spawn(move || {
            let result = parent.dispose();
            let _ = second_send.send((result, parent.status()));
        });
    }
    // The member cascade is still blocked in `slow`, so this returns at once.
    let (result, status) = second
        .recv_timeout(Duration::from_secs(5))
        .expect("the concurrent dispose waited for the member cascade");
    assert_eq!(result, Ok(()));
    assert_ne!(status, ConstructionStatus::Disposed);
    assert_ne!(next.status(), ConstructionStatus::Disposed);
    release_send.send(()).unwrap();

    assert_eq!(first.join().unwrap(), Ok(()));
    let disposed: Vec<usize> = log
        .lock()
        .unwrap()
        .iter()
        .filter(|(_, status)| *status == ConstructionStatus::Disposed)
        .map(|(id, _)| *id)
        .collect();
    assert_eq!(disposed, vec![slow.id(), next.id(), parent.id()]);
}

/// A member whose construct hook (on thread C) disposes the parent while the
/// parent's dispose (on thread A) waits for that hook: the hook's dispose is a
/// no-op, so neither thread waits on the other.
#[test]
fn a_dispose_from_a_member_hook_on_another_thread_does_not_deadlock() {
    let parent = ComponentVm::new("parent");
    let member = ComponentVm::new("member");
    let (in_hook_send, in_hook) = mpsc::channel();
    let (go_send, go) = mpsc::channel::<()>();
    let go = Mutex::new(go);
    let hook_result = Arc::new(Mutex::new(None));
    {
        let parent = parent.clone();
        let hook_result = Arc::clone(&hook_result);
        member.on_construct(move || {
            in_hook_send.send(()).unwrap();
            go.lock().unwrap().recv().unwrap();
            *hook_result.lock().unwrap() = Some((parent.dispose(), parent.status()));
            Ok(())
        });
    }
    parent.own_member(&member).unwrap();
    let (done_send, done) = mpsc::channel();

    let constructing = member.clone();
    let c_done = done_send.clone();
    std::thread::spawn(move || {
        let _ = constructing.construct();
        let _ = c_done.send("c");
    });
    in_hook.recv_timeout(Duration::from_secs(5)).unwrap();
    let disposing = parent.clone();
    std::thread::spawn(move || {
        let result = disposing.dispose();
        let _ = done_send.send(if result.is_ok() { "a" } else { "a-err" });
    });
    // Thread A has started the member's dispose, which waits for C's hook.
    let deadline = Instant::now() + Duration::from_secs(5);
    while member.status() != ConstructionStatus::Disposed {
        assert!(
            Instant::now() < deadline,
            "the parent never disposed the member"
        );
        std::thread::yield_now();
    }
    go_send.send(()).unwrap();

    let mut finished = vec![
        done.recv_timeout(Duration::from_secs(5))
            .expect("deadlock: a disposer never returned"),
        done.recv_timeout(Duration::from_secs(5))
            .expect("deadlock: a disposer never returned"),
    ];
    finished.sort_unstable();
    assert_eq!(finished, vec!["a", "c"]);
    let (result, status_seen) = hook_result.lock().unwrap().take().unwrap();
    assert_eq!(result, Ok(()));
    assert_ne!(status_seen, ConstructionStatus::Disposed);
    assert_eq!(parent.status(), ConstructionStatus::Disposed);
    assert_eq!(member.status(), ConstructionStatus::Disposed);
}

#[test]
fn a_background_component_rejects_the_standalone_walks_but_reconstructs() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = member(&hub, &dispatcher, "child", false);
    let parent = member(&hub, &dispatcher, "parent", true);
    let mut ran = false;

    let result = parent.construct_with_children(|_| {
        ran = true;
        Ok(())
    });
    assert!(matches!(result, Err(VmxError::InvalidArgument(_))));
    assert!(matches!(
        parent.destruct_with_children(|walk| walk.transition(&child)),
        Err(VmxError::InvalidArgument(_))
    ));
    assert!(!ran);
    assert_eq!(parent.status(), ConstructionStatus::Destructed);
    assert_eq!(dispatcher.queued_len(), 0);

    parent.construct().unwrap();
    dispatcher.drain();
    assert_eq!(parent.status(), ConstructionStatus::Constructed);
    let walked = child.clone();
    parent
        .reconstruct_with_children(|_| Ok(()), move |walk| walk.transition(&walked))
        .unwrap();
    assert_eq!(parent.status(), ConstructionStatus::Constructed);
    assert_eq!(child.status(), ConstructionStatus::Constructed);
}
