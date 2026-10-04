use crate::{lock, wait};
use std::any::Any;
use std::future::Future;
use std::panic::{catch_unwind, resume_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::sync::{Arc, Condvar, Mutex};
use std::task::{Context, Poll, Waker};

type PanicPayload = Box<dyn Any + Send>;

/// The terminal failure of an [`AsyncValue`] whose `map` or `and_then`
/// callback panicked.
///
/// Clones share one record. [`message`](Self::message) is available to every
/// observer; the original panic payload is handed out once, to the first
/// [`take_payload`](Self::take_payload) or re-raising observer.
#[derive(Clone)]
pub struct AsyncValuePanic {
    message: Arc<str>,
    payload: Arc<Mutex<Option<PanicPayload>>>,
}

impl AsyncValuePanic {
    fn new(payload: PanicPayload) -> Self {
        let message = payload
            .downcast_ref::<&str>()
            .map(|message| (*message).to_string())
            .or_else(|| payload.downcast_ref::<String>().cloned())
            .unwrap_or_else(|| "AsyncValue continuation panicked".to_string());
        Self {
            message: message.into(),
            payload: Arc::new(Mutex::new(Some(payload))),
        }
    }

    /// The panic message when the payload was a string, otherwise
    /// `"AsyncValue continuation panicked"`.
    pub fn message(&self) -> &str {
        &self.message
    }

    /// Takes the original panic payload. Only the first caller, across all
    /// clones and re-raising observers, receives it.
    pub fn take_payload(&self) -> Option<PanicPayload> {
        lock(&self.payload).take()
    }

    /// Re-raises the panic on the current thread, with the original payload
    /// if no observer has taken it yet and otherwise with a `String` payload
    /// carrying [`message`](Self::message).
    pub fn resume(&self) -> ! {
        match self.take_payload() {
            Some(payload) => resume_unwind(payload),
            None => resume_unwind(Box::new(self.message.to_string())),
        }
    }
}

impl std::fmt::Debug for AsyncValuePanic {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("AsyncValuePanic")
            .field("message", &self.message)
            .finish_non_exhaustive()
    }
}

#[derive(Clone)]
enum Outcome<T> {
    Value(T),
    Panicked(AsyncValuePanic),
}

impl<T> Outcome<T> {
    fn into_result(self) -> Result<T, AsyncValuePanic> {
        match self {
            Outcome::Value(value) => Ok(value),
            Outcome::Panicked(panic) => Err(panic),
        }
    }
}

type Continuation<T> = Box<dyn FnOnce(Outcome<T>) + Send + 'static>;

struct AsyncValueState<T> {
    outcome: Option<Outcome<T>>,
    wakers: Vec<Waker>,
    continuations: Vec<Continuation<T>>,
}

struct AsyncValueInner<T> {
    state: Mutex<AsyncValueState<T>>,
    ready: Condvar,
}

/// Executor-neutral, cloneable completion handle.
///
/// `AsyncValue` implements [`Future`] for async consumers and also exposes
/// [`AsyncValue::wait`] for synchronous Rust hosts that do not use an async
/// runtime. Settlement is first-wins and wakes both kinds of waiters.
///
/// A handle settles with a value through [`resolve`](Self::resolve), or as
/// panicked when the `map` or `and_then` callback that produces it panics
/// (ADR-0138). A panicked handle is terminal: [`wait`](Self::wait) and
/// `.await` re-raise the panic, [`wait_result`](Self::wait_result) and
/// [`try_result`](Self::try_result) return it as an [`AsyncValuePanic`], and
/// [`try_get`](Self::try_get) returns `None`. Every observer terminates; the
/// original payload goes to the first observer that takes or re-raises it.
/// Under `panic = "abort"` a panicking callback aborts the process, so the
/// panicked state exists only with unwinding panics.
#[derive(Clone)]
pub struct AsyncValue<T: Clone + Send + 'static> {
    inner: Arc<AsyncValueInner<T>>,
}

impl<T: Clone + Send + 'static> AsyncValue<T> {
    /// Creates an unresolved completion handle.
    pub fn pending() -> Self {
        Self {
            inner: Arc::new(AsyncValueInner {
                state: Mutex::new(AsyncValueState {
                    outcome: None,
                    wakers: Vec::new(),
                    continuations: Vec::new(),
                }),
                ready: Condvar::new(),
            }),
        }
    }

    /// Creates a completion handle already resolved to `value`.
    pub fn ready(value: T) -> Self {
        let completion = Self::pending();
        completion.resolve(value);
        completion
    }

    /// Resolves the handle once, returning whether this call supplied the
    /// value. A handle that already settled, with a value or as panicked,
    /// keeps its first outcome.
    pub fn resolve(&self, value: T) -> bool {
        self.settle(Outcome::Value(value))
    }

    fn settle(&self, outcome: Outcome<T>) -> bool {
        let (wakers, continuations) = {
            let mut state = lock(&self.inner.state);
            if state.outcome.is_some() {
                return false;
            }
            state.outcome = Some(outcome.clone());
            (
                std::mem::take(&mut state.wakers),
                std::mem::take(&mut state.continuations),
            )
        };
        self.inner.ready.notify_all();
        for waker in wakers {
            let _ = catch_unwind(AssertUnwindSafe(|| waker.wake()));
        }
        for continuation in continuations {
            let outcome = outcome.clone();
            let _ = catch_unwind(AssertUnwindSafe(|| continuation(outcome)));
        }
        true
    }

    /// Returns the resolved value without blocking, or `None` while pending
    /// or after the handle settled as panicked.
    pub fn try_get(&self) -> Option<T> {
        match &lock(&self.inner.state).outcome {
            Some(Outcome::Value(value)) => Some(value.clone()),
            _ => None,
        }
    }

    /// Returns the outcome without blocking, or `None` while pending.
    pub fn try_result(&self) -> Option<Result<T, AsyncValuePanic>> {
        lock(&self.inner.state)
            .outcome
            .clone()
            .map(Outcome::into_result)
    }

    /// Blocks the current thread until the handle settles, then returns its
    /// value or the panic of the callback that produced it.
    pub fn wait_result(&self) -> Result<T, AsyncValuePanic> {
        let mut state = lock(&self.inner.state);
        loop {
            if let Some(outcome) = state.outcome.clone() {
                return outcome.into_result();
            }
            state = wait(&self.inner.ready, state);
        }
    }

    /// Blocks the current thread until the handle settles, then clones the
    /// value.
    ///
    /// # Panics
    ///
    /// Re-raises the panic when the handle settled as panicked; see
    /// [`AsyncValuePanic::resume`].
    pub fn wait(&self) -> T {
        match self.wait_result() {
            Ok(value) => value,
            Err(panic) => panic.resume(),
        }
    }

    #[cfg(test)]
    pub(crate) fn observe_wait(&self) -> crate::runtime::wait_observation::Observation<'_> {
        crate::runtime::wait_observation::observe(&self.inner.ready)
    }

    /// Maps the eventual value through an executor-neutral continuation.
    ///
    /// The mapping runs synchronously on the thread that resolves this handle,
    /// or immediately when the handle is already resolved. A panicking mapper
    /// is isolated from the resolver and settles the returned handle as
    /// panicked; a panicked source settles it as panicked without running the
    /// mapper.
    pub fn map<U, F>(&self, mapper: F) -> AsyncValue<U>
    where
        U: Clone + Send + 'static,
        F: FnOnce(T) -> U + Send + 'static,
    {
        let mapped = AsyncValue::pending();
        let completion = mapped.clone();
        self.when_settled(move |outcome| match outcome {
            Ok(value) => match catch_unwind(AssertUnwindSafe(|| mapper(value))) {
                Ok(mapped_value) => {
                    completion.resolve(mapped_value);
                }
                Err(payload) => {
                    completion.settle(Outcome::Panicked(AsyncValuePanic::new(payload)));
                }
            },
            Err(panic) => {
                completion.settle(Outcome::Panicked(panic));
            }
        });
        mapped
    }

    /// Composes the eventual value with another executor-neutral completion.
    ///
    /// The returned handle settles as panicked when this handle, the mapper,
    /// or the handle the mapper returns settles as panicked.
    pub fn and_then<U, F>(&self, mapper: F) -> AsyncValue<U>
    where
        U: Clone + Send + 'static,
        F: FnOnce(T) -> AsyncValue<U> + Send + 'static,
    {
        let composed = AsyncValue::pending();
        let completion = composed.clone();
        self.when_settled(move |outcome| match outcome {
            Ok(value) => match catch_unwind(AssertUnwindSafe(|| mapper(value))) {
                Ok(next) => next.when_settled(move |next_outcome| {
                    completion.settle(match next_outcome {
                        Ok(next_value) => Outcome::Value(next_value),
                        Err(panic) => Outcome::Panicked(panic),
                    });
                }),
                Err(payload) => {
                    completion.settle(Outcome::Panicked(AsyncValuePanic::new(payload)));
                }
            },
            Err(panic) => {
                completion.settle(Outcome::Panicked(panic));
            }
        });
        composed
    }

    /// Returns the number of continuations retained while this handle is pending.
    ///
    /// This is useful for deterministic resource-bound diagnostics. A settled
    /// handle always reports zero.
    pub fn pending_continuation_count(&self) -> usize {
        lock(&self.inner.state).continuations.len()
    }

    /// Runs `continuation` with the outcome once the handle settles, or
    /// immediately when it already has.
    pub(crate) fn when_settled<F>(&self, continuation: F)
    where
        F: FnOnce(Result<T, AsyncValuePanic>) + Send + 'static,
    {
        let mut continuation = Some(continuation);
        let settled = {
            let mut state = lock(&self.inner.state);
            if let Some(outcome) = state.outcome.clone() {
                Some(outcome)
            } else {
                let queued = continuation.take().expect("continuation available");
                state
                    .continuations
                    .push(Box::new(move |outcome: Outcome<T>| {
                        queued(outcome.into_result())
                    }));
                None
            }
        };
        if let Some(outcome) = settled {
            let continuation = continuation.expect("continuation not queued");
            let _ = catch_unwind(AssertUnwindSafe(|| continuation(outcome.into_result())));
        }
    }
}

impl<T: Clone + Send + 'static> Future for AsyncValue<T> {
    type Output = T;

    /// Completes with the value, or re-raises the panic of a handle that
    /// settled as panicked.
    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        let mut state = lock(&self.inner.state);
        match state.outcome.clone() {
            Some(Outcome::Value(value)) => return Poll::Ready(value),
            Some(Outcome::Panicked(panic)) => {
                drop(state);
                panic.resume();
            }
            None => {}
        }
        if !state
            .wakers
            .iter()
            .any(|waker| waker.will_wake(context.waker()))
        {
            state.wakers.push(context.waker().clone());
        }
        Poll::Pending
    }
}
