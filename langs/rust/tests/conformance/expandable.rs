use vmx::{walk_expanded, Command, ExpandableState, Message};

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
    let state_expanded_changed_record = state.expanded_changed().record(1024);

    state.expand();

    assert!(state.is_expanded());
    // The emission's payload is the new value, carried as the message name.
    let values = || {
        state_expanded_changed_record
            .messages()
            .into_iter()
            .map(|message| match message {
                Message::Custom { name, .. } => name,
                other => panic!("unexpected expansion message {other:?}"),
            })
            .collect::<Vec<_>>()
    };
    assert_eq!(values(), vec!["true".to_string()]);

    state.expand();

    assert!(state.is_expanded());
    assert_eq!(
        values(),
        vec!["true".to_string()],
        "repeat expand is a no-op"
    );
}

/// EXP-003 — Collapse flips state back
#[test]
fn collapse_flips_state_back() {
    let state = ExpandableState::new_expanded();
    assert!(state.is_expanded());
    let state_expanded_changed_record = state.expanded_changed().record(1024);

    state.collapse();

    assert!(!state.is_expanded());
    // The emission's payload is the new value, carried as the message name.
    let values = state_expanded_changed_record
        .messages()
        .into_iter()
        .map(|message| match message {
            vmx::Message::Custom { name, .. } => name,
            other => panic!("unexpected expansion message {other:?}"),
        })
        .collect::<Vec<_>>();
    assert_eq!(values, vec!["false"]);
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
    let recorder = changes.record(1024);

    state.dispose();
    state.dispose();
    state.collapse();
    changes.send(Message::Custom {
        sender_id: 0,
        sender_name: "test".to_string(),
        name: "after_dispose".to_string(),
    });

    assert!(state.is_expanded());
    assert!(recorder.messages().is_empty());
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

fn expansion_values(record: &vmx::MessageRecorder) -> Vec<String> {
    record
        .messages()
        .into_iter()
        .map(|message| match message {
            Message::Custom { name, .. } => name,
            other => panic!("unexpected expansion message {other:?}"),
        })
        .collect()
}

/// EXP-006 — Expansion command predicates track the can checks and re-fire on each change
#[test]
fn expansion_command_predicates_track_can_checks_and_refire() {
    let state = ExpandableState::new();
    let expand = state.expand_command();
    let collapse = state.collapse_command();
    let toggle = state.toggle_expansion_command();
    let records =
        [&expand, &collapse, &toggle].map(|command| command.can_execute_changed().record(1024));
    let counts = || {
        records
            .iter()
            .map(|record| record.messages().len())
            .collect::<Vec<_>>()
    };

    assert!(expand.can_execute());
    assert!(!collapse.can_execute());
    assert!(toggle.can_execute());

    state.expand();
    assert_eq!(counts(), vec![1, 1, 1]);
    assert!(!expand.can_execute());
    assert!(collapse.can_execute());
    assert!(toggle.can_execute());

    state.expand(); // a no-op verb is not an expansion change
    assert_eq!(counts(), vec![1, 1, 1]);

    state.collapse();
    assert_eq!(counts(), vec![2, 2, 2]);
    assert!(expand.can_execute());
    assert!(!collapse.can_execute());

    // Every read returns a clone of the same command.
    state.expand_command().raise_can_execute_changed();
    state.collapse_command().raise_can_execute_changed();
    state.toggle_expansion_command().raise_can_execute_changed();
    assert_eq!(counts(), vec![3, 3, 3]);
}

/// EXP-007 — Executing an expansion command performs its verb
#[test]
fn executing_each_expansion_command_performs_its_verb() {
    let state = ExpandableState::new();
    let record = state.expanded_changed().record(1024);

    state.expand_command().execute();
    assert!(state.is_expanded());
    state.expand_command().execute(); // the predicate is false while expanded
    assert_eq!(expansion_values(&record), vec!["true"]);

    state.collapse_command().execute();
    assert!(!state.is_expanded());
    state.collapse_command().execute();
    assert_eq!(expansion_values(&record), vec!["true", "false"]);

    state.toggle_expansion_command().execute();
    assert!(state.is_expanded());
    state.toggle_expansion_command().execute();
    assert!(!state.is_expanded());
    assert_eq!(
        expansion_values(&record),
        vec!["true", "false", "true", "false"]
    );
}

/// EXP-008 — Disposing the helper makes its expansion commands inert
#[test]
fn disposing_the_helper_makes_expansion_commands_inert() {
    let state = ExpandableState::new();
    let commands = [
        state.expand_command(),
        state.collapse_command(),
        state.toggle_expansion_command(),
    ];
    let record = state.expanded_changed().record(1024);

    state.dispose();

    for command in &commands {
        assert!(!command.can_execute());
        command.execute();
    }
    assert!(!state.is_expanded());
    assert!(record.messages().is_empty());

    // A command first read after disposal is inert as well, also through a
    // clone of the state.
    let late = ExpandableState::new();
    late.dispose();
    let clone = late.clone();
    for command in [
        clone.expand_command(),
        clone.collapse_command(),
        clone.toggle_expansion_command(),
    ] {
        assert!(!command.can_execute());
        command.execute();
    }
    assert!(!late.is_expanded());
}
