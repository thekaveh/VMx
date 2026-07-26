//! VMx-owned typed value streams.

use crate::{
    lock, thread, wait, Arc, AssertUnwindSafe, AtomicBool, BTreeMap, Condvar, Mutex, Ordering,
    ThreadId, VecDeque, Weak,
};
use std::panic::catch_unwind;

type ValueSubscriber<T> = Arc<dyn Fn(T) + Send + Sync + 'static>;
type ValueCompletion = Arc<dyn Fn() + Send + Sync + 'static>;

struct ValueStreamSubscriber<T> {
    value: ValueSubscriber<T>,
    completion: Option<ValueCompletion>,
}

#[derive(Default)]
struct DeliveryCompletion {
    finished: Mutex<bool>,
    ready: Condvar,
}

impl DeliveryCompletion {
    fn wait(&self) {
        let mut finished = lock(&self.finished);
        while !*finished {
            finished = wait(&self.ready, finished);
        }
    }

    fn finish(&self) {
        *lock(&self.finished) = true;
        self.ready.notify_all();
    }
}

struct PendingValue<T> {
    value: T,
    subscribers: Vec<ValueSubscriber<T>>,
    completion: Arc<DeliveryCompletion>,
}

struct PendingTerminal {
    completions: Vec<ValueCompletion>,
}

enum PendingDelivery<T> {
    Value(PendingValue<T>),
    Terminal(PendingTerminal),
    Done,
}

struct ValueStreamState<T> {
    next_subscription_id: usize,
    current: T,
    revision: usize,
    subscribers: BTreeMap<usize, ValueStreamSubscriber<T>>,
    pending: VecDeque<PendingValue<T>>,
    pending_terminal: Option<PendingTerminal>,
    draining_owner: Option<ThreadId>,
    dispose_requested: bool,
    dispose_completion: Option<Arc<DeliveryCompletion>>,
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
                pending_terminal: None,
                draining_owner: None,
                dispose_requested: false,
                dispose_completion: None,
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
                pending_terminal: None,
                draining_owner: None,
                dispose_requested: false,
                dispose_completion: None,
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

        loop {
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
                continue;
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
    }

    /// Publishes `value` to current subscribers unless the stream is disposed.
    pub fn send(&self, value: T) {
        let current = thread::current().id();
        let (completion, should_drain, reentrant) = {
            let mut state = lock(&self.inner);
            if state.disposed || state.dispose_requested {
                return;
            }
            state.current = value.clone();
            state.revision = state.revision.wrapping_add(1);
            let subscribers = state
                .subscribers
                .values()
                .map(|subscriber| subscriber.value.clone())
                .collect();
            let completion = Arc::new(DeliveryCompletion::default());
            state.pending.push_back(PendingValue {
                value,
                subscribers,
                completion: completion.clone(),
            });
            let reentrant = state.draining_owner == Some(current);
            let should_drain = state.draining_owner.is_none();
            if should_drain {
                state.draining_owner = Some(current);
            }
            (completion, should_drain, reentrant)
        };
        if should_drain {
            self.drain(current);
        } else if !reentrant {
            completion.wait();
        }
    }

    fn drain(&self, current: ThreadId) {
        loop {
            let next = {
                let mut state = lock(&self.inner);
                debug_assert_eq!(state.draining_owner, Some(current));
                if let Some(value) = state.pending.pop_front() {
                    PendingDelivery::Value(value)
                } else if let Some(terminal) = state.pending_terminal.take() {
                    PendingDelivery::Terminal(terminal)
                } else {
                    state.draining_owner = None;
                    PendingDelivery::Done
                }
            };
            match next {
                PendingDelivery::Value(next) => {
                    for subscriber in next.subscribers {
                        let value = next.value.clone();
                        let _ = catch_unwind(AssertUnwindSafe(|| subscriber(value)));
                    }
                    next.completion.finish();
                }
                PendingDelivery::Terminal(terminal) => {
                    Self::notify_completions(terminal.completions);

                    let completion = {
                        let mut state = lock(&self.inner);
                        state.disposed = true;
                        state.dispose_requested = false;
                        state.draining_owner = None;
                        state.dispose_completion.clone()
                    };
                    completion
                        .expect("accepted terminal has a completion")
                        .finish();
                    return;
                }
                PendingDelivery::Done => {
                    return;
                }
            }
        }
    }

    /// Completes the stream once and makes later sends inert.
    pub fn dispose(&self) {
        let current = thread::current().id();
        let (completion, should_drain, reentrant) = {
            let mut state = lock(&self.inner);
            if state.disposed {
                let completion = state.dispose_completion.clone();
                drop(state);
                if let Some(completion) = completion {
                    completion.wait();
                }
                return;
            }
            if state.dispose_requested {
                let completion = state
                    .dispose_completion
                    .clone()
                    .expect("requested disposal has a completion");
                let reentrant = state.draining_owner == Some(current);
                drop(state);
                if !reentrant {
                    completion.wait();
                }
                return;
            }
            let completions = std::mem::take(&mut state.subscribers)
                .into_values()
                .filter_map(|subscriber| subscriber.completion)
                .collect();
            let completion = Arc::new(DeliveryCompletion::default());
            state.pending_terminal = Some(PendingTerminal { completions });
            state.dispose_requested = true;
            state.dispose_completion = Some(completion.clone());
            let reentrant = state.draining_owner == Some(current);
            let should_drain = state.draining_owner.is_none();
            if should_drain {
                state.draining_owner = Some(current);
            }
            (completion, should_drain, reentrant)
        };
        if should_drain {
            self.drain(current);
        } else if !reentrant {
            completion.wait();
        }
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
