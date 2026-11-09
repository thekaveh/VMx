//! VMx-owned typed value streams.

use crate::runtime::wait_for_owner;
use crate::wait_for_graph::{waits, Resource};
use crate::{
    lock, thread, wait, Arc, AssertUnwindSafe, AtomicBool, BTreeMap, Condvar, Mutex, Ordering,
    ThreadId, VecDeque, Weak,
};
use std::cell::Cell;
use std::panic::catch_unwind;

thread_local! {
    static VALUE_STREAM_DRAIN_DEPTH: Cell<usize> = const { Cell::new(0) };
}

struct ValueStreamDrainContext;

impl ValueStreamDrainContext {
    fn enter() -> Self {
        VALUE_STREAM_DRAIN_DEPTH.with(|depth| depth.set(depth.get() + 1));
        Self
    }

    fn is_active() -> bool {
        VALUE_STREAM_DRAIN_DEPTH.with(|depth| depth.get() > 0)
    }
}

impl Drop for ValueStreamDrainContext {
    fn drop(&mut self) {
        VALUE_STREAM_DRAIN_DEPTH.with(|depth| depth.set(depth.get() - 1));
    }
}

type ValueSubscriber<T> = Arc<dyn Fn(T) + Send + Sync + 'static>;
type ValueCompletion = Arc<dyn Fn() + Send + Sync + 'static>;

struct ValueStreamSubscriber<T> {
    value: ValueSubscriber<T>,
    completion: Option<ValueCompletion>,
}

#[derive(Default)]
struct DeliveryState {
    finished: bool,
    /// Counts the threads that wait with an edge in the wait-for graph.
    waiters: usize,
}

/// The delivery of one accepted value or terminal.
#[derive(Default)]
struct DeliveryCompletion {
    state: Mutex<DeliveryState>,
    ready: Condvar,
}

impl DeliveryCompletion {
    fn resource(&self) -> Resource {
        Resource::StreamDelivery(std::ptr::from_ref(self) as usize)
    }

    /// Waits until the delivery finishes. With `owner`, the thread that
    /// drains the stream, the wait is recorded in the wait-for graph
    /// (spec/03 §4.1, #1298). A wait that would close a cycle is refused:
    /// it returns at once, and the drainer still delivers the value later.
    fn wait(&self, owner: Option<ThreadId>) {
        let mut state = lock(&self.state);
        while !state.finished {
            let Some(owner) = owner else {
                state = wait(&self.ready, state);
                continue;
            };
            let refused;
            (state, refused) = wait_for_owner(
                &self.state,
                &self.ready,
                state,
                |state| &mut state.waiters,
                self.resource(),
                owner,
            );
            if refused {
                return;
            }
        }
    }

    /// Marks the delivery finished. The drainer removes the waits on this
    /// delivery from the graph before it wakes the waiters.
    fn finish(&self) {
        let mut state = lock(&self.state);
        state.finished = true;
        if state.waiters > 0 {
            waits().release_waiters(self.resource(), &[]);
        }
        drop(state);
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

/// A typed, synchronous stream owned by VMx.
///
/// A stream made with [`new`](Self::new) replays the current value to each new
/// subscriber. A stream made with [`hot`](Self::hot) does not: a subscriber
/// receives only later sends. Calls to [`send`](Self::send) synchronously
/// publish the replacement value, and [`dispose`](Self::dispose) completes
/// current and future subscriptions. Subscriber panics are isolated from
/// publishers and other subscribers.
///
/// ```
/// use std::sync::{Arc, Mutex};
/// use vmx::ValueStream;
///
/// let replaying = ValueStream::new(1);
/// let seen = Arc::new(Mutex::new(Vec::new()));
/// let sink = seen.clone();
/// let _replayed = replaying.subscribe(move |value| sink.lock().unwrap().push(value));
/// replaying.send(2);
/// assert_eq!(*seen.lock().unwrap(), vec![1, 2]);
///
/// let hot = ValueStream::hot(1);
/// let seen = Arc::new(Mutex::new(Vec::new()));
/// let sink = seen.clone();
/// let _live = hot.subscribe(move |value| sink.lock().unwrap().push(value));
/// hot.send(2);
/// assert_eq!(*seen.lock().unwrap(), vec![2]);
/// ```
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

    #[cfg(test)]
    pub(crate) fn active_subscription_count(&self) -> usize {
        lock(&self.inner).subscribers.len()
    }

    /// Subscribes to later values. A replaying stream ([`ValueStream::new`])
    /// first delivers its current value; a [`ValueStream::hot`] stream does not.
    pub fn subscribe<F>(&self, handler: F) -> ValueSubscription
    where
        F: Fn(T) + Send + Sync + 'static,
    {
        self.subscribe_internal(Arc::new(handler), None)
    }

    /// Subscribes to values and receives one callback when the stream completes.
    ///
    /// A subscription made after disposal receives `completion` at once. A
    /// replaying stream delivers its retained current value first; a
    /// [`ValueStream::hot`] stream does not.
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
    ///
    /// When another thread is draining the stream, `send` queues `value` and
    /// waits for that thread to deliver it. If the wait would close a wait-for
    /// cycle, `send` returns at once, and `value` stays queued in order for
    /// the draining thread (spec/03 §4.1, ADR-0209).
    pub fn send(&self, value: T) {
        self.send_if(value, || true);
    }

    /// Publishes `value` like [`send`](Self::send) if `still_current` holds.
    /// `still_current` runs under the stream lock, so publications that pass
    /// it are delivered in the order they passed it.
    pub(crate) fn send_if(&self, value: T, still_current: impl FnOnce() -> bool) {
        let current = thread::current().id();
        let (completion, should_drain, drainer, replaced) = {
            let mut state = lock(&self.inner);
            if state.disposed || state.dispose_requested || !still_current() {
                return;
            }
            let replaced = std::mem::replace(&mut state.current, value.clone());
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
            let drainer = state.draining_owner;
            let should_drain = drainer.is_none();
            if should_drain {
                state.draining_owner = Some(current);
            }
            (completion, should_drain, drainer, replaced)
        };
        // The replaced value is dropped after the stream lock is released.
        drop(replaced);
        if should_drain {
            self.drain(current);
        } else if drainer != Some(current) && !ValueStreamDrainContext::is_active() {
            completion.wait(drainer);
        }
    }

    fn drain(&self, current: ThreadId) {
        let _drain_context = ValueStreamDrainContext::enter();
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
    ///
    /// When another thread is draining the stream, `dispose` queues the
    /// completion after the queued values and waits for that thread to
    /// deliver it. If the wait would close a wait-for cycle, `dispose` returns
    /// at once, and the completion stays queued for the draining thread
    /// (spec/03 §4.1, ADR-0209).
    pub fn dispose(&self) {
        let current = thread::current().id();
        // Subscriber closures may own other subscriptions on this stream;
        // they are dropped after the state lock is released.
        let mut released = Vec::new();
        let (completion, should_drain, drainer) = {
            let mut state = lock(&self.inner);
            if state.disposed {
                // The drainer marks the stream disposed just before it
                // finishes the terminal, and runs no user code in between.
                let completion = state.dispose_completion.clone();
                drop(state);
                if let Some(completion) = completion {
                    completion.wait(None);
                }
                return;
            }
            if state.dispose_requested {
                let completion = state
                    .dispose_completion
                    .clone()
                    .expect("requested disposal has a completion");
                let drainer = state.draining_owner;
                drop(state);
                if drainer != Some(current) && !ValueStreamDrainContext::is_active() {
                    completion.wait(drainer);
                }
                return;
            }
            let mut completions = Vec::new();
            for subscriber in std::mem::take(&mut state.subscribers).into_values() {
                completions.extend(subscriber.completion.clone());
                released.push(subscriber);
            }
            let completion = Arc::new(DeliveryCompletion::default());
            state.pending_terminal = Some(PendingTerminal { completions });
            state.dispose_requested = true;
            state.dispose_completion = Some(completion.clone());
            let drainer = state.draining_owner;
            let should_drain = drainer.is_none();
            if should_drain {
                state.draining_owner = Some(current);
            }
            (completion, should_drain, drainer)
        };
        drop(released);
        if should_drain {
            self.drain(current);
        } else if drainer != Some(current) && !ValueStreamDrainContext::is_active() {
            completion.wait(drainer);
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
                    // Drop the removed closures after releasing the lock: they
                    // may own other subscriptions on this stream.
                    let removed = lock(&stream).subscribers.remove(&id);
                    drop(removed);
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
