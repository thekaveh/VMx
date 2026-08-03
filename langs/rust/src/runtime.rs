//! Core errors, messages, lifecycle, dispatch, and tree ownership contracts.
//!
//! Spec: `spec/02-lifecycle.md`, `spec/03-messages.md`, and `spec/11-threading.md`.

use super::{
    catch_unwind, resume_unwind, thread, Arc, AssertUnwindSafe, AtomicBool, AtomicUsize, BTreeMap,
    Cell, Condvar, Deserialize, HashMap, HashSet, Mutex, MutexGuard, OnceLock, Ordering, Serialize,
    ThreadId, VecDeque, Weak,
};
use crate::{ValueStream, ValueSubscription};
use std::sync::mpsc;

static NEXT_ID: AtomicUsize = AtomicUsize::new(1);
pub(crate) static HIERARCHY_TOPOLOGY_GATE: Mutex<()> = Mutex::new(());

thread_local! {
    static MESSAGE_HUB_DELIVERY_DEPTH: Cell<usize> = const { Cell::new(0) };
    static MESSAGE_HUB_DELIVERY_SENDERS: std::cell::RefCell<Vec<(usize, usize)>> = const { std::cell::RefCell::new(Vec::new()) };
}

struct MessageHubDeliveryGuard;

impl MessageHubDeliveryGuard {
    fn enter(hub_id: usize, sender_id: usize) -> Self {
        MESSAGE_HUB_DELIVERY_DEPTH.with(|depth| depth.set(depth.get() + 1));
        MESSAGE_HUB_DELIVERY_SENDERS.with(|senders| {
            senders.borrow_mut().push((hub_id, sender_id));
        });
        Self
    }
}

impl Drop for MessageHubDeliveryGuard {
    fn drop(&mut self) {
        MESSAGE_HUB_DELIVERY_SENDERS.with(|senders| {
            senders.borrow_mut().pop();
        });
        MESSAGE_HUB_DELIVERY_DEPTH.with(|depth| depth.set(depth.get() - 1));
    }
}

fn is_delivering_message_hub() -> bool {
    MESSAGE_HUB_DELIVERY_DEPTH.with(|depth| depth.get() > 0)
}

fn wait_for_message_hub_owner<'a, T>(
    condition: &Condvar,
    guard: MutexGuard<'a, T>,
    current: ThreadId,
    owner: ThreadId,
) -> (MutexGuard<'a, T>, bool) {
    static WAITS: OnceLock<Mutex<HashMap<ThreadId, ThreadId>>> = OnceLock::new();
    let waits = WAITS.get_or_init(|| Mutex::new(HashMap::new()));
    {
        let mut graph = lock(waits);
        graph.insert(current, owner);
        let mut cursor = owner;
        let mut visited = HashSet::new();
        while let Some(next) = graph.get(&cursor).copied() {
            if next == current {
                graph.remove(&current);
                return (guard, true);
            }
            if !visited.insert(cursor) {
                break;
            }
            cursor = next;
        }
    }
    let guard = wait(condition, guard);
    lock(waits).remove(&current);
    (guard, false)
}

pub(crate) fn next_id() -> usize {
    NEXT_ID.fetch_add(1, Ordering::Relaxed)
}

pub(crate) fn lock<T: ?Sized>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

pub(crate) fn wait<'a, T>(condition: &Condvar, guard: MutexGuard<'a, T>) -> MutexGuard<'a, T> {
    condition
        .wait(guard)
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

pub(crate) fn evaluate_command_predicate(predicate: impl FnOnce() -> bool) -> bool {
    catch_unwind(AssertUnwindSafe(predicate)).unwrap_or(false)
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
/// Errors produced by VMx lifecycle, ownership, validation, and service contracts.
pub enum VmxError {
    #[error("invalid lifecycle transition from {from:?} via {operation}")]
    /// A lifecycle operation is invalid for the current status.
    InvalidLifecycleTransition {
        /// Status from which the operation was attempted.
        from: ConstructionStatus,
        /// Stable operation name used in the diagnostic.
        operation: &'static str,
    },
    #[error("viewmodel is disposed")]
    /// The target view model has already been disposed.
    Disposed,
    #[error("operation already in progress")]
    /// Another lifecycle operation is already in progress.
    ConcurrentOperation,
    #[error("component is not a child of this container")]
    /// The supplied component is not a child of the container.
    NonChild,
    #[error("component is already a child of this container")]
    /// The component is already a child of the destination container.
    DuplicateChild,
    #[error("container ownership would create an ancestor cycle")]
    /// The requested parent assignment would create a cycle.
    OwnershipCycle,
    #[error("component parent state does not match parent membership")]
    /// Parent metadata and parent membership disagree.
    InconsistentParent,
    #[error("component ownership transaction is already in progress")]
    /// A hook attempted to mutate a container before its active membership transaction committed.
    OwnershipTransactionInProgress,
    #[error("component is not current")]
    /// The supplied component is not the current child.
    NotCurrent,
    #[error("builder validation failed: {0}")]
    /// A builder is missing or rejects required configuration.
    BuilderValidation(String),
    #[error("readonly model cannot be changed")]
    /// An operation attempted to replace a read-only model.
    ReadonlyModel,
    #[error("dialog already active")]
    /// A dialog operation was attempted while another is active.
    DialogReentrancy,
    #[error("operation cancelled")]
    /// A cancellable operation observed cancellation.
    Cancelled,
    #[error("invalid argument: {0}")]
    /// An argument violates the operation's contract.
    InvalidArgument(String),
    #[error("{0}")]
    /// An application-defined error message.
    Other(String),
}

/// Result type used by fallible VMx operations.
pub type VmxResult<T> = Result<T, VmxError>;

pub(crate) fn retain_first_error(first: &mut Option<VmxError>, result: VmxResult<()>) {
    if let Err(error) = result {
        if first.is_none() {
            *first = Some(error);
        }
    }
}

pub(crate) fn finish_with_first_error(first: Option<VmxError>) -> VmxResult<()> {
    first.map_or(Ok(()), Err)
}

pub(crate) enum FirstFailure {
    Error(VmxError),
    Panic(Box<dyn std::any::Any + Send>),
}

pub(crate) fn retain_first_failure<F>(first: &mut Option<FirstFailure>, action: F)
where
    F: FnOnce() -> VmxResult<()>,
{
    let outcome = catch_unwind(AssertUnwindSafe(action));
    if first.is_some() {
        return;
    }
    match outcome {
        Ok(Ok(())) => {}
        Ok(Err(error)) => *first = Some(FirstFailure::Error(error)),
        Err(payload) => *first = Some(FirstFailure::Panic(payload)),
    }
}

pub(crate) fn finish_with_first_failure(first: Option<FirstFailure>) -> VmxResult<()> {
    match first {
        None => Ok(()),
        Some(FirstFailure::Error(error)) => Err(error),
        Some(FirstFailure::Panic(payload)) => resume_unwind(payload),
    }
}

pub(crate) struct MembershipTransactionGuard {
    active: Arc<AtomicBool>,
    control: Arc<MembershipTransactionControl>,
    release: bool,
}

pub(crate) enum MembershipDisposeDisposition {
    Inactive,
    Owned,
    Foreign,
}

struct MembershipTransactionState {
    owner: Option<ThreadId>,
    finishing_owner: Option<ThreadId>,
    deferred_dispose: Option<Box<dyn FnOnce() -> VmxResult<()> + Send>>,
}

pub(crate) struct MembershipTransactionControl {
    state: Mutex<MembershipTransactionState>,
    ready: Condvar,
}

impl MembershipTransactionControl {
    pub(crate) fn new() -> Self {
        Self {
            state: Mutex::new(MembershipTransactionState {
                owner: None,
                finishing_owner: None,
                deferred_dispose: None,
            }),
            ready: Condvar::new(),
        }
    }

    fn begin(&self) {
        let mut state = lock(&self.state);
        debug_assert!(state.owner.is_none());
        debug_assert!(state.finishing_owner.is_none());
        state.owner = Some(thread::current().id());
    }

    pub(crate) fn dispose_disposition(&self) -> MembershipDisposeDisposition {
        let current = thread::current().id();
        let state = lock(&self.state);
        match (state.owner, state.finishing_owner) {
            (Some(owner), _) if owner == current => MembershipDisposeDisposition::Owned,
            (Some(_), _) => MembershipDisposeDisposition::Foreign,
            (None, Some(owner)) if owner == current => MembershipDisposeDisposition::Inactive,
            (None, Some(_)) => MembershipDisposeDisposition::Foreign,
            (None, None) => MembershipDisposeDisposition::Inactive,
        }
    }

    pub(crate) fn defer_dispose(&self, action: impl FnOnce() -> VmxResult<()> + Send + 'static) {
        let mut state = lock(&self.state);
        if state.deferred_dispose.is_none() {
            state.deferred_dispose = Some(Box::new(action));
        }
    }

    pub(crate) fn has_deferred_dispose(&self) -> bool {
        lock(&self.state).deferred_dispose.is_some()
    }

    pub(crate) fn wait_until_inactive(&self) {
        let mut state = lock(&self.state);
        while state.owner.is_some() || state.finishing_owner.is_some() {
            state = wait(&self.ready, state);
        }
    }

    fn finish(&self, active: &AtomicBool) -> VmxResult<()> {
        let current = thread::current().id();
        let action = {
            let mut state = lock(&self.state);
            state.owner = None;
            state.finishing_owner = Some(current);
            state.deferred_dispose.take()
        };
        let outcome = action.map(|action| catch_unwind(AssertUnwindSafe(action)));
        active.store(false, Ordering::Release);
        let mut state = lock(&self.state);
        state.finishing_owner = None;
        self.ready.notify_all();
        drop(state);
        match outcome {
            Some(Ok(result)) => result,
            Some(Err(payload)) => resume_unwind(payload),
            None => Ok(()),
        }
    }
}

impl MembershipTransactionGuard {
    pub(crate) fn defer(mut self) {
        self.release = false;
    }

    pub(crate) fn release_on_drop(
        active: Arc<AtomicBool>,
        control: Arc<MembershipTransactionControl>,
    ) -> Self {
        Self {
            active,
            control,
            release: true,
        }
    }

    pub(crate) fn finish(mut self) -> VmxResult<()> {
        self.release = false;
        self.control.finish(&self.active)
    }
}

impl Drop for MembershipTransactionGuard {
    fn drop(&mut self) {
        if self.release {
            let _ = self.control.finish(&self.active);
        }
    }
}

pub(crate) fn begin_membership_transaction(
    active: &Arc<AtomicBool>,
    control: &Arc<MembershipTransactionControl>,
) -> VmxResult<MembershipTransactionGuard> {
    active
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| VmxError::OwnershipTransactionInProgress)?;
    control.begin();
    Ok(MembershipTransactionGuard {
        active: Arc::clone(active),
        control: Arc::clone(control),
        release: true,
    })
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
/// Lifecycle state of a VMx view model.
pub enum ConstructionStatus {
    #[default]
    /// The view model is inactive and may be constructed.
    Destructed,
    /// Construction is currently running.
    Constructing,
    /// The view model is active.
    Constructed,
    /// Destruction is currently running.
    Destructing,
    /// The view model is terminally disposed.
    Disposed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// Lifecycle operations supported by the shared component core.
pub enum LifecycleOperation {
    /// Activate a destructed view model.
    Construct,
    /// Deactivate a constructed view model.
    Destruct,
    /// Enter the terminal disposed state.
    Dispose,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Mutation kinds carried by collection-change messages.
pub enum CollectionChangeAction {
    /// An item was added.
    Add,
    /// An item was removed.
    Remove,
    /// An item was replaced.
    Replace,
    /// An item moved between indices.
    Move,
    /// The collection projection was reset.
    Reset,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Describes an observable collection mutation.
pub struct CollectionChangedMessage {
    /// Identity of the publishing owner.
    pub sender_id: usize,
    /// Human-readable identity of the publishing owner.
    pub sender_name: String,
    /// Logical collection property name.
    pub property_name: String,
    /// Kind of mutation.
    pub action: CollectionChangeAction,
    /// Previous index when relevant to the mutation.
    pub old_index: Option<usize>,
    /// New index when relevant to the mutation.
    pub new_index: Option<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Describes a named property change.
pub struct PropertyChangedMessage {
    /// Identity of the publishing owner.
    pub sender_id: usize,
    /// Human-readable identity of the publishing owner.
    pub sender_name: String,
    /// Flavor-idiomatic property name.
    pub property_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Describes a lifecycle-status change.
pub struct ConstructionStatusChangedMessage {
    /// Identity of the publishing view model.
    pub sender_id: usize,
    /// Human-readable identity of the publishing view model.
    pub sender_name: String,
    /// Newly observable lifecycle status.
    pub status: ConstructionStatus,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Kind of mutation described by [`TreeStructureChangedMessage`].
pub enum TreeStructureChange {
    /// A previously detached child was appended.
    Added,
    /// An existing child was removed.
    Removed,
    /// A child moved atomically from another parent.
    Reparented,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Announces a structural change in a view-model tree.
pub struct TreeStructureChangedMessage {
    /// Identity of the publishing tree node.
    pub sender_id: usize,
    /// Human-readable identity of the publishing tree node.
    pub sender_name: String,
    /// Kind of structural mutation.
    pub change: TreeStructureChange,
    /// Identity of the child that was added, removed, or reparented.
    pub affected_id: usize,
    /// Child index for add/remove, or `-1` when reparenting.
    pub index: isize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Announces that a form reverted to its saved snapshot.
pub struct FormRevertedMessage {
    /// Identity of the publishing form.
    pub sender_id: usize,
    /// Human-readable identity of the publishing form.
    pub sender_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Language-neutral messages published through [`MessageHub`].
pub enum Message {
    /// A named property changed.
    PropertyChanged(PropertyChangedMessage),
    /// A lifecycle status changed.
    ConstructionStatusChanged(ConstructionStatusChangedMessage),
    /// A collection membership or order changed.
    CollectionChanged(CollectionChangedMessage),
    /// A tree's structure changed.
    TreeStructureChanged(TreeStructureChangedMessage),
    /// A form reverted its model.
    FormReverted(FormRevertedMessage),
    /// An application-defined named message.
    Custom {
        /// Identity of the publishing owner.
        sender_id: usize,
        /// Human-readable identity of the publishing owner.
        sender_name: String,
        /// Application-defined message name.
        name: String,
    },
}

impl Message {
    /// Returns the identity of the message sender.
    pub fn sender_id(&self) -> usize {
        match self {
            Self::PropertyChanged(message) => message.sender_id,
            Self::ConstructionStatusChanged(message) => message.sender_id,
            Self::CollectionChanged(message) => message.sender_id,
            Self::TreeStructureChanged(message) => message.sender_id,
            Self::FormReverted(message) => message.sender_id,
            Self::Custom { sender_id, .. } => *sender_id,
        }
    }

    /// Returns the human-readable identity of the message sender.
    pub fn sender_name(&self) -> &str {
        match self {
            Self::PropertyChanged(message) => &message.sender_name,
            Self::ConstructionStatusChanged(message) => &message.sender_name,
            Self::CollectionChanged(message) => &message.sender_name,
            Self::TreeStructureChanged(message) => &message.sender_name,
            Self::FormReverted(message) => &message.sender_name,
            Self::Custom { sender_name, .. } => sender_name,
        }
    }

    #[cfg(debug_assertions)]
    fn type_name(&self) -> &'static str {
        match self {
            Self::PropertyChanged(_) => "PropertyChangedMessage",
            Self::ConstructionStatusChanged(_) => "ConstructionStatusChangedMessage",
            Self::CollectionChanged(_) => "CollectionChangedMessage",
            Self::TreeStructureChanged(_) => "TreeStructureChangedMessage",
            Self::FormReverted(_) => "FormRevertedMessage",
            Self::Custom { .. } => "CustomMessage",
        }
    }
}

type Subscriber = Arc<dyn Fn(&Message) + Send + Sync + 'static>;
type MessageHubCompletion = Arc<dyn Fn() + Send + Sync + 'static>;

#[derive(Clone, Default)]
/// A hot synchronous message stream with FIFO, batching, and resilient delivery.
///
/// Sends update history before delivery. Re-entrant sends join the active FIFO
/// drain, subscriber panics are isolated, and disposal makes the hub inert.
pub struct MessageHub {
    inner: Arc<MessageHubShared>,
}

#[derive(Default)]
struct MessageHubShared {
    state: Mutex<MessageHubInner>,
    ready: Condvar,
}

#[derive(Default)]
struct MessageHubInner {
    next_subscription_id: usize,
    subscribers: BTreeMap<usize, Subscriber>,
    completion_subscribers: BTreeMap<usize, MessageHubCompletion>,
    history: Vec<Message>,
    pending: VecDeque<Message>,
    batch_owner: Option<ThreadId>,
    batch_depth: usize,
    borrowed_batch_depth: usize,
    draining_owner: Option<ThreadId>,
    dispose_requested: bool,
    disposed: bool,
}

type ValueEquality<T> = Arc<dyn Fn(&T, &T) -> bool + Send + Sync>;

/// Options for projecting property messages into distinct typed values.
pub struct SubscribeValueOptions<T> {
    /// Whether subscription immediately reports the initial value pair.
    pub fire_immediately: bool,
    equality: ValueEquality<T>,
}

impl<T: PartialEq> Default for SubscribeValueOptions<T> {
    fn default() -> Self {
        Self::with_equality(|current, next| current == next)
    }
}

impl<T> SubscribeValueOptions<T> {
    /// Creates options with a caller-supplied equality comparison.
    pub fn with_equality<F>(equality: F) -> Self
    where
        F: Fn(&T, &T) -> bool + Send + Sync + 'static,
    {
        Self {
            fire_immediately: false,
            equality: Arc::new(equality),
        }
    }

    /// Configures immediate initial callback delivery.
    pub fn fire_immediately(mut self, value: bool) -> Self {
        self.fire_immediately = value;
        self
    }
}

impl MessageHub {
    /// Creates an active hub with no subscribers or history.
    pub fn new() -> Self {
        Self::default()
    }

    pub(crate) fn is_delivering_from(&self, sender_id: usize) -> bool {
        let hub_id = Arc::as_ptr(&self.inner) as usize;
        MESSAGE_HUB_DELIVERY_SENDERS.with(|senders| senders.borrow().contains(&(hub_id, sender_id)))
    }

    /// Subscribes to messages published after this call.
    pub fn subscribe<F>(&self, handler: F) -> Subscription
    where
        F: Fn(&Message) + Send + Sync + 'static,
    {
        let mut inner = lock(&self.inner.state);
        if inner.disposed || inner.dispose_requested {
            return Subscription::noop();
        }
        inner.next_subscription_id += 1;
        let id = inner.next_subscription_id;
        inner.subscribers.insert(id, Arc::new(handler));
        Subscription {
            id,
            hub: Arc::downgrade(&self.inner),
        }
    }

    /// Subscribes to messages and receives one callback when the hub is disposed.
    ///
    /// Subscribing to an already-disposed hub invokes `completion` immediately
    /// and never invokes `handler`.
    pub fn subscribe_with_completion<F, C>(&self, handler: F, completion: C) -> Subscription
    where
        F: Fn(&Message) + Send + Sync + 'static,
        C: Fn() + Send + Sync + 'static,
    {
        let completion: MessageHubCompletion = Arc::new(completion);
        let mut inner = lock(&self.inner.state);
        if inner.disposed || inner.dispose_requested {
            drop(inner);
            let _ = catch_unwind(AssertUnwindSafe(|| completion()));
            return Subscription::noop();
        }
        inner.next_subscription_id += 1;
        let id = inner.next_subscription_id;
        inner.subscribers.insert(id, Arc::new(handler));
        inner.completion_subscribers.insert(id, completion);
        Subscription {
            id,
            hub: Arc::downgrade(&self.inner),
        }
    }

    /// Observes distinct selector values after property changes from `sender_id`.
    pub fn subscribe_value<T, S, C>(
        &self,
        sender_id: usize,
        selector: S,
        callback: C,
        options: SubscribeValueOptions<T>,
    ) -> Subscription
    where
        T: Clone + Send + 'static,
        S: Fn() -> T + Send + Sync + 'static,
        C: Fn(T, T) + Send + Sync + 'static,
    {
        let initial = selector();
        if options.fire_immediately {
            callback(initial.clone(), initial.clone());
        }

        let current = Arc::new(Mutex::new(initial));
        let equality = options.equality;
        self.subscribe(move |message| {
            if !matches!(message, Message::PropertyChanged(change) if change.sender_id == sender_id)
            {
                return;
            }

            let next = selector();
            let previous = {
                let mut current = lock(&current);
                if equality(&current, &next) {
                    return;
                }
                let previous = current.clone();
                *current = next.clone();
                previous
            };
            callback(next, previous);
        })
    }

    /// Publishes `message` synchronously in FIFO order.
    pub fn send(&self, message: Message) {
        let current = thread::current().id();
        let mut inner = lock(&self.inner.state);
        loop {
            let owner = inner
                .batch_owner
                .filter(|owner| *owner != current)
                .or_else(|| inner.draining_owner.filter(|owner| *owner != current));
            if let Some(owner) = owner {
                let (next, cycle) =
                    wait_for_message_hub_owner(&self.inner.ready, inner, current, owner);
                inner = next;
                if cycle {
                    break;
                }
                continue;
            }
            if inner.borrowed_batch_depth > 0 {
                if is_delivering_message_hub() {
                    break;
                }
                inner = wait(&self.inner.ready, inner);
                continue;
            }
            break;
        }
        if inner.disposed || inner.dispose_requested {
            return;
        }
        inner.history.push(message.clone());
        inner.pending.push_back(message);
        if inner.batch_owner.is_some()
            || inner.borrowed_batch_depth > 0
            || inner.draining_owner.is_some()
        {
            return;
        }
        inner.draining_owner = Some(current);
        drop(inner);
        self.drain(current);
    }

    pub(crate) fn send_prepared<R, F>(&self, prepare: F) -> R
    where
        F: FnOnce() -> (R, Option<Message>),
    {
        let current = thread::current().id();
        let mut inner = lock(&self.inner.state);
        loop {
            let owner = inner
                .batch_owner
                .filter(|owner| *owner != current)
                .or_else(|| inner.draining_owner.filter(|owner| *owner != current));
            if let Some(owner) = owner {
                let (next, cycle) =
                    wait_for_message_hub_owner(&self.inner.ready, inner, current, owner);
                inner = next;
                if cycle {
                    break;
                }
                continue;
            }
            if inner.borrowed_batch_depth > 0 {
                if is_delivering_message_hub() {
                    break;
                }
                inner = wait(&self.inner.ready, inner);
                continue;
            }
            break;
        }

        let (result, message) = prepare();
        if let Some(message) = message.filter(|_| !inner.disposed && !inner.dispose_requested) {
            inner.history.push(message.clone());
            inner.pending.push_back(message);
        }
        let should_drain = !inner.pending.is_empty()
            && inner.batch_owner.is_none()
            && inner.borrowed_batch_depth == 0
            && inner.draining_owner.is_none();
        if should_drain {
            inner.draining_owner = Some(current);
        }
        drop(inner);
        if should_drain {
            self.drain(current);
        }
        result
    }

    /// Defers delivery during `transaction`, then drains queued messages in FIFO order.
    pub fn batch<F, R>(&self, transaction: F) -> R
    where
        F: FnOnce() -> R,
    {
        let current = thread::current().id();
        let mut inner = lock(&self.inner.state);
        let borrowed = loop {
            let owner = inner
                .batch_owner
                .filter(|owner| *owner != current)
                .or_else(|| inner.draining_owner.filter(|owner| *owner != current));
            if let Some(owner) = owner {
                let (next, cycle) =
                    wait_for_message_hub_owner(&self.inner.ready, inner, current, owner);
                inner = next;
                if cycle {
                    inner.borrowed_batch_depth += 1;
                    break true;
                }
                continue;
            }
            if inner.borrowed_batch_depth > 0 && inner.batch_owner != Some(current) {
                inner = wait(&self.inner.ready, inner);
                continue;
            }
            break false;
        };
        if !borrowed {
            if inner.batch_owner == Some(current) {
                inner.batch_depth += 1;
            } else {
                inner.batch_owner = Some(current);
                inner.batch_depth = 1;
            }
        }
        drop(inner);

        let callback_result = catch_unwind(AssertUnwindSafe(transaction));
        let mut inner = lock(&self.inner.state);
        let outermost = if borrowed {
            inner.borrowed_batch_depth -= 1;
            inner.borrowed_batch_depth == 0
        } else {
            inner.batch_depth -= 1;
            let outermost = inner.batch_depth == 0;
            if outermost {
                inner.batch_owner = None;
            }
            outermost
        };
        let completions = if outermost && inner.dispose_requested {
            Self::finish_dispose(&mut inner)
        } else {
            Vec::new()
        };
        let should_drain = outermost
            && !inner.disposed
            && !inner.pending.is_empty()
            && inner.batch_owner.is_none()
            && inner.borrowed_batch_depth == 0
            && inner.draining_owner.is_none();
        if should_drain {
            inner.draining_owner = Some(current);
        }
        if outermost {
            self.inner.ready.notify_all();
        }
        drop(inner);
        Self::notify_completions(completions);

        let drain_result = if should_drain {
            catch_unwind(AssertUnwindSafe(|| self.drain(current)))
        } else {
            Ok(())
        };

        match callback_result {
            Ok(value) => {
                if let Err(error) = drain_result {
                    std::panic::resume_unwind(error);
                }
                value
            }
            Err(error) => std::panic::resume_unwind(error),
        }
    }

    fn finish_dispose(inner: &mut MessageHubInner) -> Vec<MessageHubCompletion> {
        inner.subscribers.clear();
        inner.pending.clear();
        inner.dispose_requested = false;
        inner.disposed = true;
        std::mem::take(&mut inner.completion_subscribers)
            .into_values()
            .collect()
    }

    fn notify_completions(completions: Vec<MessageHubCompletion>) {
        for completion in completions {
            let _ = catch_unwind(AssertUnwindSafe(|| completion()));
        }
    }

    fn drain(&self, current: ThreadId) {
        #[cfg(debug_assertions)]
        let mut delivered = 0usize;
        #[cfg(debug_assertions)]
        let mut message_types = HashSet::new();

        loop {
            let mut inner = lock(&self.inner.state);
            while inner.borrowed_batch_depth > 0 {
                inner = wait(&self.inner.ready, inner);
            }
            let completions = if inner.dispose_requested {
                Self::finish_dispose(&mut inner)
            } else {
                Vec::new()
            };
            if inner.disposed || inner.pending.is_empty() {
                inner.draining_owner = None;
                self.inner.ready.notify_all();
                drop(inner);
                Self::notify_completions(completions);
                return;
            }
            debug_assert_eq!(inner.draining_owner, Some(current));
            let message = inner.pending.pop_front().expect("queue checked non-empty");
            let subscribers = inner.subscribers.values().cloned().collect::<Vec<_>>();
            drop(inner);
            Self::notify_completions(completions);

            #[cfg(debug_assertions)]
            message_types.insert(message.type_name());
            for subscriber in subscribers {
                let _delivery = MessageHubDeliveryGuard::enter(
                    Arc::as_ptr(&self.inner) as usize,
                    message.sender_id(),
                );
                let _ = catch_unwind(AssertUnwindSafe(|| subscriber(&message)));
            }

            #[cfg(debug_assertions)]
            {
                delivered += 1;
                if delivered >= 10_000 {
                    let mut inner = lock(&self.inner.state);
                    if !inner.pending.is_empty() {
                        message_types.extend(inner.pending.iter().map(Message::type_name));
                        inner.pending.clear();
                        inner.draining_owner = None;
                        self.inner.ready.notify_all();
                        let names = {
                            let mut names = message_types.iter().copied().collect::<Vec<_>>();
                            names.sort_unstable();
                            names.join(", ")
                        };
                        drop(inner);
                        panic!(
                            "MessageHub drain exceeded 10000 messages; possible publish cycle involving: {names}"
                        );
                    }
                }
            }
        }
    }

    /// Returns a snapshot of every accepted message.
    pub fn history(&self) -> Vec<Message> {
        lock(&self.inner.state).history.clone()
    }

    /// Removes subscribers and pending messages and makes future sends inert.
    pub fn dispose(&self) {
        let current = thread::current().id();
        let mut inner = lock(&self.inner.state);
        if inner.draining_owner == Some(current) {
            inner.dispose_requested = true;
            self.inner.ready.notify_all();
            return;
        }
        loop {
            let owner = inner
                .batch_owner
                .filter(|owner| *owner != current)
                .or_else(|| inner.draining_owner.filter(|owner| *owner != current));
            if let Some(owner) = owner {
                let (next, cycle) =
                    wait_for_message_hub_owner(&self.inner.ready, inner, current, owner);
                inner = next;
                if cycle {
                    inner.dispose_requested = true;
                    self.inner.ready.notify_all();
                    return;
                }
                continue;
            }
            if inner.borrowed_batch_depth > 0 {
                inner = wait(&self.inner.ready, inner);
                continue;
            }
            break;
        }
        let completions = Self::finish_dispose(&mut inner);
        self.inner.ready.notify_all();
        drop(inner);
        Self::notify_completions(completions);
    }
}

#[derive(Clone)]
/// Factory for inert message hubs used by null-object services.
pub struct NullMessageHub;

impl NullMessageHub {
    /// Creates an already-disposed no-op hub.
    pub fn hub() -> MessageHub {
        MessageHub::new_noop()
    }
}

impl MessageHub {
    fn new_noop() -> Self {
        let hub = Self::new();
        hub.dispose();
        hub
    }
}

/// Disposable registration in a [`MessageHub`].
pub struct Subscription {
    id: usize,
    hub: Weak<MessageHubShared>,
}

impl Subscription {
    fn noop() -> Self {
        Self {
            id: 0,
            hub: Weak::new(),
        }
    }

    /// Detaches the subscriber; repeated calls are inert.
    pub fn dispose(&self) {
        if let Some(hub) = self.hub.upgrade() {
            let mut state = lock(&hub.state);
            state.subscribers.remove(&self.id);
            state.completion_subscribers.remove(&self.id);
        }
    }
}

impl Drop for Subscription {
    fn drop(&mut self) {
        self.dispose();
    }
}

type PropertyChangedSubscriber = Arc<dyn Fn(&str) + Send + Sync + 'static>;
type PropertyChangedCompletion = Arc<dyn Fn() + Send + Sync + 'static>;

/// Hot, per-viewmodel property-name stream used by local binding adapters.
#[derive(Clone, Default)]
pub struct PropertyChangedStream {
    inner: Arc<Mutex<PropertyChangedStreamInner>>,
}

#[derive(Default)]
struct PropertyChangedStreamInner {
    next_subscription_id: usize,
    subscribers: BTreeMap<usize, PropertyChangedSubscriber>,
    completion_subscribers: BTreeMap<usize, PropertyChangedCompletion>,
    disposed: bool,
    active_notifications: usize,
    teardown_pending: bool,
}

impl PropertyChangedStream {
    /// Subscribes to property names published after this call.
    pub fn subscribe<F>(&self, handler: F) -> PropertyChangedSubscription
    where
        F: Fn(&str) + Send + Sync + 'static,
    {
        let mut inner = lock(&self.inner);
        if inner.disposed {
            return PropertyChangedSubscription::noop();
        }
        inner.next_subscription_id += 1;
        let id = inner.next_subscription_id;
        inner.subscribers.insert(id, Arc::new(handler));
        PropertyChangedSubscription {
            id,
            stream: Arc::downgrade(&self.inner),
        }
    }

    pub(crate) fn subscribe_with_completion<F, C>(
        &self,
        handler: F,
        completion: C,
    ) -> PropertyChangedSubscription
    where
        F: Fn(&str) + Send + Sync + 'static,
        C: Fn() + Send + Sync + 'static,
    {
        let completion: PropertyChangedCompletion = Arc::new(completion);
        let mut inner = lock(&self.inner);
        if inner.disposed {
            drop(inner);
            completion();
            return PropertyChangedSubscription::noop();
        }
        inner.next_subscription_id += 1;
        let id = inner.next_subscription_id;
        inner.subscribers.insert(id, Arc::new(handler));
        inner.completion_subscribers.insert(id, completion);
        PropertyChangedSubscription {
            id,
            stream: Arc::downgrade(&self.inner),
        }
    }

    fn begin_notification(&self) -> bool {
        let mut inner = lock(&self.inner);
        if inner.disposed {
            return false;
        }
        inner.active_notifications += 1;
        true
    }

    fn send_admitted(&self, property_name: &str) {
        let subscribers = lock(&self.inner)
            .subscribers
            .values()
            .cloned()
            .collect::<Vec<_>>();
        for subscriber in subscribers {
            let _ = catch_unwind(AssertUnwindSafe(|| subscriber(property_name)));
        }
    }

    fn end_notification(&self) {
        let mut inner = lock(&self.inner);
        inner.active_notifications -= 1;
        if inner.active_notifications == 0 && inner.teardown_pending {
            inner.teardown_pending = false;
            inner.subscribers.clear();
        }
    }

    fn dispose(&self) {
        let completions = {
            let mut inner = lock(&self.inner);
            if inner.disposed {
                return;
            }
            inner.disposed = true;
            let completions = std::mem::take(&mut inner.completion_subscribers)
                .into_values()
                .collect::<Vec<_>>();
            if inner.active_notifications == 0 {
                inner.subscribers.clear();
            } else {
                inner.teardown_pending = true;
            }
            completions
        };
        for completion in completions {
            let _ = catch_unwind(AssertUnwindSafe(|| completion()));
        }
    }
}

/// Disposable registration in a [`PropertyChangedStream`].
pub struct PropertyChangedSubscription {
    id: usize,
    stream: Weak<Mutex<PropertyChangedStreamInner>>,
}

impl PropertyChangedSubscription {
    fn noop() -> Self {
        Self {
            id: 0,
            stream: Weak::new(),
        }
    }

    /// Detaches both change and completion callbacks.
    pub fn dispose(&self) {
        if let Some(stream) = self.stream.upgrade() {
            let mut stream = lock(&stream);
            stream.subscribers.remove(&self.id);
            stream.completion_subscribers.remove(&self.id);
        }
    }
}

impl Drop for PropertyChangedSubscription {
    fn drop(&mut self) {
        self.dispose();
    }
}

/// Schedules VMx foreground work.
pub trait Dispatcher: Clone + Send + Sync + 'static {
    /// Schedules foreground `action` according to the dispatcher policy.
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>);

    /// Schedules background lifecycle work.
    fn dispatch_background(&self, action: Box<dyn FnOnce() + Send>) {
        self.dispatch(action);
    }
}

#[derive(Clone)]
/// A hot typed stream of fire-and-forget background lifecycle failures.
///
/// The stream does not replay earlier failures. It completes when its component
/// is disposed.
pub struct LifecycleErrorStream {
    state: Arc<Mutex<LifecycleErrorStreamState>>,
}

struct LifecycleErrorStreamState {
    stream: ValueStream<Option<VmxError>>,
    active_emissions: usize,
    dispose_requested: bool,
    disposed: bool,
}

struct LifecycleErrorEmission {
    state: Arc<Mutex<LifecycleErrorStreamState>>,
}

impl Drop for LifecycleErrorEmission {
    fn drop(&mut self) {
        let stream = {
            let mut state = lock(&self.state);
            state.active_emissions -= 1;
            if state.active_emissions == 0 && state.dispose_requested && !state.disposed {
                state.disposed = true;
                Some(state.stream.clone())
            } else {
                None
            }
        };
        if let Some(stream) = stream {
            stream.dispose();
        }
    }
}

impl LifecycleErrorStream {
    fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(LifecycleErrorStreamState {
                stream: ValueStream::hot(None),
                active_emissions: 0,
                dispose_requested: false,
                disposed: false,
            })),
        }
    }

    /// Subscribes to failures published after this call.
    pub fn subscribe<F>(&self, handler: F) -> ValueSubscription
    where
        F: Fn(VmxError) + Send + Sync + 'static,
    {
        let stream = lock(&self.state).stream.clone();
        stream.subscribe(move |error| {
            if let Some(error) = error {
                handler(error);
            }
        })
    }

    /// Subscribes to failures and receives one callback on component disposal.
    pub fn subscribe_with_completion<F, C>(&self, handler: F, completion: C) -> ValueSubscription
    where
        F: Fn(VmxError) + Send + Sync + 'static,
        C: Fn() + Send + Sync + 'static,
    {
        let stream = lock(&self.state).stream.clone();
        stream.subscribe_with_completion(
            move |error| {
                if let Some(error) = error {
                    handler(error);
                }
            },
            completion,
        )
    }

    fn send(&self, error: VmxError) {
        let stream = {
            let state = lock(&self.state);
            (!state.disposed).then(|| state.stream.clone())
        };
        if let Some(stream) = stream {
            stream.send(Some(error));
        }
    }

    fn begin_emission(&self) -> Option<LifecycleErrorEmission> {
        let mut state = lock(&self.state);
        if state.disposed {
            return None;
        }
        state.active_emissions += 1;
        Some(LifecycleErrorEmission {
            state: Arc::clone(&self.state),
        })
    }

    fn dispose(&self) {
        let stream = {
            let mut state = lock(&self.state);
            if state.disposed || state.dispose_requested {
                return;
            }
            state.dispose_requested = true;
            if state.active_emissions == 0 {
                state.disposed = true;
                Some(state.stream.clone())
            } else {
                None
            }
        };
        if let Some(stream) = stream {
            stream.dispose();
        }
    }
}

#[derive(Debug, Clone, Copy, Default)]
/// Null-object dispatcher that runs work synchronously.
pub struct NullDispatcher;

impl NullDispatcher {
    /// Creates a synchronous null dispatcher.
    pub fn new() -> Self {
        Self
    }
}

impl Dispatcher for NullDispatcher {
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>) {
        action();
    }
}

#[derive(Debug, Clone, Copy, Default)]
/// Dispatcher that immediately runs submitted work.
pub struct ImmediateDispatcher;

impl ImmediateDispatcher {
    /// Creates an immediate dispatcher.
    pub fn new() -> Self {
        Self
    }
}

impl Dispatcher for ImmediateDispatcher {
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>) {
        action();
    }
}

type DispatchAction = Box<dyn FnOnce() + Send>;
type DispatchQueue = Arc<Mutex<VecDeque<DispatchAction>>>;

#[derive(Debug, Clone)]
/// Default paired dispatcher with dedicated serial foreground/background workers.
pub struct DefaultDispatcher {
    foreground: mpsc::Sender<DispatchAction>,
    background: mpsc::Sender<DispatchAction>,
}

impl DefaultDispatcher {
    /// Creates the default paired-channel dispatcher.
    pub fn new() -> Self {
        fn worker(name: &str) -> mpsc::Sender<DispatchAction> {
            let (sender, receiver) = mpsc::channel::<DispatchAction>();
            thread::Builder::new()
                .name(name.to_string())
                .spawn(move || {
                    while let Ok(action) = receiver.recv() {
                        let _ = catch_unwind(AssertUnwindSafe(action));
                    }
                })
                .expect("VMx default dispatcher could not start its worker");
            sender
        }

        Self {
            foreground: worker("vmx-foreground"),
            background: worker("vmx-background"),
        }
    }
}

impl Default for DefaultDispatcher {
    fn default() -> Self {
        Self::new()
    }
}

impl Dispatcher for DefaultDispatcher {
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>) {
        self.foreground
            .send(action)
            .expect("VMx default foreground worker unexpectedly stopped");
    }

    fn dispatch_background(&self, action: Box<dyn FnOnce() + Send>) {
        self.background
            .send(action)
            .expect("VMx default background worker unexpectedly stopped");
    }
}

#[derive(Clone, Default)]
/// Deterministic dispatcher that queues work until explicitly drained.
pub struct ManualDispatcher {
    foreground: DispatchQueue,
    background: DispatchQueue,
}

impl ManualDispatcher {
    /// Creates an empty manual dispatch queue.
    pub fn new() -> Self {
        Self::default()
    }

    /// Runs queued actions in FIFO order until the queue is empty.
    pub fn drain(&self) {
        loop {
            let background = lock(&self.background).pop_front();
            let foreground = lock(&self.foreground).pop_front();
            match (background, foreground) {
                (None, None) => break,
                (background, foreground) => {
                    if let Some(action) = background {
                        action();
                    }
                    if let Some(action) = foreground {
                        action();
                    }
                }
            }
        }
    }

    /// Runs queued foreground actions in FIFO order.
    pub fn drain_foreground(&self) {
        while let Some(action) = lock(&self.foreground).pop_front() {
            action();
        }
    }

    /// Runs queued background actions in FIFO order.
    pub fn drain_background(&self) {
        while let Some(action) = lock(&self.background).pop_front() {
            action();
        }
    }

    /// Returns the number of actions currently queued.
    pub fn queued_len(&self) -> usize {
        lock(&self.foreground).len() + lock(&self.background).len()
    }

    /// Returns the queued foreground action count.
    pub fn foreground_queued_len(&self) -> usize {
        lock(&self.foreground).len()
    }

    /// Returns the queued background action count.
    pub fn background_queued_len(&self) -> usize {
        lock(&self.background).len()
    }
}

impl Dispatcher for ManualDispatcher {
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>) {
        lock(&self.foreground).push_back(action);
    }

    fn dispatch_background(&self, action: Box<dyn FnOnce() + Send>) {
        lock(&self.background).push_back(action);
    }
}

type ParentLookup = Arc<dyn Fn() -> Option<ParentHandle> + Send + Sync>;
type ParentContains = Arc<dyn Fn(usize) -> bool + Send + Sync>;
type ParentDetach = Arc<dyn Fn(usize, ParentHandle) -> VmxResult<ParentTransfer> + Send + Sync>;
type ParentSelectionPredicate = Arc<dyn Fn(usize) -> bool + Send + Sync>;
type ParentSelectionAction = Arc<dyn Fn(usize) -> VmxResult<()> + Send + Sync>;

struct ParentSelection {
    is_current: ParentSelectionPredicate,
    select: ParentSelectionAction,
    deselect: ParentSelectionAction,
}

struct ParentHandleInner {
    id: usize,
    parent: ParentLookup,
    contains: ParentContains,
    detach: ParentDetach,
    selection: Option<ParentSelection>,
}

/// Type-erased weak reference to an owning VMx container.
///
/// This is exposed only so third-party `VmNode` implementations can preserve
/// exclusive ownership. Its operations remain crate-internal.
#[doc(hidden)]
#[derive(Clone)]
pub struct ParentHandle {
    inner: Weak<ParentHandleInner>,
}

impl ParentHandle {
    pub(crate) fn is_alive(&self) -> bool {
        self.inner.strong_count() > 0
    }

    pub(crate) fn id(&self) -> Option<usize> {
        self.inner.upgrade().map(|inner| inner.id)
    }

    pub(crate) fn parent(&self) -> Option<Self> {
        self.inner.upgrade().and_then(|inner| (inner.parent)())
    }

    pub(crate) fn contains(&self, child_id: usize) -> bool {
        self.inner
            .upgrade()
            .is_some_and(|inner| (inner.contains)(child_id))
    }

    pub(crate) fn detach(&self, child_id: usize) -> VmxResult<ParentTransfer> {
        let inner = self.inner.upgrade().ok_or(VmxError::InconsistentParent)?;
        (inner.detach)(child_id, self.clone())
    }

    pub(crate) fn supports_child_selection(&self) -> bool {
        self.inner
            .upgrade()
            .is_some_and(|inner| inner.selection.is_some())
    }

    pub(crate) fn is_current(&self, child_id: usize) -> bool {
        self.inner
            .upgrade()
            .and_then(|inner| {
                inner
                    .selection
                    .as_ref()
                    .map(|selection| (selection.is_current)(child_id))
            })
            .unwrap_or(false)
    }

    pub(crate) fn select(&self, child_id: usize) -> VmxResult<()> {
        let inner = self.inner.upgrade().ok_or(VmxError::InconsistentParent)?;
        let selection = inner
            .selection
            .as_ref()
            .ok_or(VmxError::InconsistentParent)?;
        (selection.select)(child_id)
    }

    pub(crate) fn deselect(&self, child_id: usize) -> VmxResult<()> {
        let inner = self.inner.upgrade().ok_or(VmxError::InconsistentParent)?;
        let selection = inner
            .selection
            .as_ref()
            .ok_or(VmxError::InconsistentParent)?;
        (selection.deselect)(child_id)
    }

    pub(crate) fn same_owner(&self, other: &Self) -> bool {
        self.inner.ptr_eq(&other.inner)
    }
}

#[derive(Clone)]
pub(crate) struct ParentRegistration {
    inner: Arc<ParentHandleInner>,
}

impl ParentRegistration {
    pub(crate) fn new(
        id: usize,
        parent: impl Fn() -> Option<ParentHandle> + Send + Sync + 'static,
        contains: impl Fn(usize) -> bool + Send + Sync + 'static,
        detach: impl Fn(usize, ParentHandle) -> VmxResult<ParentTransfer> + Send + Sync + 'static,
    ) -> Self {
        Self {
            inner: Arc::new(ParentHandleInner {
                id,
                parent: Arc::new(parent),
                contains: Arc::new(contains),
                detach: Arc::new(detach),
                selection: None,
            }),
        }
    }

    pub(crate) fn new_selectable(
        id: usize,
        parent: impl Fn() -> Option<ParentHandle> + Send + Sync + 'static,
        contains: impl Fn(usize) -> bool + Send + Sync + 'static,
        detach: impl Fn(usize, ParentHandle) -> VmxResult<ParentTransfer> + Send + Sync + 'static,
        is_current: impl Fn(usize) -> bool + Send + Sync + 'static,
        select: impl Fn(usize) -> VmxResult<()> + Send + Sync + 'static,
        deselect: impl Fn(usize) -> VmxResult<()> + Send + Sync + 'static,
    ) -> Self {
        Self {
            inner: Arc::new(ParentHandleInner {
                id,
                parent: Arc::new(parent),
                contains: Arc::new(contains),
                detach: Arc::new(detach),
                selection: Some(ParentSelection {
                    is_current: Arc::new(is_current),
                    select: Arc::new(select),
                    deselect: Arc::new(deselect),
                }),
            }),
        }
    }

    pub(crate) fn handle(&self) -> ParentHandle {
        ParentHandle {
            inner: Arc::downgrade(&self.inner),
        }
    }
}

pub(crate) struct ParentTransfer {
    commit: Option<Box<dyn FnOnce() -> VmxResult<()> + Send>>,
    rollback: Option<Box<dyn FnOnce() -> VmxResult<()> + Send>>,
}

pub(crate) fn retain_parent_transfer_commit(
    first_error: &mut Option<VmxError>,
    first_panic: &mut Option<Box<dyn std::any::Any + Send>>,
    transfer: ParentTransfer,
) {
    match catch_unwind(AssertUnwindSafe(|| transfer.commit())) {
        Ok(result) => retain_first_error(first_error, result),
        Err(payload) => {
            if first_panic.is_none() {
                *first_panic = Some(payload);
            }
        }
    }
}

impl ParentTransfer {
    pub(crate) fn new(
        commit: impl FnOnce() -> VmxResult<()> + Send + 'static,
        rollback: impl FnOnce() -> VmxResult<()> + Send + 'static,
    ) -> Self {
        Self {
            commit: Some(Box::new(commit)),
            rollback: Some(Box::new(rollback)),
        }
    }

    pub(crate) fn commit(mut self) -> VmxResult<()> {
        self.rollback = None;
        if let Some(commit) = self.commit.take() {
            commit()
        } else {
            Ok(())
        }
    }

    pub(crate) fn rollback(mut self) -> VmxResult<()> {
        self.commit = None;
        if let Some(rollback) = self.rollback.take() {
            rollback()
        } else {
            Ok(())
        }
    }
}

impl Drop for ParentTransfer {
    fn drop(&mut self) {
        self.commit = None;
        if let Some(rollback) = self.rollback.take() {
            let _ = rollback();
        }
    }
}

fn active_ownership_claims() -> &'static Mutex<HashSet<usize>> {
    static ACTIVE: OnceLock<Mutex<HashSet<usize>>> = OnceLock::new();
    ACTIVE.get_or_init(|| Mutex::new(HashSet::new()))
}

pub(crate) struct OwnershipClaim {
    child_id: usize,
}

impl Drop for OwnershipClaim {
    fn drop(&mut self) {
        lock(active_ownership_claims()).remove(&self.child_id);
    }
}

pub(crate) fn begin_ownership_claim(child_id: usize) -> VmxResult<OwnershipClaim> {
    let inserted = lock(active_ownership_claims()).insert(child_id);
    if !inserted {
        return Err(VmxError::OwnershipTransactionInProgress);
    }
    Ok(OwnershipClaim { child_id })
}

pub(crate) fn begin_parent_transfer<T: VmNode>(
    child: &T,
    destination: &ParentHandle,
) -> VmxResult<Option<ParentTransfer>> {
    let child_id = child.id();
    let claim = begin_ownership_claim(child_id)?;

    let staged = (|| {
        if destination.contains(child_id) {
            return Err(VmxError::DuplicateChild);
        }

        let mut cursor = Some(destination.clone());
        let mut visited = HashSet::new();
        while let Some(parent) = cursor {
            let parent_id = parent.id().ok_or(VmxError::InconsistentParent)?;
            if parent_id == child_id {
                return Err(VmxError::OwnershipCycle);
            }
            if !visited.insert(parent_id) {
                return Err(VmxError::OwnershipCycle);
            }
            cursor = parent.parent();
        }

        match child.parent_handle() {
            Some(parent) if !parent.is_alive() => {
                child.set_parent_handle(None);
                Ok(None)
            }
            Some(parent) => match parent.detach(child_id) {
                Ok(transfer) => Ok(Some(transfer)),
                Err(VmxError::InconsistentParent) if !parent.is_alive() => {
                    child.set_parent_handle(None);
                    Ok(None)
                }
                Err(error) => Err(error),
            },
            None if child.parent_id().is_some() => Err(VmxError::InconsistentParent),
            None => Ok(None),
        }
    })();

    let staged = staged?;
    let staged = Arc::new(Mutex::new(staged));
    let claim = Arc::new(Mutex::new(Some(claim)));
    let commit_state = Arc::clone(&staged);
    let rollback_state = Arc::clone(&staged);
    let commit_claim = Arc::clone(&claim);
    let rollback_claim = Arc::clone(&claim);
    Ok(Some(ParentTransfer::new(
        move || {
            let _claim = lock(&commit_claim).take();
            let transfer = lock(&commit_state).take();
            if let Some(transfer) = transfer {
                transfer.commit()
            } else {
                Ok(())
            }
        },
        move || {
            let _claim = lock(&rollback_claim).take();
            let transfer = lock(&rollback_state).take();
            if let Some(transfer) = transfer {
                transfer.rollback()
            } else {
                Ok(())
            }
        },
    )))
}

/// Common identity, lifecycle, ownership, and selection contract for VM nodes.
pub trait VmNode: Clone + PartialEq + Send + Sync + 'static {
    /// Returns the stable node identity.
    fn id(&self) -> usize;
    /// Constructs the node.
    fn construct(&self) -> VmxResult<()>;
    /// Destructs the node.
    fn destruct(&self) -> VmxResult<()>;
    /// Disposes the node terminally.
    fn dispose(&self) -> VmxResult<()>;
    /// Returns the current lifecycle status.
    fn status(&self) -> ConstructionStatus;
    /// Sets legacy parent identity for implementations without parent handles.
    fn set_parent_id(&self, parent_id: Option<usize>);
    /// Returns the current parent identity.
    fn parent_id(&self) -> Option<usize>;
    #[doc(hidden)]
    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.set_parent_id(parent.as_ref().and_then(ParentHandle::id));
    }
    #[doc(hidden)]
    fn parent_handle(&self) -> Option<ParentHandle> {
        None
    }
    /// Updates the node's container-owned current flag.
    fn set_current_flag(&self, _is_current: bool) {}
    /// Reports whether the node is current in its container.
    fn is_current(&self) -> bool {
        false
    }
}

/// A VM node that exposes recursive tree traversal state.
pub trait TreeNode: VmNode {
    /// Returns child nodes in traversal order.
    fn children_nodes(&self) -> Vec<Self> {
        Vec::new()
    }

    /// Returns the node's opt-in expansion capability, when present.
    fn expandable(&self) -> Option<&dyn crate::Expandable> {
        None
    }
}

type Hook = Arc<Mutex<dyn FnMut() -> VmxResult<()> + Send + 'static>>;
type OwnedCleanup = Box<dyn FnOnce() + Send + 'static>;
pub(crate) type ModelHint<M> = Arc<dyn Fn(&M) -> Option<String> + Send + Sync>;

#[derive(Clone)]
pub(crate) struct ComponentCore<D: Dispatcher = NullDispatcher> {
    inner: Arc<Mutex<ComponentCoreInner<D>>>,
    hook_ready: Arc<Condvar>,
}

struct ComponentCoreInner<D: Dispatcher> {
    id: usize,
    name: String,
    hint: Option<String>,
    status: ConstructionStatus,
    transitioning: bool,
    transition_generation: u64,
    parent: Option<ParentHandle>,
    legacy_parent_id: Option<usize>,
    hub: MessageHub,
    property_changed: PropertyChangedStream,
    background_errors: LifecycleErrorStream,
    foreground: D,
    background: bool,
    on_construct: Option<Hook>,
    on_destruct: Option<Hook>,
    on_dispose: Option<Hook>,
    owned_cleanups: Vec<OwnedCleanup>,
    active_hook_owner: Option<ThreadId>,
    deferred_core_disposal: bool,
    selected: bool,
    expanded: bool,
}

impl<D: Dispatcher> ComponentCore<D> {
    pub(crate) fn new(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        Self {
            inner: Arc::new(Mutex::new(ComponentCoreInner {
                id: next_id(),
                name: name.into(),
                hint: None,
                status: ConstructionStatus::Destructed,
                transitioning: false,
                transition_generation: 0,
                parent: None,
                legacy_parent_id: None,
                hub,
                property_changed: PropertyChangedStream::default(),
                background_errors: LifecycleErrorStream::new(),
                foreground: dispatcher,
                background: false,
                on_construct: None,
                on_destruct: None,
                on_dispose: None,
                owned_cleanups: Vec::new(),
                active_hook_owner: None,
                deferred_core_disposal: false,
                selected: false,
                expanded: false,
            })),
            hook_ready: Arc::new(Condvar::new()),
        }
    }

    pub(crate) fn id(&self) -> usize {
        lock(&self.inner).id
    }

    pub(crate) fn name(&self) -> String {
        lock(&self.inner).name.clone()
    }

    pub(crate) fn hint(&self) -> Option<String> {
        lock(&self.inner).hint.clone()
    }

    pub(crate) fn set_hint(&self, hint: Option<String>) {
        lock(&self.inner).hint = hint;
    }

    pub(crate) fn set_background(&self, background: bool) {
        lock(&self.inner).background = background;
    }

    pub(crate) fn status(&self) -> ConstructionStatus {
        lock(&self.inner).status
    }

    pub(crate) fn background_errors(&self) -> LifecycleErrorStream {
        lock(&self.inner).background_errors.clone()
    }

    pub(crate) fn set_hook(&self, operation: LifecycleOperation, hook: Hook) {
        let mut inner = lock(&self.inner);
        match operation {
            LifecycleOperation::Construct => inner.on_construct = Some(hook),
            LifecycleOperation::Destruct => inner.on_destruct = Some(hook),
            LifecycleOperation::Dispose => inner.on_dispose = Some(hook),
        }
    }

    pub(crate) fn transition(&self, operation: LifecycleOperation) -> VmxResult<()> {
        if operation != LifecycleOperation::Dispose && lock(&self.inner).background {
            return self.transition_background(operation);
        }
        self.transition_with(operation, || Ok(()))
    }

    pub(crate) fn reconstruct(&self) -> VmxResult<()> {
        self.reconstruct_sync()
    }

    fn run_sync_hook(&self, hook: Option<Hook>) -> thread::Result<VmxResult<()>> {
        let execution = catch_unwind(AssertUnwindSafe(|| {
            hook.map(|hook| (lock(&hook))()).unwrap_or(Ok(()))
        }));
        let deferred = {
            let mut inner = lock(&self.inner);
            if inner.active_hook_owner == Some(thread::current().id()) {
                inner.active_hook_owner = None;
            }
            let deferred = inner.deferred_core_disposal;
            inner.deferred_core_disposal = false;
            self.hook_ready.notify_all();
            deferred
        };
        if !deferred {
            return execution;
        }
        let disposal = self.finish_deferred_core_disposal();
        match execution {
            Ok(Ok(())) => Ok(disposal),
            other => other,
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn publish_reconstruct_status(
        &self,
        hub: &MessageHub,
        sender_id: usize,
        sender_name: &str,
        generation: u64,
        status: ConstructionStatus,
        transitioning: bool,
        claim_hook: bool,
    ) -> bool {
        hub.send_prepared(|| {
            let mut inner = lock(&self.inner);
            if inner.transition_generation != generation
                || inner.status == ConstructionStatus::Disposed
            {
                return (false, None);
            }
            inner.status = status;
            inner.transitioning = transitioning;
            if claim_hook {
                inner.active_hook_owner = Some(thread::current().id());
            }
            (
                true,
                Some(Message::ConstructionStatusChanged(
                    ConstructionStatusChangedMessage {
                        sender_id,
                        sender_name: sender_name.to_string(),
                        status,
                    },
                )),
            )
        })
    }

    fn reconstruct_sync(&self) -> VmxResult<()> {
        let hub = lock(&self.inner).hub.clone();
        let (sender_id, sender_name, destruct_hook, construct_hook, generation) = hub
            .send_prepared(|| {
                let mut inner = lock(&self.inner);
                if inner.status == ConstructionStatus::Disposed {
                    return (Err(VmxError::Disposed), None);
                }
                if inner.transitioning {
                    return (Err(VmxError::ConcurrentOperation), None);
                }
                if inner.status != ConstructionStatus::Constructed {
                    return (
                        Err(VmxError::InvalidLifecycleTransition {
                            from: inner.status,
                            operation: "reconstruct",
                        }),
                        None,
                    );
                }
                inner.transition_generation = inner.transition_generation.wrapping_add(1);
                let generation = inner.transition_generation;
                inner.transitioning = true;
                inner.status = ConstructionStatus::Destructing;
                inner.active_hook_owner = Some(thread::current().id());
                (
                    Ok((
                        inner.id,
                        inner.name.clone(),
                        inner.on_destruct.clone(),
                        inner.on_construct.clone(),
                        generation,
                    )),
                    Some(Message::ConstructionStatusChanged(
                        ConstructionStatusChangedMessage {
                            sender_id: inner.id,
                            sender_name: inner.name.clone(),
                            status: ConstructionStatus::Destructing,
                        },
                    )),
                )
            })?;

        match self.run_sync_hook(destruct_hook) {
            Ok(Ok(())) => {}
            Ok(Err(error)) => {
                self.publish_reconstruct_status(
                    &hub,
                    sender_id,
                    &sender_name,
                    generation,
                    ConstructionStatus::Constructed,
                    false,
                    false,
                );
                return Err(error);
            }
            Err(payload) => {
                self.publish_reconstruct_status(
                    &hub,
                    sender_id,
                    &sender_name,
                    generation,
                    ConstructionStatus::Constructed,
                    false,
                    false,
                );
                resume_unwind(payload);
            }
        }
        if !self.publish_reconstruct_status(
            &hub,
            sender_id,
            &sender_name,
            generation,
            ConstructionStatus::Destructed,
            true,
            false,
        ) || !self.publish_reconstruct_status(
            &hub,
            sender_id,
            &sender_name,
            generation,
            ConstructionStatus::Constructing,
            true,
            true,
        ) {
            return Ok(());
        }

        match self.run_sync_hook(construct_hook) {
            Ok(Ok(())) => {
                self.publish_reconstruct_status(
                    &hub,
                    sender_id,
                    &sender_name,
                    generation,
                    ConstructionStatus::Constructed,
                    false,
                    false,
                );
                Ok(())
            }
            Ok(Err(error)) => {
                self.publish_reconstruct_status(
                    &hub,
                    sender_id,
                    &sender_name,
                    generation,
                    ConstructionStatus::Destructed,
                    false,
                    false,
                );
                Err(error)
            }
            Err(payload) => {
                self.publish_reconstruct_status(
                    &hub,
                    sender_id,
                    &sender_name,
                    generation,
                    ConstructionStatus::Destructed,
                    false,
                    false,
                );
                resume_unwind(payload);
            }
        }
    }

    fn run_background_hook(&self, hook: Option<Hook>, generation: u64) -> Option<VmxResult<()>> {
        {
            let mut inner = lock(&self.inner);
            if inner.transition_generation != generation
                || inner.status == ConstructionStatus::Disposed
            {
                return None;
            }
            inner.active_hook_owner = Some(thread::current().id());
        }
        let execution = catch_unwind(AssertUnwindSafe(|| {
            hook.map(|hook| (lock(&hook))()).unwrap_or(Ok(()))
        }));
        let deferred = {
            let mut inner = lock(&self.inner);
            if inner.active_hook_owner == Some(thread::current().id()) {
                inner.active_hook_owner = None;
            }
            let deferred = inner.deferred_core_disposal;
            inner.deferred_core_disposal = false;
            self.hook_ready.notify_all();
            deferred
        };
        let mut result = match execution {
            Ok(result) => result,
            Err(_) => Err(VmxError::Other(
                "background lifecycle hook panicked".to_string(),
            )),
        };
        if deferred {
            let errors = self.background_errors();
            let emission = errors.begin_emission();
            let disposal = catch_unwind(AssertUnwindSafe(|| self.finish_deferred_core_disposal()));
            if result.is_ok() {
                result = match disposal {
                    Ok(result) => result,
                    Err(_) => Err(VmxError::Other(
                        "deferred background disposal hook panicked".to_string(),
                    )),
                };
            }
            if let Err(error) = result {
                errors.send(error);
            }
            drop(emission);
            return None;
        }
        let inner = lock(&self.inner);
        if inner.transition_generation != generation || inner.status == ConstructionStatus::Disposed
        {
            return None;
        }
        drop(inner);
        Some(result)
    }

    fn transition_background(&self, operation: LifecycleOperation) -> VmxResult<()> {
        let hub = lock(&self.inner).hub.clone();
        let started = hub.send_prepared(|| {
            let mut inner = lock(&self.inner);
            match (inner.status, operation) {
                (ConstructionStatus::Disposed, _) => return (Err(VmxError::Disposed), None),
                (ConstructionStatus::Constructed, LifecycleOperation::Construct)
                | (ConstructionStatus::Destructed, LifecycleOperation::Destruct) => {
                    return (Ok(None), None)
                }
                _ => {}
            }
            if inner.transitioning {
                return (Err(VmxError::ConcurrentOperation), None);
            }
            let transition_status = match operation {
                LifecycleOperation::Construct => ConstructionStatus::Constructing,
                LifecycleOperation::Destruct => ConstructionStatus::Destructing,
                LifecycleOperation::Dispose => unreachable!(),
            };
            let target = match operation {
                LifecycleOperation::Construct => ConstructionStatus::Constructed,
                LifecycleOperation::Destruct => ConstructionStatus::Destructed,
                LifecycleOperation::Dispose => unreachable!(),
            };
            inner.transition_generation = inner.transition_generation.wrapping_add(1);
            let generation = inner.transition_generation;
            inner.transitioning = true;
            inner.status = transition_status;
            let hook = match operation {
                LifecycleOperation::Construct => inner.on_construct.clone(),
                LifecycleOperation::Destruct => inner.on_destruct.clone(),
                LifecycleOperation::Dispose => unreachable!(),
            };
            let message = Message::ConstructionStatusChanged(ConstructionStatusChangedMessage {
                sender_id: inner.id,
                sender_name: inner.name.clone(),
                status: transition_status,
            });
            (
                Ok(Some((
                    inner.id,
                    inner.name.clone(),
                    inner.foreground.clone(),
                    hook,
                    target,
                    generation,
                ))),
                Some(message),
            )
        })?;
        let Some((sender_id, sender_name, dispatcher, hook, target, generation)) = started else {
            return Ok(());
        };
        let rollback = match operation {
            LifecycleOperation::Construct => ConstructionStatus::Destructed,
            LifecycleOperation::Destruct => ConstructionStatus::Constructed,
            LifecycleOperation::Dispose => unreachable!(),
        };
        let core = self.clone();
        let scheduling_core = core.clone();
        let scheduling_hub = hub.clone();
        let scheduling_name = sender_name.clone();
        let action_dispatcher = dispatcher.clone();
        let background_action = Box::new(move || {
            let Some(result) = core.run_background_hook(hook, generation) else {
                return;
            };
            let error = result.err();
            let settled = if error.is_none() { target } else { rollback };
            let publication_core = core.clone();
            let errors = core.background_errors();
            let fallback_error = error.clone().unwrap_or_else(|| {
                VmxError::Other("foreground dispatcher rejected lifecycle completion".to_string())
            });
            let fallback_core = publication_core.clone();
            let fallback_hub = hub.clone();
            let fallback_name = sender_name.clone();
            let foreground_action = Box::new(move || {
                let emission = error.as_ref().and_then(|_| errors.begin_emission());
                hub.send_prepared(|| {
                    let mut inner = lock(&publication_core.inner);
                    if inner.transition_generation != generation
                        || inner.status == ConstructionStatus::Disposed
                    {
                        return ((), None);
                    }
                    inner.status = settled;
                    inner.transitioning = false;
                    (
                        (),
                        Some(Message::ConstructionStatusChanged(
                            ConstructionStatusChangedMessage {
                                sender_id,
                                sender_name,
                                status: settled,
                            },
                        )),
                    )
                });
                if let Some(error) = error {
                    errors.send(error);
                }
                drop(emission);
            });
            if catch_unwind(AssertUnwindSafe(|| {
                action_dispatcher.dispatch(foreground_action)
            }))
            .is_err()
            {
                fallback_core.recover_background_schedule_failure(
                    &fallback_hub,
                    sender_id,
                    &fallback_name,
                    generation,
                    rollback,
                    Some(fallback_error),
                );
            }
        });
        if catch_unwind(AssertUnwindSafe(|| {
            dispatcher.clone().dispatch_background(background_action)
        }))
        .is_err()
            && scheduling_core.recover_background_schedule_failure(
                &scheduling_hub,
                sender_id,
                &scheduling_name,
                generation,
                rollback,
                None,
            )
        {
            return Err(VmxError::Other(
                "background dispatcher rejected lifecycle work".to_string(),
            ));
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn recover_background_schedule_failure(
        &self,
        hub: &MessageHub,
        sender_id: usize,
        sender_name: &str,
        generation: u64,
        rollback: ConstructionStatus,
        error: Option<VmxError>,
    ) -> bool {
        let errors = self.background_errors();
        let emission = error.as_ref().and_then(|_| errors.begin_emission());
        let recovered = hub.send_prepared(|| {
            let mut inner = lock(&self.inner);
            if inner.transition_generation != generation
                || inner.status == ConstructionStatus::Disposed
                || !inner.transitioning
            {
                return (false, None);
            }
            inner.status = rollback;
            inner.transitioning = false;
            (
                true,
                Some(Message::ConstructionStatusChanged(
                    ConstructionStatusChangedMessage {
                        sender_id,
                        sender_name: sender_name.to_string(),
                        status: rollback,
                    },
                )),
            )
        });
        if recovered {
            if let Some(error) = error {
                errors.send(error);
            }
        }
        drop(emission);
        recovered
    }

    pub(crate) fn transition_with<F>(
        &self,
        operation: LifecycleOperation,
        action: F,
    ) -> VmxResult<()>
    where
        F: FnOnce() -> VmxResult<()>,
    {
        let hub = lock(&self.inner).hub.clone();
        let started = hub.send_prepared(|| {
            let (sender_id, sender_name, hook, transition_status, target, generation) = {
                let mut inner = lock(&self.inner);
                match (inner.status, operation) {
                    (ConstructionStatus::Disposed, LifecycleOperation::Construct)
                    | (ConstructionStatus::Disposed, LifecycleOperation::Destruct) => {
                        return (Err(VmxError::Disposed), None)
                    }
                    (ConstructionStatus::Constructed, LifecycleOperation::Construct)
                    | (ConstructionStatus::Destructed, LifecycleOperation::Destruct) => {
                        return (Ok(None), None)
                    }
                    (_, LifecycleOperation::Dispose)
                        if inner.status == ConstructionStatus::Disposed =>
                    {
                        return (Ok(None), None)
                    }
                    _ => {}
                }
                if inner.transitioning && operation != LifecycleOperation::Dispose {
                    return (Err(VmxError::ConcurrentOperation), None);
                }

                let transition_status = match operation {
                    LifecycleOperation::Construct => ConstructionStatus::Constructing,
                    LifecycleOperation::Destruct => ConstructionStatus::Destructing,
                    LifecycleOperation::Dispose => ConstructionStatus::Disposed,
                };
                let target = match operation {
                    LifecycleOperation::Construct => ConstructionStatus::Constructed,
                    LifecycleOperation::Destruct => ConstructionStatus::Destructed,
                    LifecycleOperation::Dispose => ConstructionStatus::Disposed,
                };
                inner.transition_generation = inner.transition_generation.wrapping_add(1);
                let generation = inner.transition_generation;
                inner.transitioning = true;
                inner.status = transition_status;
                if operation != LifecycleOperation::Dispose {
                    inner.active_hook_owner = Some(thread::current().id());
                }
                let hook = match operation {
                    LifecycleOperation::Construct => inner.on_construct.clone(),
                    LifecycleOperation::Destruct => inner.on_destruct.clone(),
                    LifecycleOperation::Dispose => inner.on_dispose.clone(),
                };
                (
                    inner.id,
                    inner.name.clone(),
                    hook,
                    transition_status,
                    target,
                    generation,
                )
            };

            let message = Message::ConstructionStatusChanged(ConstructionStatusChangedMessage {
                sender_id,
                sender_name: sender_name.clone(),
                status: transition_status,
            });
            (
                Ok(Some((sender_id, sender_name, hook, target, generation))),
                Some(message),
            )
        })?;
        let Some((sender_id, sender_name, hook, target, generation)) = started else {
            return Ok(());
        };

        if operation == LifecycleOperation::Dispose {
            let current = thread::current().id();
            let mut inner = lock(&self.inner);
            while let Some(owner) = inner.active_hook_owner {
                if owner == current {
                    inner.deferred_core_disposal = true;
                    return Ok(());
                }
                let (next, cyclic) =
                    wait_for_message_hub_owner(&self.hook_ready, inner, current, owner);
                inner = next;
                if cyclic {
                    inner.deferred_core_disposal = true;
                    return Ok(());
                }
            }
        }

        let execution = catch_unwind(AssertUnwindSafe(|| {
            let hook_result = hook.map(|hook| (lock(&hook))()).unwrap_or(Ok(()));
            let action_allowed = operation == LifecycleOperation::Dispose || {
                let inner = lock(&self.inner);
                inner.transition_generation == generation
                    && inner.status != ConstructionStatus::Disposed
            };
            hook_result.and_then(|_| if action_allowed { action() } else { Ok(()) })
        }));
        let deferred_disposal = if operation == LifecycleOperation::Dispose {
            false
        } else {
            let mut inner = lock(&self.inner);
            if inner.active_hook_owner == Some(thread::current().id()) {
                inner.active_hook_owner = None;
            }
            let deferred = inner.deferred_core_disposal;
            inner.deferred_core_disposal = false;
            self.hook_ready.notify_all();
            deferred
        };
        let (mut operation_result, mut panic_payload) = match execution {
            Ok(result) => (result, None),
            Err(payload) => (Ok(()), Some(payload)),
        };
        if deferred_disposal {
            let disposal = catch_unwind(AssertUnwindSafe(|| self.finish_deferred_core_disposal()));
            if operation_result.is_ok() && panic_payload.is_none() {
                match disposal {
                    Ok(result) => operation_result = result,
                    Err(payload) => panic_payload = Some(payload),
                }
            }
        }
        if operation == LifecycleOperation::Dispose {
            self.dispose_owned();
            self.property_changed_stream().dispose();
            self.background_errors().dispose();
            let mut inner = lock(&self.inner);
            if inner.transition_generation == generation {
                inner.transitioning = false;
            }
            drop(inner);
            if let Some(payload) = panic_payload {
                resume_unwind(payload);
            }
            return operation_result;
        }
        let superseded = {
            let inner = lock(&self.inner);
            inner.transition_generation != generation
                || (operation != LifecycleOperation::Dispose
                    && inner.status == ConstructionStatus::Disposed)
        };
        if superseded {
            if let Some(payload) = panic_payload {
                resume_unwind(payload);
            }
            return operation_result;
        }
        if operation_result.is_err() || panic_payload.is_some() {
            let rollback = match operation {
                LifecycleOperation::Construct => ConstructionStatus::Destructed,
                LifecycleOperation::Destruct => ConstructionStatus::Constructed,
                LifecycleOperation::Dispose => ConstructionStatus::Disposed,
            };
            let rolled_back = {
                let mut inner = lock(&self.inner);
                if inner.transition_generation == generation {
                    inner.status = rollback;
                    inner.transitioning = false;
                    true
                } else {
                    false
                }
            };
            if !rolled_back {
                if let Some(payload) = panic_payload {
                    resume_unwind(payload);
                }
                return operation_result;
            }
            hub.send_prepared(|| {
                let message = self
                    .publication_is_current(generation, rollback)
                    .then_some({
                        Message::ConstructionStatusChanged(ConstructionStatusChangedMessage {
                            sender_id,
                            sender_name: sender_name.clone(),
                            status: rollback,
                        })
                    });
                ((), message)
            });
            if let Some(payload) = panic_payload {
                resume_unwind(payload);
            }
            return operation_result;
        }

        let property_changed = {
            let mut inner = lock(&self.inner);
            if inner.transition_generation != generation {
                return Ok(());
            }
            inner.status = target;
            inner.transitioning = false;
            (target == ConstructionStatus::Disposed).then(|| inner.property_changed.clone())
        };
        if let Some(property_changed) = property_changed {
            property_changed.dispose();
        }
        // Dispose has no distinct intermediate state: the first publication
        // above is already the terminal Disposed transition. Publishing the
        // same state again would make one dispose observably execute twice.
        if operation != LifecycleOperation::Dispose {
            hub.send_prepared(|| {
                let message = self.publication_is_current(generation, target).then_some({
                    Message::ConstructionStatusChanged(ConstructionStatusChangedMessage {
                        sender_id,
                        sender_name: sender_name.clone(),
                        status: target,
                    })
                });
                ((), message)
            });
        }
        Ok(())
    }

    fn finish_deferred_core_disposal(&self) -> VmxResult<()> {
        let (hook, property_changed, background_errors) = {
            let inner = lock(&self.inner);
            (
                inner.on_dispose.clone(),
                inner.property_changed.clone(),
                inner.background_errors.clone(),
            )
        };
        let result = catch_unwind(AssertUnwindSafe(|| {
            hook.map(|hook| (lock(&hook))()).unwrap_or(Ok(()))
        }));
        self.dispose_owned();
        property_changed.dispose();
        background_errors.dispose();
        match result {
            Ok(result) => result,
            Err(payload) => resume_unwind(payload),
        }
    }

    fn publication_is_current(&self, generation: u64, status: ConstructionStatus) -> bool {
        let inner = lock(&self.inner);
        inner.transition_generation == generation && inner.status == status
    }

    pub(crate) fn hub(&self) -> MessageHub {
        lock(&self.inner).hub.clone()
    }

    pub(crate) fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        let cleanup = {
            let mut inner = lock(&self.inner);
            if inner.status == ConstructionStatus::Disposed {
                Some(Box::new(cleanup) as OwnedCleanup)
            } else {
                inner.owned_cleanups.push(Box::new(cleanup));
                None
            }
        };
        if let Some(cleanup) = cleanup {
            let _ = catch_unwind(AssertUnwindSafe(cleanup));
        }
    }

    pub(crate) fn dispose_owned(&self) {
        let resources = {
            let mut inner = lock(&self.inner);
            std::mem::take(&mut inner.owned_cleanups)
        };
        for cleanup in resources.into_iter().rev() {
            let _ = catch_unwind(AssertUnwindSafe(cleanup));
        }
    }

    pub(crate) fn set_parent_id(&self, parent_id: Option<usize>) {
        let mut inner = lock(&self.inner);
        inner.parent = None;
        inner.legacy_parent_id = parent_id;
    }

    pub(crate) fn parent_id(&self) -> Option<usize> {
        let inner = lock(&self.inner);
        inner
            .parent
            .as_ref()
            .and_then(ParentHandle::id)
            .or(inner.legacy_parent_id)
    }

    pub(crate) fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        let mut inner = lock(&self.inner);
        inner.parent = parent;
        inner.legacy_parent_id = None;
    }

    pub(crate) fn parent_handle(&self) -> Option<ParentHandle> {
        let mut inner = lock(&self.inner);
        if inner
            .parent
            .as_ref()
            .is_some_and(|parent| !parent.is_alive())
        {
            inner.parent = None;
        }
        inner.parent.clone()
    }

    pub(crate) fn property_changed_stream(&self) -> PropertyChangedStream {
        lock(&self.inner).property_changed.clone()
    }

    pub(crate) fn notify_property_changed(&self, property_name: impl Into<String>) {
        let property_name = property_name.into();
        let (sender_id, sender_name, hub, local) = {
            let inner = lock(&self.inner);
            if inner.status == ConstructionStatus::Disposed {
                return;
            }
            (
                inner.id,
                inner.name.clone(),
                inner.hub.clone(),
                inner.property_changed.clone(),
            )
        };
        if !local.begin_notification() {
            return;
        }
        let hub_result = catch_unwind(AssertUnwindSafe(|| {
            hub.send(Message::PropertyChanged(PropertyChangedMessage {
                sender_id,
                sender_name,
                property_name: property_name.clone(),
            }));
        }));
        // The stream admitted this call before disposal, so the pair completes
        // even when a hub observer disposes the VM re-entrantly. Subscriber
        // additions/removals during hub delivery still affect the local send.
        local.send_admitted(&property_name);
        local.end_notification();
        if let Err(payload) = hub_result {
            resume_unwind(payload);
        }
    }

    pub(crate) fn dispatch(&self, action: Box<dyn FnOnce() + Send>) {
        let foreground = lock(&self.inner).foreground.clone();
        foreground.dispatch(action);
    }

    pub(crate) fn is_selected(&self) -> bool {
        lock(&self.inner).selected
    }

    pub(crate) fn can_select(&self) -> bool {
        let (id, status, parent) = {
            let inner = lock(&self.inner);
            (inner.id, inner.status, inner.parent.clone())
        };
        status == ConstructionStatus::Constructed
            && parent
                .as_ref()
                .is_some_and(|parent| parent.supports_child_selection() && !parent.is_current(id))
    }

    pub(crate) fn can_deselect(&self) -> bool {
        let (id, status, parent) = {
            let inner = lock(&self.inner);
            (inner.id, inner.status, inner.parent.clone())
        };
        status != ConstructionStatus::Disposed
            && parent
                .as_ref()
                .is_some_and(|parent| parent.supports_child_selection() && parent.is_current(id))
    }

    pub(crate) fn select_via_parent(&self) {
        let (id, status, parent) = {
            let inner = lock(&self.inner);
            (inner.id, inner.status, inner.parent.clone())
        };
        if status == ConstructionStatus::Disposed {
            return;
        }
        if let Some(parent) = parent.filter(|parent| parent.supports_child_selection()) {
            let _ = parent.select(id);
        }
    }

    pub(crate) fn deselect_via_parent(&self) {
        let (id, status, parent) = {
            let inner = lock(&self.inner);
            (inner.id, inner.status, inner.parent.clone())
        };
        if status == ConstructionStatus::Disposed {
            return;
        }
        if let Some(parent) = parent.filter(|parent| parent.supports_child_selection()) {
            let _ = parent.deselect(id);
        }
    }

    pub(crate) fn set_current_flag(&self, selected: bool) {
        let changed = {
            let mut inner = lock(&self.inner);
            if inner.selected == selected {
                false
            } else {
                inner.selected = selected;
                true
            }
        };
        if changed {
            self.notify_property_changed("is_current");
        }
    }

    pub(crate) fn is_expanded(&self) -> bool {
        lock(&self.inner).expanded
    }

    pub(crate) fn set_expanded(&self, expanded: bool) {
        let changed = {
            let mut inner = lock(&self.inner);
            if inner.expanded == expanded {
                false
            } else {
                inner.expanded = expanded;
                true
            }
        };
        if changed {
            self.notify_property_changed("is_expanded");
        }
    }
}
