use std::sync::{Arc, Mutex};

use vmx::{
    walk_expanded, Command, ConstructionStatus, HierarchicalVm, Message, MessageHub,
    ModeledCrudCommands, NullDispatcher, SearchableState,
};

fn leaf(name: &str) -> HierarchicalVm<String> {
    HierarchicalVm::new(name, name.to_string())
}

/// HIER-001 — Recursive generic constraint compiles
#[test]
fn recursive_generic_shape_compiles() {
    let root = leaf("root");

    assert_eq!(root.model(), "root");
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

/// HIER-008 — Eager child loading via constructor option
#[test]
fn eager_construct_materializes_descendants() {
    let calls = Arc::new(Mutex::new(0));
    let seen = calls.clone();
    let hub = MessageHub::new();
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            *seen.lock().unwrap() += 1;
            vec![leaf("child")]
        },
        true,
        hub,
    );

    root.construct().unwrap();

    assert_eq!(*calls.lock().unwrap(), 1);
    assert!(root.is_children_materialized());
}

/// HIER-009 — Depth-first construction order (eager mode)
#[test]
fn eager_construction_is_depth_first() {
    let hub = MessageHub::new();
    let child_hub = hub.clone();
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        move |_| {
            let grand_hub = child_hub.clone();
            vec![HierarchicalVm::with_children_factory(
                "child",
                "child".to_string(),
                move |_| vec![HierarchicalVm::new("grandchild", "grandchild".to_string())],
                true,
                grand_hub,
            )]
        },
        true,
        hub.clone(),
    );

    root.construct().unwrap();

    let constructed = hub
        .history()
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
    assert_eq!(constructed.last(), Some(&root.id()));
}

/// HIER-010 — PropertyChangedMessage on Parent change
#[test]
fn parent_change_publishes_property_changed() {
    let hub = MessageHub::new();
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

    assert!(hub.history().iter().any(
        |message| matches!(message, Message::PropertyChanged(change) if change.property_name == "Parent")
    ));
}

/// HIER-011 — TreeStructureChangedMessage on structural mutations
#[test]
fn structural_mutations_publish_tree_structure_changed() {
    let hub = MessageHub::new();
    let root = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    );
    let child = leaf("child");

    root.add_child(child.clone()).unwrap();
    root.remove_child(&child).unwrap();

    assert_eq!(
        hub.history()
            .iter()
            .filter(|message| matches!(message, Message::TreeStructureChanged(_)))
            .count(),
        2
    );
}

/// HIER-012 — walk_expanded honors lazy boundaries via ExpandableState
#[test]
fn walk_expanded_honors_hierarchy_expansion_boundary() {
    let root = leaf("root");
    root.set_expanded_for_walk(false);
    root.add_child(leaf("child")).unwrap();

    assert_eq!(walk_expanded(&root).len(), 1);
    root.set_expanded_for_walk(true);
    assert_eq!(walk_expanded(&root).len(), 2);
}

/// HIER-013 — Composition with SearchableState filters materialized portion
#[test]
fn searchable_state_filters_materialized_nodes() {
    let root = leaf("root");
    root.add_child(leaf("alpha")).unwrap();
    root.add_child(leaf("beta")).unwrap();
    let state = SearchableState::new(root.children(), |node, term| node.model().contains(term));
    state.set_search_term("alp");

    assert_eq!(state.filtered()[0].model(), "alpha");
}

/// HIER-014 — Composition with ModeledCrudCommands mutates the tree
#[test]
fn modeled_crud_commands_can_mutate_tree_children() {
    let root = leaf("root");
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
    crud.delete_current_command().execute();
    assert!(root.children().is_empty());
}

/// HIER-015 — HierarchicalVMBuilder<M, VM>.Build validates required fields
#[test]
fn hierarchical_builder_validates_required_fields() {
    assert!(HierarchicalVm::<String>::builder()
        .model("root".to_string())
        .children_factory(|_| Vec::new())
        .build()
        .is_err());
    assert!(HierarchicalVm::<String>::builder()
        .children_factory(|_| Vec::new())
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .is_err());
    assert!(HierarchicalVm::<String>::builder()
        .model("root".to_string())
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .is_err());
}

/// HIER-016 — HierarchicalVMBuilder<M, VM> repeated identical Build calls
#[test]
fn hierarchical_builder_repeated_builds_are_distinct_equivalent() {
    let builder = HierarchicalVm::builder()
        .model("root".to_string())
        .children_factory(|_| Vec::new())
        .services(MessageHub::new(), NullDispatcher::new())
        .hint("h")
        .eager_children(true);

    let a = builder.clone().build().unwrap();
    let b = builder.build().unwrap();

    assert_ne!(a.id(), b.id());
    assert_eq!(a.model(), b.model());
    assert_eq!(a.hint(), Some("h".to_string()));
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

    assert_eq!(node.hint(), None);
    assert_eq!(*calls.lock().unwrap(), 0);
    node.children();
    assert_eq!(*calls.lock().unwrap(), 1);
}

/// HIER-018 — ReparentChild rejects self- and ancestor-reparenting
#[test]
fn reparent_rejects_self_and_ancestor_cycles() {
    let root = leaf("root");
    let mid = leaf("mid");
    let leaf_node = leaf("leaf");
    mid.add_child(leaf_node.clone()).unwrap();
    root.add_child(mid.clone()).unwrap();

    assert!(leaf_node.reparent_child(&root).is_err());
    assert!(mid.reparent_child(&mid).is_err());
    assert_eq!(leaf_node.depth(), 2);
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
    let root = leaf("root");
    let child = leaf("child");
    child.add_child(leaf("grandchild")).unwrap();
    root.add_child(child.clone()).unwrap();
    assert!(child.is_children_materialized());

    root.invalidate_subtree();

    assert!(!root.is_children_materialized());
    assert!(!child.is_children_materialized());
}

/// HIER-022 — Child-cache invalidation publishes property changed
#[test]
fn invalidate_children_publishes_property_changed() {
    let hub = MessageHub::new();
    let node = HierarchicalVm::with_children_factory(
        "root",
        "root".to_string(),
        |_| vec![leaf("child")],
        false,
        hub.clone(),
    );
    node.children();

    node.invalidate_children();

    assert!(hub.history().iter().any(
        |message| matches!(message, Message::PropertyChanged(change) if change.property_name == "children")
    ));
}
