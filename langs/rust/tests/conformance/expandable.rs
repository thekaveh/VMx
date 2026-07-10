use vmx::{walk_expanded, ExpandableState, HierarchicalVm};

fn leaf(name: &str) -> HierarchicalVm<String> {
    HierarchicalVm::new(name, name.to_string())
}

/// EXP-001 — ExpandableState defaults to collapsed
#[test]
fn expandable_state_defaults_to_collapsed() {
    let state = ExpandableState::new();

    assert!(!state.is_expanded());
    assert!(state.can_expand());
    assert!(!state.can_collapse());
}

/// EXP-002 — Expand flips state and emits IsExpandedChanged
#[test]
fn expand_flips_state_and_emits_once() {
    let state = ExpandableState::new();

    state.expand();
    state.expand();

    assert!(state.is_expanded());
    assert_eq!(state.expanded_changed().history().len(), 1);
}

/// EXP-003 — Collapse flips state back
#[test]
fn collapse_flips_state_back() {
    let state = ExpandableState::new();
    state.expand();
    state.collapse();

    assert!(!state.is_expanded());
    assert_eq!(state.expanded_changed().history().len(), 2);
}

/// EXP-004 — ToggleExpansion alternates state
#[test]
fn toggle_expansion_alternates_state() {
    let state = ExpandableState::new();

    state.toggle_expansion();
    state.toggle_expansion();
    assert!(!state.is_expanded());
    state.toggle_expansion();
    assert!(state.is_expanded());
}

/// EXP-005 — walk_expanded skips descendants of collapsed nodes
#[test]
fn walk_expanded_skips_collapsed_descendants() {
    let root = leaf("root");
    let a = leaf("a");
    let b = leaf("b");
    b.set_expanded_for_walk(false);
    b.add_child(leaf("b1")).unwrap();
    b.add_child(leaf("b2")).unwrap();
    root.add_child(a).unwrap();
    root.add_child(b).unwrap();

    let names = walk_expanded(&root)
        .into_iter()
        .map(|node| node.model())
        .collect::<Vec<_>>();

    assert_eq!(names, vec!["root", "a", "b"]);
}
