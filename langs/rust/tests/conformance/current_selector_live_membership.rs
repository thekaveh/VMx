//! The `Current(selector)` hook receives the live membership, so it can pick
//! a child added while the construct walk waited (spec/06 §3.2, ADR-0218
//! rule 2, #1312).

use std::sync::{Arc, Mutex};
use vmx::{ComponentVm, CompositeVm, ConstructionStatus, ManualDispatcher, MessageHub, VmNode};

type Child = ComponentVm<i32, ManualDispatcher>;

fn child(hub: &MessageHub, dispatcher: &ManualDispatcher, name: &str, background: bool) -> Child {
    ComponentVm::builder()
        .name(name)
        .model(1)
        .background(background)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap()
}

/// COMP-053 — the selector runs once, after the walk, with the live
/// membership: it sees the member `a` and the child `l` added while the walk
/// waited on `a`, and its pick of `l` becomes current.
#[test]
fn comp_053_selector_receives_live_membership() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let a = child(&hub, &dispatcher, "a", true);
    let l = child(&hub, &dispatcher, "l", false);
    let p = CompositeVm::with_services("p", hub.clone(), dispatcher.clone());
    p.set_auto_construct_on_add(true);
    p.add(a.clone()).unwrap();
    let inputs: Arc<Mutex<Vec<Vec<usize>>>> = Arc::default();
    {
        let inputs = Arc::clone(&inputs);
        let wanted = l.id();
        p.set_current_selector(move |members: Vec<Child>| {
            inputs
                .lock()
                .unwrap()
                .push(members.iter().map(VmNode::id).collect());
            members.into_iter().find(|member| member.id() == wanted)
        });
    }

    p.construct().unwrap();
    assert_eq!(p.status(), ConstructionStatus::Constructing);
    p.add(l.clone()).unwrap();
    dispatcher.drain();

    assert_eq!(p.status(), ConstructionStatus::Constructed);
    let inputs = inputs.lock().unwrap().clone();
    assert_eq!(inputs.len(), 1, "the selector ran once");
    assert!(inputs[0].contains(&a.id()));
    assert!(inputs[0].contains(&l.id()));
    assert_eq!(p.current().map(|current| current.id()), Some(l.id()));
    assert!(l.is_current());
}
