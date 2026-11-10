//! A transition whose hook returned before an inline dispose cascade started
//! commits nothing once the cascade has started (spec/02 §7.2, ADR-0175,
//! LIFE-021, #1167).
//!
//! The window lies between the hook-lease release and the commit, so these
//! tests pause the transition there through the `commit_pause` seam, which an
//! integration test cannot reach.

use super::commit_pause;
use crate::{
    ComponentVm, CompositeVm, ConstructionStatus, GroupVm, Message, MessageHub, NullDispatcher,
    VmxError, VmxResult,
};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

const BOUND: Duration = Duration::from_secs(5);

type Publications = Arc<Mutex<Vec<(ConstructionStatus, ConstructionStatus)>>>;

trait Container: Clone + Send + 'static {
    fn make(hub: &MessageHub, child: ComponentVm) -> Self;
    fn id(&self) -> usize;
    fn construct(&self) -> VmxResult<()>;
    fn destruct(&self) -> VmxResult<()>;
    fn dispose(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
}

impl Container for CompositeVm<ComponentVm> {
    fn make(hub: &MessageHub, child: ComponentVm) -> Self {
        let composite = CompositeVm::with_services("box", hub.clone(), NullDispatcher::new());
        composite.add(child).unwrap();
        composite
    }
    fn id(&self) -> usize {
        CompositeVm::id(self)
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
}

impl Container for GroupVm<ComponentVm> {
    fn make(hub: &MessageHub, child: ComponentVm) -> Self {
        let group = GroupVm::with_services("box", hub.clone(), NullDispatcher::new());
        group.add(child).unwrap();
        group
    }
    fn id(&self) -> usize {
        GroupVm::id(self)
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
}

/// Pauses `construct()` (or `destruct()`) of a container on thread T after
/// its hook released the lease, disposes the container on thread D, and
/// resumes T when the child's dispose hook starts. The child's hook then
/// holds the cascade open until T's call returns. The container publishes
/// nothing between its transient status and `Disposed`.
fn no_commit_after_the_cascade_started<C: Container>(construct: bool) {
    let hub = MessageHub::new();
    let child = ComponentVm::with_services("c1", hub.clone(), NullDispatcher::new());
    let container = C::make(&hub, child.clone());
    if !construct {
        container.construct().unwrap();
    }
    let container_id = container.id();
    let publications: Publications = Arc::default();
    let subscription = hub.subscribe({
        let (publications, child) = (Arc::clone(&publications), child.clone());
        move |message| {
            if let Message::ConstructionStatusChanged(changed) = message {
                if changed.sender_id == container_id {
                    publications
                        .lock()
                        .unwrap()
                        .push((changed.status, child.status()));
                }
            }
        }
    });
    let (resume, resume_rx) = mpsc::channel::<()>();
    let (returned, returned_rx) = mpsc::channel::<()>();
    let child_disposals = Arc::new(Mutex::new(0_usize));
    child.on_dispose({
        let child_disposals = Arc::clone(&child_disposals);
        move || {
            *child_disposals.lock().unwrap() += 1;
            let _ = resume.send(());
            let _ = returned_rx.recv_timeout(BOUND);
            Ok(())
        }
    });

    let (paused, paused_rx) = mpsc::channel::<()>();
    let (transitioned, transitioned_rx) = mpsc::channel();
    let runner = thread::spawn({
        let container = container.clone();
        move || {
            commit_pause::arm(container_id, move || {
                paused.send(()).unwrap();
                let _ = resume_rx.recv_timeout(BOUND);
            });
            let result = if construct {
                container.construct()
            } else {
                container.destruct()
            };
            let _ = returned.send(());
            transitioned.send(result).unwrap();
        }
    });
    paused_rx
        .recv_timeout(BOUND)
        .expect("the transition paused before its commit");
    let (disposed, disposed_rx) = mpsc::channel();
    let disposer = thread::spawn({
        let container = container.clone();
        move || disposed.send(container.dispose()).unwrap()
    });

    assert_eq!(transitioned_rx.recv_timeout(BOUND).unwrap(), Ok(()));
    assert_eq!(disposed_rx.recv_timeout(BOUND).unwrap(), Ok(()));
    runner.join().unwrap();
    disposer.join().unwrap();
    subscription.dispose();

    let (transient, prior) = if construct {
        (
            ConstructionStatus::Constructing,
            ConstructionStatus::Destructed,
        )
    } else {
        (
            ConstructionStatus::Destructing,
            ConstructionStatus::Constructed,
        )
    };
    assert_eq!(
        *publications.lock().unwrap(),
        vec![
            (transient, prior),
            (ConstructionStatus::Disposed, ConstructionStatus::Disposed)
        ],
        "(container status, child status) at each container publication"
    );
    assert_eq!(container.status(), ConstructionStatus::Disposed);
    assert_eq!(child.status(), ConstructionStatus::Disposed);
    assert_eq!(*child_disposals.lock().unwrap(), 1);
}

#[test]
fn composite_construct_commits_nothing_after_its_inline_cascade_started() {
    no_commit_after_the_cascade_started::<CompositeVm<ComponentVm>>(true);
}

#[test]
fn composite_destruct_commits_nothing_after_its_inline_cascade_started() {
    no_commit_after_the_cascade_started::<CompositeVm<ComponentVm>>(false);
}

#[test]
fn group_construct_commits_nothing_after_its_inline_cascade_started() {
    no_commit_after_the_cascade_started::<GroupVm<ComponentVm>>(true);
}

#[test]
fn group_destruct_commits_nothing_after_its_inline_cascade_started() {
    no_commit_after_the_cascade_started::<GroupVm<ComponentVm>>(false);
}

/// The same window for a leaf with one member: its member cascade drops the
/// leaf's commit too.
#[test]
fn leaf_construct_commits_nothing_after_its_member_cascade_started() {
    let hub = MessageHub::new();
    let leaf = ComponentVm::with_services("leaf", hub.clone(), NullDispatcher::new());
    let member = ComponentVm::with_services("m1", hub.clone(), NullDispatcher::new());
    leaf.own_member(&member).unwrap();
    let leaf_id = leaf.id();
    let publications: Arc<Mutex<Vec<ConstructionStatus>>> = Arc::default();
    let subscription = hub.subscribe({
        let publications = Arc::clone(&publications);
        move |message| {
            if let Message::ConstructionStatusChanged(changed) = message {
                if changed.sender_id == leaf_id {
                    publications.lock().unwrap().push(changed.status);
                }
            }
        }
    });
    let (resume, resume_rx) = mpsc::channel::<()>();
    let (returned, returned_rx) = mpsc::channel::<()>();
    member.on_dispose(move || {
        let _ = resume.send(());
        let _ = returned_rx.recv_timeout(BOUND);
        Ok(())
    });
    let (paused, paused_rx) = mpsc::channel::<()>();
    let (constructed, constructed_rx) = mpsc::channel();
    let runner = thread::spawn({
        let leaf = leaf.clone();
        move || {
            commit_pause::arm(leaf_id, move || {
                paused.send(()).unwrap();
                let _ = resume_rx.recv_timeout(BOUND);
            });
            let result = leaf.construct();
            let _ = returned.send(());
            constructed.send(result).unwrap();
        }
    });
    paused_rx.recv_timeout(BOUND).expect("the construct paused");

    assert_eq!(leaf.dispose(), Ok(()));
    assert_eq!(constructed_rx.recv_timeout(BOUND).unwrap(), Ok(()));
    runner.join().unwrap();
    subscription.dispose();

    assert_eq!(
        *publications.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Disposed
        ]
    );
    assert_eq!(leaf.status(), ConstructionStatus::Disposed);
}

/// A failed hook's rollback is a commit too: once the cascade has started it
/// publishes nothing, and the call returns the hook's own error.
#[test]
fn rollback_after_a_failed_hook_commits_nothing_after_the_cascade_started() {
    let hub = MessageHub::new();
    let child = ComponentVm::with_services("c1", hub.clone(), NullDispatcher::new());
    let composite = CompositeVm::<ComponentVm>::make(&hub, child.clone());
    composite.on_construct(|| Err(VmxError::Other("construct failed".to_string())));
    let composite_id = composite.id();
    let publications: Arc<Mutex<Vec<ConstructionStatus>>> = Arc::default();
    let subscription = hub.subscribe({
        let publications = Arc::clone(&publications);
        move |message| {
            if let Message::ConstructionStatusChanged(changed) = message {
                if changed.sender_id == composite_id {
                    publications.lock().unwrap().push(changed.status);
                }
            }
        }
    });
    let (resume, resume_rx) = mpsc::channel::<()>();
    let (returned, returned_rx) = mpsc::channel::<()>();
    child.on_dispose(move || {
        let _ = resume.send(());
        let _ = returned_rx.recv_timeout(BOUND);
        Ok(())
    });
    let (paused, paused_rx) = mpsc::channel::<()>();
    let (constructed, constructed_rx) = mpsc::channel();
    let runner = thread::spawn({
        let composite = composite.clone();
        move || {
            commit_pause::arm(composite_id, move || {
                paused.send(()).unwrap();
                let _ = resume_rx.recv_timeout(BOUND);
            });
            let result = composite.construct();
            let _ = returned.send(());
            constructed.send(result).unwrap();
        }
    });
    paused_rx.recv_timeout(BOUND).expect("the construct paused");

    assert_eq!(composite.dispose(), Ok(()));
    assert_eq!(
        constructed_rx.recv_timeout(BOUND).unwrap(),
        Err(VmxError::Other("construct failed".to_string()))
    );
    runner.join().unwrap();
    subscription.dispose();

    assert_eq!(
        *publications.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Disposed
        ]
    );
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
}
