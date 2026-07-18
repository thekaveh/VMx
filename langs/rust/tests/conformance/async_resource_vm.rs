use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use vmx::{
    AsyncResourceRetention, AsyncResourceState, AsyncResourceStatus, AsyncResourceVm, Command,
    VmxError, VmxResult,
};

type ResultChannel = (Sender<VmxResult<i32>>, Receiver<VmxResult<i32>>);

fn channel() -> ResultChannel {
    mpsc::channel()
}

fn wait_until(predicate: impl Fn() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(2);
    while !predicate() {
        assert!(Instant::now() < deadline, "condition did not settle");
        thread::sleep(Duration::from_millis(1));
    }
}

fn controlled_vm(
    receivers: Vec<Receiver<VmxResult<i32>>>,
    retention: AsyncResourceRetention,
    cleaned: Option<Arc<Mutex<Vec<i32>>>>,
) -> AsyncResourceVm<i32> {
    let queue = Arc::new(Mutex::new(VecDeque::from(receivers)));
    let cleanup = cleaned.map(|values| {
        Arc::new(move |value| values.lock().unwrap().push(value)) as Arc<dyn Fn(i32) + Send + Sync>
    });
    AsyncResourceVm::with_options(
        "resource",
        move |_token| {
            let receiver = queue.lock().unwrap().pop_front().unwrap();
            receiver
                .recv()
                .unwrap_or_else(|_| Err(VmxError::Other("loader channel closed".into())))
        },
        retention,
        cleanup,
    )
}

/// ARES-001 — Initial state and command eligibility
#[test]
fn async_resource_initial_state_and_commands() {
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = calls.clone();
    let vm = AsyncResourceVm::new("resource", move |_| {
        observed.fetch_add(1, Ordering::SeqCst);
        Ok(1)
    });

    assert_eq!(vm.state(), AsyncResourceState::Idle);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert!(vm.load_command().can_execute());
    assert!(!vm.reload_command().can_execute());
    assert!(!vm.cancel_command().can_execute());
}

/// ARES-002 — Successful load and ordinary state notification
#[test]
fn async_resource_success_notifies_loading_and_ready() {
    let (send, receive) = channel();
    let vm = controlled_vm(vec![receive], AsyncResourceRetention::DiscardPrevious, None);
    let changes = Arc::new(Mutex::new(Vec::new()));
    let seen = changes.clone();
    let _subscription = vm.property_changed().subscribe(move |name| {
        seen.lock().unwrap().push(name.to_string());
    });

    let load = vm.load_async();
    wait_until(|| vm.status() == AsyncResourceStatus::Loading);
    send.send(Ok(42)).unwrap();
    load.join().unwrap().unwrap();

    assert_eq!(vm.state(), AsyncResourceState::Ready { value: 42 });
    assert_eq!(*changes.lock().unwrap(), vec!["state", "state"]);
    assert!(!vm.load_command().can_execute());
    assert!(vm.reload_command().can_execute());
    assert!(!vm.cancel_command().can_execute());
}

/// ARES-003 — Loader failure is error state, not command failure
#[test]
fn async_resource_failure_becomes_state() {
    let vm: AsyncResourceVm<i32> =
        AsyncResourceVm::new("resource", |_| Err(VmxError::Other("offline".into())));
    vm.load_async().join().unwrap().unwrap();
    assert_eq!(vm.status(), AsyncResourceStatus::Error);
    assert!(matches!(
        vm.state(),
        AsyncResourceState::Error { previous: None, .. }
    ));
    assert!(vm.reload_command().can_execute());
}

#[test]
fn async_resource_loader_panic_restores_stable_state_and_remains_retryable() {
    let attempt = Arc::new(AtomicUsize::new(0));
    let counter = attempt.clone();
    let vm = AsyncResourceVm::new("resource", move |_| {
        if counter.fetch_add(1, Ordering::SeqCst) == 0 {
            panic!("loader panic");
        }
        Ok(17)
    });

    let panic = vm
        .load_async()
        .join()
        .expect_err("the public load handle must preserve the loader panic");
    assert_eq!(panic.downcast_ref::<&str>(), Some(&"loader panic"));
    assert_eq!(vm.state(), AsyncResourceState::Idle);
    assert!(vm.load_command().can_execute());

    vm.load_async().join().unwrap().unwrap();
    assert_eq!(vm.state(), AsyncResourceState::Ready { value: 17 });
}

/// ARES-004 — Retry replaces error with ready
#[test]
fn async_resource_retry_replaces_error() {
    let attempt = Arc::new(AtomicUsize::new(0));
    let counter = attempt.clone();
    let vm = AsyncResourceVm::new("resource", move |_| {
        if counter.fetch_add(1, Ordering::SeqCst) == 0 {
            Err(VmxError::Other("first".into()))
        } else {
            Ok(7)
        }
    });
    vm.load_async().join().unwrap().unwrap();
    vm.reload_async().join().unwrap().unwrap();
    assert_eq!(vm.state(), AsyncResourceState::Ready { value: 7 });
}

/// ARES-005 — Cancellation restores idle without error
#[test]
fn async_resource_cancel_restores_idle() {
    let cancelled = Arc::new(AtomicBool::new(false));
    let observed = cancelled.clone();
    let vm: AsyncResourceVm<i32> = AsyncResourceVm::new("resource", move |token| loop {
        if token.is_cancelled() {
            observed.store(true, Ordering::SeqCst);
            return Err(VmxError::Other("cancelled".into()));
        }
        thread::sleep(Duration::from_millis(1));
    });
    let load = vm.load_async();
    wait_until(|| vm.status() == AsyncResourceStatus::Loading);
    vm.cancel_command().execute();
    load.join().unwrap().unwrap();
    wait_until(|| cancelled.load(Ordering::SeqCst));
    assert_eq!(vm.state(), AsyncResourceState::Idle);
    vm.cancel();
    assert_eq!(vm.state(), AsyncResourceState::Idle);
}

/// ARES-006 — Retained reload exposes and restores the previous value
#[test]
fn async_resource_retains_previous_through_cancel_and_failure() {
    let (send1, receive1) = channel();
    let (send2, receive2) = channel();
    let (send3, receive3) = channel();
    let vm = controlled_vm(
        vec![receive1, receive2, receive3],
        AsyncResourceRetention::RetainPrevious,
        None,
    );
    let first = vm.load_async();
    send1.send(Ok(3)).unwrap();
    first.join().unwrap().unwrap();

    let cancelled = vm.reload_async();
    wait_until(|| vm.status() == AsyncResourceStatus::Loading);
    assert_eq!(vm.value(), Some(3));
    vm.cancel();
    cancelled.join().unwrap().unwrap();
    assert_eq!(vm.state(), AsyncResourceState::Ready { value: 3 });

    let failed = vm.reload_async();
    send3.send(Err(VmxError::Other("refresh".into()))).unwrap();
    failed.join().unwrap().unwrap();
    assert!(matches!(
        vm.state(),
        AsyncResourceState::Error {
            previous: Some(3),
            ..
        }
    ));
    drop(send2);
}

/// ARES-007 — Discard releases previous before loading
#[test]
fn async_resource_discard_cleans_at_reload_start() {
    let (send1, receive1) = channel();
    let (_send2, receive2) = channel();
    let (send3, receive3) = channel();
    let cleaned = Arc::new(Mutex::new(Vec::new()));
    let vm = controlled_vm(
        vec![receive1, receive2, receive3],
        AsyncResourceRetention::DiscardPrevious,
        Some(cleaned.clone()),
    );
    let first = vm.load_async();
    send1.send(Ok(5)).unwrap();
    first.join().unwrap().unwrap();
    let reload = vm.reload_async();
    wait_until(|| vm.status() == AsyncResourceStatus::Loading);
    assert_eq!(*cleaned.lock().unwrap(), vec![5]);
    assert_eq!(vm.value(), None);
    vm.cancel();
    reload.join().unwrap().unwrap();
    assert_eq!(vm.state(), AsyncResourceState::Idle);
    let failed = vm.load_async();
    send3.send(Err(VmxError::Other("offline".into()))).unwrap();
    failed.join().unwrap().unwrap();
    assert_eq!(vm.value(), None);
}

#[test]
fn replacement_cleanup_that_starts_reload_suppresses_superseded_notification() {
    let holder = Arc::new(Mutex::new(None::<AsyncResourceVm<i32>>));
    let next_value = Arc::new(AtomicUsize::new(0));
    let reentered = Arc::new(AtomicBool::new(false));
    let cleanup_holder = holder.clone();
    let cleanup_reentered = reentered.clone();
    let loader_next = next_value.clone();
    let vm = AsyncResourceVm::with_options(
        "resource",
        move |_| Ok(loader_next.fetch_add(1, Ordering::SeqCst) as i32 + 1),
        AsyncResourceRetention::RetainPrevious,
        Some(Arc::new(move |value| {
            if value == 1 && !cleanup_reentered.swap(true, Ordering::SeqCst) {
                let vm = cleanup_holder.lock().unwrap().clone().unwrap();
                vm.reload_async().join().unwrap().unwrap();
            }
        })),
    );
    *holder.lock().unwrap() = Some(vm.clone());
    let changes = Arc::new(AtomicUsize::new(0));
    let observed = changes.clone();
    let _subscription = vm.property_changed().subscribe(move |_| {
        observed.fetch_add(1, Ordering::SeqCst);
    });

    vm.load_async().join().unwrap().unwrap();
    let baseline = changes.load(Ordering::SeqCst);
    vm.reload_async().join().unwrap().unwrap();

    assert_eq!(changes.load(Ordering::SeqCst) - baseline, 3);
    assert_eq!(vm.state(), AsyncResourceState::Ready { value: 3 });
    assert_eq!(next_value.load(Ordering::SeqCst), 3);
}

/// ARES-008 — Overlap is latest-start-wins
#[test]
fn async_resource_latest_start_wins() {
    let (send1, receive1) = channel();
    let (send2, receive2) = channel();
    let vm = controlled_vm(
        vec![receive1, receive2],
        AsyncResourceRetention::DiscardPrevious,
        None,
    );
    let older = vm.load_async();
    wait_until(|| vm.status() == AsyncResourceStatus::Loading);
    let newer = vm.reload_async();
    older.join().unwrap().unwrap();
    send1.send(Ok(1)).unwrap();
    thread::sleep(Duration::from_millis(5));
    assert_eq!(vm.status(), AsyncResourceStatus::Loading);
    send2.send(Ok(2)).unwrap();
    newer.join().unwrap().unwrap();
    assert_eq!(vm.state(), AsyncResourceState::Ready { value: 2 });
}

/// ARES-009 — Stale success is cleaned without notification
#[test]
fn async_resource_stale_success_cleans_silently() {
    let (send1, receive1) = channel();
    let (send2, receive2) = channel();
    let cleaned = Arc::new(Mutex::new(Vec::new()));
    let vm = controlled_vm(
        vec![receive1, receive2],
        AsyncResourceRetention::DiscardPrevious,
        Some(cleaned.clone()),
    );
    let changes = Arc::new(AtomicUsize::new(0));
    let count = changes.clone();
    let _subscription = vm.property_changed().subscribe(move |_| {
        count.fetch_add(1, Ordering::SeqCst);
    });
    let older = vm.load_async();
    wait_until(|| vm.status() == AsyncResourceStatus::Loading);
    let newer = vm.reload_async();
    older.join().unwrap().unwrap();
    send2.send(Ok(2)).unwrap();
    newer.join().unwrap().unwrap();
    let notifications = changes.load(Ordering::SeqCst);
    send1.send(Ok(1)).unwrap();
    wait_until(|| cleaned.lock().unwrap().as_slice() == [1]);
    assert_eq!(changes.load(Ordering::SeqCst), notifications);
    assert_eq!(vm.value(), Some(2));
}

/// ARES-010 — Replacement and disposal cleanup exactly once
#[test]
fn async_resource_replacement_and_dispose_cleanup_once() {
    let cleaned = Arc::new(Mutex::new(Vec::new()));
    let values = Arc::new(AtomicUsize::new(0));
    let next = values.clone();
    let vm = AsyncResourceVm::with_options(
        "resource",
        move |_| Ok(next.fetch_add(1, Ordering::SeqCst) as i32 + 1),
        AsyncResourceRetention::RetainPrevious,
        Some({
            let cleaned = cleaned.clone();
            Arc::new(move |value| cleaned.lock().unwrap().push(value))
        }),
    );
    vm.load_async().join().unwrap().unwrap();
    vm.reload_async().join().unwrap().unwrap();
    assert_eq!(*cleaned.lock().unwrap(), vec![1]);
    vm.dispose().unwrap();
    vm.dispose().unwrap();
    assert_eq!(*cleaned.lock().unwrap(), vec![1, 2]);
}

/// ARES-011 — Dispose cancels and late work is inert
#[test]
fn async_resource_dispose_cancels_and_late_completion_is_inert() {
    let (send, receive) = channel();
    let cleaned = Arc::new(Mutex::new(Vec::new()));
    let vm = controlled_vm(
        vec![receive],
        AsyncResourceRetention::DiscardPrevious,
        Some(cleaned.clone()),
    );
    let changes = Arc::new(AtomicUsize::new(0));
    let count = changes.clone();
    let _subscription = vm.property_changed().subscribe(move |_| {
        count.fetch_add(1, Ordering::SeqCst);
    });
    let load = vm.load_async();
    wait_until(|| vm.status() == AsyncResourceStatus::Loading);
    vm.dispose().unwrap();
    vm.dispose().unwrap();
    let notifications = changes.load(Ordering::SeqCst);
    assert!(!vm.load_command().can_execute());
    assert!(!vm.reload_command().can_execute());
    assert!(!vm.cancel_command().can_execute());
    load.join().unwrap().unwrap();
    send.send(Ok(9)).unwrap();
    wait_until(|| cleaned.lock().unwrap().as_slice() == [9]);
    vm.load_async().join().unwrap().unwrap();
    vm.reload_async().join().unwrap().unwrap();
    vm.cancel();
    assert_eq!(changes.load(Ordering::SeqCst), notifications);
}

#[test]
fn reentrant_disposal_during_loading_notification_prevents_loader_start() {
    let calls = Arc::new(AtomicUsize::new(0));
    let loader_calls = Arc::clone(&calls);
    let vm = AsyncResourceVm::new("resource", move |_| {
        loader_calls.fetch_add(1, Ordering::SeqCst);
        Ok(1)
    });
    let owner = Arc::new(Mutex::new(Some(vm.clone())));
    let callback_owner = Arc::clone(&owner);
    let _subscription = vm.property_changed().subscribe(move |name| {
        if name == "state" {
            callback_owner
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .dispose()
                .unwrap();
        }
    });

    vm.load_async().join().unwrap().unwrap();

    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert!(!vm.load_command().can_execute());
}

#[test]
fn discard_cleanup_disposal_prevents_notification_and_loader_start() {
    let calls = Arc::new(AtomicUsize::new(0));
    let loader_calls = Arc::clone(&calls);
    let owner = Arc::new(Mutex::new(None::<AsyncResourceVm<i32>>));
    let cleanup_owner = Arc::clone(&owner);
    let vm = AsyncResourceVm::with_options(
        "resource",
        move |_| {
            loader_calls.fetch_add(1, Ordering::SeqCst);
            Ok(1)
        },
        AsyncResourceRetention::DiscardPrevious,
        Some(Arc::new(move |_| {
            cleanup_owner
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .dispose()
                .unwrap();
        })),
    );
    *owner.lock().unwrap() = Some(vm.clone());
    vm.load_async().join().unwrap().unwrap();
    let changes = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&changes);
    let _subscription = vm.property_changed().subscribe(move |_| {
        observed.fetch_add(1, Ordering::SeqCst);
    });

    vm.reload_async().join().unwrap().unwrap();

    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(changes.load(Ordering::SeqCst), 0);
    assert!(!vm.load_command().can_execute());
}

#[test]
fn dropping_async_resource_releases_command_captures() {
    let marker = Arc::new(());
    let released = Arc::downgrade(&marker);
    let vm = AsyncResourceVm::new("resource", move |_| {
        let _keep_alive = &marker;
        Ok(1)
    });

    drop(vm);

    assert!(
        released.upgrade().is_none(),
        "cached commands must not strongly retain their owner"
    );
}
