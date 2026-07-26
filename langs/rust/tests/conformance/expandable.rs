use vmx::{walk_expanded, ExpandableState, Message};

use super::expandable_support::ExpandableHierarchy;

/// EXP-001 — ExpandableState defaults to collapsed
#[test]
fn expandable_state_defaults_to_collapsed() {
    let state = ExpandableState::new();

    assert!(!state.is_expanded());
    assert!(state.can_expand());
    assert!(!state.can_collapse());
}

#[test]
fn expandable_state_supports_initially_expanded_construction() {
    assert!(ExpandableState::with_initial(true).is_expanded());
    assert!(ExpandableState::new_expanded().is_expanded());
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

#[test]
fn expandable_state_dispose_is_idempotent_and_makes_changes_inert() {
    let state = ExpandableState::new_expanded();
    let changes = state.expanded_changed();

    state.dispose();
    state.dispose();
    state.collapse();
    changes.send(Message::Custom {
        sender_id: 0,
        sender_name: "test".to_string(),
        name: "after_dispose".to_string(),
    });

    assert!(state.is_expanded());
    assert!(changes.history().is_empty());
}

/// EXP-005 — walk_expanded skips descendants of collapsed nodes
#[test]
fn walk_expanded_skips_collapsed_descendants() {
    let root = ExpandableHierarchy::expandable("root", true);
    let a = ExpandableHierarchy::plain("a");
    let b = ExpandableHierarchy::expandable("b", false);
    b.add_child(ExpandableHierarchy::plain("b1"));
    b.add_child(ExpandableHierarchy::plain("b2"));
    root.add_child(a);
    root.add_child(b.clone());

    let names = walk_expanded(&root)
        .into_iter()
        .map(|node| node.model())
        .collect::<Vec<_>>();

    assert_eq!(names, vec!["root", "a", "b"]);

    b.expansion().unwrap().expand();
    let names = walk_expanded(&root)
        .into_iter()
        .map(|node| node.model())
        .collect::<Vec<_>>();
    assert_eq!(names, vec!["root", "a", "b", "b1", "b2"]);
}
