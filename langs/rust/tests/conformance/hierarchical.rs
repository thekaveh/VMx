use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::time::Duration;

use vmx::{
    walk_expanded, Command, ConstructionStatus, ExpandableState, HierarchicalVm, Message,
    MessageHub, ModeledCrudCommands, NullDispatcher, Reconstructable, SearchableState,
    TreeStructureChange, VmNode, VmxError,
};

fn leaf(name: &str) -> HierarchicalVm<String> {
    HierarchicalVm::new(name, name.to_string())
}

/// Error texts the hierarchy rejects with. Each test pins its text, so a change
/// to the wording fails a test (ADR-0247 D2: error texts do not change).
const FACTORY_CYCLE_MESSAGE: &str = "children factory returned this node or one of its ancestors";
const FACTORY_PARENTED_MESSAGE: &str = "children factory returned an already-parented child";
const CYCLE_MESSAGE: &str = "cannot reparent self or ancestor";

/// HIER-031 — factory hydration validates the complete snapshot before mutation.
#[test]
fn factory_hydration_is_atomic_and_retryable() {
    let first = leaf("first");
    let second = leaf("second");
    let grandchild = leaf("grandchild");
    first.add_child(grandchild.clone()).unwrap();
    assert_eq!(
        grandchild
            .path()
            .iter()
            .map(|node| node.model())
            .collect::<Vec<_>>(),
        vec!["first", "grandchild"]
    );
    let snapshot = Arc::new(Mutex::new(vec![first.clone(), first.clone()]));
    let captured = Arc::clone(&snapshot);
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| captured.lock().unwrap().clone(),
        false,
        hub.clone(),
    );

    assert!(matches!(
        root.try_children(),
        Err(VmxError::InvalidArgument(message)) if message.contains("factory")
    ));
    assert!(first.parent().is_none());
    assert!(recorder.messages().is_empty(), "no message on rejection");

    *snapshot.lock().unwrap() = vec![first.clone(), second.clone()];
    assert!(root.try_children().unwrap() == vec![first.clone(), second.clone()]);
    assert!(first.parent().as_ref() == Some(&root));
    assert!(second.parent().as_ref() == Some(&root));
    assert_eq!(
        grandchild
            .path()
            .iter()
            .map(|node| node.model())
            .collect::<Vec<_>>(),
        vec!["root", "first", "grandchild"]
    );
}

/// HIER-031 — self and already-parented factory results are rejected.
#[test]
fn factory_hydration_rejects_invalid_topology() {
    let self_slot = Arc::new(Mutex::new(None::<HierarchicalVm<String>>));
    let captured = Arc::clone(&self_slot);
    let self_node = HierarchicalVm::with_children_factory(
        "self",
        "self".to_string(),
        move |_| vec![captured.lock().unwrap().as_ref().unwrap().clone()],
        false,
        MessageHub::new(),
    );
    *self_slot.lock().unwrap() = Some(self_node.clone());
    assert!(matches!(
        self_node.try_children(),
        Err(VmxError::InvalidArgument(message)) if message == FACTORY_CYCLE_MESSAGE
    ));
    assert!(self_node.parent().is_none());

    // An ancestor in the snapshot is rejected without any hub publication.
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let ancestor = HierarchicalVm::with_children_factory(
        "ancestor",
        "ancestor".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let fresh = leaf("fresh");
    let ancestor_slot = Arc::new(Mutex::new(vec![ancestor.clone()]));
    let captured = Arc::clone(&ancestor_slot);
    let descendant = HierarchicalVm::with_children_factory(
        "descendant",
        "descendant".to_string(),
        move |_| captured.lock().unwrap().clone(),
        false,
        hub.clone(),
    );
    ancestor.add_child(descendant.clone()).unwrap();
    let before = recorder.messages().len();
    assert!(matches!(
        descendant.try_children(),
        Err(VmxError::InvalidArgument(message)) if message == FACTORY_CYCLE_MESSAGE
    ));
    assert_eq!(recorder.messages().len(), before, "no message on rejection");
    assert!(ancestor.parent().is_none());
    assert!(descendant.parent().as_ref() == Some(&ancestor));
    assert!(ancestor.children() == vec![descendant.clone()]);
    // A later access retries the factory.
    *ancestor_slot.lock().unwrap() = vec![fresh.clone()];
    assert!(descendant.try_children().unwrap() == vec![fresh.clone()]);
    assert!(fresh.parent().as_ref() == Some(&descendant));

    let old_parent = leaf("old");
    let attached = leaf("attached");
    old_parent.add_child(attached.clone()).unwrap();
    let captured_attached = attached.clone();
    let new_parent = HierarchicalVm::with_children_factory(
        "new",
        "new".to_string(),
        move |_| vec![captured_attached.clone()],
        false,
        MessageHub::new(),
    );
    assert!(matches!(
        new_parent.try_children(),
        Err(VmxError::InvalidArgument(message)) if message == FACTORY_PARENTED_MESSAGE
    ));
    assert!(attached.parent().as_ref() == Some(&old_parent));
    assert!(old_parent.children() == vec![attached.clone()]);
}

/// HIER-031 — a factory that returns its node's tree root is a cycle, so the
/// root is refused with the ancestor text and nothing moves (ADR-0248 R1).
#[test]
fn factory_returning_the_tree_root_is_a_cycle() {
    let root = leaf("root");
    let returned = root.clone();
    let mid = HierarchicalVm::with_children_factory(
        "mid",
        "mid".to_string(),
        move |_| vec![returned.clone()],
        false,
        MessageHub::new(),
    );
    root.add_child(mid.clone()).unwrap();

    assert!(matches!(
        mid.try_children(),
        Err(VmxError::InvalidArgument(message)) if message == FACTORY_CYCLE_MESSAGE
    ));
    assert!(root.parent().is_none());
    assert!(mid.parent().as_ref() == Some(&root));
    assert!(root.children() == vec![mid.clone()]);
}

/// HIER-032 — structural factory reentry rejects atomically and remains retryable.
#[test]
fn factory_structural_reentry_is_rejected_and_retryable() {
    for operation in [
        "add",
        "remove",
        "reparent",
        "attach",
        "invalidate-children",
        "invalidate-subtree",
    ] {
        let hub = MessageHub::new();
        let messages = Arc::new(Mutex::new(Vec::<Message>::new()));
        let captured_messages = Arc::clone(&messages);
        let _subscription = hub.subscribe(move |message| {
            captured_messages.lock().unwrap().push(message.clone());
        });
        let child = HierarchicalVm::with_children_factory(
            "child",
            "child".to_string(),
            |_| Vec::new(),
            false,
            hub.clone(),
        );
        let captured_child = child.clone();
        let first_attempt = Arc::new(AtomicUsize::new(0));
        let captured_attempt = Arc::clone(&first_attempt);
        let root = HierarchicalVm::with_children_factory(
            "root",
            "root".to_string(),
            move |parent| {
                if captured_attempt.fetch_add(1, Ordering::SeqCst) == 0 {
                    if operation == "add" {
                        let _ = parent.add_child(captured_child.clone());
                    } else if operation == "remove" {
                        let _ = parent.remove_child(&captured_child);
                    } else if operation == "reparent" {
                        let _ = parent.reparent_child(&captured_child);
                    } else if operation == "attach" {
                        let _ = parent.attach_many(
                            vec![captured_child.clone()],
                            |node| Ok(node.model()),
                            |_| Ok(None::<String>),
                            vmx::MissingParentPolicy::Park,
                        );
                    } else if operation == "invalidate-children" {
                        parent.invalidate_children();
                    } else {
                        parent.invalidate_subtree();
                    }
                }
                vec![captured_child.clone()]
            },
            false,
            hub,
        );

        assert!(
            root.try_children().is_err(),
            "{operation} reentry must fail"
        );
        assert!(child.parent().is_none());
        assert!(child.path() == vec![child.clone()]);
        assert_eq!(first_attempt.load(Ordering::SeqCst), 1);
        assert!(messages.lock().unwrap().is_empty());
        assert!(root.try_children().unwrap() == vec![child.clone()]);
        assert!(child.parent().as_ref() == Some(&root));
        assert_eq!(first_attempt.load(Ordering::SeqCst), 2);
        assert!(messages.lock().unwrap().is_empty());
    }
}

/// HIER-032 — unrelated structural overlap rejects without poisoning hydration.
#[test]
fn foreign_structural_overlap_is_bounded_without_poisoning_hydration() {
    let child = leaf("child");
    let captured_child = child.clone();
    let attempts = Arc::new(AtomicUsize::new(0));
    let captured_attempts = Arc::clone(&attempts);
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let captured_release = Arc::clone(&release_rx);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            if captured_attempts.fetch_add(1, Ordering::SeqCst) == 0 {
                entered_tx.send(()).unwrap();
                captured_release.lock().unwrap().recv().unwrap();
            }
            vec![captured_child.clone()]
        },
        false,
        MessageHub::new(),
    );

    let (result_tx, result_rx) = mpsc::channel();
    let first_root = root.clone();
    std::thread::spawn(move || {
        result_tx.send(first_root.try_children()).unwrap();
    });
    entered_rx.recv_timeout(Duration::from_millis(500)).unwrap();

    assert!(root.add_child(leaf("unrelated")).is_err());
    release_tx.send(()).unwrap();
    match result_rx.recv_timeout(Duration::from_millis(500)) {
        Ok(Ok(items)) => assert!(items == vec![child.clone()]),
        Ok(Err(error)) => panic!("unrelated overlap poisoned hydration: {error}"),
        Err(error) => panic!("hydration did not complete: {error}"),
    }
    assert!(child.parent().as_ref() == Some(&root));
    assert_eq!(attempts.load(Ordering::SeqCst), 1);
}

/// HIER-032 — factory work delegated to a joined thread still poisons hydration.
#[test]
fn delegated_factory_structural_reentry_is_rejected_and_retryable() {
    let hub = MessageHub::new();
    let messages = Arc::new(Mutex::new(Vec::<Message>::new()));
    let captured_messages = Arc::clone(&messages);
    let _subscription = hub.subscribe(move |message| {
        captured_messages.lock().unwrap().push(message.clone());
    });
    let child = leaf("child");
    let captured_child = child.clone();
    let attempts = Arc::new(AtomicUsize::new(0));
    let captured_attempts = Arc::clone(&attempts);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |parent| {
            if captured_attempts.fetch_add(1, Ordering::SeqCst) == 0 {
                let delegated_parent: HierarchicalVm<String> = (*parent).clone();
                let delegated_child = captured_child.clone();
                assert!(matches!(
                    std::thread::spawn(move || delegated_parent.add_child(delegated_child))
                        .join()
                        .unwrap(),
                    Err(VmxError::InvalidArgument(message)) if message.contains("factory re-entered")
                ));
            }
            vec![captured_child.clone()]
        },
        false,
        hub,
    );

    assert!(root.try_children().is_err());
    assert!(child.parent().is_none());
    assert!(child.path() == vec![child.clone()]);
    assert_eq!(attempts.load(Ordering::SeqCst), 1);
    assert!(messages.lock().unwrap().is_empty());

    assert!(root.try_children().unwrap() == vec![child.clone()]);
    assert!(child.parent().as_ref() == Some(&root));
    assert_eq!(attempts.load(Ordering::SeqCst), 2);
    assert!(messages.lock().unwrap().is_empty());
}

/// HIER-032 — a scoped worker borrowing the factory receiver remains causal.
#[test]
fn borrowed_factory_structural_reentry_is_rejected_and_retryable() {
    let hub = MessageHub::new();
    let messages = Arc::new(Mutex::new(Vec::<Message>::new()));
    let captured_messages = Arc::clone(&messages);
    let _subscription = hub.subscribe(move |message| {
        captured_messages.lock().unwrap().push(message.clone());
    });
    let child = leaf("child");
    let captured_child = child.clone();
    let attempts = Arc::new(AtomicUsize::new(0));
    let captured_attempts = Arc::clone(&attempts);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |parent| {
            if captured_attempts.fetch_add(1, Ordering::SeqCst) == 0 {
                let delegated_child = captured_child.clone();
                std::thread::scope(|scope| {
                    assert!(matches!(
                        scope
                            .spawn(move || parent.add_child(delegated_child))
                            .join()
                            .unwrap(),
                        Err(VmxError::InvalidArgument(message))
                            if message.contains("factory re-entered")
                    ));
                });
            }
            vec![captured_child.clone()]
        },
        false,
        hub,
    );

    assert!(root.try_children().is_err());
    assert!(child.parent().is_none());
    assert!(child.path() == vec![child.clone()]);
    assert_eq!(attempts.load(Ordering::SeqCst), 1);
    assert!(messages.lock().unwrap().is_empty());

    assert!(root.try_children().unwrap() == vec![child.clone()]);
    assert!(child.parent().as_ref() == Some(&root));
    assert_eq!(attempts.load(Ordering::SeqCst), 2);
    assert!(messages.lock().unwrap().is_empty());
}

/// HIER-032 — delegated recursive reads reject instead of waiting on their factory.
#[test]
fn delegated_factory_recursive_reads_are_bounded_and_retryable() {
    for (cloned_worker, panicking_reader) in
        [(false, false), (false, true), (true, false), (true, true)]
    {
        let hub = MessageHub::new();
        let messages = Arc::new(Mutex::new(Vec::<Message>::new()));
        let captured_messages = Arc::clone(&messages);
        let _subscription = hub.subscribe(move |message| {
            captured_messages.lock().unwrap().push(message.clone());
        });
        let child = leaf("child");
        let captured_child = child.clone();
        let attempts = Arc::new(AtomicUsize::new(0));
        let captured_attempts = Arc::clone(&attempts);
        let root = HierarchicalVm::with_children_factory(
            "root",
            "root".to_string(),
            move |parent| {
                if captured_attempts.fetch_add(1, Ordering::SeqCst) == 0 {
                    let rejected = if cloned_worker {
                        let delegated_parent: HierarchicalVm<String> = (*parent).clone();
                        if panicking_reader {
                            std::thread::spawn(move || delegated_parent.children())
                                .join()
                                .is_err()
                        } else {
                            matches!(
                                std::thread::spawn(move || delegated_parent.try_children())
                                    .join()
                                    .unwrap(),
                                Err(VmxError::InvalidArgument(message))
                                    if message.contains("re-entered")
                            )
                        }
                    } else if panicking_reader {
                        std::thread::scope(|scope| {
                            scope.spawn(move || parent.children()).join().is_err()
                        })
                    } else {
                        std::thread::scope(|scope| {
                            matches!(
                                scope.spawn(move || parent.try_children()).join().unwrap(),
                                Err(VmxError::InvalidArgument(message))
                                    if message.contains("re-entered")
                            )
                        })
                    };
                    assert!(rejected);
                }
                vec![captured_child.clone()]
            },
            false,
            hub,
        );

        let (result_tx, result_rx) = mpsc::channel();
        let first_root = root.clone();
        std::thread::spawn(move || {
            result_tx.send(first_root.try_children()).unwrap();
        });
        assert!(
            result_rx
                .recv_timeout(Duration::from_millis(500))
                .unwrap()
                .is_err(),
            "delegated recursive read must reject outer hydration"
        );
        assert!(child.parent().is_none());
        assert!(child.path() == vec![child.clone()]);
        assert_eq!(attempts.load(Ordering::SeqCst), 1);
        assert!(messages.lock().unwrap().is_empty());

        assert!(root.try_children().unwrap() == vec![child.clone()]);
        assert!(child.parent().as_ref() == Some(&root));
        assert_eq!(attempts.load(Ordering::SeqCst), 2);
        assert!(messages.lock().unwrap().is_empty());
    }
}

/// HIER-032 — a rejected owner releases state before a waiting owner starts.
#[test]
fn rejected_factory_handoff_cannot_clear_the_successor_state() {
    let child = leaf("child");
    let captured_child = child.clone();
    let attempts = Arc::new(AtomicUsize::new(0));
    let captured_attempts = Arc::clone(&attempts);
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let captured_release = Arc::clone(&release_rx);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |parent| {
            if captured_attempts.fetch_add(1, Ordering::SeqCst) == 0 {
                let _ = parent.add_child(captured_child.clone());
                entered_tx.send(()).unwrap();
                captured_release.lock().unwrap().recv().unwrap();
            }
            vec![captured_child.clone()]
        },
        false,
        MessageHub::new(),
    );

    let (first_tx, first_rx) = mpsc::channel();
    let first_root = root.clone();
    let first = std::thread::spawn(move || {
        first_tx.send(first_root.try_children().is_err()).unwrap();
    });
    entered_rx.recv_timeout(Duration::from_millis(500)).unwrap();

    let (second_tx, second_rx) = mpsc::channel();
    let second_root = root.clone();
    let second = std::thread::spawn(move || {
        second_tx
            .send(second_root.try_children().map(|items| items.len()))
            .unwrap();
    });
    release_tx.send(()).unwrap();

    assert_eq!(first_rx.recv_timeout(Duration::from_millis(500)), Ok(true));
    assert!(matches!(
        second_rx.recv_timeout(Duration::from_millis(500)),
        Ok(Ok(1))
    ));
    first.join().unwrap();
    second.join().unwrap();
    assert!(child.parent().as_ref() == Some(&root));
}

/// Consumer node data: the Rust form of a `TVM` subclass (ADR-0202).
struct FolderData {
    size: u64,
}

type Folder = HierarchicalVm<String, FolderData>;

/// Adds a method to every folder node, as a `TVM` subclass would.
trait FolderExt {
    fn size(&self) -> u64;
}

impl FolderExt for Folder {
    fn size(&self) -> u64 {
        self.node_data().size
    }
}

/// A folder whose children factory returns `children` once.
fn folder(name: &str, size: u64, children: Vec<Folder>) -> Folder {
    let children = Mutex::new(Some(children));
    HierarchicalVm::with_node_data(
        name,
        name.to_string(),
        FolderData { size },
        move |_| children.lock().unwrap().take().unwrap_or_default(),
        false,
        MessageHub::new(),
    )
}

/// HIER-001 — Recursive generic constraint compiles
#[test]
fn recursive_generic_shape_compiles() {
    let root = leaf("root");

    assert_eq!(root.model(), "root");

    // root (1) -> a (2) -> aa (3), each node of type `Folder`.
    let aa = folder("aa", 3, Vec::new());
    let a = folder("a", 2, vec![aa.clone()]);
    let root: Folder = folder("root", 1, vec![a.clone()]);

    assert_eq!(root.children()[0].node_data().size, 2);
    assert_eq!(a.children()[0].size(), 3);
    assert_eq!(aa.parent().unwrap().node_data().size, 2);
    assert_eq!(
        aa.path()
            .iter()
            .map(|node| node.node_data().size)
            .collect::<Vec<_>>(),
        [1, 2, 3]
    );
    assert_eq!(root.size(), 1);
}

#[test]
fn node_data_builder_builds_a_root_with_data() {
    let root = vmx::HierarchicalVmBuilder::with_node_data(FolderData { size: 7 })
        .model("root".to_string())
        .children_factory(|_: &Folder| vec![folder("child", 8, Vec::new())])
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .unwrap();

    assert_eq!(root.node_data().size, 7);
    assert_eq!(root.children()[0].size(), 8);

    let missing_services = vmx::HierarchicalVmBuilder::with_node_data(FolderData { size: 7 })
        .model("root".to_string())
        .children_factory(|_: &Folder| Vec::new())
        .build();
    assert!(matches!(
        missing_services,
        Err(VmxError::BuilderValidation(message)) if message.contains("services")
    ));
}

#[test]
fn node_data_survives_attach_many_and_reparent() {
    let root = folder("root", 1, Vec::new());
    let a = folder("a", 2, Vec::new());
    let b = folder("b", 3, Vec::new());
    let result: vmx::BatchAttachResult<Folder> = root.attach_many(
        vec![b.clone(), a.clone()],
        |item| Ok(item.model()),
        |item| Ok((item.model() == "b").then(|| "a".to_string())),
        vmx::MissingParentPolicy::Reject,
    );

    assert_eq!(
        result
            .added
            .iter()
            .map(|node| node.node_data().size)
            .collect::<Vec<_>>(),
        [2, 3]
    );
    assert_eq!(b.parent().unwrap().size(), 2);

    root.reparent_child(&b).unwrap();

    assert_eq!(b.parent().unwrap().size(), 1);
    assert_eq!(
        root.children()
            .iter()
            .map(FolderExt::size)
            .collect::<Vec<_>>(),
        [2, 3]
    );
}

#[test]
fn clones_share_node_data() {
    let child = HierarchicalVm::with_node_data(
        "child",
        "child".to_string(),
        AtomicUsize::new(0),
        |_| Vec::new(),
        false,
        MessageHub::new(),
    );
    let root = HierarchicalVm::with_node_data(
        "root",
        "root".to_string(),
        AtomicUsize::new(0),
        |_| Vec::new(),
        false,
        MessageHub::new(),
    );
    root.add_child(child.clone()).unwrap();

    child.clone().node_data().store(5, Ordering::SeqCst);

    assert_eq!(child.node_data().load(Ordering::SeqCst), 5);
    assert_eq!(root.children()[0].node_data().load(Ordering::SeqCst), 5);
    assert_eq!(
        child.parent().unwrap().node_data().load(Ordering::SeqCst),
        0
    );
}

/// HIER-002 — Parent is null for root, non-null for non-root
#[test]
fn parent_is_set_for_child_not_root() {
    let root = leaf("root");
    let child = leaf("child");
    root.add_child(child.clone()).unwrap();

    assert!(root.parent().is_none());
    assert_eq!(child.parent().unwrap().id(), root.id());
}

/// HIER-003 — Depth derivation
#[test]
fn depth_is_derived_from_parent_chain() {
    let root = leaf("root");
    let child = leaf("child");
    let grandchild = leaf("grandchild");
    child.add_child(grandchild.clone()).unwrap();
    root.add_child(child.clone()).unwrap();

    assert_eq!(root.depth(), 0);
    assert_eq!(child.depth(), 1);
    assert_eq!(grandchild.depth(), 2);
}

/// HIER-004 — Path materialization and cache identity
#[test]
fn path_materializes_root_first_and_updates_after_reparent() {
    let root = leaf("root");
    let other = leaf("other");
    let child = leaf("child");
    let grandchild = leaf("grandchild");
    child.add_child(grandchild.clone()).unwrap();
    root.add_child(child).unwrap();

    let path = grandchild
        .path()
        .into_iter()
        .map(|node| node.model())
        .collect::<Vec<_>>();
    assert_eq!(path, vec!["root", "child", "grandchild"]);

    other.reparent_child(&grandchild).unwrap();
    let updated = grandchild
        .path()
        .into_iter()
        .map(|node| node.model())
        .collect::<Vec<_>>();
    assert_eq!(updated, vec!["other", "grandchild"]);
}

/// HIER-005 — IsLeaf and IsRoot derivation
#[test]
fn root_and_leaf_flags_are_derived() {
    let root = leaf("root");
    let a = leaf("a");
    let b = leaf("b");
    root.add_child(a.clone()).unwrap();
    root.add_child(b.clone()).unwrap();

    assert!(root.is_root());
    assert!(!root.is_leaf());
    assert!(!a.is_root());
    assert!(a.is_leaf());
    assert!(b.is_leaf());
}

/// HIER-006 — IsFirst and IsLast position predicates
#[test]
fn sibling_position_flags_are_derived() {
    let root = leaf("root");
    let a = leaf("a");
    let b = leaf("b");
    let c = leaf("c");
    root.add_child(a.clone()).unwrap();
    root.add_child(b.clone()).unwrap();
    root.add_child(c.clone()).unwrap();

    assert!(a.is_first());
    assert!(!a.is_last());
    assert!(!b.is_first());
    assert!(!b.is_last());
    assert!(c.is_last());
    assert!(!root.is_first());
    assert!(!root.is_last());
}

/// HIER-007 — Default lazy child loading
#[test]
fn children_factory_is_lazy_by_default() {
    let calls = Arc::new(Mutex::new(0));
    let seen = calls.clone();
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            *seen.lock().unwrap() += 1;
            vec![leaf("child")]
        },
        false,
        MessageHub::new(),
    );

    assert_eq!(*calls.lock().unwrap(), 0);
    assert_eq!(root.children().len(), 1);
    assert_eq!(*calls.lock().unwrap(), 1);
}

#[test]
fn concurrent_children_materialization_runs_factory_once() {
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&calls);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            observed.fetch_add(1, Ordering::SeqCst);
            std::thread::sleep(Duration::from_millis(100));
            vec![leaf("child")]
        },
        false,
        MessageHub::new(),
    );
    let start = Arc::new(Barrier::new(3));
    let mut workers = Vec::new();
    for _ in 0..2 {
        let root = root.clone();
        let start = Arc::clone(&start);
        workers.push(std::thread::spawn(move || {
            start.wait();
            root.children()
        }));
    }

    start.wait();
    for worker in workers {
        assert_eq!(worker.join().unwrap().len(), 1);
    }
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn concurrent_reparenting_keeps_one_parent_child_pair() {
    const PARENT_COUNT: usize = 32;
    let child = leaf("child");
    let parents = (0..PARENT_COUNT)
        .map(|index| leaf(&format!("parent-{index}")))
        .collect::<Vec<_>>();
    let start = Arc::new(Barrier::new(PARENT_COUNT + 1));
    let mut workers = Vec::new();
    for parent in &parents {
        let parent = parent.clone();
        let child = child.clone();
        let start = Arc::clone(&start);
        workers.push(std::thread::spawn(move || {
            start.wait();
            parent.add_child(child)
        }));
    }

    start.wait();
    for worker in workers {
        worker.join().unwrap().unwrap();
    }

    let parent_id = child.parent().expect("child must remain attached").id();
    let memberships = parents
        .iter()
        .flat_map(HierarchicalVm::children)
        .filter(|candidate| candidate.id() == child.id())
        .collect::<Vec<_>>();
    assert_eq!(memberships.len(), 1);
    assert!(parents
        .iter()
        .find(|parent| parent.id() == parent_id)
        .unwrap()
        .children()
        .iter()
        .any(|candidate| candidate.id() == child.id()));
}

/// HIER-008 — Eager child loading via constructor option
#[test]
fn eager_construct_materializes_descendants() {
    // root -> {a -> {a1 -> {a1x}}, b}: three levels below the root.
    fn eager_node(name: &str, calls: Arc<Mutex<Vec<String>>>) -> HierarchicalVm<String> {
        HierarchicalVm::with_children_factory(
            name,
            name.to_string(),
            move |node| {
                let model = node.model();
                calls.lock().unwrap().push(model.clone());
                let children: &[&str] = match model.as_str() {
                    "root" => &["a", "b"],
                    "a" => &["a1"],
                    "a1" => &["a1x"],
                    _ => &[],
                };
                children
                    .iter()
                    .map(|child| eager_node(child, calls.clone()))
                    .collect()
            },
            true,
            MessageHub::new(),
        )
    }
    let calls = Arc::new(Mutex::new(Vec::new()));
    let root = eager_node("root", calls.clone());
    assert!(calls.lock().unwrap().is_empty());

    root.construct().unwrap();

    let mut invoked = calls.lock().unwrap().clone();
    invoked.sort();
    assert_eq!(invoked, vec!["a", "a1", "a1x", "b", "root"]);

    // Every descendant is materialized before any explicit children access.
    let mut stack = vec![root.clone()];
    let mut visited = Vec::new();
    while let Some(node) = stack.pop() {
        assert!(node.is_children_materialized(), "{}", node.model());
        visited.push(node.model());
        stack.extend(node.children());
    }
    visited.sort();
    assert_eq!(visited, vec!["a", "a1", "a1x", "b", "root"]);
    assert_eq!(calls.lock().unwrap().len(), 5, "no factory re-invocation");
}

/// HIER-009 — Depth-first construction order (eager mode)
#[test]
fn eager_construction_is_depth_first() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let child_hub = hub.clone();
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            let grand_hub = child_hub.clone();
            vec![HierarchicalVm::with_children_factory(
                "child",
                "child".to_string(),
                {
                    let leaf_hub = grand_hub.clone();
                    move |_| {
                        vec![HierarchicalVm::with_children_factory(
                            "grandchild",
                            "grandchild".to_string(),
                            |_| Vec::new(),
                            false,
                            leaf_hub.clone(),
                        )]
                    }
                },
                true,
                grand_hub,
            )]
        },
        true,
        hub.clone(),
    );

    root.construct().unwrap();

    let a = root.children().remove(0);
    let aa = a.children().remove(0);
    let constructed = recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change)
                if change.status == ConstructionStatus::Constructed =>
            {
                Some(change.sender_id)
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    // Full depth-first order: AA before A, A before root, root last.
    assert_eq!(constructed, vec![aa.id(), a.id(), root.id()]);
    assert_eq!(aa.status(), ConstructionStatus::Constructed);
}

fn eager_tree(hub: &MessageHub) -> HierarchicalVm<String> {
    let child_hub = hub.clone();
    HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            vec![HierarchicalVm::with_children_factory(
                "child",
                "child".to_string(),
                |_| Vec::new(),
                false,
                child_hub.clone(),
            )]
        },
        true,
        hub.clone(),
    )
}

/// HIER-009 — Eager construction enters the parent's Constructing before any child
#[test]
fn eager_construction_starts_the_parent_before_its_children() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let root = eager_tree(&hub);

    root.construct().unwrap();

    let first = recorder
        .messages()
        .into_iter()
        .find_map(|message| match message {
            Message::ConstructionStatusChanged(change) => Some(change.sender_id),
            _ => None,
        });
    assert_eq!(first, Some(root.id()));
}

/// HIER-009 — A rejected construct does not construct eager children
#[test]
fn a_rejected_eager_construct_leaves_children_untouched() {
    let hub = MessageHub::new();
    let root = eager_tree(&hub);
    let child = root.try_children().unwrap().remove(0);
    root.dispose().unwrap();

    assert!(root.construct().is_err());
    assert_eq!(child.status(), ConstructionStatus::Destructed);
}

/// HIER-009 — Constructing an already-constructed eager parent is a no-op
#[test]
fn constructing_a_constructed_eager_parent_does_not_touch_children() {
    let hub = MessageHub::new();
    let root = eager_tree(&hub);
    root.construct().unwrap();
    let child = root.try_children().unwrap().remove(0);
    child.dispose().unwrap();

    assert_eq!(root.construct(), Ok(()));
}

/// HIER-045 — Eager construction skips a disposed child (spec/18 §3, ADR-0258)
#[test]
fn eager_construction_skips_a_disposed_child() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let a = HierarchicalVm::with_children_factory(
        "a",
        "a".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let b = HierarchicalVm::with_children_factory(
        "b",
        "b".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let (a_child, b_child) = (a.clone(), b.clone());
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| vec![a_child.clone(), b_child.clone()],
        true,
        hub.clone(),
    );

    root.construct().unwrap();
    a.dispose().unwrap();
    VmNode::destruct(&root).unwrap();
    VmNode::destruct(&b).unwrap();
    let before = recorder.messages().len();

    // construct() and reconstruct() must not fail: the walk skips the disposed child.
    root.construct().unwrap();
    Reconstructable::reconstruct(&root);

    assert_eq!(root.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
    assert_eq!(a.status(), ConstructionStatus::Disposed);
    let a_changes = recorder
        .messages()
        .into_iter()
        .skip(before)
        .filter(|message| {
            matches!(message, Message::ConstructionStatusChanged(change) if change.sender_id == a.id())
        })
        .count();
    assert_eq!(
        a_changes, 0,
        "a disposed child publishes no construction-status change"
    );
}

/// HIER-010 — PropertyChangedMessage on Parent change
#[test]
fn parent_change_publishes_property_changed() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let child = HierarchicalVm::with_children_factory(
        "child",
        "child".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );

    root.add_child(child).unwrap();

    assert!(recorder.messages().iter().any(
        |message| matches!(message, Message::PropertyChanged(change) if change.property_name == "parent")
    ));
}

/// HIER-011 — TreeStructureChangedMessage on structural mutations
#[test]
fn structural_mutations_publish_tree_structure_changed() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let destination = HierarchicalVm::with_children_factory(
        "destination",
        "destination".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let child = leaf("child");

    root.add_child(child.clone()).unwrap();
    root.remove_child(&child).unwrap();
    root.add_child(child.clone()).unwrap();
    destination.reparent_child(&child).unwrap();

    let changes = recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::TreeStructureChanged(change) => Some(change),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(changes.len(), 4);
    assert_eq!(changes[0].sender_id, root.id());
    assert_eq!(changes[0].change, TreeStructureChange::Added);
    assert_eq!(changes[0].affected_id, child.id());
    assert_eq!(changes[0].index, 0);
    assert_eq!(changes[1].sender_id, root.id());
    assert_eq!(changes[1].change, TreeStructureChange::Removed);
    assert_eq!(changes[1].affected_id, child.id());
    assert_eq!(changes[1].index, 0);
    assert_eq!(changes[2].change, TreeStructureChange::Added);
    assert_eq!(changes[2].affected_id, child.id());
    assert_eq!(changes[2].index, 0);
    assert_eq!(changes[3].sender_id, destination.id());
    assert_eq!(changes[3].change, TreeStructureChange::Reparented);
    assert_eq!(changes[3].affected_id, child.id());
    assert_eq!(changes[3].index, -1);
}

#[test]
fn explicit_reparent_of_detached_child_reports_reparented() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let destination = HierarchicalVm::with_children_factory(
        "destination",
        "destination".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let detached = leaf("detached");

    destination.reparent_child(&detached).unwrap();

    let changes = recorder
        .messages()
        .into_iter()
        .filter_map(|message| match message {
            Message::TreeStructureChanged(change) => Some(change),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(changes.len(), 1);
    assert_eq!(changes[0].change, TreeStructureChange::Reparented);
    assert_eq!(changes[0].affected_id, detached.id());
    assert_eq!(changes[0].index, -1);
}

#[test]
fn removing_a_non_child_is_a_noop() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let foreign = leaf("foreign");

    root.remove_child(&foreign).unwrap();

    assert!(root.children().is_empty());
    assert!(foreign.parent().is_none());
    assert!(!recorder
        .messages()
        .iter()
        .any(|message| matches!(message, Message::TreeStructureChanged(_))));
}

/// HIER-012 — walk_expanded honors lazy boundaries via ExpandableState
#[test]
fn walk_expanded_honors_hierarchy_expansion_boundary() {
    let root = leaf("root");
    root.compose_expansion(ExpandableState::new()).unwrap();
    root.add_child(leaf("child")).unwrap();

    assert_eq!(walk_expanded(&root).unwrap().len(), 1);
    root.expansion().unwrap().expand();
    assert_eq!(walk_expanded(&root).unwrap().len(), 2);
    assert!(
        root.compose_expansion(ExpandableState::new()).is_err(),
        "a node composes one expansion state"
    );
}

/// HIER-013 — Composition with SearchableState filters materialized portion
#[test]
fn searchable_state_filters_materialized_nodes() {
    let root = leaf("root");
    // A grandchild that matches below a node whose children are materialized,
    // so the search must cover deeper nodes, not only the root's children
    // (#1399).
    let alpha = leaf("alpha");
    alpha.add_child(leaf("alpaca")).unwrap();
    assert!(alpha.is_children_materialized());
    root.add_child(alpha).unwrap();
    root.add_child(leaf("beta")).unwrap();
    root.add_child(leaf("alps")).unwrap();
    let lazy_calls = Arc::new(AtomicUsize::new(0));
    let lazy_seen = lazy_calls.clone();
    // A lazy node whose un-materialized child would match the term.
    let lazy = HierarchicalVm::with_children_factory(
        "lazy",
        "lazy".to_string(),
        move |_| {
            lazy_seen.fetch_add(1, Ordering::SeqCst);
            vec![leaf("alpine")]
        },
        false,
        MessageHub::new(),
    );
    root.add_child(lazy.clone()).unwrap();
    assert!(!lazy.is_children_materialized());

    // Search the materialized portion only: never force a lazy factory.
    let tree = root.clone();
    let state = SearchableState::from_items(
        move || {
            let mut nodes = Vec::new();
            let mut stack = vec![tree.clone()];
            while let Some(node) = stack.pop() {
                if node.is_children_materialized() {
                    let mut children = node.children();
                    children.reverse();
                    stack.extend(children);
                }
                nodes.push(node);
            }
            nodes
        },
        |node: &HierarchicalVm<String>, term: &str| node.model().contains(term),
    );
    state.set_search_term("alp");

    let filtered = state.filtered();
    assert_eq!(
        filtered.iter().map(|node| node.model()).collect::<Vec<_>>(),
        vec!["alpha", "alpaca", "alps"],
        "exactly the matching materialized nodes, in walk order"
    );
    assert!(
        !filtered.iter().any(|node| node.model() == "alpine"),
        "the un-materialized lazy child is not in the results"
    );
    assert_eq!(lazy_calls.load(Ordering::SeqCst), 0);
    assert!(!lazy.is_children_materialized());
}

/// HIER-014 — Composition with ModeledCrudCommands mutates the tree
#[test]
fn modeled_crud_commands_can_mutate_tree_children() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let tree_changes = |recorder: &vmx::MessageRecorder| {
        recorder
            .messages()
            .into_iter()
            .filter_map(|message| match message {
                Message::TreeStructureChanged(change) => {
                    Some((change.sender_id, change.change, change.affected_id))
                }
                _ => None,
            })
            .collect::<Vec<_>>()
    };
    let current = Arc::new(Mutex::new(None::<HierarchicalVm<String>>));
    let current_for_create = current.clone();
    let root_for_create = root.clone();
    let root_for_delete = root.clone();
    let current_for_delete = current.clone();
    let crud = ModeledCrudCommands::new(
        move || current.lock().unwrap().clone(),
        move || {
            let child = leaf("created");
            root_for_create.add_child(child.clone()).unwrap();
            *current_for_create.lock().unwrap() = Some(child);
        },
        |_| {},
        move |child| {
            root_for_delete.remove_child(&child).unwrap();
            *current_for_delete.lock().unwrap() = None;
        },
    );

    crud.create_new_command().execute();
    assert_eq!(root.children().len(), 1);
    let created = root.children().remove(0);
    assert_eq!(
        tree_changes(&recorder),
        vec![(root.id(), TreeStructureChange::Added, created.id())]
    );
    crud.delete_current_command().execute();
    assert!(root.children().is_empty());
    assert_eq!(
        tree_changes(&recorder),
        vec![
            (root.id(), TreeStructureChange::Added, created.id()),
            (root.id(), TreeStructureChange::Removed, created.id())
        ]
    );
}

/// HIER-015 — HierarchicalVMBuilder<M, VM>.Build validates required fields
#[test]
fn hierarchical_builder_validates_required_fields() {
    assert!(matches!(
        HierarchicalVm::<String>::builder()
            .model("root".to_string())
            .children_factory(|_| Vec::new())
            .build(),
        Err(VmxError::BuilderValidation(message)) if message.contains("services")
    ));
    assert!(matches!(
        HierarchicalVm::<String>::builder()
            .children_factory(|_| Vec::new())
            .services(MessageHub::new(), NullDispatcher::new())
            .build(),
        Err(VmxError::BuilderValidation(message)) if message.contains("model")
    ));
    assert!(matches!(
        HierarchicalVm::<String>::builder()
            .model("root".to_string())
            .services(MessageHub::new(), NullDispatcher::new())
            .build(),
        Err(VmxError::BuilderValidation(message)) if message.contains("children_factory")
    ));
}

/// HIER-016 — HierarchicalVMBuilder<M, VM> repeated identical Build calls
#[test]
fn hierarchical_builder_repeated_builds_are_distinct_equivalent() {
    let calls = Arc::new(AtomicUsize::new(0));
    let seen = Arc::clone(&calls);
    let builder = HierarchicalVm::builder()
        .model("root".to_string())
        .children_factory(move |_| {
            seen.fetch_add(1, Ordering::SeqCst);
            vec![leaf("child")]
        })
        .services(MessageHub::new(), NullDispatcher::new())
        .hint("h")
        .eager_children(true);

    let a = builder.clone().build().unwrap();
    let b = builder.build().unwrap();

    assert_ne!(a.id(), b.id());
    assert_eq!(a.model(), "root");
    assert_eq!(b.model(), "root");
    assert_eq!(a.hint(), "h");
    assert_eq!(b.hint(), "h");

    // Eager children: constructing materializes each subtree without a
    // separate children access.
    a.construct().unwrap();
    b.construct().unwrap();
    assert!(a.is_children_materialized());
    assert!(b.is_children_materialized());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(a.children().len(), 1);
    assert_eq!(b.children().len(), 1);
    assert_eq!(calls.load(Ordering::SeqCst), 2, "no re-evaluation");
}

/// HIER-017 — HierarchicalVMBuilder<M, VM> field defaults applied when not set
#[test]
fn hierarchical_builder_defaults_are_lazy() {
    let calls = Arc::new(Mutex::new(0));
    let seen = calls.clone();
    let node = HierarchicalVm::builder()
        .model("root".to_string())
        .children_factory(move |_| {
            *seen.lock().unwrap() += 1;
            Vec::new()
        })
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .unwrap();

    assert_eq!(node.hint(), "");
    assert_eq!(node.name(), "HierarchicalVm");
    // Lazy default: construction does not evaluate the children factory.
    node.construct().unwrap();
    assert_eq!(*calls.lock().unwrap(), 0);
    assert!(!node.is_children_materialized());
    node.children();
    assert_eq!(*calls.lock().unwrap(), 1);
    assert!(node.is_children_materialized());
}

/// HIER-018 — ReparentChild rejects self- and ancestor-reparenting
#[test]
fn reparent_rejects_self_and_ancestor_cycles() {
    let hub = MessageHub::new();
    let node = |name: &str| {
        HierarchicalVm::with_children_factory(
            name,
            name.to_string(),
            |_| Vec::new(),
            false,
            hub.clone(),
        )
    };
    let root = node("root");
    let mid = node("mid");
    let leaf_node = node("leaf");
    mid.add_child(leaf_node.clone()).unwrap();
    root.add_child(mid.clone()).unwrap();
    let shape = |n: &HierarchicalVm<String>| {
        (
            n.parent().map(|p| p.id()),
            n.depth(),
            n.path().iter().map(|p| p.id()).collect::<Vec<_>>(),
        )
    };
    let before = [shape(&root), shape(&mid), shape(&leaf_node)];
    let recorder = hub.record(1024);
    let tree_changes = |recorder: &vmx::MessageRecorder| {
        recorder
            .messages()
            .into_iter()
            .filter_map(|message| match message {
                Message::TreeStructureChanged(change) => Some((change.change, change.affected_id)),
                _ => None,
            })
            .collect::<Vec<_>>()
    };

    assert!(matches!(
        leaf_node.reparent_child(&root),
        Err(VmxError::InvalidArgument(message)) if message == CYCLE_MESSAGE
    ));
    assert!(matches!(
        mid.reparent_child(&mid),
        Err(VmxError::InvalidArgument(message)) if message == CYCLE_MESSAGE
    ));
    assert!(matches!(
        leaf_node.add_child(leaf_node.clone()),
        Err(VmxError::InvalidArgument(message)) if message == CYCLE_MESSAGE
    ));
    assert!(matches!(
        leaf_node.add_child(root.clone()),
        Err(VmxError::InvalidArgument(message)) if message == CYCLE_MESSAGE
    ));
    assert_eq!(leaf_node.depth(), 2);
    assert_eq!([shape(&root), shape(&mid), shape(&leaf_node)], before);
    assert!(
        tree_changes(&recorder).is_empty(),
        "no message on rejection"
    );

    // A successful explicit reparent publishes `Reparented` for the child.
    let other = node("other");
    other.reparent_child(&leaf_node).unwrap();
    assert!(leaf_node.parent().as_ref() == Some(&other));
    assert!(mid.children().is_empty());
    assert!(tree_changes(&recorder).contains(&(TreeStructureChange::Reparented, leaf_node.id())));

    // `node` shares the recorded hub; `leaf` would publish to a private hub.
    let new_parent = node("new-parent");
    let before_transfer = tree_changes(&recorder).len();
    new_parent.add_child(leaf_node.clone()).unwrap();
    assert!(other.children().is_empty());
    assert!(mid.children().is_empty());
    let transferred = new_parent.children();
    assert!(transferred.len() == 1 && transferred[0] == leaf_node);
    assert!(leaf_node.parent().as_ref() == Some(&new_parent));
    // The add_child transfer publishes exactly one Reparented message.
    assert_eq!(
        tree_changes(&recorder)[before_transfer..].to_vec(),
        vec![(TreeStructureChange::Reparented, leaf_node.id())],
        "AddChild transfer publishes one Reparented message"
    );
}

/// HIER-018 — an explicit add of a parented ancestor is a cycle, and a move of a
/// parented sibling within the same tree is not (ADR-0248 R2 (d)).
#[test]
fn explicit_add_of_a_parented_ancestor_is_a_cycle() {
    let root = leaf("root");
    let mid = leaf("mid");
    let deep = leaf("deep");
    let side = leaf("side");
    root.add_child(mid.clone()).unwrap();
    root.add_child(side.clone()).unwrap();
    mid.add_child(deep.clone()).unwrap();

    // An admitted cycle never returns from the restamp, so the add runs on a
    // worker and a missing answer fails the test instead of hanging it.
    let (sent, received) = mpsc::channel();
    let (worker, ancestor) = (deep.clone(), mid.clone());
    std::thread::spawn(move || {
        let _ = sent.send(worker.add_child(ancestor));
    });
    let outcome = received
        .recv_timeout(Duration::from_secs(5))
        .expect("the cycle is refused, not admitted");
    assert!(matches!(
        outcome,
        Err(VmxError::InvalidArgument(message)) if message == CYCLE_MESSAGE
    ));
    assert!(matches!(
        deep.reparent_child(&mid),
        Err(VmxError::InvalidArgument(message)) if message == CYCLE_MESSAGE
    ));
    assert!(mid.parent().as_ref() == Some(&root));
    assert!(deep.parent().as_ref() == Some(&mid));
    assert_eq!(deep.depth(), 2);

    // `side` is parented in the same tree, but it is no ancestor of `deep`.
    deep.add_child(side.clone()).unwrap();
    assert!(side.parent().as_ref() == Some(&deep));
    assert!(root.children() == vec![mid.clone()]);
}

/// HIER-019 — InvalidateChildren reloads on next access
#[test]
fn invalidate_children_reloads_on_next_access() {
    let calls = Arc::new(Mutex::new(0));
    let seen = calls.clone();
    let node = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            let next = {
                let mut calls = seen.lock().unwrap();
                *calls += 1;
                *calls
            };
            vec![leaf(&format!("child-{next}"))]
        },
        false,
        MessageHub::new(),
    );

    assert_eq!(node.children()[0].model(), "child-1");
    node.invalidate_children();
    assert_eq!(node.children()[0].model(), "child-2");
}

#[test]
fn invalidate_children_detaches_discarded_children() {
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        |_| vec![leaf("child")],
        false,
        MessageHub::new(),
    );
    let discarded = root.children()[0].clone();

    root.invalidate_children();
    let replacement = root.children()[0].clone();

    assert!(replacement != discarded);
    assert!(discarded.parent().is_none());
    assert!(discarded.is_root());
    root.add_child(discarded.clone()).unwrap();
    assert!(root.children().contains(&discarded));
}

/// HIER-020 — InvalidateChildren on an unmaterialized node is a no-op
#[test]
fn invalidate_unmaterialized_children_is_noop() {
    let calls = Arc::new(Mutex::new(0));
    let seen = calls.clone();
    let node = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            *seen.lock().unwrap() += 1;
            Vec::new()
        },
        false,
        MessageHub::new(),
    );

    node.invalidate_children();
    assert_eq!(*calls.lock().unwrap(), 0);
    node.children();
    assert_eq!(*calls.lock().unwrap(), 1);
}

/// HIER-021 — InvalidateSubtree invalidates materialized descendants
#[test]
fn invalidate_subtree_invalidates_materialized_descendants() {
    let root_calls = Arc::new(Mutex::new(0));
    let root_seen = root_calls.clone();
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            *root_seen.lock().unwrap() += 1;
            Vec::new()
        },
        false,
        MessageHub::new(),
    );
    let child_calls = Arc::new(Mutex::new(0));
    let child_seen = child_calls.clone();
    let child = HierarchicalVm::with_children_factory(
        "child",
        "child".to_string(),
        move |_| {
            *child_seen.lock().unwrap() += 1;
            Vec::new()
        },
        false,
        MessageHub::new(),
    );
    root.add_child(child.clone()).unwrap();
    child.children();
    assert_eq!(*root_calls.lock().unwrap(), 1);
    assert_eq!(*child_calls.lock().unwrap(), 1);
    assert!(root.is_children_materialized());
    assert!(child.is_children_materialized());

    root.invalidate_subtree();

    assert!(!root.is_children_materialized());
    assert!(!child.is_children_materialized());
    root.children();
    child.children();
    assert_eq!(
        *root_calls.lock().unwrap(),
        2,
        "the root factory runs again"
    );
    assert_eq!(
        *child_calls.lock().unwrap(),
        2,
        "the materialized descendant factory runs again"
    );
}

/// HIER-022 — Child-cache invalidation publishes property changed
#[test]
fn invalidate_children_publishes_property_changed() {
    let hub = MessageHub::new();
    let recorder = hub.record(1024);
    let node = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        |_| vec![leaf("child")],
        false,
        hub.clone(),
    );
    node.children();

    node.invalidate_children();

    assert!(recorder.messages().iter().any(
        |message| matches!(message, Message::PropertyChanged(change) if change.property_name == "children")
    ));
}

#[test]
fn dropping_a_materialized_tree_releases_parent_and_child_state() {
    let marker = Arc::new(());
    let released = Arc::downgrade(&marker);
    {
        let root = HierarchicalVm::new("root", ("root", marker.clone()));
        let child = HierarchicalVm::new("child", ("child", Arc::new(())));
        root.add_child(child).unwrap();
    }
    drop(marker);

    assert!(
        released.upgrade().is_none(),
        "parent back-references must not keep an unreachable tree alive"
    );
}

/// A factory that asks its own receiver `is_leaf` re-enters materialization;
/// `try_children` reports that as an error instead of panicking, and the
/// node can be retried with a well-behaved factory result.
#[test]
fn try_children_reports_factory_is_leaf_reentry_as_error() {
    let reenter = Arc::new(Mutex::new(true));
    let gate = Arc::clone(&reenter);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |node: &HierarchicalVm<String>| {
            if *gate.lock().unwrap() {
                let _ = node.is_leaf();
            }
            vec![leaf("child")]
        },
        false,
        MessageHub::new(),
    );

    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| root.try_children()));

    let result = outcome.expect("try_children must return the re-entry error, not panic");
    assert!(matches!(
        result,
        Err(VmxError::InvalidArgument(message)) if message.contains("re-entered")
    ));
    assert!(!root.is_children_materialized());

    *reenter.lock().unwrap() = false;
    assert_eq!(root.try_children().unwrap().len(), 1);
}

/// `HierarchicalVmBuilder::services` accepts any dispatcher, as the other
/// builders do; the hierarchy keeps only the hub (#1268, ADR-0206).
#[test]
fn hierarchical_builder_accepts_any_dispatcher() {
    let immediate = HierarchicalVm::<String>::builder()
        .model("root".to_string())
        .children_factory(|_| Vec::new())
        .services(MessageHub::new(), vmx::ImmediateDispatcher::new())
        .build();
    let default = HierarchicalVm::<String>::builder()
        .model("root".to_string())
        .children_factory(|_| Vec::new())
        .services(MessageHub::new(), vmx::DefaultDispatcher::new())
        .build();

    assert!(immediate.is_ok());
    assert!(default.is_ok());
}
