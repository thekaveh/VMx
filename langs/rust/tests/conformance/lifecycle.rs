use std::sync::{Arc, Mutex};
use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, ConstructionStatusChangedMessage, Message,
    MessageHub, NullDispatcher, VmxError,
};

fn statuses(hub: &MessageHub) -> Arc<Mutex<Vec<ConstructionStatus>>> {
    let observed = Arc::new(Mutex::new(Vec::new()));
    let observed_clone = observed.clone();
    let _subscription = hub.subscribe(move |message| {
        if let Message::ConstructionStatusChanged(ConstructionStatusChangedMessage {
            status, ..
        }) = message
        {
            observed_clone.lock().unwrap().push(*status);
        }
    });
    std::mem::forget(_subscription);
    observed
}

/// LIFE-001 — construct from Destructed transitions through Constructing to Constructed
#[test]
fn construct_from_destructed_transitions_to_constructed() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    let observed = statuses(&hub);

    vm.construct().unwrap();

    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed
        ]
    );
    assert!(vm.is_constructed());
}

/// LIFE-002 — destruct from Constructed transitions through Destructing to Destructed
#[test]
fn destruct_from_constructed_transitions_to_destructed() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    vm.construct().unwrap();
    let observed = statuses(&hub);

    vm.destruct().unwrap();

    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            ConstructionStatus::Destructing,
            ConstructionStatus::Destructed
        ]
    );
    assert!(!vm.is_constructed());
}

/// LIFE-003 — reconstruct emits the full Destruct then Construct sequence
#[test]
fn reconstruct_emits_destruct_then_construct_sequence() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    vm.construct().unwrap();
    let observed = statuses(&hub);

    vm.reconstruct().unwrap();

    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            ConstructionStatus::Destructing,
            ConstructionStatus::Destructed,
            ConstructionStatus::Constructing,
            ConstructionStatus::Constructed,
        ]
    );
}

/// LIFE-004 — dispose transitions to Disposed from any state
#[test]
fn dispose_transitions_to_disposed_from_destructed_and_constructed() {
    for construct_first in [false, true] {
        let hub = MessageHub::new();
        let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
        if construct_first {
            vm.construct().unwrap();
        }
        let observed = statuses(&hub);

        vm.dispose().unwrap();

        assert_eq!(vm.status(), ConstructionStatus::Disposed);
        assert!(observed
            .lock()
            .unwrap()
            .contains(&ConstructionStatus::Disposed));
    }
}

/// LIFE-005 — construct from Disposed raises
#[test]
fn construct_from_disposed_raises() {
    let vm = ComponentVm::new("vm");
    vm.dispose().unwrap();

    assert!(matches!(vm.construct(), Err(VmxError::Disposed)));
}

/// LIFE-006 — destruct from Disposed raises
#[test]
fn destruct_from_disposed_raises() {
    let vm = ComponentVm::new("vm");
    vm.dispose().unwrap();

    assert!(matches!(vm.destruct(), Err(VmxError::Disposed)));
}

/// LIFE-007 — IsConstructed equals Status == Constructed
#[test]
fn is_constructed_matches_constructed_status() {
    let vm = ComponentVm::new("vm");
    assert_eq!(
        vm.is_constructed(),
        vm.status() == ConstructionStatus::Constructed
    );
    vm.construct().unwrap();
    assert_eq!(
        vm.is_constructed(),
        vm.status() == ConstructionStatus::Constructed
    );
    vm.destruct().unwrap();
    assert_eq!(
        vm.is_constructed(),
        vm.status() == ConstructionStatus::Constructed
    );
    vm.dispose().unwrap();
    assert_eq!(
        vm.is_constructed(),
        vm.status() == ConstructionStatus::Constructed
    );
}

/// LIFE-008 — Concurrent operation while transitioning raises
#[test]
fn concurrent_operation_while_transitioning_raises() {
    let vm = ComponentVm::new("vm");
    let vm_clone = vm.clone();
    let inner_error = Arc::new(Mutex::new(None));
    let inner_error_clone = inner_error.clone();
    vm.on_construct(move || {
        *inner_error_clone.lock().unwrap() = Some(vm_clone.construct().unwrap_err());
        Ok(())
    });

    vm.construct().unwrap();

    assert!(matches!(
        inner_error.lock().unwrap().as_ref(),
        Some(VmxError::ConcurrentOperation)
    ));
}

/// LIFE-009 — construct from Constructed is idempotent (no-op)
#[test]
fn construct_from_constructed_is_noop() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    vm.construct().unwrap();
    let observed = statuses(&hub);

    vm.construct().unwrap();

    assert!(observed.lock().unwrap().is_empty());
    assert_eq!(vm.status(), ConstructionStatus::Constructed);
}

/// LIFE-010 — destruct from Destructed is idempotent (no-op)
#[test]
fn destruct_from_destructed_is_noop() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    let observed = statuses(&hub);

    vm.destruct().unwrap();

    assert!(observed.lock().unwrap().is_empty());
    assert_eq!(vm.status(), ConstructionStatus::Destructed);
}

/// LIFE-011 — Lifecycle transition table matches fixture
#[test]
fn lifecycle_transition_fixture_contains_required_transitions() {
    let fixture: serde_json::Value =
        serde_json::from_str(vmx::lifecycle_transition_fixture()).unwrap();
    let transitions = fixture["transitions"].as_array().unwrap();

    assert!(transitions.iter().any(|row| {
        row["from"] == "Destructed"
            && row["via"] == "construct"
            && row["to_intermediate"] == "Constructing"
            && row["to_final"] == "Constructed"
            && row["legal"] == true
    }));
    assert!(transitions.iter().any(|row| {
        row["from"] == "Disposed"
            && row["via"] == "construct"
            && row["to_final"].is_null()
            && row["legal"] == false
    }));
}

/// LIFE-012 — dispose from Disposed emits no message
#[test]
fn dispose_from_disposed_emits_no_message() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    vm.dispose().unwrap();
    let observed = statuses(&hub);

    vm.dispose().unwrap();

    assert!(observed.lock().unwrap().is_empty());
}

/// LIFE-013 — dispose on a parent disposes every child depth-first
#[test]
fn dispose_on_parent_disposes_children_before_parent() {
    let parent_hub = MessageHub::new();
    let parent = CompositeVm::with_services("parent", parent_hub.clone(), NullDispatcher::new());
    let child_a = ComponentVm::new("a");
    let child_b = ComponentVm::new("b");
    parent.add(child_a.clone()).unwrap();
    parent.add(child_b.clone()).unwrap();

    parent.dispose().unwrap();

    assert_eq!(child_a.status(), ConstructionStatus::Disposed);
    assert_eq!(child_b.status(), ConstructionStatus::Disposed);
    assert_eq!(parent.status(), ConstructionStatus::Disposed);
}

/// DISP-001 — VM disposal and owned child cascades are observably idempotent
#[test]
fn repeated_parent_dispose_emits_one_terminal_transition_per_node() {
    let hub = MessageHub::new();
    let parent = CompositeVm::with_services("parent", hub.clone(), NullDispatcher::new());
    let child = ComponentVm::with_services("child", hub.clone(), NullDispatcher::new());
    let parent_id = parent.id();
    let child_id = child.id();
    parent.add(child).unwrap();

    parent.dispose().unwrap();
    parent.dispose().unwrap();

    let disposed = hub
        .history()
        .into_iter()
        .filter_map(|message| match message {
            Message::ConstructionStatusChanged(change)
                if change.status == ConstructionStatus::Disposed =>
            {
                Some(change.sender_id)
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(disposed.iter().filter(|id| **id == child_id).count(), 1);
    assert_eq!(disposed.iter().filter(|id| **id == parent_id).count(), 1);
}

/// LIFE-014 — A throwing construct/destruct hook rolls Status back (transactional)
#[test]
fn throwing_lifecycle_hook_rolls_status_back() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    let observed = statuses(&hub);
    vm.on_construct(|| Err(VmxError::Other("boom".to_string())));

    assert!(vm.construct().is_err());

    assert_eq!(vm.status(), ConstructionStatus::Destructed);
    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Destructed
        ]
    );
}
