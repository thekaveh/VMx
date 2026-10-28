use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use vmx::{
    ConstructionStatus, HierarchicalVm, MessageHub, NullDispatcher, TreeSelection, ValueStream,
    ValueSubscription, VmNode, VmxError,
};

fn leaf(name: &str) -> HierarchicalVm<String> {
    HierarchicalVm::new(name, name.to_string())
}

type Seen = Arc<Mutex<Vec<Option<String>>>>;

/// Records every emission of `stream` as the emitted node's model.
fn record(stream: ValueStream<Option<HierarchicalVm<String>>>) -> (Seen, ValueSubscription) {
    let seen: Seen = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&seen);
    let subscription =
        stream.subscribe(move |node| sink.lock().unwrap().push(node.map(|node| node.model())));
    (seen, subscription)
}

fn some(name: &str) -> Option<String> {
    Some(name.to_string())
}

/// root -> a -> aa and root -> b, each node on its own hub.
fn tree() -> [HierarchicalVm<String>; 4] {
    let [root, a, aa, b] = ["root", "a", "aa", "b"].map(leaf);
    root.add_child(a.clone()).unwrap();
    a.add_child(aa.clone()).unwrap();
    root.add_child(b.clone()).unwrap();
    [root, a, aa, b]
}

/// A node on `hub` whose children factory counts its calls.
fn counted(name: &str, hub: &MessageHub, calls: &Arc<AtomicUsize>) -> HierarchicalVm<String> {
    let calls = Arc::clone(calls);
    HierarchicalVm::with_children_factory(
        name,
        name.to_string(),
        move |_| {
            calls.fetch_add(1, Ordering::SeqCst);
            Vec::new()
        },
        false,
        hub.clone(),
    )
}

/// HIER-033 — `TreeSelection` selects a member and publishes each change once.
#[test]
fn tree_selection_selects_a_member_and_publishes_each_change_once() {
    let [root, a, aa, _] = tree();
    let selection = TreeSelection::new(&root);
    let (seen, _subscription) = record(selection.current_changed());

    assert!(selection.can_select(&root));
    assert!(selection.can_select(&a));
    assert!(selection.can_select(&aa));

    selection.select(&aa).unwrap();
    assert!(selection.current() == Some(aa.clone()));
    selection.select(&aa).unwrap();
    selection.clear();
    assert!(selection.current().is_none());
    selection.clear();

    assert_eq!(*seen.lock().unwrap(), vec![some("aa"), None]);
}

/// HIER-033 — a subscriber that selects again while it receives a value does
/// not reorder the changes for a later subscriber.
#[test]
fn tree_selection_delivers_a_reentrant_select_to_every_subscriber_in_order() {
    let [root, a, aa, _] = tree();
    let selection = TreeSelection::new(&root);
    let reselect = {
        let selection = selection.clone();
        let (a, aa) = (a.clone(), aa.clone());
        selection.clone().current_changed().subscribe(move |node| {
            if node.as_ref() == Some(&aa) {
                selection.select(&a).unwrap();
            }
        })
    };
    let (seen, _subscription) = record(selection.current_changed());

    selection.select(&aa).unwrap();

    assert_eq!(*seen.lock().unwrap(), vec![some("aa"), some("a")]);
    assert!(selection.current() == Some(a.clone()));
    reselect.dispose();
    selection.dispose();
}

/// HIER-034 — a current node that left the tree before the helper observed it
/// is rejected like any other non-member.
#[test]
fn tree_selection_rejects_a_stale_current_node() {
    let [root, a, aa, _] = tree();
    let selection = TreeSelection::new(&root);
    selection.select(&aa).unwrap();

    // Both hubs defer delivery, so the helper has not seen the removal yet.
    let result = a.hub().batch(|| {
        aa.hub().batch(|| {
            a.remove_child(&aa).unwrap();
            assert!(selection.current() == Some(aa.clone()));
            selection.select(&aa)
        })
    });

    assert!(matches!(result, Err(VmxError::InvalidArgument(_))));
    assert!(selection.current().is_none());
}

/// HIER-034 — `TreeSelection` rejects a node outside the materialized tree.
#[test]
fn tree_selection_rejects_a_node_outside_the_materialized_tree() {
    let calls = Arc::new(AtomicUsize::new(0));
    let hub = MessageHub::new();
    let root = counted("root", &hub, &calls);
    let a = counted("a", &hub, &calls);
    let disposed = counted("disposed", &hub, &calls);
    root.add_child(a.clone()).unwrap();
    root.add_child(disposed.clone()).unwrap();
    disposed.dispose().unwrap();
    let detached = counted("detached", &hub, &calls);
    let other_root = counted("other-root", &MessageHub::new(), &calls);
    let other_child = counted("other-child", &MessageHub::new(), &calls);
    other_root.add_child(other_child.clone()).unwrap();
    let factory_calls = calls.load(Ordering::SeqCst);

    let selection = TreeSelection::new(&root);
    selection.select(&a).unwrap();
    let (seen, _subscription) = record(selection.current_changed());

    for outsider in [&detached, &other_root, &other_child, &disposed] {
        assert!(!selection.can_select(outsider), "{}", outsider.model());
        assert!(
            matches!(
                selection.select(outsider),
                Err(VmxError::InvalidArgument(_))
            ),
            "{}",
            outsider.model()
        );
        assert!(selection.current() == Some(a.clone()));
    }

    assert!(seen.lock().unwrap().is_empty());
    assert_eq!(calls.load(Ordering::SeqCst), factory_calls);
    assert!(!a.is_children_materialized());
}

/// HIER-035 — removing an ancestor of the current node clears the selection.
#[test]
fn tree_selection_clears_when_an_ancestor_is_removed() {
    let [root, a, aa, _] = tree();
    let selection = TreeSelection::new(&root);
    selection.select(&aa).unwrap();
    let (seen, _subscription) = record(selection.current_changed());

    root.remove_child(&a).unwrap();

    assert!(selection.current().is_none());
    assert_eq!(*seen.lock().unwrap(), vec![None]);
}

/// HIER-035 — removing the current node itself clears the selection.
#[test]
fn tree_selection_clears_when_the_current_node_is_removed() {
    let [root, a, aa, _] = tree();
    let selection = TreeSelection::new(&root);
    selection.select(&aa).unwrap();
    let (seen, _subscription) = record(selection.current_changed());

    a.remove_child(&aa).unwrap();

    assert!(selection.current().is_none());
    assert_eq!(*seen.lock().unwrap(), vec![None]);
}

/// HIER-036 — a move inside keeps the selection; a transfer out clears it.
#[test]
fn tree_selection_keeps_a_move_inside_and_clears_a_transfer_out() {
    let [root, a, aa, b] = tree();
    let other_hub = MessageHub::new();
    let other_root = counted("other-root", &other_hub, &Arc::new(AtomicUsize::new(0)));
    let root_messages = root.hub().record(64);
    let selection = TreeSelection::new(&root);
    selection.select(&aa).unwrap();
    let (seen, _subscription) = record(selection.current_changed());

    b.add_child(a.clone()).unwrap();
    assert!(selection.current() == Some(aa.clone()));
    assert!(seen.lock().unwrap().is_empty());

    let other_messages = other_hub.record(64);
    let root_messages_before = root_messages.messages().len();
    other_root.add_child(a.clone()).unwrap();
    assert!(selection.current().is_none());
    assert_eq!(*seen.lock().unwrap(), vec![None]);
    // The transfer's structure message is on the other tree's hub only.
    assert_eq!(other_messages.messages().len(), 1);
    assert_eq!(root_messages.messages().len(), root_messages_before);
}

/// HIER-037 — invalidating an ancestor's child cache clears the selection.
#[test]
fn tree_selection_clears_when_an_ancestor_is_invalidated() {
    let [root, a, aa, _] = tree();
    let selection = TreeSelection::new(&root);
    selection.select(&aa).unwrap();
    let (seen, _subscription) = record(selection.current_changed());

    a.invalidate_children();

    assert!(selection.current().is_none());
    assert_eq!(*seen.lock().unwrap(), vec![None]);
    assert!(aa.parent().is_none());
    assert_ne!(aa.status(), ConstructionStatus::Disposed);
    assert!(!selection.can_select(&aa));
}

/// HIER-038 — disposing an ancestor of the current node clears the selection.
#[test]
fn tree_selection_clears_when_an_ancestor_is_disposed() {
    let [root, a, aa, _] = tree();
    let selection = TreeSelection::new(&root);
    selection.select(&aa).unwrap();
    let (seen, _subscription) = record(selection.current_changed());

    a.dispose().unwrap();

    assert!(selection.current().is_none());
    assert_eq!(*seen.lock().unwrap(), vec![None]);
    assert!(!selection.can_select(&aa));
    assert!(a.parent() == Some(root.clone()));
    assert!(aa.parent() == Some(a.clone()));
}

/// HIER-038 — disposing the current node itself clears the selection.
#[test]
fn tree_selection_clears_when_the_current_node_is_disposed() {
    let [root, _, aa, _] = tree();
    let selection = TreeSelection::new(&root);
    selection.select(&aa).unwrap();
    let (seen, _subscription) = record(selection.current_changed());

    aa.dispose().unwrap();

    assert!(selection.current().is_none());
    assert_eq!(*seen.lock().unwrap(), vec![None]);
    assert!(!selection.can_select(&aa));
}

/// HIER-039 — selection does not navigate.
#[test]
fn tree_selection_does_not_navigate() {
    let hub = MessageHub::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let a = counted("a", &hub, &calls);
    let child_for_root = a.clone();
    let root = HierarchicalVm::builder()
        .model("root".to_string())
        .children_factory(move |_| vec![child_for_root.clone()])
        .services(hub.clone(), NullDispatcher::new())
        .build()
        .unwrap();
    assert_eq!(root.children().len(), 1);
    let recorder = hub.record(64);
    let snapshot = |node: &HierarchicalVm<String>| {
        (
            node.status(),
            node.parent().map(|parent| parent.id()),
            VmNode::is_current(node),
        )
    };
    let before = [snapshot(&root), snapshot(&a)];
    let selection = TreeSelection::new(&root);

    selection.select(&a).unwrap();
    selection.select(&root).unwrap();
    selection.clear();

    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert!(!a.is_children_materialized());
    assert_eq!([snapshot(&root), snapshot(&a)], before);
    assert!(recorder.messages().is_empty());
}

/// HIER-040 — a disposed `TreeSelection` is inert.
#[test]
fn a_disposed_tree_selection_is_inert() {
    let [root, a, aa, b] = tree();
    let selection = TreeSelection::new(&root);
    selection.select(&aa).unwrap();
    let completions = Arc::new(AtomicUsize::new(0));
    let completed = Arc::clone(&completions);
    let seen: Seen = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&seen);
    let _subscription = selection.current_changed().subscribe_with_completion(
        move |node| sink.lock().unwrap().push(node.map(|node| node.model())),
        move || {
            completed.fetch_add(1, Ordering::SeqCst);
        },
    );

    selection.dispose();

    assert_eq!(completions.load(Ordering::SeqCst), 1);
    assert!(seen.lock().unwrap().is_empty());
    assert!(selection.current().is_none());
    for node in [&root, &a, &aa, &b] {
        assert!(!selection.can_select(node));
    }

    selection.select(&b).unwrap();
    selection.clear();
    root.remove_child(&a).unwrap();
    aa.dispose().unwrap();
    selection.dispose();

    assert!(selection.current().is_none());
    assert!(seen.lock().unwrap().is_empty());
    assert_eq!(completions.load(Ordering::SeqCst), 1);
    assert_ne!(root.status(), ConstructionStatus::Disposed);
    assert_ne!(b.status(), ConstructionStatus::Disposed);
}
