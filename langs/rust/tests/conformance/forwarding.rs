use std::sync::{Arc, Mutex};

use vmx::{
    Command, ConstructionStatus, ForwardingComponentVm, ForwardingCompositeVm, MessageHub,
    NullDispatcher,
};

type Child = vmx::ComponentVm<&'static str>;

fn child(name: &'static str) -> Child {
    Child::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

/// FWD-001 — ForwardingComponentVM delegates every member to wrapped
#[test]
fn forwarding_component_delegates_to_inner() {
    let inner = child("inner");
    let forwarding = ForwardingComponentVm::new(inner.clone())
        .with_model_hint(|model| Some(format!("model:{model}")));
    let lifecycle = Arc::new(Mutex::new(Vec::new()));
    let construct_lifecycle = Arc::clone(&lifecycle);
    forwarding.on_construct(move || {
        construct_lifecycle.lock().unwrap().push("construct");
        Ok(())
    });
    let destruct_lifecycle = Arc::clone(&lifecycle);
    forwarding.on_destruct(move || {
        destruct_lifecycle.lock().unwrap().push("destruct");
        Ok(())
    });
    let dispose_lifecycle = Arc::clone(&lifecycle);
    forwarding.on_dispose(move || {
        dispose_lifecycle.lock().unwrap().push("dispose");
        Ok(())
    });

    forwarding.construct().unwrap();
    forwarding.set_model("updated");

    assert_eq!(forwarding.id(), inner.id());
    assert_eq!(forwarding.name(), inner.name());
    assert_eq!(forwarding.model(), "updated");
    assert_eq!(forwarding.modeled_hint(), Some("model:updated".to_string()));
    assert_eq!(forwarding.status(), ConstructionStatus::Constructed);
    assert_eq!(forwarding.can_select(), inner.can_select());
    assert_eq!(forwarding.can_deselect(), inner.can_deselect());
    assert_eq!(
        forwarding.deselect_command().can_execute(),
        inner.deselect_command().can_execute()
    );
    assert_eq!(
        forwarding.select_next_command().can_execute(),
        inner.select_next_command().can_execute()
    );
    assert_eq!(
        forwarding.select_previous_command().can_execute(),
        inner.select_previous_command().can_execute()
    );
    assert_eq!(
        forwarding.reconstruct_command().can_execute(),
        inner.reconstruct_command().can_execute()
    );
    forwarding.expand();
    assert!(forwarding.is_expanded());
    assert!(inner.is_expanded());
    forwarding.toggle_expansion();
    assert!(!forwarding.is_expanded());
    forwarding.expand();
    forwarding.collapse();
    assert!(!inner.is_expanded());
    forwarding.destruct().unwrap();
    forwarding.dispose().unwrap();
    assert_eq!(
        *lifecycle.lock().unwrap(),
        vec!["construct", "destruct", "dispose"]
    );
}

#[test]
fn forwarding_component_is_a_transparent_container_child() {
    let inner = child("inner");
    let forwarding = ForwardingComponentVm::new(inner.clone());
    let composite = vmx::CompositeVm::new("root");

    composite.add(forwarding.clone()).unwrap();
    composite.construct().unwrap();
    assert!(forwarding.select_command().can_execute());
    forwarding.select_command().execute();

    assert_eq!(forwarding.parent_id(), Some(composite.id()));
    assert!(forwarding.is_current());
    assert!(inner.is_current());
    assert!(composite.current() == Some(forwarding));
}

/// FWD-004 — a forwarding component preserves one transferable underlying owner
#[test]
fn forwarding_component_transfers_one_underlying_owner() {
    let inner = child("inner");
    let old_parent = vmx::CompositeVm::new("old");
    let group = vmx::GroupVm::new("group");
    let destination = vmx::CompositeVm::new("destination");
    old_parent.add(inner.clone()).unwrap();
    let forwarding = ForwardingComponentVm::new(inner.clone());
    let first = forwarding.with_hint_override(|| Some("first".to_string()));
    let nested_forwarding = ForwardingComponentVm::wrap(first);

    assert_eq!(nested_forwarding.hint(), Some("first".to_string()));

    group.add(nested_forwarding.clone()).unwrap();

    assert!(old_parent.is_empty());
    assert!(group.items() == vec![nested_forwarding.clone()]);

    let alternate_forwarding = ForwardingComponentVm::new(inner.clone());
    destination.add(alternate_forwarding.clone()).unwrap();
    destination.construct().unwrap();
    destination.select_component(&alternate_forwarding).unwrap();

    assert!(group.is_empty());
    assert!(destination.items() == vec![alternate_forwarding.clone()]);
    assert!(destination.current() == Some(alternate_forwarding));
    assert!(inner.is_current());

    group.add(nested_forwarding.clone()).unwrap();

    assert!(destination.is_empty());
    assert!(destination.current().is_none());
    assert!(group.items() == vec![nested_forwarding]);
}

/// FWD-002 — Selective override replaces a single behavior
#[test]
fn selective_override_replaces_one_behavior() {
    let inner = child("inner");
    let forwarding =
        ForwardingComponentVm::new(inner).with_hint_override(|| Some("override".to_string()));

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
