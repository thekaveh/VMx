use crate::{lock, wait};
use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Condvar, Mutex};
use std::task::{Context, Poll, Waker};

struct AsyncValueState<T> {
    value: Option<T>,
    wakers: Vec<Waker>,
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
    pub fn pending() -> Self {
        Self {
            inner: Arc::new(AsyncValueInner {
                state: Mutex::new(AsyncValueState {
                    value: None,
                    wakers: Vec::new(),
                }),
                ready: Condvar::new(),
            }),
        }
    }

    pub fn ready(value: T) -> Self {
        let completion = Self::pending();
        completion.resolve(value);
        completion
    }

    pub fn resolve(&self, value: T) -> bool {
        let wakers = {
            let mut state = lock(&self.inner.state);
            if state.value.is_some() {
                return false;
            }
            state.value = Some(value);
            std::mem::take(&mut state.wakers)
        };
        self.inner.ready.notify_all();
        for waker in wakers {
            waker.wake();
        }
        true
    }

    pub fn try_get(&self) -> Option<T> {
        lock(&self.inner.state).value.clone()
    }

    pub fn wait(&self) -> T {
        let mut state = lock(&self.inner.state);
        loop {
            if let Some(value) = state.value.clone() {
                return value;
            }
            state = wait(&self.inner.ready, state);
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
