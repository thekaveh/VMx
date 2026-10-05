//! Every awaited `AsyncResourceVm` load completes promptly, and every accepted
//! value is cleaned exactly once, whatever ends the load (#356).

use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Barrier, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use vmx::{
    AsyncResourceRetention, AsyncResourceState, AsyncResourceStatus, AsyncResourceVm, VmxError,
    VmxResult,
};

const BOUND: Duration = Duration::from_secs(5);

type Cleaned = Arc<Mutex<Vec<i32>>>;

/// Joins `handle` within the bound, so a stranded waiter fails the test
/// instead of hanging it.
fn join_within(handle: JoinHandle<VmxResult<()>>) -> thread::Result<VmxResult<()>> {
    let (sender, joined) = mpsc::channel();
    thread::spawn(move || {
        let _ = sender.send(handle.join());
    });
    joined
        .recv_timeout(BOUND)
        .expect("the awaited handle completed within the bound")
}

fn wait_until(predicate: impl Fn() -> bool) {
    let deadline = Instant::now() + BOUND;
    while !predicate() {
        assert!(Instant::now() < deadline, "condition did not settle");
        thread::sleep(Duration::from_millis(1));
    }
}

fn cleaned_values(cleaned: &Cleaned) -> Vec<i32> {
    cleaned.lock().unwrap().clone()
}

/// The control side of a loader that reports each start, then ignores its
/// token and blocks until the test hands it a result.
struct Gate {
    started: Receiver<()>,
    results: Sender<VmxResult<i32>>,
}

fn gated_resource() -> (AsyncResourceVm<i32>, Gate, Cleaned) {
    let (started_sender, started) = mpsc::channel();
    let (results, pending_results) = mpsc::channel();
    let pending_results = Mutex::new(pending_results);
    let cleaned: Cleaned = Arc::new(Mutex::new(Vec::new()));
    let cleanup = {
        let cleaned = cleaned.clone();
        Arc::new(move |value| cleaned.lock().unwrap().push(value)) as Arc<dyn Fn(i32) + Send + Sync>
    };
    let resource = AsyncResourceVm::with_options(
        "resource",
        move |_ignored_token| {
            let _ = started_sender.send(());
            pending_results
                .lock()
                .unwrap()
                .recv()
                .unwrap_or_else(|_| Err(VmxError::Other("gate closed".into())))
        },
        AsyncResourceRetention::DiscardPrevious,
        Some(cleanup),
    );
    (resource, Gate { started, results }, cleaned)
}

impl Gate {
    fn wait_for_start(&self) {
        self.started
            .recv_timeout(BOUND)
            .expect("the loader started within the bound");
    }
}

#[test]
fn a_successful_loader_completes_the_awaited_load() {
    let (resource, gate, cleaned) = gated_resource();

    let load = resource.load_async();
    gate.wait_for_start();
    gate.results.send(Ok(1)).unwrap();

    join_within(load).unwrap().unwrap();
    assert_eq!(resource.state(), AsyncResourceState::Ready { value: 1 });
    assert!(cleaned_values(&cleaned).is_empty());
    resource.dispose().unwrap();
    assert_eq!(cleaned_values(&cleaned), vec![1]);
}

#[test]
fn a_failing_loader_completes_the_awaited_load() {
    let (resource, gate, cleaned) = gated_resource();
    let error = VmxError::InvalidArgument("unavailable".into());

    let load = resource.load_async();
    gate.wait_for_start();
    gate.results.send(Err(error.clone())).unwrap();

    join_within(load).unwrap().unwrap();
    assert_eq!(
        resource.state(),
        AsyncResourceState::Error {
            previous: None,
            error
        }
    );
    resource.dispose().unwrap();
    assert!(cleaned_values(&cleaned).is_empty());
}

#[test]
fn a_panicking_loader_completes_the_awaited_load_with_its_panic() {
    let resource = AsyncResourceVm::new("resource", |_| -> VmxResult<i32> {
        panic!("loader failed")
    });

    let payload = join_within(resource.load_async()).expect_err("the loader panic propagates");

    assert_eq!(payload.downcast_ref::<&str>(), Some(&"loader failed"));
    assert_eq!(resource.state(), AsyncResourceState::Idle);
    assert!(resource.load_command().can_execute());
}

#[test]
fn cancelling_before_the_loader_starts_completes_the_awaited_load_without_running_it() {
    let (resource, gate, cleaned) = gated_resource();
    let holder = Arc::new(Mutex::new(Some(resource.clone())));
    let observed = holder.clone();
    let _subscription = resource.property_changed().subscribe(move |name| {
        let resource = observed.lock().unwrap().clone();
        if let Some(resource) = resource {
            if name == "state" && resource.resource_status() == AsyncResourceStatus::Loading {
                resource.cancel();
            }
        }
    });

    join_within(resource.load_async()).unwrap().unwrap();
    holder.lock().unwrap().take();

    assert!(gate.started.try_recv().is_err(), "the loader ran");
    assert_eq!(resource.state(), AsyncResourceState::Idle);
    assert!(cleaned_values(&cleaned).is_empty());
}

#[test]
fn cancelling_an_uncooperative_loader_wakes_the_awaited_load_promptly() {
    let (resource, gate, _cleaned) = gated_resource();

    let load = resource.load_async();
    gate.wait_for_start();
    resource.cancel();

    // The loader is still blocked: only the cancellation can complete the load.
    join_within(load).unwrap().unwrap();
    assert_eq!(resource.state(), AsyncResourceState::Idle);
    assert!(resource.load_command().can_execute());
    gate.results
        .send(Err(VmxError::Other("released".into())))
        .unwrap();
}

#[test]
fn cancelling_the_load_command_wakes_its_worker_promptly() {
    let (resource, gate, cleaned) = gated_resource();

    let load = resource.load_command().execute_async();
    gate.wait_for_start();
    // Cancels only the command's token, not the resource operation directly.
    resource.load_command().cancel();

    join_within(load).unwrap().unwrap();
    assert_eq!(resource.state(), AsyncResourceState::Idle);
    gate.results.send(Ok(3)).unwrap();
    wait_until(|| cleaned_values(&cleaned) == [3]);
    assert_eq!(resource.state(), AsyncResourceState::Idle);
}

#[test]
fn an_uncooperative_late_success_is_cleaned_once_and_not_committed() {
    let (resource, gate, cleaned) = gated_resource();
    let notifications = Arc::new(Mutex::new(0));
    let counted = notifications.clone();
    let _subscription = resource.property_changed().subscribe(move |_| {
        *counted.lock().unwrap() += 1;
    });

    let load = resource.load_async();
    gate.wait_for_start();
    resource.cancel();
    join_within(load).unwrap().unwrap();
    let after_cancel = *notifications.lock().unwrap();
    gate.results.send(Ok(7)).unwrap();

    wait_until(|| cleaned_values(&cleaned) == [7]);
    assert_eq!(resource.state(), AsyncResourceState::Idle);
    assert_eq!(*notifications.lock().unwrap(), after_cancel);
    resource.dispose().unwrap();
    assert_eq!(cleaned_values(&cleaned), vec![7]);
}

#[test]
fn disposal_wakes_the_awaited_load_and_cleans_its_late_value_once() {
    let (resource, gate, cleaned) = gated_resource();

    let load = resource.load_async();
    gate.wait_for_start();
    resource.dispose().unwrap();

    join_within(load).unwrap().unwrap();
    gate.results.send(Ok(9)).unwrap();
    wait_until(|| cleaned_values(&cleaned) == [9]);
    resource.dispose().unwrap();
    assert_eq!(cleaned_values(&cleaned), vec![9]);
}

#[test]
fn a_superseding_reload_wakes_the_previous_awaited_load() {
    let (resource, gate, cleaned) = gated_resource();

    let older = resource.load_async();
    gate.wait_for_start();
    let newer = resource.reload_async();

    join_within(older).unwrap().unwrap();
    gate.wait_for_start();
    gate.results.send(Ok(1)).unwrap();
    gate.results.send(Ok(2)).unwrap();
    join_within(newer).unwrap().unwrap();
    wait_until(|| cleaned_values(&cleaned) == [1]);
    assert_eq!(resource.state(), AsyncResourceState::Ready { value: 2 });
}

#[test]
fn cancellation_racing_completion_settles_each_value_once() {
    const ROUNDS: i32 = 50;
    let mut committed_rounds = 0;
    for round in 0..ROUNDS {
        let cleaned: Cleaned = Arc::new(Mutex::new(Vec::new()));
        let start = Arc::new(Barrier::new(2));
        let loader_start = start.clone();
        let resource = AsyncResourceVm::with_options(
            "resource",
            move |_| {
                loader_start.wait();
                Ok(round)
            },
            AsyncResourceRetention::DiscardPrevious,
            Some({
                let cleaned = cleaned.clone();
                Arc::new(move |value| cleaned.lock().unwrap().push(value))
            }),
        );

        let load = resource.load_async();
        start.wait();
        resource.cancel();
        join_within(load).unwrap().unwrap();

        // Either the value committed, or the cancellation won and the late
        // value is cleaned by the loader worker.
        wait_until(|| {
            resource.state() == AsyncResourceState::Ready { value: round }
                || cleaned_values(&cleaned) == [round]
        });
        if resource.state() == (AsyncResourceState::Ready { value: round }) {
            committed_rounds += 1;
        }
        resource.dispose().unwrap();
        assert_eq!(cleaned_values(&cleaned), vec![round], "round {round}");
    }
    println!("{committed_rounds} of {ROUNDS} rounds committed before the cancellation");
}
