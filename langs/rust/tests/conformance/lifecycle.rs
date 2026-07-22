use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::time::Duration;
use vmx::{
    AggregateVm2, ComponentVm, CompositeVm, ConstructionStatus, ConstructionStatusChangedMessage,
    GroupVm, ManualDispatcher, Message, MessageHub, NullDispatcher, ParentHandle, VmNode, VmxError,
};

#[derive(Clone)]
struct BlockingAdmissionNode {
    inner: ComponentVm,
    block_once: Arc<AtomicBool>,
    entered: mpsc::Sender<()>,
    release: Arc<Mutex<mpsc::Receiver<()>>>,
}

impl PartialEq for BlockingAdmissionNode {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl VmNode for BlockingAdmissionNode {
    fn id(&self) -> usize {
        self.inner.id()
    }
    fn construct(&self) -> vmx::VmxResult<()> {
        self.inner.construct()
    }
    fn destruct(&self) -> vmx::VmxResult<()> {
        self.inner.destruct()
    }
    fn dispose(&self) -> vmx::VmxResult<()> {
        self.inner.dispose()
    }
    fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }
    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.set_parent_id(parent_id);
    }
    fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }
    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner.set_parent_handle(parent);
    }
    fn parent_handle(&self) -> Option<ParentHandle> {
        if self.block_once.swap(false, Ordering::AcqRel) {
            self.entered.send(()).unwrap();
            self.release.lock().unwrap().recv().unwrap();
        }
        self.inner.parent_handle()
    }
}

fn blocking_admission_node() -> (BlockingAdmissionNode, mpsc::Receiver<()>, mpsc::Sender<()>) {
    let (entered_send, entered_receive) = mpsc::channel();
    let (release_send, release_receive) = mpsc::channel();
    (
        BlockingAdmissionNode {
            inner: ComponentVm::new("late"),
            block_once: Arc::new(AtomicBool::new(true)),
            entered: entered_send,
            release: Arc::new(Mutex::new(release_receive)),
        },
        entered_receive,
        release_send,
    )
}

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

#[test]
fn dispose_supersedes_constructing_without_resurrection() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    let observed = statuses(&hub);
    let hook_vm = vm.clone();
    vm.on_construct(move || hook_vm.dispose());

    vm.construct().unwrap();

    assert_eq!(vm.status(), ConstructionStatus::Disposed);
    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Disposed
        ]
    );
}

#[test]
fn dispose_supersedes_destructing_without_resurrection() {
    let hub = MessageHub::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), NullDispatcher::new());
    vm.construct().unwrap();
    let observed = statuses(&hub);
    let hook_vm = vm.clone();
    vm.on_destruct(move || hook_vm.dispose());

    vm.destruct().unwrap();

    assert_eq!(vm.status(), ConstructionStatus::Disposed);
    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            ConstructionStatus::Destructing,
            ConstructionStatus::Disposed
        ]
    );
}

#[test]
fn queued_terminal_publication_is_suppressed_after_disposal() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let vm = ComponentVm::with_services("vm", hub.clone(), dispatcher.clone());
    let observed = statuses(&hub);

    vm.construct().unwrap();
    assert_eq!(
        *observed.lock().unwrap(),
        vec![ConstructionStatus::Constructing]
    );

    vm.dispose().unwrap();
    dispatcher.drain();

    assert_eq!(vm.status(), ConstructionStatus::Disposed);
    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            ConstructionStatus::Constructing,
            ConstructionStatus::Disposed
        ]
    );
}

#[test]
fn opposing_lifecycle_callbacks_do_not_deadlock() {
    let left_hub = MessageHub::new();
    let right_hub = MessageHub::new();
    let left = ComponentVm::with_services("left", left_hub.clone(), NullDispatcher::new());
    let right = ComponentVm::with_services("right", right_hub.clone(), NullDispatcher::new());
    let callbacks_entered = Arc::new(Barrier::new(2));

    let _left_subscription = left_hub.subscribe({
        let right = right.clone();
        let callbacks_entered = Arc::clone(&callbacks_entered);
        move |message| {
            if matches!(
                message,
                Message::ConstructionStatusChanged(ConstructionStatusChangedMessage {
                    status: ConstructionStatus::Constructing,
                    ..
                })
            ) {
                callbacks_entered.wait();
                right.dispose().unwrap();
            }
        }
    });
    let _right_subscription = right_hub.subscribe({
        let left = left.clone();
        let callbacks_entered = Arc::clone(&callbacks_entered);
        move |message| {
            if matches!(
                message,
                Message::ConstructionStatusChanged(ConstructionStatusChangedMessage {
                    status: ConstructionStatus::Constructing,
                    ..
                })
            ) {
                callbacks_entered.wait();
                left.dispose().unwrap();
            }
        }
    });

    let (returned_tx, returned_rx) = mpsc::channel();
    let left_worker = std::thread::spawn({
        let left = left.clone();
        let returned_tx = returned_tx.clone();
        move || {
            left.construct().unwrap();
            returned_tx.send(()).unwrap();
        }
    });
    let right_worker = std::thread::spawn(move || {
        right.construct().unwrap();
        returned_tx.send(()).unwrap();
    });

    returned_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    returned_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    left_worker.join().unwrap();
    right_worker.join().unwrap();
    assert_eq!(left.status(), ConstructionStatus::Disposed);
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

#[test]
fn disposal_closes_child_admission_before_taking_the_cascade_snapshot() {
    let parent = CompositeVm::new("parent");
    let child = ComponentVm::new("child");
    let late = ComponentVm::new("late");
    let callback_parent = parent.clone();
    let callback_late = late.clone();
    child.on_dispose(move || {
        assert_eq!(
            callback_parent.add(callback_late.clone()),
            Err(VmxError::Disposed)
        );
        Ok(())
    });
    parent.add(child).unwrap();

    parent.dispose().unwrap();

    assert_eq!(late.parent_id(), None);
    assert_eq!(parent.len(), 1);
}

#[test]
fn concurrent_admission_cannot_escape_disposal_snapshot() {
    let composite = CompositeVm::new("composite");
    let (late, entered, release) = blocking_admission_node();
    let add_parent = composite.clone();
    let add_late = late.clone();
    let admission = std::thread::spawn(move || add_parent.add(add_late));
    entered.recv_timeout(Duration::from_secs(2)).unwrap();
    let dispose_parent = composite.clone();
    let (dispose_started_tx, dispose_started_rx) = mpsc::channel();
    let (dispose_done_tx, dispose_done_rx) = mpsc::channel();
    let disposal = std::thread::spawn(move || {
        dispose_started_tx.send(()).unwrap();
        dispose_done_tx.send(dispose_parent.dispose()).unwrap();
    });
    dispose_started_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    assert!(dispose_done_rx
        .recv_timeout(Duration::from_millis(50))
        .is_err());
    release.send(()).unwrap();
    admission.join().unwrap().unwrap();
    dispose_done_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap()
        .unwrap();
    disposal.join().unwrap();
    assert_eq!(composite.len(), 1);
    assert_eq!(late.status(), ConstructionStatus::Disposed);

    let group = GroupVm::new("group");
    let (late, entered, release) = blocking_admission_node();
    let add_parent = group.clone();
    let add_late = late.clone();
    let admission = std::thread::spawn(move || add_parent.add(add_late));
    entered.recv_timeout(Duration::from_secs(2)).unwrap();
    let dispose_parent = group.clone();
    let (dispose_started_tx, dispose_started_rx) = mpsc::channel();
    let (dispose_done_tx, dispose_done_rx) = mpsc::channel();
    let disposal = std::thread::spawn(move || {
        dispose_started_tx.send(()).unwrap();
        dispose_done_tx.send(dispose_parent.dispose()).unwrap();
    });
    dispose_started_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    assert!(dispose_done_rx
        .recv_timeout(Duration::from_millis(50))
        .is_err());
    release.send(()).unwrap();
    admission.join().unwrap().unwrap();
    dispose_done_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap()
        .unwrap();
    disposal.join().unwrap();
    assert_eq!(group.len(), 1);
    assert_eq!(late.status(), ConstructionStatus::Disposed);
}

/// LIFE-013 — one disposal failure cannot strand later siblings or the parent
#[test]
fn disposal_cascades_finish_before_returning_the_first_error() {
    fn failing_child(name: &'static str, error: &'static str) -> ComponentVm {
        let child = ComponentVm::new(name);
        child.on_dispose(move || Err(VmxError::Other(error.to_string())));
        child
    }

    let first = failing_child("first", "first dispose failure");
    let second = failing_child("second", "second dispose failure");
    let composite = CompositeVm::new("composite");
    composite.add(first.clone()).unwrap();
    composite.add(second.clone()).unwrap();
    assert_eq!(composite.len(), 2);
    assert_eq!(
        composite.dispose(),
        Err(VmxError::Other("first dispose failure".to_string()))
    );
    assert_eq!(first.status(), ConstructionStatus::Disposed);
    assert_eq!(second.status(), ConstructionStatus::Disposed);
    assert_eq!(composite.status(), ConstructionStatus::Disposed);

    let first = failing_child("first", "first dispose failure");
    let second = failing_child("second", "second dispose failure");
    let group = GroupVm::new("group");
    group.add(first.clone()).unwrap();
    group.add(second.clone()).unwrap();
    assert_eq!(
        group.dispose(),
        Err(VmxError::Other("first dispose failure".to_string()))
    );
    assert_eq!(first.status(), ConstructionStatus::Disposed);
    assert_eq!(second.status(), ConstructionStatus::Disposed);
    assert_eq!(group.status(), ConstructionStatus::Disposed);

    let first = failing_child("first", "first dispose failure");
    let second = failing_child("second", "second dispose failure");
    let aggregate = AggregateVm2::try_new("aggregate", first.clone(), second.clone()).unwrap();
    assert_eq!(
        aggregate.dispose(),
        Err(VmxError::Other("first dispose failure".to_string()))
    );
    assert_eq!(first.status(), ConstructionStatus::Disposed);
    assert_eq!(second.status(), ConstructionStatus::Disposed);
    assert_eq!(aggregate.status(), ConstructionStatus::Disposed);
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
