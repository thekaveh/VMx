use std::sync::{Arc, Mutex};

use vmx::{find, walk, HierarchicalVm};

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
        .into_iter()
        .map(|node| node.model())
        .collect::<Vec<_>>();

    assert_eq!(names, vec!["root", "a", "b", "b1", "b2"]);
}

/// UTIL-002 — walk skips empty aggregate slots
#[test]
fn walk_skips_empty_child_slots_by_construction() {
    let root = leaf("root");
    root.add_child(leaf("a")).unwrap();
    root.add_child(leaf("c")).unwrap();

    let names = walk(&root)
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
    });

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
