use std::future::Future;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Wake, Waker};

use vmx::{AsyncValue, Command, ConfirmationDecoratorCommand, RelayCommand};

struct PanicWake {
    wakes: Arc<AtomicUsize>,
}

impl Wake for PanicWake {
    fn wake(self: Arc<Self>) {
        self.wakes.fetch_add(1, Ordering::SeqCst);
        panic!("waker boom");
    }
}

struct CountingWake {
    wakes: Arc<AtomicUsize>,
}

impl Wake for CountingWake {
    fn wake(self: Arc<Self>) {
        self.wakes.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn async_value_maps_and_composes_without_an_executor() {
    let source = AsyncValue::pending();
    let mapped = source.map(|value: i32| value * 2);
    let composed = mapped.and_then(|value| AsyncValue::ready(value.to_string()));

    assert_eq!(source.pending_continuation_count(), 1);
    source.resolve(3);

    assert_eq!(composed.wait(), "6");
    assert_eq!(source.pending_continuation_count(), 0);
}

#[test]
fn async_value_continuation_panics_are_isolated_and_first_resolution_wins() {
    let source = AsyncValue::pending();
    let failing = source.map(|_: i32| -> i32 { panic!("continuation boom") });
    let observed = Arc::new(Mutex::new(Vec::new()));
    let values = observed.clone();
    let healthy = source.map(move |value| {
        values.lock().unwrap().push(value);
        value
    });

    assert!(catch_unwind(AssertUnwindSafe(|| source.resolve(1))).is_ok());
    assert!(!source.resolve(2));

    assert_eq!(healthy.wait(), 1);
    assert_eq!(*observed.lock().unwrap(), vec![1]);
    assert_eq!(
        failing.wait_result().unwrap_err().message(),
        "continuation boom"
    );
}

#[test]
fn async_value_isolates_each_waker_panic_before_continuations() {
    let source = AsyncValue::pending();
    let panic_wakes = Arc::new(AtomicUsize::new(0));
    let healthy_wakes = Arc::new(AtomicUsize::new(0));

    let mut panicking_future = source.clone();
    let panicking_waker = Waker::from(Arc::new(PanicWake {
        wakes: panic_wakes.clone(),
    }));
    let mut panicking_context = Context::from_waker(&panicking_waker);
    assert_eq!(
        Pin::new(&mut panicking_future).poll(&mut panicking_context),
        Poll::Pending
    );

    let mut healthy_future = source.clone();
    let healthy_waker = Waker::from(Arc::new(CountingWake {
        wakes: healthy_wakes.clone(),
    }));
    let mut healthy_context = Context::from_waker(&healthy_waker);
    assert_eq!(
        Pin::new(&mut healthy_future).poll(&mut healthy_context),
        Poll::Pending
    );

    let mapped = source.map(|approved| if approved { "approved" } else { "rejected" });
    let composed = mapped.and_then(|decision| AsyncValue::ready(format!("{decision}:continued")));

    let executions = Arc::new(AtomicUsize::new(0));
    let observed_executions = executions.clone();
    let pending_decision = source.clone();
    let command = ConfirmationDecoratorCommand::new(
        RelayCommand::new(move || {
            observed_executions.fetch_add(1, Ordering::SeqCst);
        }),
        move || pending_decision.clone(),
    );
    command.execute();

    let resolution = catch_unwind(AssertUnwindSafe(|| source.resolve(true)));

    assert!(resolution.is_ok(), "waker panic escaped resolve");
    assert_eq!(panic_wakes.load(Ordering::SeqCst), 1);
    assert_eq!(healthy_wakes.load(Ordering::SeqCst), 1);
    assert_eq!(composed.try_get(), Some("approved:continued".to_string()));
    assert_eq!(executions.load(Ordering::SeqCst), 1);
    assert!(!source.resolve(false), "resolution must remain first-wins");
}

const SETTLE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(5);

/// Runs `observe` on a worker and reports its outcome, failing instead of
/// hanging when the observed handle never settles.
fn observe_on_worker<R: Send + 'static>(
    observe: impl FnOnce() -> R + Send + 'static,
) -> std::thread::Result<R> {
    let (finished, outcome) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let result = catch_unwind(AssertUnwindSafe(observe));
        let _ = finished.send(result);
    });
    outcome
        .recv_timeout(SETTLE_TIMEOUT)
        .expect("the observed handle settled instead of hanging")
}

fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    payload
        .downcast_ref::<&str>()
        .map(|message| (*message).to_string())
        .or_else(|| payload.downcast_ref::<String>().cloned())
        .unwrap_or_default()
}

#[derive(Debug, PartialEq)]
struct MapperPayload(u32);

#[test]
fn wait_on_a_handle_whose_mapper_panicked_re_raises_instead_of_hanging() {
    let source = AsyncValue::pending();
    let mapped = source.map(|_: i32| -> i32 { panic!("mapper boom") });
    source.resolve(1);

    let outcome = observe_on_worker(move || mapped.wait());

    let payload = outcome.expect_err("wait re-raises the mapper panic");
    assert!(panic_message(payload.as_ref()).contains("mapper boom"));
}

#[test]
fn map_panic_before_readiness_settles_the_mapped_handle() {
    let source = AsyncValue::pending();
    let mapped = source.map(|_: i32| -> i32 { panic!("late boom") });
    assert_eq!(mapped.try_result().map(|result| result.is_ok()), None);

    source.resolve(1);

    let panic = mapped.wait_result().expect_err("mapped handle panicked");
    assert_eq!(panic.message(), "late boom");
    assert_eq!(mapped.try_get(), None);
    assert!(matches!(mapped.try_result(), Some(Err(_))));
    assert_eq!(source.pending_continuation_count(), 0);
    assert_eq!(mapped.pending_continuation_count(), 0);
}

#[test]
fn map_panic_after_readiness_settles_the_mapped_handle_immediately() {
    let source = AsyncValue::ready(1);

    let mapped = source.map(|_: i32| -> i32 { std::panic::panic_any(MapperPayload(7)) });

    let panic = mapped.try_result().expect("settled").expect_err("panicked");
    assert_eq!(panic.message(), "AsyncValue continuation panicked");
    let payload = panic
        .take_payload()
        .expect("first observer takes the payload");
    assert_eq!(
        payload.downcast_ref::<MapperPayload>(),
        Some(&MapperPayload(7))
    );
    assert!(panic.take_payload().is_none());
}

#[test]
fn and_then_panics_settle_the_composed_handle_before_and_after_readiness() {
    let pending = AsyncValue::pending();
    let late = pending.and_then(|_: i32| -> AsyncValue<i32> { panic!("and_then boom") });
    pending.resolve(1);
    assert_eq!(late.wait_result().unwrap_err().message(), "and_then boom");

    let ready = AsyncValue::ready(1);
    let early = ready.and_then(|_: i32| -> AsyncValue<i32> { panic!("and_then ready boom") });
    assert_eq!(
        early.wait_result().unwrap_err().message(),
        "and_then ready boom"
    );
}

#[test]
fn a_panic_propagates_through_nested_compositions() {
    let source = AsyncValue::pending();
    let downstream_mapper_runs = Arc::new(AtomicUsize::new(0));
    let failing = source.map(|_: i32| -> i32 { panic!("inner boom") });
    let mapped_again = failing.map({
        let runs = downstream_mapper_runs.clone();
        move |value| {
            runs.fetch_add(1, Ordering::SeqCst);
            value + 1
        }
    });
    let inner_failure = failing.clone();
    let composed = AsyncValue::ready(5).and_then(move |_: i32| inner_failure.clone());

    source.resolve(1);

    assert_eq!(
        mapped_again.wait_result().unwrap_err().message(),
        "inner boom"
    );
    assert_eq!(composed.wait_result().unwrap_err().message(), "inner boom");
    assert_eq!(downstream_mapper_runs.load(Ordering::SeqCst), 0);
}

#[test]
fn several_clones_waiting_on_a_failed_result_all_terminate() {
    let source = AsyncValue::pending();
    let mapped = source.map(|_: i32| -> i32 { std::panic::panic_any(MapperPayload(9)) });
    let (started, ready) = std::sync::mpsc::channel();
    let waiters = (0..3)
        .map(|_| {
            let handle = mapped.clone();
            let started = started.clone();
            std::thread::spawn(move || {
                started.send(()).unwrap();
                catch_unwind(AssertUnwindSafe(|| handle.wait()))
            })
        })
        .collect::<Vec<_>>();
    for _ in 0..3 {
        ready.recv_timeout(SETTLE_TIMEOUT).unwrap();
    }
    let result_waiter = {
        let handle = mapped.clone();
        std::thread::spawn(move || {
            handle
                .wait_result()
                .map_err(|panic| panic.message().to_string())
        })
    };

    source.resolve(1);

    let payloads = waiters
        .into_iter()
        .map(|waiter| waiter.join().unwrap().expect_err("each waiter re-raises"))
        .collect::<Vec<_>>();
    let originals = payloads
        .iter()
        .filter(|payload| payload.downcast_ref::<MapperPayload>().is_some())
        .count();
    assert!(
        originals <= 1,
        "the original payload is handed out at most once"
    );
    assert!(payloads
        .iter()
        .filter(|payload| payload.downcast_ref::<MapperPayload>().is_none())
        .all(|payload| panic_message(payload.as_ref()) == "AsyncValue continuation panicked"));
    assert_eq!(
        result_waiter.join().unwrap(),
        Err("AsyncValue continuation panicked".to_string())
    );
}

#[test]
fn other_continuations_and_wakers_still_run_when_one_mapper_panics() {
    let source = AsyncValue::pending();
    let wakes = Arc::new(AtomicUsize::new(0));
    let mut failing_future = source.map(|_: i32| -> i32 { panic!("boom") });
    let waker = Waker::from(Arc::new(CountingWake {
        wakes: wakes.clone(),
    }));
    let mut context = Context::from_waker(&waker);
    assert_eq!(
        Pin::new(&mut failing_future).poll(&mut context),
        Poll::Pending
    );
    let healthy = source.map(|value| value * 10);

    assert!(catch_unwind(AssertUnwindSafe(|| source.resolve(4))).is_ok());

    assert_eq!(healthy.try_get(), Some(40));
    assert_eq!(wakes.load(Ordering::SeqCst), 1);
    let polled = catch_unwind(AssertUnwindSafe(|| {
        Pin::new(&mut failing_future).poll(&mut context)
    }));
    assert!(polled.is_err(), "polling a panicked handle re-raises");
    assert_eq!(source.pending_continuation_count(), 0);
    assert_eq!(failing_future.pending_continuation_count(), 0);
}

#[test]
fn a_mapper_may_reenter_the_source_before_panicking() {
    let source = AsyncValue::pending();
    let reentrant = Arc::new(Mutex::new(None));
    let slot = reentrant.clone();
    let reentering_source = source.clone();
    let mapped = source.map(move |_: i32| -> i32 {
        *slot.lock().unwrap() = Some(reentering_source.map(|inner: i32| inner * 2));
        panic!("after reentry")
    });

    source.resolve(3);

    assert_eq!(mapped.wait_result().unwrap_err().message(), "after reentry");
    let inner = reentrant.lock().unwrap().take().expect("reentrant map");
    assert_eq!(inner.try_get(), Some(6));
}

#[test]
fn concurrent_resolutions_settle_the_panicking_map_once() {
    for _ in 0..50 {
        let source = AsyncValue::pending();
        let runs = Arc::new(AtomicUsize::new(0));
        let mapped = source.map({
            let runs = runs.clone();
            move |_: i32| -> i32 {
                runs.fetch_add(1, Ordering::SeqCst);
                panic!("raced")
            }
        });
        let barrier = Arc::new(std::sync::Barrier::new(2));
        let racers = (0..2)
            .map(|value| {
                let source = source.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    source.resolve(value)
                })
            })
            .collect::<Vec<_>>();
        let wins = racers
            .into_iter()
            .map(|racer| racer.join().unwrap())
            .filter(|won| *won)
            .count();

        assert_eq!(wins, 1);
        assert_eq!(runs.load(Ordering::SeqCst), 1);
        assert_eq!(mapped.wait_result().unwrap_err().message(), "raced");
    }
}

#[test]
fn a_panicked_handle_keeps_its_first_outcome() {
    let source = AsyncValue::ready(1);
    let mapped = source.map(|_: i32| -> i32 { panic!("first outcome") });

    assert!(
        !mapped.resolve(5),
        "a panicked handle cannot be resolved later"
    );
    assert_eq!(mapped.wait_result().unwrap_err().message(), "first outcome");
}

#[test]
fn observers_dropped_before_settlement_release_their_continuations() {
    let source = AsyncValue::pending();
    let mapped = source.map(|_: i32| -> i32 { panic!("unobserved") });
    let mut future = mapped.clone();
    let waker = Waker::from(Arc::new(CountingWake {
        wakes: Arc::new(AtomicUsize::new(0)),
    }));
    let mut context = Context::from_waker(&waker);
    assert_eq!(Pin::new(&mut future).poll(&mut context), Poll::Pending);
    drop(future);
    drop(mapped);
    assert_eq!(source.pending_continuation_count(), 1);

    assert!(catch_unwind(AssertUnwindSafe(|| source.resolve(1))).is_ok());

    assert_eq!(source.pending_continuation_count(), 0);
}

#[test]
fn confirmation_execution_terminates_when_the_confirmation_mapper_panics() {
    let source = AsyncValue::pending();
    let decision = source.map(|_: i32| -> bool { panic!("confirm mapper boom") });
    let command = ConfirmationDecoratorCommand::new(RelayCommand::noop(), move || decision.clone());

    let execution = command.execute_async();
    source.resolve(1);
    let joined = observe_on_worker(move || execution.join()).expect("join itself returns");

    let payload = joined.expect_err("join reports the confirmation panic");
    assert!(panic_message(payload.as_ref()).contains("confirm mapper boom"));
}

#[test]
fn fire_and_forget_confirmation_reports_a_panicked_confirmation_mapper() {
    let decision = AsyncValue::ready(1).map(|_: i32| -> bool { panic!("decision boom") });
    let command = ConfirmationDecoratorCommand::new(RelayCommand::noop(), move || decision.clone());
    let errors = Arc::new(Mutex::new(Vec::new()));
    let observed = errors.clone();
    let _subscription = command
        .error_stream()
        .subscribe(move |error| observed.lock().unwrap().push(error));

    command.execute();

    assert_eq!(
        *errors.lock().unwrap(),
        vec![vmx::VmxError::Other(
            "command panicked: decision boom".to_string()
        )]
    );
}
