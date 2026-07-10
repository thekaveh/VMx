use vmx::{
    ConstructionStatus, ForwardingComponentVm, ForwardingCompositeVm, MessageHub, NullDispatcher,
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
    assert_eq!(forwarding.items(), vec![a, b]);
}
