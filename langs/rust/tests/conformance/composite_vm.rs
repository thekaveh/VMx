use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use vmx::{
    CollectionChangeAction, ConstructionStatus, Dispatcher, ManualDispatcher, Message, MessageHub,
    NullDispatcher, VmNode, VmxError,
};

type Child = vmx::ComponentVm<&'static str>;

fn child(name: &'static str) -> Child {
    Child::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

fn collection_actions(hub: &MessageHub) -> Vec<CollectionChangeAction> {
    hub.history()
        .into_iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) => Some(change.action),
            _ => None,
        })
        .collect()
}

/// COMP-001 — Add emits CollectionChanged(action=Add)
#[test]
fn add_emits_collection_changed_add() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());

    composite.add(child("a")).unwrap();

    assert_eq!(collection_actions(&hub), vec![CollectionChangeAction::Add]);
}

/// COMP-002 — Remove emits CollectionChanged(action=Remove)
#[test]
fn remove_emits_collection_changed_remove() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());
    let item = child("a");
    composite.add(item.clone()).unwrap();

    composite.remove(&item).unwrap();

    assert!(collection_actions(&hub).contains(&CollectionChangeAction::Remove));
    assert_eq!(item.parent_id(), None);
}

/// COMP-003 — select_component sets Current
#[test]
fn select_component_sets_current_and_child_current_flag() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");
    composite.add(item.clone()).unwrap();
    item.construct().unwrap();

    composite.select_component(&item).unwrap();

    assert_eq!(composite.current(), Some(item.clone()));
    assert!(item.is_current());
}

/// COMP-004 — Construct waits until all children reach Constructed
#[test]
fn construct_constructs_all_children() {
    let composite = vmx::CompositeVm::new("root");
    let a = child("a");
    let b = child("b");
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();

    composite.construct().unwrap();

    assert_eq!(a.status(), ConstructionStatus::Constructed);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
}

#[test]
fn parent_reaches_constructed_only_after_children() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());
    let item = Child::with_model("child", "child", hub.clone(), NullDispatcher::new());
    composite.add(item.clone()).unwrap();

    composite.construct().unwrap();

    let statuses = hub
        .history()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change) => Some((change.sender_id, change.status)),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        statuses,
        vec![
            (composite.id(), ConstructionStatus::Constructing),
            (item.id(), ConstructionStatus::Constructing),
            (item.id(), ConstructionStatus::Constructed),
            (composite.id(), ConstructionStatus::Constructed),
        ]
    );
}

/// COMP-005 — Destruct waits until all children reach Destructed
#[test]
fn destruct_clears_current_and_destructs_children() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");
    composite.add(item.clone()).unwrap();
    composite.construct().unwrap();
    composite.select_component(&item).unwrap();

    composite.destruct().unwrap();

    assert_eq!(composite.current(), None);
    assert_eq!(item.status(), ConstructionStatus::Destructed);
    assert!(!item.is_current());
}

/// COMP-006 — IsCurrent change on the previously-Current child dispatches on foreground
#[test]
fn previous_current_change_can_be_observed_on_foreground_dispatcher() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let composite = vmx::CompositeVm::<Child, ManualDispatcher>::with_services(
        "root",
        hub.clone(),
        dispatcher.clone(),
    );
    let a = Child::with_model("a", "a", hub.clone(), NullDispatcher::new());
    let b = Child::with_model("b", "b", hub.clone(), NullDispatcher::new());
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    composite.construct().unwrap();
    composite.select_component(&a).unwrap();

    let observed = Arc::new(Mutex::new(0));
    let observed_inner = observed.clone();
    let observer_dispatcher = dispatcher.clone();
    let a_id = a.id();
    let _subscription = hub.subscribe(move |message| {
        if matches!(
            message,
            Message::PropertyChanged(change)
                if change.sender_id == a_id && change.property_name == "is_current"
        ) {
            let observed_inner = observed_inner.clone();
            observer_dispatcher.dispatch(Box::new(move || *observed_inner.lock().unwrap() += 1));
        }
    });

    composite.select_component(&b).unwrap();

    assert_eq!(*observed.lock().unwrap(), 0);
    dispatcher.drain();
    assert_eq!(*observed.lock().unwrap(), 1);
}

/// COMP-007 — Modeled composite maps model factory output to children
#[test]
fn modeled_composite_maps_model_factory_output_to_children() {
    let composite =
        vmx::ModeledCompositeVm::<i32, vmx::ComponentVm<i32>, NullDispatcher>::builder()
            .name("modeled")
            .services(MessageHub::new(), NullDispatcher::new())
            .children_models(|| vec![1, 2])
            .child_model_to_child_view_model(|model| {
                vmx::ComponentVm::with_model(
                    format!("child-{model}"),
                    model,
                    MessageHub::new(),
                    NullDispatcher::new(),
                )
            })
            .build()
            .unwrap();

    composite.construct().unwrap();

    assert_eq!(composite.len(), 2);
    assert_eq!(composite.get(0).unwrap().model(), 1);
    assert_eq!(composite.get(1).unwrap().model(), 2);
}

/// COMP-008 — can_select_component returns false for non-children
#[test]
fn can_select_component_false_for_non_child() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("outside");
    item.construct().unwrap();

    assert!(!composite.can_select_component(&item));
}

/// COMP-009 — Current setter raises when assigned a non-child
#[test]
fn set_current_rejects_non_child() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("outside");

    let result = composite.set_current(Some(item));

    assert_eq!(result, Err(VmxError::NonChild));
    assert_eq!(composite.current(), None);
}

/// COMP-010 — AsyncSelection dispatches Current change via foreground scheduler
#[test]
fn async_selection_dispatches_current_change_via_foreground() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let composite = vmx::CompositeVm::<Child, ManualDispatcher>::with_services(
        "root",
        hub.clone(),
        dispatcher.clone(),
    );
    composite.set_async_selection(true);
    let item = child("a");
    composite.add(item.clone()).unwrap();
    item.construct().unwrap();
    let observed = Arc::new(Mutex::new(0));
    let observed_inner = observed.clone();
    let observer_dispatcher = dispatcher.clone();
    let composite_id = composite.id();
    let _subscription = hub.subscribe(move |message| {
        if matches!(
            message,
            Message::PropertyChanged(change)
                if change.sender_id == composite_id && change.property_name == "current"
        ) {
            let observed_inner = observed_inner.clone();
            observer_dispatcher.dispatch(Box::new(move || *observed_inner.lock().unwrap() += 1));
        }
    });

    composite.select_component(&item).unwrap();

    assert_eq!(composite.current(), None);
    assert_eq!(*observed.lock().unwrap(), 0);
    dispatcher.drain();
    assert_eq!(composite.current(), Some(item));
    assert_eq!(*observed.lock().unwrap(), 1);
}

/// COMP-011 — deselect_component raises when vm is not Current
#[test]
fn deselect_component_rejects_non_current_child() {
    let composite = vmx::CompositeVm::new("root");
    let a = child("a");
    let b = child("b");
    composite.add(a.clone()).unwrap();
    composite.add(b.clone()).unwrap();
    a.construct().unwrap();
    b.construct().unwrap();
    composite.select_component(&a).unwrap();

    let result = composite.deselect_component(&b);

    assert_eq!(result, Err(VmxError::NotCurrent));
    assert_eq!(composite.current(), Some(a));
}

/// COMP-012 — AutoConstructOnAdd(true) auto-constructs late children
#[test]
fn auto_construct_on_add_constructs_late_child_before_event() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());
    composite.set_auto_construct_on_add(true);
    composite.construct().unwrap();
    let item = child("late");

    composite.add(item.clone()).unwrap();

    assert_eq!(item.status(), ConstructionStatus::Constructed);
    assert_eq!(
        collection_actions(&hub).last(),
        Some(&CollectionChangeAction::Add)
    );
}

/// COMP-013 — BatchUpdate suppresses per-mutation events and emits one Reset
#[test]
fn batch_update_emits_single_reset() {
    let hub = MessageHub::new();
    let composite = vmx::CompositeVm::with_services("root", hub.clone(), NullDispatcher::new());

    composite.batch_update(|| {
        composite.add(child("a")).unwrap();
        composite.add(child("b")).unwrap();
    });

    assert_eq!(
        collection_actions(&hub),
        vec![CollectionChangeAction::Reset]
    );
}

/// COMP-025 — `Current(selector)` builder hook drives initial selection during construct
#[test]
fn current_selector_builder_hook_drives_initial_selection_during_construct() {
    let hub = MessageHub::new();
    let children = vec![child("a"), child("b"), child("c")];
    let calls = Arc::new(AtomicUsize::new(0));
    let calls_inner = calls.clone();
    let composite = vmx::CompositeVm::<Child>::builder()
        .name("root")
        .services(hub, NullDispatcher::new())
        .children({
            let children = children.clone();
            move || children.clone()
        })
        .current(move |items| {
            calls_inner.fetch_add(1, Ordering::SeqCst);
            assert!(items
                .iter()
                .all(|item| item.status() == ConstructionStatus::Constructed));
            items.get(1).cloned()
        })
        .build()
        .unwrap();

    composite.construct().unwrap();

    assert_eq!(composite.current(), Some(children[1].clone()));
    assert_eq!(calls.load(Ordering::SeqCst), 1);

    let hub = MessageHub::new();
    let null_selector = vmx::CompositeVm::<Child>::builder()
        .name("root")
        .services(hub.clone(), NullDispatcher::new())
        .children(|| vec![child("a")])
        .current(|_| None)
        .build()
        .unwrap();

    null_selector.construct().unwrap();

    assert_eq!(null_selector.current(), None);
    assert!(!hub.history().iter().any(|message| matches!(
        message,
        Message::PropertyChanged(change) if change.property_name == "current"
    )));
}

/// COMP-026 — OnCurrentChanged(callback) fires synchronously after each Current change
#[test]
fn on_current_changed_fires_after_current_changes() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");
    composite.add(item.clone()).unwrap();
    item.construct().unwrap();
    let observed = Arc::new(Mutex::new(Vec::new()));
    let seen = observed.clone();
    composite.on_current_changed(move |current| {
        seen.lock()
            .unwrap()
            .push(current.map(|vm| vm.name()).unwrap_or_default());
    });

    composite.select_component(&item).unwrap();
    composite.deselect_component(&item).unwrap();

    assert_eq!(
        observed.lock().unwrap().clone(),
        vec!["a".to_string(), String::new()]
    );
}

/// COMP-027 — Adding a child sets its Parent; removing clears it
#[test]
fn add_and_remove_manage_child_parent() {
    let composite = vmx::CompositeVm::new("root");
    let item = child("a");

    composite.add(item.clone()).unwrap();
    assert_eq!(item.parent_id(), Some(composite.id()));

    composite.remove(&item).unwrap();
    assert_eq!(item.parent_id(), None);
}
