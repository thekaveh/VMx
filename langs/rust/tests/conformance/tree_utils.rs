use std::sync::{Arc, Mutex};

use vmx::{find, walk, walk_expanded, HierarchicalVm, MessageHub, VmxError};

fn leaf(name: &str) -> HierarchicalVm<String> {
    HierarchicalVm::new(name, name.to_string())
}

fn sample_tree() -> HierarchicalVm<String> {
    let root = leaf("root");
    let a = leaf("a");
    let b = leaf("b");
    let b1 = leaf("b1");
    let b2 = leaf("b2");
    b.add_child(b1).unwrap();
    b.add_child(b2).unwrap();
    root.add_child(a).unwrap();
    root.add_child(b).unwrap();
    root
}

/// UTIL-001 — walk yields root then descendants in DFS pre-order
#[test]
fn walk_yields_depth_first_preorder() {
    let root = sample_tree();

    let names = walk(&root)
        .unwrap()
        .into_iter()
        .map(|node| node.model())
        .collect::<Vec<_>>();

    assert_eq!(names, vec!["root", "a", "b", "b1", "b2"]);
}

/// UTIL-002 — walk skips empty aggregate slots
///
/// Rust gap: `AggregateVm3` does not implement `TreeNode`, and `walk` is
/// homogeneous (`Vec<T>`), so an aggregate cannot be walked at all. Every
/// slot is also required by the builder, so a constructed aggregate has no
/// empty slot to skip. This test pins that actual behavior and the tree-walk
/// guarantee that `walk` never yields an entry for an absent child.
#[test]
fn walk_skips_empty_child_slots_by_construction() {
    let missing_slot = vmx::AggregateVm3::<
        vmx::ComponentVm<i32>,
        vmx::ComponentVm<i32>,
        vmx::ComponentVm<i32>,
    >::builder()
    .name("aggregate")
    .services(vmx::MessageHub::new(), vmx::NullDispatcher::new())
    .component_1(|| {
        vmx::ComponentVm::<i32>::with_model(
            "one",
            1,
            vmx::MessageHub::new(),
            vmx::NullDispatcher::new(),
        )
    })
    .component_3(|| {
        vmx::ComponentVm::<i32>::with_model(
            "three",
            3,
            vmx::MessageHub::new(),
            vmx::NullDispatcher::new(),
        )
    })
    .build();
    assert!(
        matches!(&missing_slot, Err(vmx::VmxError::BuilderValidation(message)) if message.contains("component_2")),
        "an aggregate cannot be built with an empty Component2 slot"
    );

    let root = leaf("root");
    root.add_child(leaf("a")).unwrap();
    root.add_child(leaf("c")).unwrap();

    let names = walk(&root)
        .unwrap()
        .into_iter()
        .map(|node| node.model())
        .collect::<Vec<_>>();

    assert_eq!(names, vec!["root", "a", "c"]);
}

/// UTIL-003 — find returns first matching node and short-circuits
#[test]
fn find_returns_first_match_and_short_circuits() {
    let root = sample_tree();
    let visited = Arc::new(Mutex::new(Vec::new()));
    let visited_inner = visited.clone();

    let found = find(&root, move |node| {
        visited_inner.lock().unwrap().push(node.model());
        node.model() == "b1"
    })
    .unwrap();

    assert_eq!(found.unwrap().model(), "b1");
    assert_eq!(
        *visited.lock().unwrap(),
        vec![
            "root".to_string(),
            "a".to_string(),
            "b".to_string(),
            "b1".to_string()
        ]
    );
}

/// Tree walks over invalid factory output (spec/13 §6, ADR-0170, #1060):
/// `walk`, `walk_expanded` and `find` return the factory error instead of
/// panicking, and the node stays unmaterialized so a later walk retries.
#[test]
fn walks_return_invalid_factory_output_error_and_stay_retryable() {
    let dup = leaf("dup");
    let other = leaf("other");
    let snapshot = Arc::new(Mutex::new(vec![dup.clone(), dup.clone()]));
    let captured = Arc::clone(&snapshot);
    let calls = Arc::new(Mutex::new(0_usize));
    let counted = Arc::clone(&calls);
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            *counted.lock().unwrap() += 1;
            captured.lock().unwrap().clone()
        },
        false,
        MessageHub::new(),
    );
    let is_factory_error = |error: &VmxError| matches!(error, VmxError::InvalidArgument(message) if message.contains("factory"));

    assert!(walk(&root).is_err_and(|error| is_factory_error(&error)));
    assert!(walk_expanded(&root).is_err_and(|error| is_factory_error(&error)));
    assert!(find(&root, |_| false).is_err_and(|error| is_factory_error(&error)));
    assert_eq!(*calls.lock().unwrap(), 3, "each walk retries the factory");
    assert!(
        dup.parent().is_none(),
        "a rejected snapshot assigns no parent"
    );
    assert!(!root.is_children_materialized());

    // A predicate that matches the root returns before any child is read.
    let target = root.clone();
    assert!(find(&root, move |node| *node == target).unwrap() == Some(root.clone()));
    assert_eq!(*calls.lock().unwrap(), 3);

    *snapshot.lock().unwrap() = vec![dup.clone(), other.clone()];
    assert_eq!(walk(&root).unwrap().len(), 3);
    assert_eq!(walk_expanded(&root).unwrap().len(), 3);
    let wanted = other.clone();
    assert!(find(&root, move |node| *node == wanted).unwrap() == Some(other.clone()));
}
