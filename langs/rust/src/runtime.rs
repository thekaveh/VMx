//! Core errors, messages, lifecycle, dispatch, and tree ownership contracts.
//!
//! Spec: `spec/03-lifecycle.md`, `spec/05-messages.md`, and `spec/06-services.md`.

use super::{
    catch_unwind, resume_unwind, thread, Arc, AssertUnwindSafe, AtomicUsize, BTreeMap, Cell,
    Condvar, Deserialize, HashSet, Mutex, MutexGuard, Ordering, Serialize, ThreadId, VecDeque,
    Weak,
};

static NEXT_ID: AtomicUsize = AtomicUsize::new(1);
pub(crate) static HIERARCHY_TOPOLOGY_GATE: Mutex<()> = Mutex::new(());

thread_local! {
    static MESSAGE_HUB_DELIVERY_DEPTH: Cell<usize> = const { Cell::new(0) };
}

struct MessageHubDeliveryGuard;

impl MessageHubDeliveryGuard {
    fn enter() -> Self {
        MESSAGE_HUB_DELIVERY_DEPTH.with(|depth| depth.set(depth.get() + 1));
        Self
    }
}

impl Drop for MessageHubDeliveryGuard {
    fn drop(&mut self) {
        MESSAGE_HUB_DELIVERY_DEPTH.with(|depth| depth.set(depth.get() - 1));
    }
}

fn is_delivering_message_hub() -> bool {
    MESSAGE_HUB_DELIVERY_DEPTH.with(|depth| depth.get() > 0)
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
    /// Flavor-idiomatic property name.
    pub property_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Describes a lifecycle-status change.
pub struct ConstructionStatusChangedMessage {
    /// Identity of the publishing view model.
    pub sender_id: usize,
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
    history: Vec<Message>,
    pending: VecDeque<Message>,
    batch_owner: Option<ThreadId>,
    batch_depth: usize,
    draining_owner: Option<ThreadId>,
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

    /// Subscribes to messages published after this call.
    pub fn subscribe<F>(&self, handler: F) -> Subscription
    where
        F: Fn(&Message) + Send + Sync + 'static,
    {
        let mut inner = lock(&self.inner.state);
        if inner.disposed {
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
        while inner.batch_owner.is_some_and(|owner| owner != current)
            || inner.draining_owner.is_some_and(|owner| owner != current)
        {
            if is_delivering_message_hub() {
                break;
            }
            inner = wait(&self.inner.ready, inner);
        }
        if inner.disposed {
            return;
        }
        inner.history.push(message.clone());
        inner.pending.push_back(message);
        if inner.batch_owner.is_some() || inner.draining_owner.is_some() {
            return;
        }
        inner.draining_owner = Some(current);
        drop(inner);
        self.drain(current);
    }

    /// Defers delivery during `transaction`, then drains queued messages in FIFO order.
    pub fn batch<F, R>(&self, transaction: F) -> R
    where
        F: FnOnce() -> R,
    {
        let current = thread::current().id();
        let mut inner = lock(&self.inner.state);
        while inner.batch_owner.is_some_and(|owner| owner != current)
            || inner.draining_owner.is_some_and(|owner| owner != current)
        {
            inner = wait(&self.inner.ready, inner);
        }
        if inner.batch_owner == Some(current) {
            inner.batch_depth += 1;
        } else {
            inner.batch_owner = Some(current);
            inner.batch_depth = 1;
        }
        drop(inner);

        let callback_result = catch_unwind(AssertUnwindSafe(transaction));
        let mut inner = lock(&self.inner.state);
        inner.batch_depth -= 1;
        let outermost = inner.batch_depth == 0;
        let should_drain = outermost
            && !inner.disposed
            && !inner.pending.is_empty()
            && inner.draining_owner != Some(current);
        if outermost {
            inner.batch_owner = None;
            if should_drain {
                inner.draining_owner = Some(current);
            }
            self.inner.ready.notify_all();
        }
        drop(inner);

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
            Err(error) => {
                // The transaction body's original panic takes precedence over
                // a development overflow diagnostic raised while draining.
                std::panic::resume_unwind(error)
            }
        }
    }

    fn drain(&self, current: ThreadId) {
        #[cfg(debug_assertions)]
        let mut delivered = 0usize;
        #[cfg(debug_assertions)]
        let mut message_types = HashSet::new();

        loop {
            let (message, subscribers) = {
                let mut inner = lock(&self.inner.state);
                if inner.disposed || inner.pending.is_empty() {
                    inner.draining_owner = None;
                    self.inner.ready.notify_all();
                    return;
                }
                debug_assert_eq!(inner.draining_owner, Some(current));
                let message = inner.pending.pop_front().expect("queue checked non-empty");
                let subscribers = inner.subscribers.values().cloned().collect::<Vec<_>>();
                (message, subscribers)
            };

            #[cfg(debug_assertions)]
            message_types.insert(message.type_name());
            for subscriber in subscribers {
                let _delivery = MessageHubDeliveryGuard::enter();
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
        while inner.batch_owner.is_some_and(|owner| owner != current)
            || inner.draining_owner.is_some_and(|owner| owner != current)
        {
            inner = wait(&self.inner.ready, inner);
        }
        inner.subscribers.clear();
        inner.pending.clear();
        inner.disposed = true;
        self.inner.ready.notify_all();
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
            lock(&hub.state).subscribers.remove(&self.id);
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
    /// Schedules `action` according to the dispatcher policy.
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>);
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

#[derive(Clone, Default)]
/// Deterministic dispatcher that queues work until explicitly drained.
pub struct ManualDispatcher {
    queue: DispatchQueue,
}

impl ManualDispatcher {
    /// Creates an empty manual dispatch queue.
    pub fn new() -> Self {
        Self::default()
    }

    /// Runs queued actions in FIFO order until the queue is empty.
    pub fn drain(&self) {
        loop {
            let action = lock(&self.queue).pop_front();
            match action {
                Some(action) => action(),
                None => break,
            }
        }
    }

    /// Returns the number of actions currently queued.
    pub fn queued_len(&self) -> usize {
        lock(&self.queue).len()
    }
}

impl Dispatcher for ManualDispatcher {
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>) {
        lock(&self.queue).push_back(action);
    }
}

type ParentLookup = Arc<dyn Fn() -> Option<ParentHandle> + Send + Sync>;
type ParentContains = Arc<dyn Fn(usize) -> bool + Send + Sync>;
type ParentDetach = Arc<dyn Fn(usize, ParentHandle) -> VmxResult<ParentTransfer> + Send + Sync>;

struct ParentHandleInner {
    id: usize,
    parent: ParentLookup,
    contains: ParentContains,
    detach: ParentDetach,
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
    commit: Option<Box<dyn FnOnce() + Send>>,
    rollback: Option<Box<dyn FnOnce() + Send>>,
}

impl ParentTransfer {
    pub(crate) fn new(
        commit: impl FnOnce() + Send + 'static,
        rollback: impl FnOnce() + Send + 'static,
    ) -> Self {
        Self {
            commit: Some(Box::new(commit)),
            rollback: Some(Box::new(rollback)),
        }
    }

    pub(crate) fn commit(mut self) {
        self.rollback = None;
        if let Some(commit) = self.commit.take() {
            commit();
        }
    }

    pub(crate) fn rollback(mut self) {
        self.commit = None;
        if let Some(rollback) = self.rollback.take() {
            rollback();
        }
    }
}

pub(crate) fn begin_parent_transfer<T: VmNode>(
    child: &T,
    destination: &ParentHandle,
) -> VmxResult<Option<ParentTransfer>> {
    if destination.contains(child.id()) {
        return Err(VmxError::DuplicateChild);
    }

    let mut cursor = Some(destination.clone());
    let mut visited = HashSet::new();
    while let Some(parent) = cursor {
        let parent_id = parent.id().ok_or(VmxError::InconsistentParent)?;
        if parent_id == child.id() {
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
        Some(parent) => match parent.detach(child.id()) {
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

    /// Reports whether expanded-only traversal should enter this node.
    fn is_expanded_for_walk(&self) -> bool {
        true
    }
}

type Hook = Arc<Mutex<dyn FnMut() -> VmxResult<()> + Send + 'static>>;
type OwnedCleanup = Box<dyn FnOnce() + Send + 'static>;
pub(crate) type ModelHint<M> = Arc<dyn Fn(&M) -> Option<String> + Send + Sync>;

#[derive(Clone)]
pub(crate) struct ComponentCore<D: Dispatcher = NullDispatcher> {
    inner: Arc<Mutex<ComponentCoreInner<D>>>,
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
    foreground: D,
    on_construct: Option<Hook>,
    on_destruct: Option<Hook>,
    on_dispose: Option<Hook>,
    owned_cleanups: Vec<OwnedCleanup>,
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
                foreground: dispatcher,
                on_construct: None,
                on_destruct: None,
                on_dispose: None,
                owned_cleanups: Vec::new(),
                selected: false,
                expanded: false,
            })),
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

    pub(crate) fn status(&self) -> ConstructionStatus {
        lock(&self.inner).status
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
        self.transition_with(operation, || Ok(()))
    }

    pub(crate) fn transition_with<F>(
        &self,
        operation: LifecycleOperation,
        action: F,
    ) -> VmxResult<()>
    where
        F: FnOnce() -> VmxResult<()>,
    {
        let (sender_id, hub, foreground, hook, target, generation) = {
            let mut inner = lock(&self.inner);
            match (inner.status, operation) {
                (ConstructionStatus::Disposed, LifecycleOperation::Construct) => {
                    return Err(VmxError::Disposed)
                }
                (ConstructionStatus::Disposed, LifecycleOperation::Destruct) => {
                    return Err(VmxError::Disposed)
                }
                (ConstructionStatus::Constructed, LifecycleOperation::Construct)
                | (ConstructionStatus::Destructed, LifecycleOperation::Destruct) => return Ok(()),
                (_, LifecycleOperation::Dispose)
                    if inner.status == ConstructionStatus::Disposed =>
                {
                    return Ok(())
                }
                _ => {}
            }
            if inner.transitioning && operation != LifecycleOperation::Dispose {
                return Err(VmxError::ConcurrentOperation);
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
            let hook = match operation {
                LifecycleOperation::Construct => inner.on_construct.clone(),
                LifecycleOperation::Destruct => inner.on_destruct.clone(),
                LifecycleOperation::Dispose => inner.on_dispose.clone(),
            };
            (
                inner.id,
                inner.hub.clone(),
                inner.foreground.clone(),
                hook,
                target,
                generation,
            )
        };

        hub.send(Message::ConstructionStatusChanged(
            ConstructionStatusChangedMessage {
                sender_id,
                status: self.status(),
            },
        ));

        let operation_result = hook
            .map(|hook| (lock(&hook))())
            .unwrap_or(Ok(()))
            .and_then(|_| action());
        if operation == LifecycleOperation::Dispose {
            self.dispose_owned();
            self.property_changed_stream().dispose();
        }
        let superseded = {
            let inner = lock(&self.inner);
            inner.transition_generation != generation
                || (operation != LifecycleOperation::Dispose
                    && inner.status == ConstructionStatus::Disposed)
        };
        if superseded {
            return operation_result;
        }
        if let Err(error) = operation_result {
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
                return Err(error);
            }
            foreground.dispatch(Box::new(move || {
                hub.send(Message::ConstructionStatusChanged(
                    ConstructionStatusChangedMessage {
                        sender_id,
                        status: rollback,
                    },
                ));
            }));
            return Err(error);
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
            foreground.dispatch(Box::new(move || {
                hub.send(Message::ConstructionStatusChanged(
                    ConstructionStatusChangedMessage {
                        sender_id,
                        status: target,
                    },
                ));
            }));
        }
        Ok(())
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
        let (sender_id, hub, local) = {
            let inner = lock(&self.inner);
            if inner.status == ConstructionStatus::Disposed {
                return;
            }
            (inner.id, inner.hub.clone(), inner.property_changed.clone())
        };
        if !local.begin_notification() {
            return;
        }
        let hub_result = catch_unwind(AssertUnwindSafe(|| {
            hub.send(Message::PropertyChanged(PropertyChangedMessage {
                sender_id,
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
        lock(&self.inner).foreground.dispatch(action);
    }

    pub(crate) fn is_selected(&self) -> bool {
        lock(&self.inner).selected
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

    pub(crate) fn select(&self) {
        let changed = {
            let mut inner = lock(&self.inner);
            if inner.selected {
                false
            } else {
                inner.selected = true;
                true
            }
        };
        if changed {
            self.notify_property_changed("is_selected");
        }
    }

    pub(crate) fn deselect(&self) {
        let changed = {
            let mut inner = lock(&self.inner);
            if inner.selected {
                inner.selected = false;
                true
            } else {
                false
            }
        };
        if changed {
            self.notify_property_changed("is_selected");
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
