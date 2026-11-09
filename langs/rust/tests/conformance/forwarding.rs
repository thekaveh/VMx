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
    let forwarding =
        ForwardingComponentVm::new(inner.clone()).with_model_hint(|model| format!("model:{model}"));
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
    assert_eq!(forwarding.modeled_hint(), "model:updated");
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
    let first = forwarding.with_hint_override(|| "first".to_string());
    let nested_forwarding = ForwardingComponentVm::wrap(first);

    assert_eq!(nested_forwarding.hint(), "first");

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
    let inner = Child::builder()
        .name("inner")
        .hint("inner-hint")
        .model("inner")
        .services(MessageHub::new(), NullDispatcher::new())
        .build()
        .unwrap();
    let forwarding =
        ForwardingComponentVm::new(inner.clone()).with_hint_override(|| "OVERRIDE".to_string());

    assert_eq!(forwarding.hint(), "OVERRIDE");
    assert_eq!(inner.hint(), "inner-hint", "the wrapped VM is unchanged");

    // Every other member still delegates to the wrapped VM.
    assert_eq!(forwarding.id(), inner.id());
    assert_eq!(forwarding.name(), inner.name());
    assert_eq!(forwarding.view_model_type(), inner.view_model_type());
    assert_eq!(forwarding.model(), inner.model());
    assert_eq!(forwarding.parent_id(), inner.parent_id());
    assert_eq!(forwarding.status(), inner.status());
    forwarding.construct().unwrap();
    assert_eq!(inner.status(), ConstructionStatus::Constructed);
    assert_eq!(forwarding.status(), inner.status());
    forwarding.set_model("updated");
    assert_eq!(inner.model(), "updated");
    assert_eq!(forwarding.model(), "updated");
    assert_eq!(forwarding.can_select(), inner.can_select());
    assert_eq!(forwarding.is_selected(), inner.is_selected());
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
    forwarding.clear().unwrap();

    assert!(composite.is_empty());
    assert_eq!(forwarding.current(), None);
}

fn record(log: &Arc<Mutex<Vec<&'static str>>>, entry: &'static str) -> impl FnOnce() + Send {
    let log = Arc::clone(log);
    move || log.lock().unwrap().push(entry)
}

/// FWD-005 — decorators register owned resources on the wrapped component
#[test]
fn forwarding_decorators_register_owned_resources_on_the_wrapped_component() {
    let inner = child("inner");
    let first = ForwardingComponentVm::new(inner.clone());
    let second = ForwardingComponentVm::wrap(first.clone());
    let released = Arc::new(Mutex::new(Vec::new()));
    first.own(record(&released, "r1"));
    second.own(record(&released, "r2"));
    inner.construct().unwrap();

    second.dispose().unwrap();

    assert_eq!(inner.status(), ConstructionStatus::Disposed);
    assert_eq!(*released.lock().unwrap(), vec!["r2", "r1"]);

    first.own(record(&released, "r3"));
    assert_eq!(*released.lock().unwrap(), vec!["r2", "r1", "r3"]);

    first.dispose().unwrap();
    second.dispose().unwrap();
    inner.dispose().unwrap();
    assert_eq!(*released.lock().unwrap(), vec!["r2", "r1", "r3"]);
}

/// FWD-005 — disposing the wrapped component releases decorator resources
#[test]
fn disposing_the_wrapped_component_releases_decorator_resources() {
    let inner = child("inner");
    let first = ForwardingComponentVm::new(inner.clone());
    let second = ForwardingComponentVm::wrap(first.clone());
    let released = Arc::new(Mutex::new(Vec::new()));
    first.own(record(&released, "r1"));
    second.own(record(&released, "r2"));

    inner.dispose().unwrap();

    assert_eq!(*released.lock().unwrap(), vec!["r2", "r1"]);
    second.dispose().unwrap();
    assert_eq!(*released.lock().unwrap(), vec!["r2", "r1"]);
}

type Leaf = vmx::ComponentVm<i32>;
type Wrapped = vmx::CompositeVm<Leaf>;
type Decorated = ForwardingCompositeVm<Leaf>;

fn leaf(name: &'static str) -> Leaf {
    Leaf::with_model(name, 0, MessageHub::new(), NullDispatcher::new())
}

/// FWD-004 — a forwarding composite is a selectable container child that
/// shares the wrapped composite's current flag
#[test]
fn forwarding_composite_is_a_selectable_container_child() {
    let parent: vmx::CompositeVm<Decorated> = vmx::CompositeVm::new("parent");
    parent.construct().unwrap();
    let inner = Wrapped::new("inner");
    let decorator = ForwardingCompositeVm::new(inner.clone());

    parent.add(decorator.clone()).unwrap();
    decorator.construct().unwrap();
    parent.select_component(&decorator).unwrap();

    assert!(parent.current() == Some(decorator.clone()));
    assert!(decorator.is_current());
    assert!(inner.is_current());
    assert_eq!(decorator.parent_id(), Some(parent.id()));
}

/// FWD-004 — two decorators of one composite share one ownership identity
#[test]
fn forwarding_composite_decorators_transfer_one_owner() {
    let first: vmx::CompositeVm<Decorated> = vmx::CompositeVm::new("first");
    let second: vmx::CompositeVm<Decorated> = vmx::CompositeVm::new("second");
    let inner = Wrapped::new("inner");
    let d1 = ForwardingCompositeVm::new(inner.clone());
    let d2 = ForwardingCompositeVm::new(inner.clone());

    first.add(d1).unwrap();
    second.add(d2.clone()).unwrap();

    assert!(first.is_empty());
    assert!(second.items() == vec![d2]);
    assert_eq!(inner.parent_id(), Some(second.id()));
}

/// FWD-004 — adding the wrapped composite elsewhere detaches its decorator
#[test]
fn adding_the_wrapped_composite_detaches_its_decorator() {
    let first: vmx::CompositeVm<Decorated> = vmx::CompositeVm::new("first");
    let second: vmx::CompositeVm<Wrapped> = vmx::CompositeVm::new("second");
    let inner = Wrapped::new("inner");
    let decorator = ForwardingCompositeVm::new(inner.clone());

    first.add(decorator).unwrap();
    second.add(inner.clone()).unwrap();

    assert!(first.is_empty());
    assert!(second.items() == vec![inner.clone()]);
    assert_eq!(inner.parent_id(), Some(second.id()));
}

fn counted(name: &'static str, constructs: &Arc<Mutex<usize>>) -> Wrapped {
    let inner = Wrapped::new(name);
    let constructs = Arc::clone(constructs);
    inner.on_construct(move || {
        *constructs.lock().unwrap() += 1;
        Ok(())
    });
    inner
}

/// FWD-004 — a group and an aggregate run a decorated composite's lifecycle
/// once through the decorator
#[test]
fn group_and_aggregate_run_a_decorated_composite_lifecycle() {
    let group_constructs = Arc::new(Mutex::new(0));
    let group_inner = counted("group-inner", &group_constructs);
    let group = vmx::GroupVm::new("group");
    group
        .add(ForwardingCompositeVm::new(group_inner.clone()))
        .unwrap();

    let aggregate_constructs = Arc::new(Mutex::new(0));
    let aggregate_inner = counted("aggregate-inner", &aggregate_constructs);
    let aggregate = vmx::AggregateVm1::new(
        "aggregate",
        ForwardingCompositeVm::new(aggregate_inner.clone()),
    );

    group.construct().unwrap();
    aggregate.construct().unwrap();
    assert_eq!(group_inner.status(), ConstructionStatus::Constructed);
    assert_eq!(aggregate_inner.status(), ConstructionStatus::Constructed);
    group.dispose().unwrap();
    aggregate.dispose().unwrap();

    assert_eq!(*group_constructs.lock().unwrap(), 1);
    assert_eq!(*aggregate_constructs.lock().unwrap(), 1);
    assert_eq!(group_inner.status(), ConstructionStatus::Disposed);
    assert_eq!(aggregate_inner.status(), ConstructionStatus::Disposed);
}

/// The composite decorator forwards selection, expansion, commands, hooks,
/// callbacks and configuration to the wrapped composite (spec/09 §2)
#[test]
fn forwarding_composite_forwards_the_remaining_composite_surface() {
    let parent: vmx::CompositeVm<Decorated> = vmx::CompositeVm::new("parent");
    let inner = Wrapped::new("inner");
    let decorator = ForwardingCompositeVm::new(inner.clone());
    parent.add(decorator.clone()).unwrap();

    // Lifecycle hooks registered on the decorator run on the wrapped composite.
    let log = Arc::new(Mutex::new(Vec::new()));
    let hook_log = Arc::clone(&log);
    decorator.on_construct(move || {
        hook_log.lock().unwrap().push("construct");
        Ok(())
    });
    let hook_log = Arc::clone(&log);
    decorator.on_destruct(move || {
        hook_log.lock().unwrap().push("destruct");
        Ok(())
    });
    let hook_log = Arc::clone(&log);
    decorator.on_dispose(move || {
        hook_log.lock().unwrap().push("dispose");
        Ok(())
    });

    // The selector set on the decorator runs in the wrapped construct walk.
    let a = leaf("a");
    let b = leaf("b");
    decorator.add(a.clone()).unwrap();
    decorator.add(b.clone()).unwrap();
    decorator.set_current_selector(|items| items.last().cloned());
    let changes = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&changes);
    decorator.on_current_changed(move |current: Option<Leaf>| {
        sink.lock().unwrap().push(current.map(|item| item.id()));
    });
    parent.construct().unwrap();
    assert_eq!(inner.current(), Some(b.clone()));
    assert_eq!(*changes.lock().unwrap(), vec![Some(b.id())]);
    inner.set_current(Some(a.clone())).unwrap();
    assert_eq!(
        *changes.lock().unwrap(),
        vec![Some(b.id()), Some(a.id())],
        "the callback set on the decorator observes the wrapped composite"
    );

    // Selection through the parent.
    assert_eq!(decorator.can_select(), inner.can_select());
    assert!(decorator.can_select());
    decorator.select();
    assert!(decorator.is_current());
    assert_eq!(decorator.is_current(), inner.is_current());
    assert_eq!(decorator.can_deselect(), inner.can_deselect());
    assert!(decorator.can_deselect());
    decorator.deselect();
    assert!(!inner.is_current());
    assert_eq!(decorator.is_current(), inner.is_current());

    // Commands are the wrapped composite's stable commands.
    assert_eq!(
        decorator.select_command().can_execute(),
        inner.select_command().can_execute()
    );
    decorator.select_command().execute();
    assert!(inner.is_current());
    assert_eq!(
        decorator.deselect_command().can_execute(),
        inner.deselect_command().can_execute()
    );
    decorator.deselect_command().execute();
    assert!(!inner.is_current());
    assert_eq!(
        decorator.select_next_command().can_execute(),
        inner.select_next_command().can_execute()
    );
    assert_eq!(
        decorator.select_previous_command().can_execute(),
        inner.select_previous_command().can_execute()
    );
    assert_eq!(
        decorator.reconstruct_command().can_execute(),
        inner.reconstruct_command().can_execute()
    );

    // Expansion.
    decorator.expand();
    assert!(inner.is_expanded());
    assert_eq!(decorator.is_expanded(), inner.is_expanded());
    decorator.toggle_expansion();
    assert!(!inner.is_expanded());
    decorator.expand();
    decorator.collapse();
    assert!(!inner.is_expanded());
    assert_eq!(decorator.is_expanded(), inner.is_expanded());

    // Auto-construct on add, configured through the decorator.
    decorator.set_auto_construct_on_add(true);
    let late = leaf("late");
    decorator.add(late.clone()).unwrap();
    assert_eq!(late.status(), ConstructionStatus::Constructed);

    parent.destruct().unwrap();
    parent.dispose().unwrap();
    assert_eq!(
        *log.lock().unwrap(),
        vec!["construct", "destruct", "dispose"]
    );
}

/// Async selection and deferred lifecycle errors configured or observed
/// through the composite decorator act on the wrapped composite (spec/09 §2)
#[test]
fn forwarding_composite_forwards_async_selection_and_background_errors() {
    use vmx::{ComponentVm, CompositeVm, ManualDispatcher, VmxError};
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = ComponentVm::builder()
        .name("child")
        .model(0)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let inner = CompositeVm::with_services("inner", hub.clone(), dispatcher.clone());
    let decorator = ForwardingCompositeVm::new(inner.clone());
    decorator.add(child.clone()).unwrap();
    decorator.construct().unwrap();
    dispatcher.drain();

    decorator.set_async_selection(true);
    decorator.set_current(Some(child.clone())).unwrap();
    assert_eq!(
        inner.current(),
        None,
        "the selection waits for the dispatcher"
    );
    dispatcher.drain();
    assert_eq!(inner.current(), Some(child));

    let failing = ComponentVm::builder()
        .name("failing")
        .model(0)
        .background(true)
        .on_construct(|| Err(VmxError::Other("failed".to_string())))
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    let failing_inner = CompositeVm::with_services("failing", hub, dispatcher.clone());
    let failing_decorator = ForwardingCompositeVm::new(failing_inner.clone());
    failing_decorator.add(failing).unwrap();
    let errors = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&errors);
    let _subscription = failing_decorator
        .background_errors()
        .subscribe(move |error| {
            sink.lock().unwrap().push(error);
        });
    failing_decorator.construct().unwrap();
    dispatcher.drain();

    assert_eq!(failing_inner.status(), ConstructionStatus::Destructed);
    assert_eq!(errors.lock().unwrap().len(), 1);
}

/// Property-change hub messages recorded as `(sender_id, name)`.
type PropertyMessages = Arc<Mutex<Vec<(usize, String)>>>;

/// Records the property-change hub messages of `hub` as `(sender_id, name)`.
fn record_property_messages(hub: &MessageHub) -> (PropertyMessages, vmx::Subscription) {
    let messages = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&messages);
    let subscription = hub.subscribe(move |message| {
        if let vmx::Message::PropertyChanged(change) = message {
            sink.lock()
                .unwrap()
                .push((change.sender_id, change.property_name.clone()));
        }
    });
    (messages, subscription)
}

/// FWD-006 — A component decorator's notification helper publishes through
/// the wrapped VM, and nothing after the wrapped VM is disposed (#1352,
/// ADR-0221)
#[test]
fn forwarding_component_notification_helper_publishes_through_the_wrapped_vm() {
    let inner = child("inner");
    let decorator = ForwardingComponentVm::new(inner.clone());
    let (messages, _hub_subscription) = record_property_messages(&inner.hub());
    let names = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&names);
    let _local = decorator
        .property_changed()
        .subscribe(move |name| sink.lock().unwrap().push(name.to_string()));

    decorator.notify_property_changed("custom");

    assert_eq!(*names.lock().unwrap(), vec!["custom".to_string()]);
    assert_eq!(
        *messages.lock().unwrap(),
        vec![(inner.id(), "custom".to_string())]
    );

    inner.dispose().unwrap();
    names.lock().unwrap().clear();
    messages.lock().unwrap().clear();
    decorator.notify_property_changed("after");

    assert!(names.lock().unwrap().is_empty());
    assert!(messages.lock().unwrap().is_empty());
}

/// FWD-006 — A composite decorator's notification helper publishes through
/// the wrapped composite, and nothing after it is disposed (#1352, ADR-0221)
#[test]
fn forwarding_composite_notification_helper_publishes_through_the_wrapped_vm() {
    let inner = Wrapped::new("inner");
    let decorator = ForwardingCompositeVm::new(inner.clone());
    let (messages, _hub_subscription) = record_property_messages(&inner.hub());
    let names = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&names);
    let _local = decorator
        .property_changed()
        .subscribe(move |name| sink.lock().unwrap().push(name.to_string()));

    decorator.notify_property_changed("custom");

    assert_eq!(*names.lock().unwrap(), vec!["custom".to_string()]);
    assert_eq!(
        *messages.lock().unwrap(),
        vec![(inner.id(), "custom".to_string())]
    );

    inner.dispose().unwrap();
    names.lock().unwrap().clear();
    messages.lock().unwrap().clear();
    decorator.notify_property_changed("after");

    assert!(names.lock().unwrap().is_empty());
    assert!(messages.lock().unwrap().is_empty());
}
