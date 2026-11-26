//! The supported child-transition helper and depth-first member disposal
//! (spec/02 §6.1 and §7.1, ADR-0162).
//!
//! Rust has no subclassing, so each "leaf view-model" here is a consumer type
//! defined in this test crate: it composes a `ComponentVm`, keeps its members
//! in fields, and drives them through `construct_with_children`,
//! `destruct_with_children`, `then`, and `own_member`.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use vmx::{
    ComponentVm, ConstructionStatus, GroupVm, ManualDispatcher, Message, MessageHub, Subscription,
    VmxError, VmxResult,
};

type Child = ComponentVm<i32, ManualDispatcher>;
type Parent = ComponentVm<(), ManualDispatcher>;
type Log = Arc<Mutex<Vec<Event>>>;

#[derive(Debug, Clone, PartialEq, Eq)]
enum Event {
    Status(usize, ConstructionStatus),
    After,
}

/// A leaf view-model whose construct and destruct walk its member children in
/// the order they are stored.
struct Leaf {
    component: Parent,
    children: Vec<Child>,
}

impl Leaf {
    fn new(hub: &MessageHub, dispatcher: &ManualDispatcher, children: Vec<Child>) -> Self {
        Self {
            component: Parent::with_services("leaf", hub.clone(), dispatcher.clone()),
            children,
        }
    }

    fn id(&self) -> usize {
        self.component.id()
    }

    fn status(&self) -> ConstructionStatus {
        self.component.status()
    }

    fn construct_then<F>(&self, after: F) -> VmxResult<()>
    where
        F: FnOnce() -> VmxResult<()> + Send + 'static,
    {
        let children = self.children.clone();
        self.component.construct_with_children(move |walk| {
            for child in &children {
                walk.transition(child)?;
            }
            walk.then(after)
        })
    }

    fn construct(&self) -> VmxResult<()> {
        self.construct_then(|| Ok(()))
    }

    fn destruct(&self) -> VmxResult<()> {
        let children = self.children.clone();
        self.component.destruct_with_children(move |walk| {
            for child in &children {
                walk.transition(child)?;
            }
            Ok(())
        })
    }
}

fn child(hub: &MessageHub, dispatcher: &ManualDispatcher, name: &str, background: bool) -> Child {
    ComponentVm::builder()
        .name(name)
        .model(1)
        .background(background)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap()
}

fn failing_child(hub: &MessageHub, dispatcher: &ManualDispatcher, name: &str) -> Child {
    ComponentVm::builder()
        .name(name)
        .model(1)
        .on_construct(|| Err(VmxError::Other("child construct failed".to_string())))
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap()
}

fn record(hub: &MessageHub) -> (Log, Subscription) {
    let log: Log = Arc::default();
    let sink = Arc::clone(&log);
    let subscription = hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(change) = message {
            sink.lock()
                .unwrap()
                .push(Event::Status(change.sender_id, change.status));
        }
    });
    (log, subscription)
}

fn position(log: &Log, event: &Event) -> usize {
    log.lock()
        .unwrap()
        .iter()
        .position(|entry| entry == event)
        .unwrap_or_else(|| panic!("{event:?} never recorded"))
}

/// LIFE-016 — the helper waits for a background child: the parent stays
/// Constructing, the next child and `then` wait, and the parent publishes
/// Constructed only after both children and `then`.
#[test]
fn helper_waits_for_background_child() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let a = child(&hub, &dispatcher, "a", true);
    let b = child(&hub, &dispatcher, "b", false);
    let leaf = Leaf::new(&hub, &dispatcher, vec![a.clone(), b.clone()]);
    let (log, _subscription) = record(&hub);
    let after_runs = Arc::new(AtomicUsize::new(0));
    let after_log = Arc::clone(&log);
    let counter = Arc::clone(&after_runs);

    leaf.construct_then(move || {
        counter.fetch_add(1, Ordering::SeqCst);
        after_log.lock().unwrap().push(Event::After);
        Ok(())
    })
    .unwrap();

    assert_eq!(leaf.status(), ConstructionStatus::Constructing);
    assert_eq!(a.status(), ConstructionStatus::Constructing);
    assert_eq!(b.status(), ConstructionStatus::Destructed);
    assert_eq!(after_runs.load(Ordering::SeqCst), 0);

    dispatcher.drain();

    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
    assert_eq!(leaf.status(), ConstructionStatus::Constructed);
    assert_eq!(after_runs.load(Ordering::SeqCst), 1);
    let a_done = position(
        &log,
        &Event::Status(a.id(), ConstructionStatus::Constructed),
    );
    let b_start = position(
        &log,
        &Event::Status(b.id(), ConstructionStatus::Constructing),
    );
    let b_done = position(
        &log,
        &Event::Status(b.id(), ConstructionStatus::Constructed),
    );
    let after = position(&log, &Event::After);
    let leaf_done = position(
        &log,
        &Event::Status(leaf.id(), ConstructionStatus::Constructed),
    );
    assert!(a_done < b_start);
    assert!(b_done < after);
    assert!(after < leaf_done);
}

/// LIFE-017 — a child failure in the helper rolls the parent back, surfaces
/// from the call, keeps the sibling that already constructed, and never
/// starts the next child.
#[test]
fn child_failure_rolls_parent_back() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let a = child(&hub, &dispatcher, "a", false);
    let b = failing_child(&hub, &dispatcher, "b");
    let c = child(&hub, &dispatcher, "c", false);
    let leaf = Leaf::new(&hub, &dispatcher, vec![a.clone(), b.clone(), c.clone()]);
    let (log, _subscription) = record(&hub);

    let result = leaf.construct();

    assert_eq!(
        result,
        Err(VmxError::Other("child construct failed".to_string()))
    );
    assert_eq!(leaf.status(), ConstructionStatus::Destructed);
    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Destructed);
    assert_eq!(c.status(), ConstructionStatus::Destructed);
    assert!(!log
        .lock()
        .unwrap()
        .contains(&Event::Status(c.id(), ConstructionStatus::Constructing)));
}

/// LIFE-017 — a background child that fails after the call returned rolls the
/// parent back through the background-failure path and never starts the next
/// child.
#[test]
fn background_child_failure_rolls_parent_back() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let a = child(&hub, &dispatcher, "a", false);
    let b: Child = ComponentVm::builder()
        .name("b")
        .model(1)
        .background(true)
        .on_construct(|| Err(VmxError::Other("child construct failed".to_string())))
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let c = child(&hub, &dispatcher, "c", false);
    let leaf = Leaf::new(&hub, &dispatcher, vec![a.clone(), b.clone(), c.clone()]);
    let (errors_send, errors) = mpsc::channel();
    let _errors = leaf.component.background_errors().subscribe(move |error| {
        errors_send.send(error).unwrap();
    });

    leaf.construct().unwrap();
    assert_eq!(leaf.status(), ConstructionStatus::Constructing);
    dispatcher.drain();

    assert_eq!(leaf.status(), ConstructionStatus::Destructed);
    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Destructed);
    assert_eq!(c.status(), ConstructionStatus::Destructed);
    assert!(matches!(errors.try_recv(), Ok(VmxError::Other(_))));
}

/// A leaf view-model whose members are a group (with one child) and a plain
/// component, both registered for depth-first disposal.
struct Dashboard {
    component: Parent,
    group: GroupVm<Child, ManualDispatcher>,
    grouped: Child,
    detail: Child,
}

impl Dashboard {
    fn new(hub: &MessageHub, dispatcher: &ManualDispatcher) -> Self {
        let component = Parent::with_services("dashboard", hub.clone(), dispatcher.clone());
        let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
        let grouped = child(hub, dispatcher, "grouped", false);
        group.add(grouped.clone()).unwrap();
        let detail = child(hub, dispatcher, "detail", false);
        component.own_member(&group).unwrap();
        component.own_member(&detail).unwrap();
        Self {
            component,
            group,
            grouped,
            detail,
        }
    }

    fn construct(&self) -> VmxResult<()> {
        let (group, detail) = (self.group.clone(), self.detail.clone());
        self.component.construct_with_children(move |walk| {
            walk.transition(&group)?;
            walk.transition(&detail)
        })
    }
}

fn disposed_senders(log: &Log) -> Vec<usize> {
    log.lock()
        .unwrap()
        .iter()
        .filter_map(|event| match event {
            Event::Status(id, ConstructionStatus::Disposed) => Some(*id),
            _ => None,
        })
        .collect()
}

/// LIFE-018 — registered members are disposed depth-first, in registration
/// order, before the parent publishes Disposed.
#[test]
fn members_dispose_depth_first_before_parent() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let dashboard = Dashboard::new(&hub, &dispatcher);
    dashboard.construct().unwrap();
    assert_eq!(dashboard.grouped.status(), ConstructionStatus::Constructed);
    let (log, _subscription) = record(&hub);

    dashboard.component.dispose().unwrap();

    assert_eq!(
        disposed_senders(&log),
        vec![
            dashboard.grouped.id(),
            dashboard.group.id(),
            dashboard.detail.id(),
            dashboard.component.id(),
        ]
    );
}

/// LIFE-018 — a failing member disposal hook does not strand the next member
/// or the parent, and the first failure is returned.
#[test]
fn member_disposal_failure_is_best_effort() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let dashboard = Dashboard::new(&hub, &dispatcher);
    dashboard
        .group
        .on_dispose(|| Err(VmxError::Other("group dispose failed".to_string())));
    dashboard
        .detail
        .on_dispose(|| Err(VmxError::Other("detail dispose failed".to_string())));
    dashboard.construct().unwrap();
    let (log, _subscription) = record(&hub);

    let result = dashboard.component.dispose();

    assert_eq!(
        result,
        Err(VmxError::Other("group dispose failed".to_string()))
    );
    assert_eq!(dashboard.group.status(), ConstructionStatus::Disposed);
    assert_eq!(dashboard.detail.status(), ConstructionStatus::Disposed);
    assert_eq!(dashboard.component.status(), ConstructionStatus::Disposed);
    assert_eq!(
        disposed_senders(&log),
        vec![
            dashboard.grouped.id(),
            dashboard.group.id(),
            dashboard.detail.id(),
            dashboard.component.id(),
        ]
    );
}

/// LIFE-018 — a member registered after the parent reached Disposed is
/// disposed when it is registered.
#[test]
fn member_registered_after_disposal_is_disposed_at_once() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let dashboard = Dashboard::new(&hub, &dispatcher);
    dashboard.component.dispose().unwrap();
    let late = child(&hub, &dispatcher, "late", false);

    dashboard.component.own_member(&late).unwrap();

    assert_eq!(late.status(), ConstructionStatus::Disposed);
}

/// LIFE-019 — the helper destructs background children in the order the
/// caller passes, one at a time, and the parent publishes Destructed last.
#[test]
fn helper_destructs_in_caller_order() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let a = child(&hub, &dispatcher, "a", true);
    let b = child(&hub, &dispatcher, "b", true);
    let c = child(&hub, &dispatcher, "c", true);
    // The leaf stores its children reversed, so its destruct walks c, b, a.
    let leaf = Leaf::new(&hub, &dispatcher, vec![c.clone(), b.clone(), a.clone()]);
    for vm in [&a, &b, &c] {
        vm.construct().unwrap();
    }
    leaf.component.construct().unwrap();
    dispatcher.drain();
    assert!([&a, &b, &c]
        .iter()
        .all(|vm| vm.status() == ConstructionStatus::Constructed));
    let (log, _subscription) = record(&hub);

    leaf.destruct().unwrap();
    assert_eq!(leaf.status(), ConstructionStatus::Destructing);
    assert_eq!(c.status(), ConstructionStatus::Destructing);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
    dispatcher.drain();

    use ConstructionStatus::{Destructed, Destructing};
    assert_eq!(
        *log.lock().unwrap(),
        vec![
            Event::Status(leaf.id(), Destructing),
            Event::Status(c.id(), Destructing),
            Event::Status(c.id(), Destructed),
            Event::Status(b.id(), Destructing),
            Event::Status(b.id(), Destructed),
            Event::Status(a.id(), Destructing),
            Event::Status(a.id(), Destructed),
            Event::Status(leaf.id(), Destructed),
        ]
    );
}

/// LIFE-020 — the helper joins a child that is already Constructing: no
/// lifecycle transition error, the child's hook runs once, and the parent
/// stays Constructing until the child settles.
#[test]
fn helper_joins_child_in_transit() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let hook_runs = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&hook_runs);
    let a: Child = ComponentVm::builder()
        .name("a")
        .model(1)
        .background(true)
        .on_construct(move || {
            counter.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let leaf = Leaf::new(&hub, &dispatcher, vec![a.clone()]);
    let (log, _subscription) = record(&hub);
    a.construct().unwrap();
    assert_eq!(a.status(), ConstructionStatus::Constructing);

    assert_eq!(leaf.construct(), Ok(()));
    assert_eq!(leaf.status(), ConstructionStatus::Constructing);
    dispatcher.drain();

    assert_eq!(hook_runs.load(Ordering::SeqCst), 1);
    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(leaf.status(), ConstructionStatus::Constructed);
    assert!(
        position(
            &log,
            &Event::Status(a.id(), ConstructionStatus::Constructed)
        ) < position(
            &log,
            &Event::Status(leaf.id(), ConstructionStatus::Constructed)
        )
    );
}

/// A child whose construct hook counts its runs.
fn counting_child(
    hub: &MessageHub,
    dispatcher: &ManualDispatcher,
    name: &str,
) -> (Child, Arc<AtomicUsize>) {
    let runs = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&runs);
    let child = ComponentVm::builder()
        .name(name)
        .model(1)
        .on_construct(move || {
            counter.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    (child, runs)
}

/// LIFE-023 — a walk that lists its own view-model fails with the usage error
/// before it starts a child: the view-model rolls back, and the sibling listed
/// after it never runs its hook.
#[test]
fn walk_listing_its_own_view_model_fails_and_starts_no_child() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let walker = child(&hub, &dispatcher, "walker", false);
    let (sibling, sibling_runs) = counting_child(&hub, &dispatcher, "sibling");
    let (me, after) = (walker.clone(), sibling.clone());
    walker.on_construct_children(move |walk| {
        walk.transition(&me)?;
        walk.transition(&after)
    });

    let result = walker.construct();

    assert!(matches!(result, Err(VmxError::OwnershipCycle)));
    assert_eq!(walker.status(), ConstructionStatus::Destructed);
    assert_eq!(sibling.status(), ConstructionStatus::Destructed);
    assert_eq!(sibling_runs.load(Ordering::SeqCst), 0);
}

/// LIFE-024 — two view-models whose walks list each other: construct on one
/// fails with the cycle error, and both end settled instead of Constructing.
#[test]
fn walks_listing_each_other_both_settle() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let p = child(&hub, &dispatcher, "p", false);
    let q = child(&hub, &dispatcher, "q", false);
    let (q_handle, p_handle) = (q.clone(), p.clone());
    p.on_construct_children(move |walk| walk.transition(&q_handle));
    q.on_construct_children(move |walk| walk.transition(&p_handle));

    let result = p.construct();

    assert!(matches!(result, Err(VmxError::OwnershipCycle)));
    assert_eq!(p.status(), ConstructionStatus::Destructed);
    assert_eq!(q.status(), ConstructionStatus::Destructed);
}

/// LIFE-024 — a leaf whose walk lists its own group: the group's construct
/// fails with the cycle error, and the group rolls back.
#[test]
fn leaf_walking_its_own_group_fails_the_group() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    let leaf = child(&hub, &dispatcher, "leaf", false);
    group.add(leaf.clone()).unwrap();
    let group_handle = group.clone();
    leaf.on_construct_children(move |walk| walk.transition(&group_handle));

    let result = group.construct();

    assert!(matches!(result, Err(VmxError::OwnershipCycle)));
    assert_eq!(group.status(), ConstructionStatus::Destructed);
    assert_eq!(leaf.status(), ConstructionStatus::Destructed);
}

/// LIFE-020 — the diamond control: two walks that share one child construct
/// all three view-models, and the shared child's hook runs once.
#[test]
fn diamond_walks_construct_all_three_view_models() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let (shared, shared_runs) = counting_child(&hub, &dispatcher, "shared");
    let a = child(&hub, &dispatcher, "a", false);
    let b = child(&hub, &dispatcher, "b", false);
    let (shared_for_a, shared_for_b) = (shared.clone(), shared.clone());
    a.on_construct_children(move |walk| walk.transition(&shared_for_a));
    b.on_construct_children(move |walk| walk.transition(&shared_for_b));

    a.construct().unwrap();
    b.construct().unwrap();

    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
    assert_eq!(shared.status(), ConstructionStatus::Constructed);
    assert_eq!(shared_runs.load(Ordering::SeqCst), 1);
}

/// Sets its flag when the last model handle drops.
struct DropSentinel(Arc<AtomicBool>);

impl Drop for DropSentinel {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

impl PartialEq for DropSentinel {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }
}

type Tracked = ComponentVm<Arc<DropSentinel>, ManualDispatcher>;

/// A component whose model sets the returned flag when it drops.
fn tracked_child(
    hub: &MessageHub,
    dispatcher: &ManualDispatcher,
    name: &str,
) -> (Tracked, Arc<AtomicBool>) {
    let dropped = Arc::new(AtomicBool::new(false));
    let child = ComponentVm::builder()
        .name(name)
        .model(Arc::new(DropSentinel(Arc::clone(&dropped))))
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    (child, dropped)
}

/// LIFE-024 — after a refused cycle both components are freed. Only `q`
/// stores a walk, and it captures `p`; `p`'s walk is passed to
/// `construct_with_children` and is not kept, so no stored walk forms a
/// reference loop (#750).
#[test]
fn refused_cycle_frees_both_components() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let (p, p_dropped) = tracked_child(&hub, &dispatcher, "p");
    let (q, q_dropped) = tracked_child(&hub, &dispatcher, "q");
    let p_for_q = p.clone();
    q.on_construct_children(move |walk| walk.transition(&p_for_q));
    let q_for_p = q.clone();

    let result = p.construct_with_children(move |walk| walk.transition(&q_for_p));

    assert!(matches!(result, Err(VmxError::OwnershipCycle)));
    assert_eq!(p.status(), ConstructionStatus::Destructed);
    assert_eq!(q.status(), ConstructionStatus::Destructed);
    drop(p);
    drop(q);
    assert!(
        p_dropped.load(Ordering::SeqCst),
        "the refused cycle leaked p"
    );
    assert!(
        q_dropped.load(Ordering::SeqCst),
        "the refused cycle leaked q"
    );
}

/// LIFE-024 — a member whose construct hook adds a child to its own group (a
/// late add) makes the group's walk wait on a child whose walk waits back on
/// the group. The group's walk refuses the late join with the cycle error,
/// and both end settled.
#[test]
fn late_add_closing_a_walk_cycle_is_refused() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    group.set_auto_construct_on_add(true);
    let late = child(&hub, &dispatcher, "late", false);
    let group_handle = group.clone();
    late.on_construct_children(move |walk| walk.transition(&group_handle));
    let (group_for_member, late_for_member) = (group.clone(), late.clone());
    let member: Child = ComponentVm::builder()
        .name("member")
        .model(1)
        .on_construct(move || group_for_member.add(late_for_member.clone()))
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    group.add(member.clone()).unwrap();

    let result = group.construct();
    dispatcher.drain();

    assert!(matches!(result, Err(VmxError::OwnershipCycle)));
    assert_eq!(group.status(), ConstructionStatus::Destructed);
    assert_eq!(late.status(), ConstructionStatus::Destructed);
}
