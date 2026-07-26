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
    let _failing = source.map(|_: i32| -> i32 { panic!("continuation boom") });
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
