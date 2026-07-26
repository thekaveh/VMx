//! VMx-owned typed value streams.

use crate::{lock, Arc, AssertUnwindSafe, AtomicBool, BTreeMap, Mutex, Ordering, VecDeque, Weak};
use std::panic::catch_unwind;

type ValueSubscriber<T> = Arc<dyn Fn(T) + Send + Sync + 'static>;
type ValueCompletion = Arc<dyn Fn() + Send + Sync + 'static>;

struct ValueStreamSubscriber<T> {
    value: ValueSubscriber<T>,
    completion: Option<ValueCompletion>,
}

struct ValueStreamState<T> {
    next_subscription_id: usize,
    current: T,
    revision: usize,
    subscribers: BTreeMap<usize, ValueStreamSubscriber<T>>,
    pending: VecDeque<T>,
    draining: bool,
    dispose_requested: bool,
    replay_current: bool,
    disposed: bool,
}

/// A typed, synchronous, replaying stream owned by VMx.
///
/// Every subscriber immediately receives the current value. Calls to
/// [`send`](Self::send) synchronously publish the replacement value, and
/// [`dispose`](Self::dispose) completes current and future subscriptions.
/// Subscriber panics are isolated from publishers and other subscribers.
#[derive(Clone)]
pub struct ValueStream<T: Clone + Send + 'static> {
    inner: Arc<Mutex<ValueStreamState<T>>>,
}

impl<T: Clone + Send + 'static> ValueStream<T> {
    /// Creates an active stream whose first subscription replay is `initial`.
    pub fn new(initial: T) -> Self {
        Self {
            inner: Arc::new(Mutex::new(ValueStreamState {
                next_subscription_id: 0,
                current: initial,
                revision: 0,
                subscribers: BTreeMap::new(),
                pending: VecDeque::new(),
                draining: false,
                dispose_requested: false,
                replay_current: true,
                disposed: false,
            })),
        }
    }

    /// Creates a typed hot stream that does not replay its retained value.
    ///
    /// This shape is used for event-like value changes: current subscribers
    /// receive future sends and completion, while late subscribers do not
    /// receive an earlier event.
    pub fn hot(initial: T) -> Self {
        Self {
            inner: Arc::new(Mutex::new(ValueStreamState {
                next_subscription_id: 0,
                current: initial,
                revision: 0,
                subscribers: BTreeMap::new(),
                pending: VecDeque::new(),
                draining: false,
                dispose_requested: false,
                replay_current: false,
                disposed: false,
            })),
        }
    }

    /// Returns a snapshot of the most recently accepted value.
    pub fn value(&self) -> T {
        lock(&self.inner).current.clone()
    }

    /// Subscribes to the current value and all later values.
    pub fn subscribe<F>(&self, handler: F) -> ValueSubscription
    where
        F: Fn(T) + Send + Sync + 'static,
    {
        self.subscribe_internal(Arc::new(handler), None)
    }

    /// Subscribes to values and receives one callback when the stream completes.
    ///
    /// A subscription made after disposal receives the retained current value
    /// followed immediately by `completion`.
    pub fn subscribe_with_completion<F, C>(&self, handler: F, completion: C) -> ValueSubscription
    where
        F: Fn(T) + Send + Sync + 'static,
        C: Fn() + Send + Sync + 'static,
    {
        self.subscribe_internal(Arc::new(handler), Some(Arc::new(completion)))
    }

    fn subscribe_internal(
        &self,
        handler: ValueSubscriber<T>,
        completion: Option<ValueCompletion>,
    ) -> ValueSubscription {
        if !lock(&self.inner).replay_current {
            let mut state = lock(&self.inner);
            if state.disposed || state.dispose_requested {
                drop(state);
                if let Some(completion) = completion {
                    let _ = catch_unwind(AssertUnwindSafe(|| completion()));
                }
                return ValueSubscription::noop();
            }
            state.next_subscription_id += 1;
            let id = state.next_subscription_id;
            state.subscribers.insert(
                id,
                ValueStreamSubscriber {
                    value: handler,
                    completion,
                },
            );
            return ValueSubscription::new(id, Arc::downgrade(&self.inner));
        }

        let (value, revision, disposed) = {
            let state = lock(&self.inner);
            (
                state.current.clone(),
                state.revision,
                state.disposed || state.dispose_requested,
            )
        };
        let _ = catch_unwind(AssertUnwindSafe(|| handler(value)));
        if disposed {
            if let Some(completion) = completion {
                let _ = catch_unwind(AssertUnwindSafe(|| completion()));
            }
            return ValueSubscription::noop();
        }

        let mut state = lock(&self.inner);
        if state.disposed || state.dispose_requested {
            let latest = (state.revision != revision).then(|| state.current.clone());
            drop(state);
            if let Some(latest) = latest {
                let _ = catch_unwind(AssertUnwindSafe(|| handler(latest)));
            }
            if let Some(completion) = completion {
                let _ = catch_unwind(AssertUnwindSafe(|| completion()));
            }
            return ValueSubscription::noop();
        }
        if state.revision != revision {
            let latest = state.current.clone();
            drop(state);
            let _ = catch_unwind(AssertUnwindSafe(|| handler(latest)));
            state = lock(&self.inner);
            if state.disposed || state.dispose_requested {
                drop(state);
                if let Some(completion) = completion {
                    let _ = catch_unwind(AssertUnwindSafe(|| completion()));
                }
                return ValueSubscription::noop();
            }
        }

        state.next_subscription_id += 1;
        let id = state.next_subscription_id;
        state.subscribers.insert(
            id,
            ValueStreamSubscriber {
                value: handler,
                completion,
            },
        );
        ValueSubscription::new(id, Arc::downgrade(&self.inner))
    }

    /// Publishes `value` to current subscribers unless the stream is disposed.
    pub fn send(&self, value: T) {
        let should_drain = {
            let mut state = lock(&self.inner);
            if state.disposed || state.dispose_requested {
                return;
            }
            state.current = value.clone();
            state.revision = state.revision.wrapping_add(1);
            state.pending.push_back(value);
            if state.draining {
                false
            } else {
                state.draining = true;
                true
            }
        };
        if !should_drain {
            return;
        }

        loop {
            let next = {
                let mut state = lock(&self.inner);
                if state.dispose_requested {
                    let completions = Self::finish_dispose(&mut state);
                    drop(state);
                    Self::notify_completions(completions);
                    return;
                }
                let Some(value) = state.pending.pop_front() else {
                    state.draining = false;
                    return;
                };
                let subscribers = state
                    .subscribers
                    .values()
                    .map(|subscriber| subscriber.value.clone())
                    .collect::<Vec<_>>();
                (value, subscribers)
            };
            for subscriber in next.1 {
                let value = next.0.clone();
                let _ = catch_unwind(AssertUnwindSafe(|| subscriber(value)));
            }
        }
    }

    /// Completes the stream once and makes later sends inert.
    pub fn dispose(&self) {
        let completions = {
            let mut state = lock(&self.inner);
            if state.disposed || state.dispose_requested {
                return;
            }
            if state.draining {
                state.dispose_requested = true;
                return;
            }
            Self::finish_dispose(&mut state)
        };
        Self::notify_completions(completions);
    }

    fn finish_dispose(state: &mut ValueStreamState<T>) -> Vec<ValueCompletion> {
        state.disposed = true;
        state.dispose_requested = false;
        state.draining = false;
        state.pending.clear();
        std::mem::take(&mut state.subscribers)
            .into_values()
            .filter_map(|subscriber| subscriber.completion)
            .collect()
    }

    fn notify_completions(completions: Vec<ValueCompletion>) {
        for completion in completions {
            let _ = catch_unwind(AssertUnwindSafe(|| completion()));
        }
    }
}

/// Disposable registration in a [`ValueStream`].
pub struct ValueSubscription {
    active: AtomicBool,
    dispose_action: Arc<dyn Fn() + Send + Sync>,
}

impl ValueSubscription {
    fn new<T: Clone + Send + 'static>(id: usize, stream: Weak<Mutex<ValueStreamState<T>>>) -> Self {
        Self {
            active: AtomicBool::new(true),
            dispose_action: Arc::new(move || {
                if let Some(stream) = stream.upgrade() {
                    lock(&stream).subscribers.remove(&id);
                }
            }),
        }
    }

    fn noop() -> Self {
        Self {
            active: AtomicBool::new(false),
            dispose_action: Arc::new(|| {}),
        }
    }

    /// Detaches value and completion callbacks; repeated calls are inert.
    pub fn dispose(&self) {
        if self.active.swap(false, Ordering::SeqCst) {
            (self.dispose_action)();
        }
    }
}

impl Drop for ValueSubscription {
    fn drop(&mut self) {
        self.dispose();
    }
}
