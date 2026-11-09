//! Public-API tests for the per-phase lifecycle hook methods of
//! `HierarchicalVm`, `ModeledCompositeVm` and `ForwardingCompositeVm`
//! (spec/02 §2.2, ADR-0203).

use std::sync::{Arc, Mutex};
use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, ForwardingCompositeVm, HierarchicalVm, Message,
    MessageHub, ModeledCompositeVm, NullDispatcher, Subscription, VmNode, VmxError, VmxResult,
};

type Log = Arc<Mutex<Vec<String>>>;

/// Records the hub status changes of the view-model `id` and the hook events
/// in one ordered log.
fn record(hub: &MessageHub, id: impl Fn() -> usize + Send + Sync + 'static) -> (Log, Subscription) {
    let log: Log = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&log);
    let subscription = hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(change) = message {
            if change.sender_id == id() {
                sink.lock().unwrap().push(format!("{:?}", change.status));
            }
        }
    });
    (log, subscription)
}

/// A hook that appends `event` to `log`.
fn hook(log: &Log, event: &'static str) -> impl FnMut() -> VmxResult<()> + Send + 'static {
    let log = Arc::clone(log);
    move || {
        log.lock().unwrap().push(event.to_string());
        Ok(())
    }
}

fn take(log: &Log) -> Vec<String> {
    std::mem::take(&mut *log.lock().unwrap())
}

fn hierarchy(hub: &MessageHub, eager: bool) -> HierarchicalVm<String> {
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
        eager,
        hub.clone(),
    )
}

#[test]
fn hierarchical_vm_hooks_run_once_in_their_phase_with_lazy_and_eager_children() {
    for eager in [false, true] {
        let hub = MessageHub::new();
        let node = hierarchy(&hub, eager);
        let id = node.id();
        let (log, _subscription) = record(&hub, move || id);
        node.on_construct(hook(&log, "on_construct"));
        node.on_destruct(hook(&log, "on_destruct"));
        node.on_dispose(hook(&log, "on_dispose"));

        node.construct().unwrap();
        assert_eq!(
            take(&log),
            ["Constructing", "on_construct", "Constructed"],
            "eager: {eager}"
        );
        assert_eq!(
            node.is_children_materialized(),
            eager,
            "only an eager node materializes its children"
        );
        if eager {
            assert_eq!(node.children()[0].status(), ConstructionStatus::Constructed);
        }

        VmNode::destruct(&node).unwrap();
        assert_eq!(
            take(&log),
            ["Destructing", "on_destruct", "Destructed"],
            "eager: {eager}"
        );

        node.dispose().unwrap();
        assert_eq!(take(&log), ["Disposed", "on_dispose"], "eager: {eager}");
    }
}

#[test]
fn a_failing_construct_hook_fails_a_hierarchical_vm_like_a_component_vm() {
    let failure = || VmxError::Other("construct failed".to_string());
    for eager in [false, true] {
        let hub = MessageHub::new();
        let node = hierarchy(&hub, eager);
        node.on_construct(move || Err(failure()));
        let component = ComponentVm::new("component");
        component.on_construct(move || Err(failure()));

        assert_eq!(node.construct(), Err(failure()), "eager: {eager}");
        assert_eq!(component.construct(), Err(failure()));
        assert_eq!(node.status(), component.status(), "eager: {eager}");
        assert_eq!(node.status(), ConstructionStatus::Destructed);
        assert!(
            !node.is_children_materialized(),
            "a failing hook constructs no child (eager: {eager})"
        );
    }
}

#[test]
fn modeled_composite_vm_hooks_run_once_in_their_phase_and_in_reconstruct() {
    let hub = MessageHub::new();
    let child_hub = hub.clone();
    let composite: ModeledCompositeVm<i32, ComponentVm<i32>> = ModeledCompositeVm::new(
        "modeled",
        hub.clone(),
        NullDispatcher::new(),
        || vec![1, 2],
        move |model| {
            ComponentVm::with_model("child", model, child_hub.clone(), NullDispatcher::new())
        },
    );
    let id = VmNode::id(&composite);
    let (log, _subscription) = record(&hub, move || id);
    composite.on_construct(hook(&log, "on_construct"));
    composite.on_destruct(hook(&log, "on_destruct"));
    composite.on_dispose(hook(&log, "on_dispose"));

    composite.construct().unwrap();
    assert_eq!(take(&log), ["Constructing", "on_construct", "Constructed"]);
    assert_eq!(composite.len(), 2);

    composite.reconstruct().unwrap();
    assert_eq!(
        take(&log),
        [
            "Destructing",
            "on_destruct",
            "Destructed",
            "Constructing",
            "on_construct",
            "Constructed"
        ]
    );

    VmNode::destruct(&composite).unwrap();
    assert_eq!(take(&log), ["Destructing", "on_destruct", "Destructed"]);

    VmNode::dispose(&composite).unwrap();
    assert_eq!(take(&log), ["Disposed", "on_dispose"]);
}

#[test]
fn forwarding_composite_vm_forwards_the_hooks_to_the_wrapped_composite() {
    let hub = MessageHub::new();
    let inner: CompositeVm<ComponentVm> =
        CompositeVm::with_services("inner", hub.clone(), NullDispatcher::new());
    let wrapper = ForwardingCompositeVm::new(inner);
    let id = wrapper.id();
    let (log, _subscription) = record(&hub, move || id);
    wrapper.on_construct(hook(&log, "on_construct"));
    wrapper.on_destruct(hook(&log, "on_destruct"));
    wrapper.on_dispose(hook(&log, "on_dispose"));

    wrapper.construct().unwrap();
    assert_eq!(take(&log), ["Constructing", "on_construct", "Constructed"]);

    wrapper.destruct().unwrap();
    assert_eq!(take(&log), ["Destructing", "on_destruct", "Destructed"]);

    wrapper.dispose().unwrap();
    assert_eq!(take(&log), ["Disposed", "on_dispose"]);
}
