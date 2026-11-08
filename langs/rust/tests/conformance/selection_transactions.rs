//! Selection during membership transactions (spec/06 §3.2, §4.3 and §5,
//! ADR-0165, ADR-0173).
//!
//! These rules are observable only while another operation is in flight, so,
//! as in ADR-0165, they have no conformance ID. Every cross-thread wait is
//! bounded by `GUARD`.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, ManualDispatcher, Message, MessageHub, VmNode,
    VmxError,
};

type Leaf = ComponentVm<&'static str, ManualDispatcher>;
type Root = CompositeVm<Leaf, ManualDispatcher>;
type Log = Arc<Mutex<Vec<String>>>;
/// What a callback's `dispose()` returned and the status it read afterwards.
type DisposalLog = Arc<Mutex<Vec<(Result<(), VmxError>, ConstructionStatus)>>>;

/// The hang guard for every cross-thread wait in this file.
const GUARD: Duration = Duration::from_secs(2);

fn leaf(name: &'static str) -> Leaf {
    ComponentVm::with_model(name, name, MessageHub::new(), ManualDispatcher::new())
}

fn background_leaf(name: &'static str, dispatcher: &ManualDispatcher) -> Leaf {
    ComponentVm::builder()
        .name(name)
        .model(name)
        .background(true)
        .services(MessageHub::new(), dispatcher.clone())
        .build()
        .unwrap()
}

fn root(name: &str, dispatcher: &ManualDispatcher) -> Root {
    CompositeVm::with_services(name, MessageHub::new(), dispatcher.clone())
}

fn name_of(current: Option<Leaf>) -> String {
    current.map_or_else(|| "None".to_string(), |child| child.name())
}

/// Records every value that `on_current_changed` receives.
fn record_current_changes(root: &Root) -> Log {
    let log: Log = Arc::default();
    let sink = Arc::clone(&log);
    root.on_current_changed(move |current| sink.lock().unwrap().push(name_of(current)));
    log
}

fn entries(log: &Log) -> Vec<String> {
    log.lock().unwrap().clone()
}

/// Runs `body` on another thread and returns its result within the guard.
fn within_guard<R: Send + 'static>(what: &str, body: impl FnOnce() -> R + Send + 'static) -> R {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(body());
    });
    match rx.recv_timeout(GUARD) {
        Ok(value) => value,
        Err(RecvTimeoutError::Timeout) => panic!("{what} did not finish within the hang guard"),
        Err(RecvTimeoutError::Disconnected) => panic!("{what} panicked"),
    }
}

/// A one-shot signal between two threads with a bounded wait.
#[derive(Clone)]
struct Signal {
    tx: mpsc::Sender<()>,
    rx: Arc<Mutex<mpsc::Receiver<()>>>,
}

impl Signal {
    fn new() -> Self {
        let (tx, rx) = mpsc::channel();
        Self {
            tx,
            rx: Arc::new(Mutex::new(rx)),
        }
    }

    fn set(&self) {
        let _ = self.tx.send(());
    }

    fn wait(&self, what: &str) {
        self.rx
            .lock()
            .unwrap()
            .recv_timeout(GUARD)
            .unwrap_or_else(|_| panic!("{what} within the hang guard"));
    }
}

/// A worker that holds `root`'s add transaction: it adds `child`, whose
/// construct hook (auto-construct on add) signals `entered` and then waits for
/// `release`. Returns the join handle of the add.
fn hold_add_transaction(
    root: &Root,
    child: &Leaf,
) -> (
    Signal,
    Signal,
    std::thread::JoinHandle<Result<(), VmxError>>,
) {
    let entered = Signal::new();
    let release = Signal::new();
    let (hook_entered, hook_release) = (entered.clone(), release.clone());
    child.on_construct(move || {
        hook_entered.set();
        hook_release.wait("the test releases the add");
        Ok(())
    });
    root.set_auto_construct_on_add(true);
    let (worker_root, worker_child) = (root.clone(), child.clone());
    let worker = std::thread::spawn(move || worker_root.add(worker_child));
    entered.wait("the worker's add reaches the child's construct hook");
    (entered, release, worker)
}

fn join_within_guard<R>(worker: std::thread::JoinHandle<R>, what: &str) -> R {
    let deadline = Instant::now() + GUARD;
    while !worker.is_finished() {
        assert!(
            Instant::now() < deadline,
            "{what} did not finish within the hang guard"
        );
        std::thread::yield_now();
    }
    worker.join().unwrap()
}

// ---------------------------------------------------------------------------
// The construct walk's assignment (#1151, ADR-0165 rules 1, 2, 4 and 5).
// ---------------------------------------------------------------------------

/// Case 1 of #1151: the walk resumes inside an add that has attached `late` but
/// not admitted it. The selector's `late` is not a committed member, and the
/// adding thread is inside its own uncommitted transaction, so the assignment
/// is a silent no-op.
fn walk_skips_unadmitted_child(attach: impl FnOnce(&Root, Leaf) -> Result<(), VmxError>) {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let first = background_leaf("first", &dispatcher);
    root.add(first.clone()).unwrap();
    root.add(leaf("second")).unwrap();
    let late = leaf("late");
    let selected = late.clone();
    root.set_current_selector(move |_| Some(selected.clone()));
    root.set_auto_construct_on_add(true);
    let log = record_current_changes(&root);
    let drain = dispatcher.clone();
    late.on_construct(move || {
        drain.drain();
        Ok(())
    });

    root.construct().unwrap();
    assert_eq!(root.status(), ConstructionStatus::Constructing);
    assert_eq!(attach(&root, late.clone()), Ok(()));

    assert_eq!(root.status(), ConstructionStatus::Constructed);
    assert!(root.items().contains(&late));
    assert_eq!(root.current(), None);
    assert!(!late.is_current());
    assert_eq!(late.status(), ConstructionStatus::Constructed);
    assert!(!entries(&log).contains(&"late".to_string()));
}

#[test]
fn walk_assignment_skips_a_child_that_add_has_not_admitted() {
    walk_skips_unadmitted_child(|root, late| root.add(late));
}

#[test]
fn walk_assignment_skips_a_child_that_insert_has_not_admitted() {
    walk_skips_unadmitted_child(|root, late| root.insert(0, late));
}

#[test]
fn walk_assignment_skips_a_child_that_replace_has_not_admitted() {
    walk_skips_unadmitted_child(|root, late| root.replace(1, late).map(|_| ()));
}

/// Case 2 of #1151: a selector that disposes the composite gets no assignment.
#[test]
fn walk_assignment_is_a_no_op_while_disposal_is_pending() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let a = leaf("a");
    root.add(a.clone()).unwrap();
    let disposer = root.clone();
    let selected = a.clone();
    root.set_current_selector(move |_| {
        disposer.dispose().unwrap();
        Some(selected.clone())
    });
    let log = record_current_changes(&root);

    assert_eq!(root.construct(), Ok(()));

    assert_eq!(root.current(), None);
    assert!(entries(&log).is_empty());
    assert!(!a.is_current());
    assert_eq!(root.status(), ConstructionStatus::Disposed);
}

/// Case 3 of #1151: a disposal from the walk's `on_current_changed` is
/// deferred until the publication ends.
#[test]
fn walk_callback_disposal_is_deferred_until_publication_ends() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let a = leaf("a");
    root.add(a.clone()).unwrap();
    let selected = a.clone();
    root.set_current_selector(move |_| Some(selected.clone()));
    let seen: DisposalLog = Arc::default();
    let (disposer, sink) = (root.clone(), Arc::clone(&seen));
    root.on_current_changed(move |current| {
        if current.is_some() {
            let disposed = disposer.dispose();
            sink.lock().unwrap().push((disposed, disposer.status()));
        }
    });

    root.construct().unwrap();

    assert_eq!(
        *seen.lock().unwrap(),
        vec![(Ok(()), ConstructionStatus::Constructing)]
    );
    assert_eq!(root.status(), ConstructionStatus::Disposed);
    assert_eq!(a.status(), ConstructionStatus::Disposed);
}

/// Case 3 of #1151 from a hub subscriber of the selected child's `is_current`.
#[test]
fn walk_current_flag_subscriber_disposal_is_deferred() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let a = leaf("a");
    root.add(a.clone()).unwrap();
    let selected = a.clone();
    root.set_current_selector(move |_| Some(selected.clone()));
    let seen: DisposalLog = Arc::default();
    let (disposer, sink, observed) = (root.clone(), Arc::clone(&seen), a.clone());
    let _subscription = a.hub().subscribe(move |message| {
        if let Message::PropertyChanged(change) = message {
            if change.property_name == "is_current" && observed.is_current() {
                let disposed = disposer.dispose();
                sink.lock().unwrap().push((disposed, disposer.status()));
            }
        }
    });

    root.construct().unwrap();

    assert_eq!(
        *seen.lock().unwrap(),
        vec![(Ok(()), ConstructionStatus::Constructing)]
    );
    assert_eq!(root.status(), ConstructionStatus::Disposed);
    assert_eq!(a.status(), ConstructionStatus::Disposed);
}

/// Case 3 of #1151, hand-off: while the deferred disposal waits for the
/// publication, an add on another thread is refused.
#[test]
fn deferred_walk_disposal_refuses_a_foreign_add() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let a = leaf("a");
    root.add(a.clone()).unwrap();
    let selected = a.clone();
    root.set_current_selector(move |_| Some(selected.clone()));
    let added: Arc<Mutex<Option<Result<(), VmxError>>>> = Arc::default();
    let (disposer, sink) = (root.clone(), Arc::clone(&added));
    let extra = leaf("extra");
    let extra_for_worker = extra.clone();
    root.on_current_changed(move |current| {
        if current.is_none() {
            return;
        }
        disposer.dispose().unwrap();
        let (worker_root, worker_child) = (disposer.clone(), extra_for_worker.clone());
        let result = within_guard("the foreign add", move || worker_root.add(worker_child));
        *sink.lock().unwrap() = Some(result);
    });

    root.construct().unwrap();

    assert_eq!(*added.lock().unwrap(), Some(Err(VmxError::Disposed)));
    assert_eq!(root.status(), ConstructionStatus::Disposed);
    assert!(!root.items().contains(&extra));
}

/// Builds case 4 of #1151: `root` constructs with a background child `first`
/// and selects it, while a worker holds `root`'s add of `y` and waits in the
/// old parent's remove handler for `root` to reach `Constructed`.
fn walk_under_foreign_transaction(dispose_from_callback: bool) {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let first = background_leaf("first", &dispatcher);
    root.add(first.clone()).unwrap();
    let selected = first.clone();
    root.set_current_selector(move |_| Some(selected.clone()));
    root.set_auto_construct_on_add(true);
    let callback: DisposalLog = Arc::default();
    if dispose_from_callback {
        let (disposer, sink) = (root.clone(), Arc::clone(&callback));
        root.on_current_changed(move |current| {
            if current.is_some() {
                let disposed = disposer.dispose();
                sink.lock().unwrap().push((disposed, disposer.status()));
            }
        });
    }
    let source_hub = MessageHub::new();
    let source: Root = CompositeVm::with_services("source", source_hub.clone(), dispatcher.clone());
    let y = leaf("y");
    source.add(y.clone()).unwrap();
    let entered = Signal::new();
    let owner_saw: Arc<Mutex<Option<ConstructionStatus>>> = Arc::default();
    let (handler_entered, handler_root, handler_saw) =
        (entered.clone(), root.clone(), Arc::clone(&owner_saw));
    let source_id = source.id();
    let _remove = source_hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            if change.sender_id != source_id {
                return;
            }
            handler_entered.set();
            let deadline = Instant::now() + GUARD;
            while handler_root.status() != ConstructionStatus::Constructed
                && Instant::now() < deadline
            {
                std::thread::yield_now();
            }
            *handler_saw.lock().unwrap() = Some(handler_root.status());
        }
    });

    root.construct().unwrap();
    let (worker_root, worker_y) = (root.clone(), y.clone());
    let worker = std::thread::spawn(move || worker_root.add(worker_y));
    entered.wait("the worker reaches the old parent's remove handler");
    let started = Instant::now();
    dispatcher.drain();
    assert!(
        started.elapsed() < GUARD / 2,
        "the walk's assignment waited for the foreign transaction"
    );
    assert_eq!(join_within_guard(worker, "the worker's add"), Ok(()));

    assert_eq!(
        *owner_saw.lock().unwrap(),
        Some(ConstructionStatus::Constructed)
    );
    if dispose_from_callback {
        assert_eq!(
            *callback.lock().unwrap(),
            vec![(Ok(()), ConstructionStatus::Constructing)]
        );
        assert_eq!(root.status(), ConstructionStatus::Disposed);
    } else {
        assert_eq!(root.status(), ConstructionStatus::Constructed);
        assert_eq!(root.current(), Some(first.clone()));
        assert!(first.is_current());
    }
}

#[test]
fn walk_callback_disposal_does_not_wait_for_a_foreign_transaction() {
    walk_under_foreign_transaction(true);
}

#[test]
fn walk_assignment_does_not_wait_for_a_foreign_transaction() {
    walk_under_foreign_transaction(false);
}

/// Case 5 of #1151 on the adding thread: the walk resumes inside `dest`'s add
/// while `root`'s transfer detach of `x` is uncommitted on that thread, so the
/// assignment is a silent no-op (spec/06 §4.3 rule 4). The transfer commit
/// then clears `x`, which is still current.
#[test]
fn walk_assignment_is_a_no_op_inside_the_threads_own_transfer() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let first = background_leaf("first", &dispatcher);
    let x = leaf("x");
    root.add(first.clone()).unwrap();
    root.add(x.clone()).unwrap();
    root.set_current(Some(x.clone())).unwrap();
    let selected = first.clone();
    root.set_current_selector(move |_| Some(selected.clone()));
    let log = record_current_changes(&root);
    let dest = self::root("dest", &dispatcher);
    dest.set_auto_construct_on_add(true);
    dest.construct().unwrap();
    let drain = dispatcher.clone();
    x.on_construct(move || {
        drain.drain();
        Ok(())
    });
    root.construct().unwrap();

    assert_eq!(dest.add(x.clone()), Ok(()));

    assert_eq!(root.status(), ConstructionStatus::Constructed);
    assert_eq!(root.current(), None);
    assert!(!first.is_current());
    assert!(!x.is_current());
    assert_eq!(entries(&log), vec!["None".to_string()]);
}

/// Rule 6 (detach clear): a selection that another thread makes while a
/// transfer has detached the current child stays when the transfer commits.
#[test]
fn transfer_commit_keeps_a_selection_made_after_the_detach() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let (first, x) = (leaf("first"), leaf("x"));
    root.add(first.clone()).unwrap();
    root.add(x.clone()).unwrap();
    root.set_current(Some(x.clone())).unwrap();
    let log = record_current_changes(&root);
    let dest = self::root("dest", &dispatcher);
    dest.construct().unwrap();
    let (_entered, release, worker) = hold_add_transaction(&dest, &x);

    // `root`'s detach of `x` is uncommitted on the worker thread.
    assert_eq!(root.set_current(Some(first.clone())), Ok(()));
    release.set();
    assert_eq!(join_within_guard(worker, "the transfer"), Ok(()));

    assert_eq!(root.current(), Some(first.clone()));
    assert!(first.is_current());
    assert!(!x.is_current());
    assert_eq!(entries(&log), vec!["first".to_string()]);
}

// ---------------------------------------------------------------------------
// Selection calls (#1145: ADR-0173 rules 1 to 4 and 7).
// ---------------------------------------------------------------------------

/// Rules 1 and 2: another thread's add neither fails nor delays a selection,
/// and the child it has not admitted is not a member.
#[test]
fn selection_commits_while_another_thread_holds_an_add() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let (a, b) = (leaf("a"), leaf("b"));
    root.add(a.clone()).unwrap();
    root.add(b.clone()).unwrap();
    root.construct().unwrap();
    let late = leaf("late");
    let (_entered, release, worker) = hold_add_transaction(&root, &late);

    let selector = root.clone();
    let (selected_a, staged) = (a.clone(), late.clone());
    let outcome = within_guard("selection during a foreign add", move || {
        (
            selector.set_current(Some(selected_a.clone())),
            selector.can_select_component(&selected_a),
            selector.set_current(Some(staged.clone())),
            selector.select_component(&staged),
            selector.can_select_component(&staged),
            selector.deselect_component(&selected_a),
            selector.select_component(&selected_a),
        )
    });
    release.set();
    assert_eq!(join_within_guard(worker, "the add"), Ok(()));

    assert_eq!(
        outcome,
        (
            Ok(()),
            true,
            Err(VmxError::NonChild),
            Err(VmxError::NonChild),
            false,
            Ok(()),
            Ok(())
        )
    );
    assert_eq!(root.current(), Some(a.clone()));
    assert!(a.is_current());
    assert!(!late.is_current());
    // Admitted now: selectable.
    assert_eq!(root.select_component(&late), Ok(()));
}

/// Rule 4: on the thread whose own add has not committed, every selection call
/// on the composite fails, a null clear too, and `Current` stays.
#[test]
fn selection_inside_the_threads_own_uncommitted_add_is_refused() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let a = leaf("a");
    root.add(a.clone()).unwrap();
    root.construct().unwrap();
    root.set_current(Some(a.clone())).unwrap();
    root.set_auto_construct_on_add(true);
    let late = leaf("late");
    type Seen = (
        Result<(), VmxError>,
        Result<(), VmxError>,
        Result<(), VmxError>,
        Result<(), VmxError>,
        bool,
    );
    let seen: Arc<Mutex<Option<Seen>>> = Arc::default();
    let (hook_root, hook_a, sink) = (root.clone(), a.clone(), Arc::clone(&seen));
    late.on_construct(move || {
        *sink.lock().unwrap() = Some((
            hook_root.set_current(Some(hook_a.clone())),
            hook_root.set_current(None),
            hook_root.select_component(&hook_a),
            hook_root.deselect_component(&hook_a),
            hook_root.can_select_component(&hook_a),
        ));
        Err(VmxError::Other("late fails".to_string()))
    });

    assert!(root.add(late.clone()).is_err());

    let refused = Err(VmxError::OwnershipTransactionInProgress);
    assert_eq!(
        seen.lock().unwrap().clone(),
        Some((
            refused.clone(),
            refused.clone(),
            refused.clone(),
            refused,
            false
        ))
    );
    assert_eq!(root.current(), Some(a.clone()));
    assert!(a.is_current());
    assert!(!root.items().contains(&late));
}

/// Rule 4 ends at the commit: a `CollectionChanged` subscriber on the adding
/// thread selects the child that was just added.
#[test]
fn collection_changed_subscriber_on_the_adding_thread_selects_the_new_child() {
    let dispatcher = ManualDispatcher::new();
    let hub = MessageHub::new();
    let root: Root = CompositeVm::with_services("root", hub.clone(), dispatcher.clone());
    root.construct().unwrap();
    let late = leaf("late");
    late.construct().unwrap();
    let selected: Arc<Mutex<Option<Result<(), VmxError>>>> = Arc::default();
    let (selector, child, sink, root_id) =
        (root.clone(), late.clone(), Arc::clone(&selected), root.id());
    let _subscription = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            if change.sender_id == root_id {
                *sink.lock().unwrap() = Some(selector.select_component(&child));
            }
        }
    });

    assert_eq!(root.add(late.clone()), Ok(()));

    assert_eq!(*selected.lock().unwrap(), Some(Ok(())));
    assert_eq!(root.current(), Some(late.clone()));
    assert!(late.is_current());
}

/// Rule 3: while disposal is deferred, a non-null selection is refused and a
/// null clear still commits.
#[test]
fn deferred_disposal_refuses_non_null_selection_but_not_a_clear() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let (a, b) = (leaf("a"), leaf("b"));
    root.add(a.clone()).unwrap();
    root.add(b.clone()).unwrap();
    root.construct().unwrap();
    root.set_current(Some(a.clone())).unwrap();
    root.set_auto_construct_on_add(true);
    let late = leaf("late");
    let entered = Signal::new();
    let release = Signal::new();
    let (hook_root, hook_entered, hook_release) = (root.clone(), entered.clone(), release.clone());
    late.on_construct(move || {
        // The add owns the transaction, so this disposal is deferred.
        hook_root.dispose().unwrap();
        hook_entered.set();
        hook_release.wait("the test releases the add");
        Ok(())
    });
    let (worker_root, worker_late) = (root.clone(), late.clone());
    let worker = std::thread::spawn(move || worker_root.add(worker_late));
    entered.wait("the worker defers the disposal");

    let selector = root.clone();
    let (selected_b, deselected_a) = (b.clone(), a.clone());
    let outcome = within_guard("selection while disposal is deferred", move || {
        (
            selector.set_current(Some(selected_b.clone())),
            selector.select_component(&selected_b),
            selector.can_select_component(&selected_b),
            selector.deselect_component(&deselected_a),
            selector.set_current(None),
            selector.current(),
        )
    });
    release.set();
    assert_eq!(
        join_within_guard(worker, "the add"),
        Err(VmxError::Disposed)
    );

    assert_eq!(
        outcome,
        (
            Err(VmxError::Disposed),
            Err(VmxError::Disposed),
            false,
            Ok(()),
            Ok(()),
            None
        )
    );
    assert!(!a.is_current());
    assert_eq!(root.status(), ConstructionStatus::Disposed);
}

/// Rule 5: a disposal on another thread while a selection publishes is
/// deferred through the lease and returns at once.
#[test]
fn foreign_disposal_during_a_selection_publication_is_deferred() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let a = leaf("a");
    root.add(a.clone()).unwrap();
    root.construct().unwrap();
    let entered = Signal::new();
    let release = Signal::new();
    let seen: Arc<Mutex<Vec<ConstructionStatus>>> = Arc::default();
    let (callback_root, callback_entered, callback_release, sink) = (
        root.clone(),
        entered.clone(),
        release.clone(),
        Arc::clone(&seen),
    );
    root.on_current_changed(move |current| {
        if current.is_some() {
            callback_entered.set();
            callback_release.wait("the test releases the publication");
            sink.lock().unwrap().push(callback_root.status());
        }
    });
    let (worker_root, worker_a) = (root.clone(), a.clone());
    let selection = std::thread::spawn(move || worker_root.set_current(Some(worker_a)));
    entered.wait("the selection publishes");

    let disposer = root.clone();
    assert_eq!(
        within_guard("dispose during a publication", move || disposer.dispose()),
        Ok(())
    );
    assert_eq!(root.status(), ConstructionStatus::Constructed);
    release.set();
    assert_eq!(join_within_guard(selection, "the selection"), Ok(()));

    assert_eq!(*seen.lock().unwrap(), vec![ConstructionStatus::Constructed]);
    assert_eq!(root.status(), ConstructionStatus::Disposed);
    assert_eq!(a.status(), ConstructionStatus::Disposed);
}

/// Rule 7: the asynchronous setter validates at call time without a
/// transaction, and its delivery validates again.
#[test]
fn async_selection_validates_at_call_time_and_at_delivery() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let (a, b) = (leaf("a"), leaf("b"));
    root.add(a.clone()).unwrap();
    root.add(b.clone()).unwrap();
    root.construct().unwrap();
    root.set_async_selection(true);
    let late = leaf("late");
    let (_entered, release, worker) = hold_add_transaction(&root, &late);

    let selector = root.clone();
    let (selected_a, staged) = (a.clone(), late.clone());
    let outcome = within_guard("async selection during a foreign add", move || {
        (
            selector.set_current(Some(selected_a)),
            selector.set_current(Some(staged)),
        )
    });
    assert_eq!(outcome, (Ok(()), Err(VmxError::NonChild)));
    assert_eq!(root.current(), None);
    dispatcher.drain_foreground();
    assert_eq!(root.current(), Some(a.clone()));
    release.set();
    assert_eq!(join_within_guard(worker, "the add"), Ok(()));

    // A delivery that is no longer valid drops silently.
    assert_eq!(root.set_current(Some(b.clone())), Ok(()));
    root.remove(&b).unwrap();
    dispatcher.drain_foreground();
    assert_eq!(root.current(), Some(a.clone()));
    assert!(!b.is_current());
}

/// Rule 7: the walk's assignment stays synchronous with async selection.
#[test]
fn walk_assignment_is_synchronous_with_async_selection() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let a = leaf("a");
    root.add(a.clone()).unwrap();
    root.set_async_selection(true);
    let selected = a.clone();
    root.set_current_selector(move |_| Some(selected.clone()));

    root.construct().unwrap();

    assert_eq!(root.status(), ConstructionStatus::Constructed);
    assert_eq!(root.current(), Some(a.clone()));
    assert!(a.is_current());
}

// ---------------------------------------------------------------------------
// The destruct clear (#1144, Rust part; ADR-0173 rule 8).
// ---------------------------------------------------------------------------

/// A disposal from `on_current_changed(None)` during destruct is deferred
/// until the clear's publication ends.
#[test]
fn destruct_clear_defers_a_callback_disposal() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let (a, b) = (leaf("a"), leaf("b"));
    root.add(a.clone()).unwrap();
    root.add(b.clone()).unwrap();
    root.construct().unwrap();
    root.set_current(Some(a.clone())).unwrap();
    let seen: DisposalLog = Arc::default();
    let (disposer, sink) = (root.clone(), Arc::clone(&seen));
    root.on_current_changed(move |current| {
        if current.is_none() {
            let disposed = disposer.dispose();
            sink.lock().unwrap().push((disposed, disposer.status()));
        }
    });

    let _ = root.destruct();

    assert_eq!(
        *seen.lock().unwrap(),
        vec![(Ok(()), ConstructionStatus::Destructing)]
    );
    assert_eq!(root.current(), None);
    assert!(!a.is_current());
    assert_eq!(root.status(), ConstructionStatus::Disposed);
    assert_eq!(a.status(), ConstructionStatus::Disposed);
    assert_eq!(b.status(), ConstructionStatus::Disposed);
}

/// The destruct clear runs inside the composite's own add publication.
#[test]
fn destruct_clear_runs_inside_the_composites_own_add() {
    let dispatcher = ManualDispatcher::new();
    let hub = MessageHub::new();
    let root: Root = CompositeVm::with_services("root", hub.clone(), dispatcher.clone());
    let first = leaf("first");
    root.add(first.clone()).unwrap();
    let selected = first.clone();
    root.set_current_selector(move |_| Some(selected.clone()));
    root.construct().unwrap();
    assert_eq!(root.current(), Some(first.clone()));
    let destructed: Arc<Mutex<Option<Result<(), VmxError>>>> = Arc::default();
    let (destructor, sink, root_id) = (root.clone(), Arc::clone(&destructed), root.id());
    let once = AtomicBool::new(false);
    let _subscription = hub.subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            if change.sender_id == root_id && !once.swap(true, Ordering::SeqCst) {
                *sink.lock().unwrap() = Some(destructor.destruct());
            }
        }
    });

    assert_eq!(root.add(leaf("late")), Ok(()));

    assert_eq!(*destructed.lock().unwrap(), Some(Ok(())));
    assert_eq!(root.status(), ConstructionStatus::Destructed);
    assert_eq!(root.current(), None);
    assert!(!first.is_current());
}

/// The destruct clear runs while disposal is deferred and while another
/// thread holds the composite's transfer transaction.
#[test]
fn destruct_clear_runs_while_disposal_is_deferred_by_a_foreign_transfer() {
    let dispatcher = ManualDispatcher::new();
    let root = root("root", &dispatcher);
    let first = leaf("first");
    root.add(first.clone()).unwrap();
    root.construct().unwrap();
    root.set_current(Some(first.clone())).unwrap();
    // `root` does not auto-construct on add, so `moved` stays Destructed and
    // `dest` constructs it during the transfer.
    let moved = leaf("moved");
    root.add(moved.clone()).unwrap();
    let dest = self::root("dest", &dispatcher);
    dest.construct().unwrap();
    let entered = Signal::new();
    let release = Signal::new();
    let (hook_root, hook_entered, hook_release) = (root.clone(), entered.clone(), release.clone());
    moved.on_construct(move || {
        // The worker owns `root`'s detach transaction: this disposal defers.
        hook_root.dispose().unwrap();
        hook_entered.set();
        hook_release.wait("the test releases the transfer");
        Ok(())
    });
    dest.set_auto_construct_on_add(true);
    let (worker_dest, worker_moved) = (dest.clone(), moved.clone());
    let worker = std::thread::spawn(move || worker_dest.add(worker_moved));
    entered.wait("the worker defers root's disposal");

    let destructor = root.clone();
    let destructed = within_guard("destruct while disposal is deferred", move || {
        let result = destructor.destruct();
        (result, destructor.current())
    });
    release.set();
    let _ = join_within_guard(worker, "the transfer");

    assert_eq!(destructed.1, None);
    assert!(!first.is_current());
    assert_eq!(root.status(), ConstructionStatus::Disposed);
}

/// Records what another thread saw when it tried to select `moved` in
/// `dest` from `old`'s detach-commit callback: `can_select_component` and the
/// `set_current` result.
type CommitWindowLog = Arc<Mutex<Option<(bool, Result<(), VmxError>)>>>;

/// Rule 2 with a transfer (COMP-006): the destination admits the moved child
/// after the old parent's detach commit. That commit clears the child's
/// `is_current` flag; an earlier admission would let another thread select
/// the child in the destination first, and the commit would then reset the
/// flag of a child that is current there. During the old parent's commit,
/// another thread's selection of the child in the destination is refused.
/// Rust admits in this order already; the test pins it for add, insert and
/// replace (the population path is private in Rust).
#[test]
fn transfer_destination_admits_the_moved_child_after_the_old_parents_detach_commit() {
    for operation in ["add", "insert", "replace"] {
        let dispatcher = ManualDispatcher::new();
        let old = root("old", &dispatcher);
        let moved = leaf("moved");
        old.add(moved.clone()).unwrap();
        old.construct().unwrap();
        old.set_current(Some(moved.clone())).unwrap();
        assert!(moved.is_current());
        let dest = root("dest", &dispatcher);
        if operation == "replace" {
            dest.add(leaf("filler")).unwrap();
        }
        dest.construct().unwrap();
        let seen: CommitWindowLog = Arc::default();
        let armed = Arc::new(AtomicBool::new(true));
        let (sink, window_dest, window_child) = (Arc::clone(&seen), dest.clone(), moved.clone());
        old.on_current_changed(move |current| {
            if current.is_some() || !armed.swap(false, Ordering::SeqCst) {
                return;
            }
            let (dest, child) = (window_dest.clone(), window_child.clone());
            let observed = within_guard("the foreign selection", move || {
                let can_select = dest.can_select_component(&child);
                (can_select, dest.set_current(Some(child)))
            });
            *sink.lock().unwrap() = Some(observed);
        });

        match operation {
            "add" => dest.add(moved.clone()).unwrap(),
            "insert" => dest.insert(0, moved.clone()).unwrap(),
            _ => drop(dest.replace(0, moved.clone()).unwrap()),
        }

        let observed = seen.lock().unwrap().take();
        assert_eq!(
            observed,
            Some((false, Err(VmxError::NonChild))),
            "{operation}: the moved child is not admitted during the old parent's commit"
        );
        assert_eq!(old.current(), None, "{operation}");
        assert_eq!(dest.current(), None, "{operation}");
        assert!(!moved.is_current(), "{operation}");
        dest.set_current(Some(moved.clone())).unwrap();
        assert!(moved.is_current(), "{operation}");
    }
}

// ---------------------------------------------------------------------------
// Replacing the current child (#1219).

/// The action a `FreeProbe` runs once, right after its parent is cleared.
type FreeAction = Arc<Mutex<Option<Box<dyn FnOnce() + Send>>>>;

/// A leaf that runs a test action once, right after a container clears its
/// parent. Another thread can adopt the child at that point, so the action
/// stands in for that thread (#1219).
#[derive(Clone)]
struct FreeProbe {
    inner: Leaf,
    on_freed: FreeAction,
}

impl FreeProbe {
    fn new(name: &'static str) -> Self {
        Self {
            inner: leaf(name),
            on_freed: Arc::default(),
        }
    }

    fn arm(&self, action: impl FnOnce() + Send + 'static) {
        *self.on_freed.lock().unwrap() = Some(Box::new(action));
    }
}

impl PartialEq for FreeProbe {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl VmNode for FreeProbe {
    fn id(&self) -> usize {
        self.inner.id()
    }

    fn construct(&self) -> vmx::VmxResult<()> {
        self.inner.construct()
    }

    fn destruct(&self) -> vmx::VmxResult<()> {
        self.inner.destruct()
    }

    fn dispose(&self) -> vmx::VmxResult<()> {
        self.inner.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        VmNode::set_parent_id(&self.inner, parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        VmNode::parent_id(&self.inner)
    }

    fn set_parent_handle(&self, parent: Option<vmx::ParentHandle>) {
        let freed = parent.is_none();
        VmNode::set_parent_handle(&self.inner, parent);
        if freed {
            let action = self.on_freed.lock().unwrap().take();
            if let Some(action) = action {
                action();
            }
        }
    }

    fn parent_handle(&self) -> Option<vmx::ParentHandle> {
        VmNode::parent_handle(&self.inner)
    }

    fn set_current_flag(&self, is_current: bool) {
        VmNode::set_current_flag(&self.inner, is_current);
    }

    fn commit_current_flag(&self, is_current: bool) -> bool {
        VmNode::commit_current_flag(&self.inner, is_current)
    }

    fn publish_current_flag(&self, is_current: bool) {
        VmNode::publish_current_flag(&self.inner, is_current);
    }

    fn is_current(&self) -> bool {
        VmNode::is_current(&self.inner)
    }
}

/// #1219 — the replacement commit clears the replaced child as current before
/// it frees the child, as `remove_at` does. A container that adopts and
/// selects the freed child keeps its selection and the child's flag
/// (COMP-006, spec/06 §4.3 rule 6).
#[test]
fn replacement_clears_the_old_current_child_before_it_frees_it() {
    let dispatcher = ManualDispatcher::new();
    let sut: CompositeVm<FreeProbe, ManualDispatcher> =
        CompositeVm::with_services("sut", MessageHub::new(), dispatcher.clone());
    let other: CompositeVm<FreeProbe, ManualDispatcher> =
        CompositeVm::with_services("other", MessageHub::new(), dispatcher);
    let (a, b) = (FreeProbe::new("a"), FreeProbe::new("b"));
    sut.add(a.clone()).unwrap();
    sut.add(b.clone()).unwrap();
    sut.set_current(Some(a.clone())).unwrap();
    let adopted: Arc<Mutex<Option<vmx::VmxResult<()>>>> = Arc::default();
    let (adopter, child, sink) = (other.clone(), a.clone(), Arc::clone(&adopted));
    a.arm(move || {
        let result = adopter
            .add(child.clone())
            .and_then(|()| adopter.set_current(Some(child)));
        *sink.lock().unwrap() = Some(result);
    });

    let replaced = sut.replace(0, FreeProbe::new("replacement")).unwrap();

    assert_eq!(replaced.id(), a.id());
    assert_eq!(
        *adopted.lock().unwrap(),
        Some(Ok(())),
        "another container adopts and selects the freed child"
    );
    assert_eq!(sut.current().map(|c| c.id()), None);
    assert_eq!(other.current().map(|c| c.id()), Some(a.id()));
    assert!(
        VmNode::is_current(&a),
        "the replacement's clear never resets a selection in another composite"
    );
}
