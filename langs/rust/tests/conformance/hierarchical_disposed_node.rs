//! A disposed hierarchy node refuses structural calls (spec/18 §7.1,
//! ADR-0190).

use vmx::{
    BatchAttachRejectionReason, ConstructionStatus, HierarchicalVm, Message, MessageHub,
    MessageRecorder, MissingParentPolicy, VmxError,
};

type Node = HierarchicalVm<String>;

fn node(hub: &MessageHub, name: &str) -> Node {
    HierarchicalVm::with_children_factory(
        name,
        name.to_string(),
        |_| Vec::new(),
        false,
        hub.clone(),
    )
}

fn attach(
    receiver: &Node,
    items: Vec<Node>,
    parent_key: Option<&str>,
    policy: MissingParentPolicy,
) -> vmx::BatchAttachResult<Node> {
    let parent_key = parent_key.map(str::to_string);
    receiver.attach_many(
        items,
        |item| Ok(item.model()),
        move |_| Ok(parent_key.clone()),
        policy,
    )
}

fn structural_messages(recorder: &MessageRecorder) -> Vec<Message> {
    recorder
        .messages()
        .into_iter()
        .filter(|message| {
            matches!(
                message,
                Message::TreeStructureChanged(_) | Message::PropertyChanged(_)
            )
        })
        .collect()
}

fn children_change_from(recorder: &MessageRecorder, sender: &Node) -> bool {
    recorder.messages().iter().any(|message| {
        matches!(
            message,
            Message::PropertyChanged(change)
                if change.sender_id == sender.id() && change.property_name == "children"
        )
    })
}

/// HIER-041 — A disposed node refuses structural calls, without mutation or
/// messages; a transfer from a disposed parent refuses; `attach_many` rejects
/// a candidate under a disposed parent; `invalidate_subtree` skips a disposed
/// descendant.
#[test]
fn disposed_node_refuses_structural_calls() {
    let hub = MessageHub::new();
    let r = node(&hub, "r");
    let a = node(&hub, "a");
    let b = node(&hub, "b");
    let aa = node(&hub, "aa");
    let d = node(&hub, "d");
    r.add_child(a.clone()).unwrap();
    r.add_child(b.clone()).unwrap();
    a.add_child(aa.clone()).unwrap();
    for vm in [&r, &a, &b, &aa, &d] {
        vm.construct().unwrap();
        vm.children();
    }
    let recorder = hub.record(1024);

    assert_eq!(a.status(), ConstructionStatus::Constructed);
    a.dispose().unwrap();
    recorder.clear();

    assert_eq!(a.add_child(d.clone()), Err(VmxError::Disposed));
    assert_eq!(a.remove_child(&aa), Err(VmxError::Disposed));
    assert_eq!(a.reparent_child(&d), Err(VmxError::Disposed));
    assert_eq!(
        a.add_child(aa.clone()),
        Err(VmxError::Disposed),
        "re-add of a member"
    );
    assert_eq!(
        a.remove_child(&d),
        Err(VmxError::Disposed),
        "remove of a non-member"
    );
    a.invalidate_children();
    a.invalidate_subtree();
    let batch = attach(&a, vec![d.clone()], None, MissingParentPolicy::Park);
    assert!(batch.added.is_empty());
    assert!(batch.orphans.is_empty());
    assert_eq!(batch.rejections.len(), 1);
    assert_eq!(
        batch.rejections[0].reason,
        BatchAttachRejectionReason::AttachmentFailed
    );
    assert_eq!(
        batch.rejections[0].detail,
        Some(VmxError::Disposed.to_string())
    );

    assert!(a.is_children_materialized());
    assert!(a.children() == vec![aa.clone()]);
    assert!(aa.parent().as_ref() == Some(&a));
    assert!(d.parent().is_none());
    assert_eq!(r.parked_attach_count(), 0);
    assert!(structural_messages(&recorder).is_empty());

    assert_eq!(b.add_child(aa.clone()), Err(VmxError::Disposed));
    assert_eq!(b.reparent_child(&aa), Err(VmxError::Disposed));
    assert!(aa.parent().as_ref() == Some(&a));
    assert!(a.children() == vec![aa.clone()]);
    assert!(b.children().is_empty());
    assert!(structural_messages(&recorder).is_empty());

    let batch = attach(&r, vec![d.clone()], Some("a"), MissingParentPolicy::Park);
    assert!(batch.added.is_empty());
    assert!(batch.orphans.is_empty(), "not an orphan");
    assert_eq!(batch.rejections.len(), 1);
    assert_eq!(
        batch.rejections[0].reason,
        BatchAttachRejectionReason::AttachmentFailed
    );
    assert_eq!(r.parked_attach_count(), 0, "not parked");
    assert!(d.parent().is_none());
    assert!(a.children() == vec![aa.clone()]);
    assert!(structural_messages(&recorder).is_empty());

    r.invalidate_subtree();
    assert!(!r.is_children_materialized());
    assert!(!aa.is_children_materialized());
    assert!(!b.is_children_materialized());
    assert!(a.is_children_materialized());
    assert!(a.children() == vec![aa.clone()]);
    assert!(aa.parent().as_ref() == Some(&a));
    assert!(children_change_from(&recorder, &r));
    assert!(children_change_from(&recorder, &aa));
    assert!(!children_change_from(&recorder, &a));
}

/// HIER-041 — a live receiver under a disposed structural root refuses
/// `attach_many` and parks nothing.
#[test]
fn attach_many_under_a_disposed_root_rejects_every_item() {
    let hub = MessageHub::new();
    let root = node(&hub, "root");
    let c = node(&hub, "c");
    root.add_child(c.clone()).unwrap();
    c.children();
    root.dispose().unwrap();
    let item = node(&hub, "item");

    let batch = attach(
        &c,
        vec![item.clone()],
        Some("missing"),
        MissingParentPolicy::Park,
    );

    assert!(batch.added.is_empty());
    assert!(batch.orphans.is_empty());
    assert_eq!(batch.rejections.len(), 1);
    assert_eq!(
        batch.rejections[0].reason,
        BatchAttachRejectionReason::AttachmentFailed
    );
    assert_eq!(root.parked_attach_count(), 0);
    assert!(item.parent().is_none());
    assert!(c.children().is_empty());
}

/// HIER-041 — a live node can still remove, transfer and invalidate a
/// disposed child.
#[test]
fn live_node_still_moves_a_disposed_child() {
    let hub = MessageHub::new();
    let p = node(&hub, "p");
    let q = node(&hub, "q");
    let x = node(&hub, "x");
    let y = node(&hub, "y");
    p.add_child(x.clone()).unwrap();
    p.add_child(y.clone()).unwrap();
    x.dispose().unwrap();
    y.dispose().unwrap();

    q.add_child(x.clone()).unwrap();
    assert!(x.parent().as_ref() == Some(&q));
    p.remove_child(&y).unwrap();
    assert!(y.parent().is_none());
    q.invalidate_children();
    assert!(!q.is_children_materialized());
    assert!(x.parent().is_none());
}

/// HIER-041 — a refused transfer out of a disposed parent leaves a lazy
/// receiver unmaterialized: its factory does not run.
#[test]
fn refused_transfer_does_not_materialize_a_lazy_receiver() {
    let hub = MessageHub::new();
    let a = node(&hub, "a");
    let aa = node(&hub, "aa");
    a.add_child(aa.clone()).unwrap();
    a.dispose().unwrap();
    let factory_calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let calls = factory_calls.clone();
    let b: Node = HierarchicalVm::with_children_factory(
        "b",
        "b".to_string(),
        move |_| {
            calls.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            Vec::new()
        },
        false,
        hub.clone(),
    );

    assert_eq!(b.add_child(aa.clone()), Err(VmxError::Disposed));
    assert_eq!(b.reparent_child(&aa), Err(VmxError::Disposed));

    assert_eq!(factory_calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    assert!(!b.is_children_materialized());
    assert!(aa.parent().as_ref() == Some(&a));
}
