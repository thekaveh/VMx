use vmx::{BatchAttachRejectionReason, HierarchicalVm, MissingParentPolicy, VmxError, VmxResult};

#[derive(Clone, Debug, PartialEq)]
struct Model {
    key: String,
    parent_key: Option<String>,
}

fn node(key: &str, parent_key: Option<&str>) -> HierarchicalVm<Model> {
    HierarchicalVm::new(
        key,
        Model {
            key: key.to_string(),
            parent_key: parent_key.map(str::to_string),
        },
    )
}

fn attach(
    root: &HierarchicalVm<Model>,
    items: Vec<HierarchicalVm<Model>>,
    policy: MissingParentPolicy,
) -> vmx::BatchAttachResult<HierarchicalVm<Model>> {
    root.attach_many(
        items,
        |item| Ok(item.model().key),
        |item| Ok(item.model().parent_key),
        policy,
    )
}

/// HIER-023 — child-before-parent input resolves to a stable fixpoint.
#[test]
fn child_before_parent_reaches_stable_fixpoint() {
    let root = node("root", None);
    let grandchild = node("grandchild", Some("child-a"));
    let child_b = node("child-b", Some("parent"));
    let child_a = node("child-a", Some("parent"));
    let parent = node("parent", None);
    let result = attach(
        &root,
        vec![
            grandchild.clone(),
            child_b.clone(),
            child_a.clone(),
            parent.clone(),
        ],
        MissingParentPolicy::Park,
    );

    assert_eq!(result.added.len(), 4);
    assert!(root.children() == vec![parent.clone()]);
    assert!(parent.children() == vec![child_b, child_a.clone()]);
    assert!(child_a.children() == vec![grandchild.clone()]);
    assert_eq!(
        grandchild
            .path()
            .into_iter()
            .map(|item| item.name())
            .collect::<Vec<_>>(),
        vec!["root", "parent", "child-a", "grandchild"]
    );
    assert!(result.rejections.is_empty());
}

/// HIER-024 — None parent keys attach directly below the structural root.
#[test]
fn multiple_root_items_preserve_input_order() {
    let root = node("root", None);
    let first = node("first", None);
    let second = node("second", None);
    let result = attach(
        &root,
        vec![first.clone(), second.clone()],
        MissingParentPolicy::Park,
    );
    assert!(result.added == vec![first.clone(), second.clone()]);
    assert!(root.children() == vec![first, second]);
}

/// HIER-025 — duplicate keys never replace the authoritative node.
#[test]
fn duplicate_keys_are_non_throwing_and_non_replacing() {
    let root = node("root", None);
    let existing = node("existing", None);
    root.add_child(existing.clone()).unwrap();
    let conflict = node("existing", None);
    let first = node("new", None);
    let batch_conflict = node("new", None);
    let result = attach(
        &root,
        vec![conflict.clone(), first.clone(), batch_conflict.clone()],
        MissingParentPolicy::Park,
    );
    assert!(result.added == vec![first.clone()]);
    assert!(result.duplicates == vec![conflict, batch_conflict]);
    assert_eq!(
        result
            .rejections
            .iter()
            .map(|item| item.reason)
            .collect::<Vec<_>>(),
        vec![
            BatchAttachRejectionReason::DuplicateExistingKey,
            BatchAttachRejectionReason::DuplicateBatchKey,
        ]
    );
    assert!(root.children() == vec![existing, first.clone()]);
    assert_eq!(
        attach(&root, vec![first], MissingParentPolicy::Park)
            .duplicates
            .len(),
        1
    );
}

/// HIER-026 — parked orphans retry when their parent arrives later.
#[test]
fn parked_orphan_resolves_across_batches() {
    let root = node("root", None);
    let child = node("child", Some("parent"));
    assert!(
        attach(&root, vec![child.clone()], MissingParentPolicy::Park).orphans
            == vec![child.clone()]
    );
    assert_eq!(root.parked_attach_count(), 1);
    let parent = node("parent", None);
    let result = attach(&root, vec![parent.clone()], MissingParentPolicy::Park);
    assert_eq!(result.added.len(), 2);
    assert!(child.parent() == Some(parent));
    assert_eq!(root.parked_attach_count(), 0);
}

/// HIER-027 — reject policy does not retain an unresolved item.
#[test]
fn reject_policy_does_not_retain_orphan() {
    let root = node("root", None);
    let child = node("child", Some("parent"));
    assert!(
        attach(&root, vec![child.clone()], MissingParentPolicy::Reject).orphans
            == vec![child.clone()]
    );
    assert_eq!(root.parked_attach_count(), 0);
    let parent = node("parent", None);
    attach(&root, vec![parent.clone()], MissingParentPolicy::Park);
    assert!(child.parent().is_none());
    assert!(parent.children().is_empty());
}

/// HIER-028 — parent-key cycles are terminal, non-throwing rejections.
#[test]
fn cycles_are_terminal_rejections() {
    let root = node("root", None);
    let first = node("first", Some("second"));
    let second = node("second", Some("first"));
    let result = attach(&root, vec![first, second], MissingParentPolicy::Park);
    assert!(result.added.is_empty());
    assert!(result.orphans.is_empty());
    assert_eq!(
        result
            .rejections
            .iter()
            .map(|item| item.reason)
            .collect::<Vec<_>>(),
        vec![
            BatchAttachRejectionReason::Cycle,
            BatchAttachRejectionReason::Cycle
        ]
    );
    assert_eq!(root.parked_attach_count(), 0);
}

/// HIER-029 — typed failures preserve existing parent links atomically.
#[test]
fn rejections_are_structured_and_atomic() {
    let root = node("root", None);
    let outside = node("outside", None);
    let attached = node("attached", None);
    outside.add_child(attached.clone()).unwrap();
    let detached_same_key = node("attached", None);
    let result = attach(
        &root,
        vec![attached.clone(), detached_same_key.clone()],
        MissingParentPolicy::Park,
    );
    assert_eq!(
        result.rejections[0].reason,
        BatchAttachRejectionReason::AlreadyAttached
    );
    assert!(attached.parent() == Some(outside.clone()));
    assert!(outside.children() == vec![attached]);
    assert!(result.added == vec![detached_same_key.clone()]);
    assert!(root.children() == vec![detached_same_key]);

    let failed = root.attach_many::<String, _, _>(
        vec![node("bad", None)],
        |_| Err(VmxError::Other("bad key".to_string())),
        |_| Ok(None),
        MissingParentPolicy::Park,
    );
    assert_eq!(
        failed.rejections[0].reason,
        BatchAttachRejectionReason::SelectorFailed
    );
}

/// HIER-030 — disposal clears root-owned parked state.
#[test]
fn disposal_clears_parked_items() -> VmxResult<()> {
    let root = node("root", None);
    attach(
        &root,
        vec![node("child", Some("missing"))],
        MissingParentPolicy::Park,
    );
    assert_eq!(root.parked_attach_count(), 1);
    root.dispose()?;
    assert_eq!(root.parked_attach_count(), 0);
    Ok(())
}

// Selector failures on individual items (#362 coverage review). A failing
// selector rejects only that item; a parked item stays parked for a later batch.

#[test]
fn parent_selector_failure_rejects_only_that_item() {
    let root = node("root", None);
    let good = node("good", None);
    let bad = node("bad", None);

    let result = root.attach_many(
        vec![good.clone(), bad.clone()],
        |item| Ok(item.model().key),
        |item| {
            if item.model().key == "bad" {
                Err(VmxError::Other("no parent key".to_string()))
            } else {
                Ok(item.model().parent_key)
            }
        },
        MissingParentPolicy::Park,
    );

    assert!(result.added == vec![good.clone()]);
    assert_eq!(result.rejections.len(), 1);
    assert!(result.rejections[0].item == bad);
    assert_eq!(
        result.rejections[0].reason,
        BatchAttachRejectionReason::SelectorFailed
    );
    assert!(root.children() == vec![good]);
    assert!(bad.parent().is_none());
}

#[test]
fn a_parked_item_whose_selector_fails_stays_parked_for_the_next_batch() {
    let root = node("root", None);
    let orphan = node("orphan", Some("parent"));
    let parked = attach(&root, vec![orphan.clone()], MissingParentPolicy::Park);
    assert!(parked.added.is_empty());

    // The key selector fails for the parked item on this batch only.
    let failed = root.attach_many(
        Vec::new(),
        |item| {
            if item.model().key == "orphan" {
                Err(VmxError::Other("key unavailable".to_string()))
            } else {
                Ok(item.model().key)
            }
        },
        |item| Ok(item.model().parent_key),
        MissingParentPolicy::Park,
    );
    assert!(failed
        .rejections
        .iter()
        .any(|rejection| rejection.item == orphan
            && rejection.reason == BatchAttachRejectionReason::SelectorFailed));
    assert!(orphan.parent().is_none());

    // The item was re-parked, so a batch that brings its parent attaches it.
    let parent = node("parent", None);
    let resolved = attach(&root, vec![parent.clone()], MissingParentPolicy::Park);
    assert!(resolved.added.contains(&orphan));
    assert!(orphan.parent() == Some(parent.clone()));
    assert!(parent.children() == vec![orphan]);
}
