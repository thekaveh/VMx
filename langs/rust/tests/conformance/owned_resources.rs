use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Arc, Mutex};

use vmx::{ComponentVm, Message, MessageHub, NullDispatcher};

fn probe(hub: MessageHub) -> ComponentVm<(), NullDispatcher> {
    ComponentVm::with_services("probe", hub, NullDispatcher::new())
}

/// DISP-007 — owned resources are cleaned in LIFO order.
#[test]
fn owned_resources_are_lifo() {
    let trace = Arc::new(Mutex::new(Vec::new()));
    let vm = probe(MessageHub::new());
    let hook_trace = trace.clone();
    vm.on_dispose(move || {
        hook_trace.lock().unwrap().push("hook");
        Ok(())
    });
    for value in ["first", "second", "last"] {
        let trace = trace.clone();
        vm.own(move || trace.lock().unwrap().push(value));
    }

    vm.dispose().unwrap();

    assert_eq!(
        *trace.lock().unwrap(),
        vec!["hook", "last", "second", "first"]
    );
}

/// DISP-008 — repeated VM disposal cleans each resource exactly once.
#[test]
fn repeated_dispose_cleans_owned_resource_once() {
    let calls = Arc::new(Mutex::new(0));
    let vm = probe(MessageHub::new());
    let observed = calls.clone();
    vm.own(move || *observed.lock().unwrap() += 1);
    vm.dispose().unwrap();
    vm.dispose().unwrap();
    assert_eq!(*calls.lock().unwrap(), 1);
}

/// DISP-009 — cleanup panic is swallowed and later resources still run.
#[test]
fn cleanup_panic_is_isolated() {
    let trace = Arc::new(Mutex::new(Vec::new()));
    let vm = probe(MessageHub::new());
    let first = trace.clone();
    vm.own(move || first.lock().unwrap().push("first"));
    vm.own(|| panic!("boom"));
    let last = trace.clone();
    vm.own(move || last.lock().unwrap().push("last"));

    let result = catch_unwind(AssertUnwindSafe(|| vm.dispose().unwrap()));

    assert!(result.is_ok());
    assert_eq!(*trace.lock().unwrap(), vec!["last", "first"]);
}

/// DISP-010 — registration after disposal is cleaned immediately once.
#[test]
fn post_dispose_registration_cleans_immediately() {
    let calls = Arc::new(Mutex::new(0));
    let vm = probe(MessageHub::new());
    vm.dispose().unwrap();
    let observed = calls.clone();
    vm.own(move || *observed.lock().unwrap() += 1);
    vm.dispose().unwrap();
    assert_eq!(*calls.lock().unwrap(), 1);
}

/// DISP-011 — disposal-lifetime resources survive reconstruct.
#[test]
fn owned_resource_survives_reconstruct() {
    let calls = Arc::new(Mutex::new(0));
    let vm = probe(MessageHub::new());
    let observed = calls.clone();
    vm.own(move || *observed.lock().unwrap() += 1);
    vm.construct().unwrap();
    vm.reconstruct().unwrap();
    assert_eq!(*calls.lock().unwrap(), 0);
    vm.dispose().unwrap();
    assert_eq!(*calls.lock().unwrap(), 1);
}

/// DISP-012 — injected hub is publicly visible and read-only.
#[test]
fn injected_hub_is_publicly_visible() {
    let hub = MessageHub::new();
    let vm = probe(hub.clone());
    vm.hub().send(Message::Custom {
        sender_id: vm.id(),
        sender_name: vm.name(),
        name: "visible".to_string(),
    });
    assert_eq!(hub.history().len(), 1);
}

/// DISP-013 — VM disposal does not dispose the shared injected hub.
#[test]
fn vm_disposal_does_not_dispose_hub() {
    let hub = MessageHub::new();
    let vm = probe(hub.clone());
    vm.dispose().unwrap();
    let baseline = hub.history().len();

    hub.send(Message::Custom {
        sender_id: vm.id(),
        sender_name: vm.name(),
        name: "still-alive".to_string(),
    });

    assert_eq!(hub.history().len(), baseline + 1);
}
