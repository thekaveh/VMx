use crate::{lock, wait};
use std::future::Future;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::sync::{Arc, Condvar, Mutex};
use std::task::{Context, Poll, Waker};

struct AsyncValueState<T> {
    value: Option<T>,
    wakers: Vec<Waker>,
    continuations: Vec<Box<dyn FnOnce(T) + Send + 'static>>,
}

struct AsyncValueInner<T> {
    state: Mutex<AsyncValueState<T>>,
    ready: Condvar,
}

/// Executor-neutral, cloneable completion handle.
///
/// `AsyncValue` implements [`Future`] for async consumers and also exposes
/// [`AsyncValue::wait`] for synchronous Rust hosts that do not use an async
/// runtime. Resolution is first-wins and wakes both kinds of waiters.
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
                    value: None,
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

    /// Resolves the handle once, returning whether this call supplied the value.
    pub fn resolve(&self, value: T) -> bool {
        let (wakers, continuations) = {
            let mut state = lock(&self.inner.state);
            if state.value.is_some() {
                return false;
            }
            state.value = Some(value.clone());
            (
                std::mem::take(&mut state.wakers),
                std::mem::take(&mut state.continuations),
            )
        };
        self.inner.ready.notify_all();
        for waker in wakers {
            waker.wake();
        }
        for continuation in continuations {
            let value = value.clone();
            let _ = catch_unwind(AssertUnwindSafe(|| continuation(value)));
        }
        true
    }

    /// Returns the resolved value without blocking, or `None` while pending.
    pub fn try_get(&self) -> Option<T> {
        lock(&self.inner.state).value.clone()
    }

    /// Blocks the current thread until the value is resolved, then clones it.
    pub fn wait(&self) -> T {
        let mut state = lock(&self.inner.state);
        loop {
            if let Some(value) = state.value.clone() {
                return value;
            }
            state = wait(&self.inner.ready, state);
        }
    }

    /// Maps the eventual value through an executor-neutral continuation.
    ///
    /// The mapping runs synchronously on the thread that resolves this handle,
    /// or immediately when the handle is already resolved. A panicking mapper
    /// is isolated from the resolver and leaves the returned handle pending.
    pub fn map<U, F>(&self, mapper: F) -> AsyncValue<U>
    where
        U: Clone + Send + 'static,
        F: FnOnce(T) -> U + Send + 'static,
    {
        let mapped = AsyncValue::pending();
        let completion = mapped.clone();
        self.continue_with(move |value| {
            completion.resolve(mapper(value));
        });
        mapped
    }

    /// Composes the eventual value with another executor-neutral completion.
    pub fn and_then<U, F>(&self, mapper: F) -> AsyncValue<U>
    where
        U: Clone + Send + 'static,
        F: FnOnce(T) -> AsyncValue<U> + Send + 'static,
    {
        let composed = AsyncValue::pending();
        let completion = composed.clone();
        self.continue_with(move |value| {
            let next = mapper(value);
            next.continue_with(move |next_value| {
                completion.resolve(next_value);
            });
        });
        composed
    }

    /// Returns the number of continuations retained while this handle is pending.
    ///
    /// This is useful for deterministic resource-bound diagnostics. A resolved
    /// handle always reports zero.
    pub fn pending_continuation_count(&self) -> usize {
        lock(&self.inner.state).continuations.len()
    }

    fn continue_with<F>(&self, continuation: F)
    where
        F: FnOnce(T) + Send + 'static,
    {
        let mut continuation = Some(continuation);
        let ready = {
            let mut state = lock(&self.inner.state);
            if let Some(value) = state.value.clone() {
                Some(value)
            } else {
                state.continuations.push(Box::new(
                    continuation.take().expect("continuation available"),
                ));
                None
            }
        };
        if let Some(value) = ready {
            let continuation = continuation.expect("continuation not queued");
            let _ = catch_unwind(AssertUnwindSafe(|| continuation(value)));
        }
    }
}

impl<T: Clone + Send + 'static> Future for AsyncValue<T> {
    type Output = T;

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        let mut state = lock(&self.inner.state);
        if let Some(value) = state.value.clone() {
            return Poll::Ready(value);
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
