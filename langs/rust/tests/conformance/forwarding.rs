use vmx::{
    ConstructionStatus, ForwardingComponentVm, ForwardingCompositeVm, MessageHub, NullDispatcher,
    VmNode,
};

type Child = vmx::ComponentVm<&'static str>;

fn child(name: &'static str) -> Child {
    Child::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

struct HintOverride {
    inner: ForwardingComponentVm<&'static str>,
}

impl HintOverride {
    fn new(inner: Child) -> Self {
        Self {
            inner: ForwardingComponentVm::new(inner),
        }
    }

    fn hint(&self) -> Option<String> {
        Some("override".to_string())
    }

    fn name(&self) -> String {
        self.inner.name()
    }

    fn model(&self) -> &'static str {
        self.inner.model()
    }
}

/// FWD-001 — ForwardingComponentVM delegates every member to wrapped
#[test]
fn forwarding_component_delegates_to_inner() {
    let inner = child("inner");
    let forwarding = ForwardingComponentVm::new(inner.clone());

    forwarding.construct().unwrap();
    forwarding.set_model("updated");

    assert_eq!(forwarding.id(), inner.id());
    assert_eq!(forwarding.name(), inner.name());
    assert_eq!(forwarding.model(), "updated");
    assert_eq!(forwarding.status(), ConstructionStatus::Constructed);
}

#[test]
fn forwarding_component_is_a_transparent_container_child() {
    let inner = child("inner");
    let forwarding = ForwardingComponentVm::new(inner.clone());
    let composite = vmx::CompositeVm::new("root");

    composite.add(forwarding.clone()).unwrap();
    forwarding.construct().unwrap();
    composite.select_component(&forwarding).unwrap();

    assert_eq!(forwarding.parent_id(), Some(composite.id()));
    assert!(forwarding.is_current());
    assert!(inner.is_current());
    assert!(composite.current() == Some(forwarding));
}

/// FWD-002 — Selective override replaces a single behavior
#[test]
fn selective_override_replaces_one_behavior() {
    let inner = child("inner");
    let forwarding = HintOverride::new(inner);

    assert_eq!(forwarding.hint(), Some("override".to_string()));
    assert_eq!(forwarding.name(), "inner");
    assert_eq!(forwarding.model(), "inner");
}

/// FWD-003 — ForwardingCompositeVM forwards iteration
#[test]
fn forwarding_composite_forwards_items() {
    let composite = vmx::CompositeVm::new("root");
    let a = child("a");
    let b = child("b");
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    let forwarding = ForwardingCompositeVm::new(composite);

    assert_eq!(forwarding.len(), 2);
    assert_eq!((&forwarding).into_iter().collect::<Vec<_>>(), vec![a, b]);
}

#[test]
fn forwarding_composite_delegates_complete_collection_and_selection_surface() {
    let composite = vmx::CompositeVm::new("root");
    let a = child("a");
    let b = child("b");
    let c = child("c");
    let d = child("d");
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    composite.construct().unwrap();
    let forwarding = ForwardingCompositeVm::new(composite.clone());

    assert_eq!(forwarding.name(), composite.name());
    assert_eq!(forwarding.hint(), composite.hint());
    assert!(forwarding.is_constructed());
    forwarding.reconstruct().unwrap();
    assert!(forwarding.is_constructed());
    assert_eq!(forwarding.parent_id(), composite.parent_id());
    assert_eq!(forwarding.get(0), Some(a.clone()));
    forwarding.insert(1, c.clone()).unwrap();
    assert_eq!(forwarding.replace(1, d).unwrap(), c);
    forwarding.move_item(0, 1).unwrap();
    forwarding.batch_update(|| forwarding.add(c.clone()).unwrap());
    forwarding.set_current(Some(a.clone())).unwrap();
    assert_eq!(forwarding.current(), Some(a.clone()));
    assert!(forwarding.can_select_component(&b));
    assert_eq!(forwarding.remove_at(3).unwrap(), c);
    forwarding.clear();

    assert!(composite.is_empty());
    assert_eq!(forwarding.current(), None);
}
