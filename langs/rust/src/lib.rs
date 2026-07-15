//! VMx Rust flavor.
//!
//! The Rust flavor mirrors the VMx language-neutral specification while using
//! Rust naming and error handling. Rust has no inheritance, so the class-family
//! hierarchy used by other flavors is represented by cloneable handles,
//! trait-based contracts, and shared lifecycle/message cores.

use serde::{Deserialize, Serialize};
use std::cell::Cell;
use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::fmt;
use std::future::Future;
use std::hash::Hash;
use std::panic::{catch_unwind, resume_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, OnceLock, Weak};
use std::task::{Context, Poll};
use std::thread::{self, ThreadId};

mod aggregate_change_stream;
mod async_resource_vm;
mod async_value;
pub use aggregate_change_stream::{
    AggregateChange, AggregateChangeObservable, AggregateChangeReason, AggregateChangeStream,
    AggregateChangeSubscription, AggregateObserveOptions, ObservableMembershipSource,
    ObservablePropertySource,
};
pub use async_resource_vm::{
    AsyncResourceRetention, AsyncResourceState, AsyncResourceStatus, AsyncResourceVm,
};
pub use async_value::AsyncValue;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
pub const MIN_SPEC_VERSION: &str = "3.22.0";

static NEXT_ID: AtomicUsize = AtomicUsize::new(1);
static HIERARCHY_TOPOLOGY_GATE: Mutex<()> = Mutex::new(());

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

fn next_id() -> usize {
    NEXT_ID.fetch_add(1, Ordering::Relaxed)
}

fn lock<T: ?Sized>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn wait<'a, T>(condition: &Condvar, guard: MutexGuard<'a, T>) -> MutexGuard<'a, T> {
    condition
        .wait(guard)
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn evaluate_command_predicate(predicate: impl FnOnce() -> bool) -> bool {
    catch_unwind(AssertUnwindSafe(predicate)).unwrap_or(false)
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum VmxError {
    #[error("invalid lifecycle transition from {from:?} via {operation}")]
    InvalidLifecycleTransition {
        from: ConstructionStatus,
        operation: &'static str,
    },
    #[error("viewmodel is disposed")]
    Disposed,
    #[error("operation already in progress")]
    ConcurrentOperation,
    #[error("component is not a child of this container")]
    NonChild,
    #[error("component is already a child of this container")]
    DuplicateChild,
    #[error("container ownership would create an ancestor cycle")]
    OwnershipCycle,
    #[error("component parent state does not match parent membership")]
    InconsistentParent,
    #[error("component is not current")]
    NotCurrent,
    #[error("builder validation failed: {0}")]
    BuilderValidation(String),
    #[error("readonly model cannot be changed")]
    ReadonlyModel,
    #[error("dialog already active")]
    DialogReentrancy,
    #[error("operation cancelled")]
    Cancelled,
    #[error("invalid argument: {0}")]
    InvalidArgument(String),
    #[error("{0}")]
    Other(String),
}

pub type VmxResult<T> = Result<T, VmxError>;

fn retain_first_error(first: &mut Option<VmxError>, result: VmxResult<()>) {
    if let Err(error) = result {
        if first.is_none() {
            *first = Some(error);
        }
    }
}

fn finish_with_first_error(first: Option<VmxError>) -> VmxResult<()> {
    first.map_or(Ok(()), Err)
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub enum ConstructionStatus {
    #[default]
    Destructed,
    Constructing,
    Constructed,
    Destructing,
    Disposed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LifecycleOperation {
    Construct,
    Destruct,
    Dispose,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CollectionChangeAction {
    Add,
    Remove,
    Replace,
    Move,
    Reset,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollectionChangedMessage {
    pub sender_id: usize,
    pub property_name: String,
    pub action: CollectionChangeAction,
    pub old_index: Option<usize>,
    pub new_index: Option<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PropertyChangedMessage {
    pub sender_id: usize,
    pub property_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConstructionStatusChangedMessage {
    pub sender_id: usize,
    pub status: ConstructionStatus,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TreeStructureChangedMessage {
    pub sender_id: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FormRevertedMessage {
    pub sender_id: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Message {
    PropertyChanged(PropertyChangedMessage),
    ConstructionStatusChanged(ConstructionStatusChangedMessage),
    CollectionChanged(CollectionChangedMessage),
    TreeStructureChanged(TreeStructureChangedMessage),
    FormReverted(FormRevertedMessage),
    Custom { sender_id: usize, name: String },
}

impl Message {
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

pub struct SubscribeValueOptions<T> {
    pub fire_immediately: bool,
    equality: ValueEquality<T>,
}

impl<T: PartialEq> Default for SubscribeValueOptions<T> {
    fn default() -> Self {
        Self::with_equality(|current, next| current == next)
    }
}

impl<T> SubscribeValueOptions<T> {
    pub fn with_equality<F>(equality: F) -> Self
    where
        F: Fn(&T, &T) -> bool + Send + Sync + 'static,
    {
        Self {
            fire_immediately: false,
            equality: Arc::new(equality),
        }
    }

    pub fn fire_immediately(mut self, value: bool) -> Self {
        self.fire_immediately = value;
        self
    }
}

impl MessageHub {
    pub fn new() -> Self {
        Self::default()
    }

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

    pub fn history(&self) -> Vec<Message> {
        lock(&self.inner.state).history.clone()
    }

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
pub struct NullMessageHub;

impl NullMessageHub {
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

    fn subscribe_with_completion<F, C>(
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

pub trait Dispatcher: Clone + Send + Sync + 'static {
    fn dispatch(&self, action: Box<dyn FnOnce() + Send>);
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NullDispatcher;

impl NullDispatcher {
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
pub struct ImmediateDispatcher;

impl ImmediateDispatcher {
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
pub struct ManualDispatcher {
    queue: DispatchQueue,
}

impl ManualDispatcher {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn drain(&self) {
        loop {
            let action = lock(&self.queue).pop_front();
            match action {
                Some(action) => action(),
                None => break,
            }
        }
    }

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
    fn id(&self) -> Option<usize> {
        self.inner.upgrade().map(|inner| inner.id)
    }

    fn parent(&self) -> Option<Self> {
        self.inner.upgrade().and_then(|inner| (inner.parent)())
    }

    fn contains(&self, child_id: usize) -> bool {
        self.inner
            .upgrade()
            .is_some_and(|inner| (inner.contains)(child_id))
    }

    fn detach(&self, child_id: usize) -> VmxResult<ParentTransfer> {
        let inner = self.inner.upgrade().ok_or(VmxError::InconsistentParent)?;
        (inner.detach)(child_id, self.clone())
    }

    fn same_owner(&self, other: &Self) -> bool {
        self.inner.ptr_eq(&other.inner)
    }
}

#[derive(Clone)]
struct ParentRegistration {
    inner: Arc<ParentHandleInner>,
}

impl ParentRegistration {
    fn new(
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

    fn handle(&self) -> ParentHandle {
        ParentHandle {
            inner: Arc::downgrade(&self.inner),
        }
    }
}

struct ParentTransfer {
    commit: Option<Box<dyn FnOnce() + Send>>,
    rollback: Option<Box<dyn FnOnce() + Send>>,
}

impl ParentTransfer {
    fn new(
        commit: impl FnOnce() + Send + 'static,
        rollback: impl FnOnce() + Send + 'static,
    ) -> Self {
        Self {
            commit: Some(Box::new(commit)),
            rollback: Some(Box::new(rollback)),
        }
    }

    fn commit(mut self) {
        self.rollback = None;
        if let Some(commit) = self.commit.take() {
            commit();
        }
    }

    fn rollback(mut self) {
        self.commit = None;
        if let Some(rollback) = self.rollback.take() {
            rollback();
        }
    }
}

fn begin_parent_transfer<T: VmNode>(
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
        Some(parent) => parent.detach(child.id()).map(Some),
        None if child.parent_id().is_some() => Err(VmxError::InconsistentParent),
        None => Ok(None),
    }
}

pub trait VmNode: Clone + PartialEq + Send + Sync + 'static {
    fn id(&self) -> usize;
    fn construct(&self) -> VmxResult<()>;
    fn destruct(&self) -> VmxResult<()>;
    fn dispose(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    fn set_parent_id(&self, parent_id: Option<usize>);
    fn parent_id(&self) -> Option<usize>;
    #[doc(hidden)]
    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.set_parent_id(parent.as_ref().and_then(ParentHandle::id));
    }
    #[doc(hidden)]
    fn parent_handle(&self) -> Option<ParentHandle> {
        None
    }
    fn set_current_flag(&self, _is_current: bool) {}
    fn is_current(&self) -> bool {
        false
    }
}

pub trait TreeNode: VmNode {
    fn children_nodes(&self) -> Vec<Self> {
        Vec::new()
    }

    fn is_expanded_for_walk(&self) -> bool {
        true
    }
}

type Hook = Arc<Mutex<dyn FnMut() -> VmxResult<()> + Send + 'static>>;
type OwnedCleanup = Box<dyn FnOnce() + Send + 'static>;
type ModelHint<M> = Arc<dyn Fn(&M) -> Option<String> + Send + Sync>;

#[derive(Clone)]
struct ComponentCore<D: Dispatcher = NullDispatcher> {
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
    fn new(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
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

    fn id(&self) -> usize {
        lock(&self.inner).id
    }

    fn name(&self) -> String {
        lock(&self.inner).name.clone()
    }

    fn hint(&self) -> Option<String> {
        lock(&self.inner).hint.clone()
    }

    fn set_hint(&self, hint: Option<String>) {
        lock(&self.inner).hint = hint;
    }

    fn status(&self) -> ConstructionStatus {
        lock(&self.inner).status
    }

    fn set_hook(&self, operation: LifecycleOperation, hook: Hook) {
        let mut inner = lock(&self.inner);
        match operation {
            LifecycleOperation::Construct => inner.on_construct = Some(hook),
            LifecycleOperation::Destruct => inner.on_destruct = Some(hook),
            LifecycleOperation::Dispose => inner.on_dispose = Some(hook),
        }
    }

    fn transition(&self, operation: LifecycleOperation) -> VmxResult<()> {
        self.transition_with(operation, || Ok(()))
    }

    fn transition_with<F>(&self, operation: LifecycleOperation, action: F) -> VmxResult<()>
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

    fn hub(&self) -> MessageHub {
        lock(&self.inner).hub.clone()
    }

    fn own<F>(&self, cleanup: F)
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

    fn dispose_owned(&self) {
        let resources = {
            let mut inner = lock(&self.inner);
            std::mem::take(&mut inner.owned_cleanups)
        };
        for cleanup in resources.into_iter().rev() {
            let _ = catch_unwind(AssertUnwindSafe(cleanup));
        }
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        let mut inner = lock(&self.inner);
        inner.parent = None;
        inner.legacy_parent_id = parent_id;
    }

    fn parent_id(&self) -> Option<usize> {
        let inner = lock(&self.inner);
        inner
            .parent
            .as_ref()
            .and_then(ParentHandle::id)
            .or(inner.legacy_parent_id)
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        let mut inner = lock(&self.inner);
        inner.parent = parent;
        inner.legacy_parent_id = None;
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        lock(&self.inner).parent.clone()
    }

    fn property_changed_stream(&self) -> PropertyChangedStream {
        lock(&self.inner).property_changed.clone()
    }

    fn notify_property_changed(&self, property_name: impl Into<String>) {
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

    fn dispatch(&self, action: Box<dyn FnOnce() + Send>) {
        lock(&self.inner).foreground.dispatch(action);
    }

    fn is_selected(&self) -> bool {
        lock(&self.inner).selected
    }

    fn set_current_flag(&self, selected: bool) {
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

    fn select(&self) {
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

    fn deselect(&self) {
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

    fn is_expanded(&self) -> bool {
        lock(&self.inner).expanded
    }

    fn set_expanded(&self, expanded: bool) {
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

mod components;
pub use components::{ComponentVm, ComponentVmBuilder, ComponentVmOptions, ReadonlyComponentVm};

mod commands;
pub use commands::{
    AsyncRelayCommand, AsyncRelayCommandBuilder, CancellationToken, Command, CommandOf,
    CompositeCommand, ConfirmationDecoratorCommand, DecoratorCommand, RelayCommand,
    RelayCommandBuilder, RelayCommandOf,
};

mod collections;
pub use collections::{
    KeyedServicedObservableCollection, ObservableDictionary, ObservableList,
    ObservableMultiDictionary, ServicedObservableCollection,
};

type CurrentChangedCallback<T> = Arc<dyn Fn(Option<T>) + Send + Sync>;
type CurrentSelector<T> = Arc<dyn Fn(Vec<T>) -> Option<T> + Send + Sync>;

/// Shared ordered, observable child-collection capability without selection.
pub trait VmCollection<T: VmNode> {
    fn items(&self) -> Vec<T>;
    fn get(&self, index: usize) -> Option<T>;
    fn len(&self) -> usize;
    fn is_empty(&self) -> bool;
    fn add(&self, item: T) -> VmxResult<()>;
    fn insert(&self, index: usize, item: T) -> VmxResult<()>;
    fn remove(&self, item: &T) -> VmxResult<()>;
    fn remove_at(&self, index: usize) -> VmxResult<T>;
    fn replace(&self, index: usize, item: T) -> VmxResult<T>;
    fn clear(&self);
    fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()>;
    fn batch_update<F>(&self, action: F)
    where
        F: FnOnce();
}

/// VM collection that additionally owns a current-child selection slot.
pub trait SelectableVmCollection<T: VmNode>: VmCollection<T> {
    fn current(&self) -> Option<T>;
    fn set_current(&self, item: Option<T>) -> VmxResult<()>;
    fn select_component(&self, item: &T) -> VmxResult<()>;
    fn deselect_component(&self, item: &T) -> VmxResult<()>;
    fn can_select_component(&self, item: &T) -> bool;
}

#[derive(Clone)]
pub struct CompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    items: ObservableList<T>,
    ownership: ParentRegistration,
    current: Arc<Mutex<Option<T>>>,
    auto_construct_on_add: Arc<Mutex<bool>>,
    async_selection: Arc<Mutex<bool>>,
    current_selector: Arc<Mutex<Option<CurrentSelector<T>>>>,
    on_current_changed: Arc<Mutex<Option<CurrentChangedCallback<T>>>>,
}

impl<T: VmNode> CompositeVm<T, NullDispatcher> {
    pub fn new(name: impl Into<String>) -> Self {
        Self::with_services(name, MessageHub::new(), NullDispatcher::new())
    }
}

impl<T: VmNode, D: Dispatcher> CompositeVm<T, D> {
    pub fn with_services(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        let core = ComponentCore::new(name, hub.clone(), dispatcher);
        let items: ObservableList<T> = ObservableList::new(core.id(), hub);
        let current = Arc::new(Mutex::new(None));
        let current_selector = Arc::new(Mutex::new(None));
        let on_current_changed: Arc<Mutex<Option<CurrentChangedCallback<T>>>> =
            Arc::new(Mutex::new(None));
        let ownership = ParentRegistration::new(
            core.id(),
            {
                let core = core.clone();
                move || core.parent_handle()
            },
            {
                let items = items.clone();
                move |child_id| items.to_vec().iter().any(|item| item.id() == child_id)
            },
            {
                let core = core.clone();
                let items = items.clone();
                let current = Arc::clone(&current);
                let on_current_changed = Arc::clone(&on_current_changed);
                move |child_id, owner_handle| {
                    let index = items
                        .to_vec()
                        .iter()
                        .position(|item| item.id() == child_id)
                        .ok_or(VmxError::InconsistentParent)?;
                    let removed = items
                        .remove_at_silent(index)
                        .ok_or(VmxError::InconsistentParent)?;
                    let was_current = lock(&current)
                        .as_ref()
                        .is_some_and(|item: &T| item.id() == child_id);
                    let commit_items = items.clone();
                    let commit_current = Arc::clone(&current);
                    let commit_callback = Arc::clone(&on_current_changed);
                    let commit_core = core.clone();
                    let commit_removed = removed.clone();
                    let rollback_items = items.clone();
                    Ok(ParentTransfer::new(
                        move || {
                            if was_current {
                                *lock(&commit_current) = None;
                                commit_removed.set_current_flag(false);
                                commit_core.notify_property_changed("current");
                                if let Some(callback) = lock(&commit_callback).clone() {
                                    callback(None);
                                }
                            }
                            commit_items.publish_remove(index);
                        },
                        move || {
                            rollback_items
                                .insert_silent(index, removed.clone())
                                .expect("rollback index remains valid");
                            removed.set_parent_handle(Some(owner_handle));
                        },
                    ))
                }
            },
        );
        Self {
            core,
            items,
            ownership,
            current,
            auto_construct_on_add: Arc::new(Mutex::new(false)),
            async_selection: Arc::new(Mutex::new(false)),
            current_selector,
            on_current_changed,
        }
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn name(&self) -> String {
        self.core.name()
    }

    pub fn hint(&self) -> Option<String> {
        self.core.hint()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.core.own(cleanup);
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    pub fn items(&self) -> Vec<T> {
        self.items.to_vec()
    }

    pub fn get(&self, index: usize) -> Option<T> {
        self.items.get(index)
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    pub fn add(&self, item: T) -> VmxResult<()> {
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        item.set_parent_handle(Some(self.ownership.handle()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            if let Err(error) = item.construct() {
                item.set_parent_handle(None);
                if let Some(transfer) = transfer {
                    transfer.rollback();
                }
                return Err(error);
            }
        }
        if let Some(transfer) = transfer {
            transfer.commit();
        }
        self.items.push(item);
        Ok(())
    }

    fn attach_population(&self, candidates: Vec<T>, construct: bool) -> VmxResult<()> {
        let start = self.len();
        let mut transfers = Vec::with_capacity(candidates.len());
        let mut original_statuses = Vec::with_capacity(candidates.len());
        let result = (|| {
            for child in &candidates {
                let transfer = begin_parent_transfer(child, &self.ownership.handle())?;
                transfers.push(transfer);
                original_statuses.push(child.status());
                child.set_parent_handle(Some(self.ownership.handle()));
                self.items.insert_silent(self.len(), child.clone())?;
            }
            // Make the entire snapshot visible before any child hook runs.
            if construct {
                for child in &candidates {
                    if child.status() != ConstructionStatus::Constructed {
                        child.construct()?;
                    }
                }
            }
            Ok(())
        })();
        if let Err(error) = result {
            while self.len() > start {
                let _ = self.items.remove_at_silent(self.len() - 1);
            }
            for (child, original_status) in candidates
                .iter()
                .zip(&original_statuses)
                .take(transfers.len())
                .rev()
            {
                if *original_status == ConstructionStatus::Destructed
                    && child.status() == ConstructionStatus::Constructed
                {
                    let _ = child.destruct();
                }
                if child
                    .parent_handle()
                    .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
                {
                    child.set_parent_handle(None);
                }
            }
            for transfer in transfers.into_iter().rev().flatten() {
                transfer.rollback();
            }
            return Err(error);
        }

        for transfer in transfers.into_iter().flatten() {
            transfer.commit();
        }
        for child in &candidates {
            if let Some(index) = self
                .items
                .to_vec()
                .iter()
                .position(|candidate| candidate.id() == child.id())
                .filter(|index| *index >= start)
            {
                self.items.publish_add(index);
            }
        }
        Ok(())
    }

    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        if index > self.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        item.set_parent_handle(Some(self.ownership.handle()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            if let Err(error) = item.construct() {
                item.set_parent_handle(None);
                if let Some(transfer) = transfer {
                    transfer.rollback();
                }
                return Err(error);
            }
        }
        if let Some(transfer) = transfer {
            transfer.commit();
        }
        self.items.insert(index, item)
    }

    pub fn remove(&self, item: &T) -> VmxResult<()> {
        let index = self
            .items()
            .iter()
            .position(|candidate| candidate == item)
            .ok_or(VmxError::NonChild)?;
        let removed = self.items.remove_at(index).expect("index checked");
        if removed
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            removed.set_parent_handle(None);
        }
        if lock(&self.current).as_ref() == Some(&removed) {
            self.assign_current(None);
        }
        Ok(())
    }

    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let removed = self
            .items
            .remove_at(index)
            .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?;
        if removed
            .parent_handle()
            .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
        {
            removed.set_parent_handle(None);
        }
        if lock(&self.current).as_ref() == Some(&removed) {
            self.assign_current(None);
        }
        Ok(removed)
    }

    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let old = self
            .items
            .get(index)
            .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?;
        let transfer = begin_parent_transfer(&item, &self.ownership.handle())?;
        item.set_parent_handle(Some(self.ownership.handle()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            if let Err(error) = item.construct() {
                item.set_parent_handle(None);
                if let Some(transfer) = transfer {
                    transfer.rollback();
                }
                return Err(error);
            }
        }
        if let Some(transfer) = transfer {
            transfer.commit();
        }
        old.set_parent_handle(None);
        if lock(&self.current).as_ref() == Some(&old) {
            self.assign_current(None);
        }
        self.items.replace(index, item)?;
        Ok(old)
    }

    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        self.items.move_item(from_index, to_index)
    }

    pub fn clear(&self) {
        for item in self.items() {
            if item
                .parent_handle()
                .is_some_and(|parent| parent.same_owner(&self.ownership.handle()))
            {
                item.set_parent_handle(None);
            }
            item.set_current_flag(false);
        }
        self.assign_current(None);
        self.items.clear();
    }

    pub fn current(&self) -> Option<T> {
        lock(&self.current).clone()
    }

    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        if let Some(item) = item.as_ref() {
            if !self.items().iter().any(|candidate| candidate == item) {
                return Err(VmxError::NonChild);
            }
        }
        self.assign_current_maybe_async(item);
        Ok(())
    }

    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        if !self.can_select_component(item) {
            return Err(VmxError::NonChild);
        }
        self.assign_current_maybe_async(Some(item.clone()));
        Ok(())
    }

    pub fn deselect_component(&self, item: &T) -> VmxResult<()> {
        if self.current().as_ref() != Some(item) {
            return Err(VmxError::NotCurrent);
        }
        self.assign_current_maybe_async(None);
        Ok(())
    }

    pub fn can_select_component(&self, item: &T) -> bool {
        self.items().iter().any(|candidate| candidate == item)
            && item.status() == ConstructionStatus::Constructed
    }

    pub fn set_auto_construct_on_add(&self, enabled: bool) {
        *lock(&self.auto_construct_on_add) = enabled;
    }

    pub fn set_async_selection(&self, enabled: bool) {
        *lock(&self.async_selection) = enabled;
    }

    pub fn set_current_selector<F>(&self, selector: F)
    where
        F: Fn(Vec<T>) -> Option<T> + Send + Sync + 'static,
    {
        *lock(&self.current_selector) = Some(Arc::new(selector));
    }

    pub fn on_current_changed<F>(&self, callback: F)
    where
        F: Fn(Option<T>) + Send + Sync + 'static,
    {
        *lock(&self.on_current_changed) = Some(Arc::new(callback));
    }

    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        self.items.batch_update(action);
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                for item in self.items() {
                    item.construct()?;
                }
                if let Some(selector) = lock(&self.current_selector).clone() {
                    if let Some(selected) = selector(self.items()) {
                        if self.items().contains(&selected) {
                            self.assign_current(selected.into());
                        }
                    }
                }
                Ok(())
            })
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            self.assign_current(None);
            for item in self.items() {
                item.destruct()?;
            }
            Ok(())
        })
    }

    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        for item in self.items() {
            retain_first_error(&mut first_error, item.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
    }

    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }

    pub fn reconstruct(&self) -> VmxResult<()> {
        self.destruct()?;
        self.construct()
    }

    pub fn is_constructed(&self) -> bool {
        self.status() == ConstructionStatus::Constructed
    }

    pub fn parent_id(&self) -> Option<usize> {
        self.core.parent_id()
    }

    fn assign_current(&self, next: Option<T>) {
        let previous = {
            let mut current = lock(&self.current);
            if *current == next {
                return;
            }
            let previous = current.clone();
            *current = next.clone();
            previous
        };
        if let Some(previous) = previous {
            previous.set_current_flag(false);
        }
        if let Some(next_current) = next.clone() {
            next_current.set_current_flag(true);
        }
        self.core.notify_property_changed("current");
        self.invoke_current_changed(next);
    }

    fn assign_current_maybe_async(&self, next: Option<T>) {
        if *lock(&self.async_selection) {
            let this = self.clone();
            self.core
                .dispatch(Box::new(move || this.assign_current(next)));
        } else {
            self.assign_current(next);
        }
    }

    fn invoke_current_changed(&self, current: Option<T>) {
        if let Some(callback) = lock(&self.on_current_changed).clone() {
            callback(current);
        }
    }
}

impl<T: VmNode, D: Dispatcher> VmCollection<T> for CompositeVm<T, D> {
    fn items(&self) -> Vec<T> {
        CompositeVm::items(self)
    }
    fn get(&self, index: usize) -> Option<T> {
        CompositeVm::get(self, index)
    }
    fn len(&self) -> usize {
        CompositeVm::len(self)
    }
    fn is_empty(&self) -> bool {
        CompositeVm::is_empty(self)
    }
    fn add(&self, item: T) -> VmxResult<()> {
        CompositeVm::add(self, item)
    }
    fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        CompositeVm::insert(self, index, item)
    }
    fn remove(&self, item: &T) -> VmxResult<()> {
        CompositeVm::remove(self, item)
    }
    fn remove_at(&self, index: usize) -> VmxResult<T> {
        CompositeVm::remove_at(self, index)
    }
    fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        CompositeVm::replace(self, index, item)
    }
    fn clear(&self) {
        CompositeVm::clear(self);
    }
    fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        CompositeVm::move_item(self, from_index, to_index)
    }
    fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        CompositeVm::batch_update(self, action);
    }
}

impl<T: VmNode, D: Dispatcher> SelectableVmCollection<T> for CompositeVm<T, D> {
    fn current(&self) -> Option<T> {
        CompositeVm::current(self)
    }
    fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        CompositeVm::set_current(self, item)
    }
    fn select_component(&self, item: &T) -> VmxResult<()> {
        CompositeVm::select_component(self, item)
    }
    fn deselect_component(&self, item: &T) -> VmxResult<()> {
        CompositeVm::deselect_component(self, item)
    }
    fn can_select_component(&self, item: &T) -> bool {
        CompositeVm::can_select_component(self, item)
    }
}

impl<T: VmNode, D: Dispatcher> VmNode for CompositeVm<T, D> {
    fn id(&self) -> usize {
        CompositeVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        CompositeVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        CompositeVm::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        CompositeVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        CompositeVm::status(self)
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.core.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.core.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.core.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.core.parent_handle()
    }

    fn set_current_flag(&self, is_current: bool) {
        self.core.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.core.is_selected()
    }
}

impl<T: TreeNode, D: Dispatcher> TreeNode for CompositeVm<T, D> {
    fn children_nodes(&self) -> Vec<Self> {
        Vec::new()
    }
}

impl<T: TreeNode, D: Dispatcher> CompositeVm<T, D> {
    pub fn child_nodes(&self) -> Vec<T> {
        self.items()
    }

    pub fn is_expanded_for_walk(&self) -> bool {
        self.core.is_expanded()
    }
}

impl<T: VmNode, D: Dispatcher> PartialEq for CompositeVm<T, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T: VmNode, D: Dispatcher> Eq for CompositeVm<T, D> {}

type FilterPredicate<T> = Arc<dyn Fn(&T) -> bool + Send + Sync>;
type ScorePredicate<T> = Arc<dyn Fn(&T) -> Option<i32> + Send + Sync>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FilteredCursorPolicy {
    Clear,
    SnapToFirst,
}

#[derive(Clone)]
pub struct FilteredCompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    source: CompositeVm<T, D>,
    predicate: Arc<Mutex<FilterPredicate<T>>>,
    scorer: Arc<Mutex<Option<ScorePredicate<T>>>>,
    current: Arc<Mutex<Option<T>>>,
    cursor_policy: Arc<Mutex<FilteredCursorPolicy>>,
    disposed: Arc<Mutex<bool>>,
    frozen: Arc<Mutex<Vec<T>>>,
}

impl<T: VmNode, D: Dispatcher> FilteredCompositeVm<T, D> {
    pub fn new<F>(source: CompositeVm<T, D>, predicate: F) -> Self
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        Self {
            source,
            predicate: Arc::new(Mutex::new(Arc::new(predicate))),
            scorer: Arc::new(Mutex::new(None)),
            current: Arc::new(Mutex::new(None)),
            cursor_policy: Arc::new(Mutex::new(FilteredCursorPolicy::Clear)),
            disposed: Arc::new(Mutex::new(false)),
            frozen: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn hub(&self) -> MessageHub {
        self.source.hub()
    }

    pub fn scored<F>(source: CompositeVm<T, D>, scorer: F) -> Self
    where
        F: Fn(&T) -> Option<i32> + Send + Sync + 'static,
    {
        Self {
            source,
            predicate: Arc::new(Mutex::new(Arc::new(|_| true))),
            scorer: Arc::new(Mutex::new(Some(Arc::new(scorer)))),
            current: Arc::new(Mutex::new(None)),
            cursor_policy: Arc::new(Mutex::new(FilteredCursorPolicy::Clear)),
            disposed: Arc::new(Mutex::new(false)),
            frozen: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn visible(&self) -> Vec<T> {
        if *lock(&self.disposed) {
            return lock(&self.frozen).clone();
        }
        let predicate = lock(&self.predicate).clone();
        let scorer = lock(&self.scorer).clone();
        let mut indexed = self
            .source
            .items()
            .into_iter()
            .enumerate()
            .filter(|(_, item)| predicate(item))
            .filter_map(|(index, item)| match &scorer {
                Some(score) => score(&item).map(|score| (index, Some(score), item)),
                None => Some((index, None, item)),
            })
            .collect::<Vec<_>>();
        if scorer.is_some() {
            indexed.sort_by(
                |(left_index, left_score, _), (right_index, right_score, _)| {
                    right_score
                        .cmp(left_score)
                        .then_with(|| left_index.cmp(right_index))
                },
            );
        }
        indexed.into_iter().map(|(_, _, item)| item).collect()
    }

    pub fn visible_count(&self) -> usize {
        self.visible().len()
    }

    pub fn current(&self) -> Option<T> {
        lock(&self.current).clone()
    }

    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        if let Some(item) = item.as_ref() {
            if !self.visible().contains(item) {
                return Err(VmxError::NonChild);
            }
        }
        *lock(&self.current) = item;
        Ok(())
    }

    pub fn set_predicate<F>(&self, predicate: F)
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        *lock(&self.predicate) = Arc::new(predicate);
        self.reconcile_current();
    }

    pub fn set_cursor_policy(&self, policy: FilteredCursorPolicy) {
        *lock(&self.cursor_policy) = policy;
    }

    pub fn refresh(&self) {
        self.reconcile_current();
    }

    pub fn refresh_scores(&self) {
        self.reconcile_current();
    }

    pub fn move_next_visible(&self) {
        let visible = self.visible();
        if visible.is_empty() {
            *lock(&self.current) = None;
            return;
        }
        let next_index = self
            .current()
            .and_then(|current| visible.iter().position(|item| *item == current))
            .map(|index| (index + 1).min(visible.len() - 1))
            .unwrap_or(0);
        *lock(&self.current) = Some(visible[next_index].clone());
    }

    pub fn move_previous_visible(&self) {
        let visible = self.visible();
        if visible.is_empty() {
            *lock(&self.current) = None;
            return;
        }
        let previous_index = self
            .current()
            .and_then(|current| visible.iter().position(|item| *item == current))
            .map(|index| index.saturating_sub(1))
            .unwrap_or(0);
        *lock(&self.current) = Some(visible[previous_index].clone());
    }

    pub fn dispose(&self) {
        *lock(&self.frozen) = self.visible();
        *lock(&self.disposed) = true;
    }

    fn reconcile_current(&self) {
        let visible = self.visible();
        let current_is_visible = self
            .current()
            .map(|current| visible.contains(&current))
            .unwrap_or(true);
        if current_is_visible {
            return;
        }
        let next = match *lock(&self.cursor_policy) {
            FilteredCursorPolicy::Clear => None,
            FilteredCursorPolicy::SnapToFirst => visible.first().cloned(),
        };
        *lock(&self.current) = next;
    }
}

type ChildrenFactory<T> = Arc<dyn Fn() -> Vec<T> + Send + Sync>;

#[derive(Clone)]
pub struct CompositeVmBuilder<T: VmNode, D: Dispatcher = NullDispatcher> {
    name: Option<String>,
    hint: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    children: Option<ChildrenFactory<T>>,
    auto_construct_on_add: bool,
    async_selection: bool,
    current_selector: Option<CurrentSelector<T>>,
}

impl<T: VmNode> Default for CompositeVmBuilder<T, NullDispatcher> {
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            hub: None,
            dispatcher: None,
            children: None,
            auto_construct_on_add: false,
            async_selection: false,
            current_selector: None,
        }
    }
}

impl<T: VmNode, D: Dispatcher> CompositeVmBuilder<T, D> {
    pub fn name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    pub fn hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }

    pub fn services(mut self, hub: MessageHub, dispatcher: D) -> Self {
        self.hub = Some(hub);
        self.dispatcher = Some(dispatcher);
        self
    }

    pub fn children<F>(mut self, children: F) -> Self
    where
        F: Fn() -> Vec<T> + Send + Sync + 'static,
    {
        self.children = Some(Arc::new(children));
        self
    }

    pub fn auto_construct_on_add(mut self, enabled: bool) -> Self {
        self.auto_construct_on_add = enabled;
        self
    }

    pub fn async_selection(mut self, enabled: bool) -> Self {
        self.async_selection = enabled;
        self
    }

    pub fn current<F>(mut self, selector: F) -> Self
    where
        F: Fn(Vec<T>) -> Option<T> + Send + Sync + 'static,
    {
        self.current_selector = Some(Arc::new(selector));
        self
    }

    pub fn build(self) -> VmxResult<CompositeVm<T, D>> {
        let name = self
            .name
            .ok_or_else(|| VmxError::BuilderValidation("name is required".to_string()))?;
        let children = self
            .children
            .ok_or_else(|| VmxError::BuilderValidation("children is required".to_string()))?;
        let hub = self
            .hub
            .ok_or_else(|| VmxError::BuilderValidation("hub is required".to_string()))?;
        let dispatcher = self
            .dispatcher
            .ok_or_else(|| VmxError::BuilderValidation("dispatcher is required".to_string()))?;
        let vm = CompositeVm::with_services(name, hub, dispatcher);
        if let Some(hint) = self.hint {
            vm.core.set_hint(Some(hint));
        }
        vm.set_auto_construct_on_add(self.auto_construct_on_add);
        vm.set_async_selection(self.async_selection);
        if let Some(selector) = self.current_selector {
            vm.set_current_selector(move |items| selector(items));
        }
        vm.attach_population(children(), false)?;
        Ok(vm)
    }
}

impl<T: VmNode> CompositeVm<T, NullDispatcher> {
    pub fn builder() -> CompositeVmBuilder<T, NullDispatcher> {
        CompositeVmBuilder::default()
    }

    pub fn create(options: CompositeVmOptions<T>) -> VmxResult<Self> {
        let mut builder = Self::builder();
        if let Some(name) = options.name {
            builder = builder.name(name);
        }
        if let Some(hint) = options.hint {
            builder = builder.hint(hint);
        }
        if let Some(children) = options.children {
            builder = builder.children(move || children.clone());
        }
        builder
            .services(options.hub, options.dispatcher)
            .auto_construct_on_add(options.auto_construct_on_add)
            .build()
    }
}

pub struct CompositeVmOptions<T: VmNode> {
    pub name: Option<String>,
    pub hint: Option<String>,
    pub hub: MessageHub,
    pub dispatcher: NullDispatcher,
    pub children: Option<Vec<T>>,
    pub auto_construct_on_add: bool,
}

type ModelFactory<M> = Arc<dyn Fn() -> Vec<M> + Send + Sync>;
type ChildModelMapper<M, T> = Arc<dyn Fn(M) -> T + Send + Sync>;

#[derive(Clone)]
pub struct ModeledCompositeVm<
    M: Clone + PartialEq + Send + Sync + 'static,
    T: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    inner: CompositeVm<T, D>,
    children_models: ModelFactory<M>,
    child_model_to_child_view_model: ChildModelMapper<M, T>,
    loaded: Arc<Mutex<bool>>,
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher>
    ModeledCompositeVm<M, T, D>
{
    pub fn new<F, G>(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        children_models: F,
        child_model_to_child_view_model: G,
    ) -> Self
    where
        F: Fn() -> Vec<M> + Send + Sync + 'static,
        G: Fn(M) -> T + Send + Sync + 'static,
    {
        Self {
            inner: CompositeVm::with_services(name, hub, dispatcher),
            children_models: Arc::new(children_models),
            child_model_to_child_view_model: Arc::new(child_model_to_child_view_model),
            loaded: Arc::new(Mutex::new(false)),
        }
    }

    pub fn builder() -> ModeledCompositeVmBuilder<M, T, D> {
        ModeledCompositeVmBuilder::default()
    }

    pub fn items(&self) -> Vec<T> {
        self.inner.items()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.property_changed()
    }

    pub fn hub(&self) -> MessageHub {
        self.inner.hub()
    }

    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.inner.own(cleanup);
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.notify_property_changed(property_name);
    }

    pub fn get(&self, index: usize) -> Option<T> {
        self.inner.get(index)
    }

    pub fn len(&self) -> usize {
        self.inner.len()
    }

    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    pub fn current(&self) -> Option<T> {
        self.inner.current()
    }

    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        self.inner.set_current(item)
    }

    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        self.inner.select_component(item)
    }

    pub fn construct(&self) -> VmxResult<()> {
        let should_load = !*lock(&self.loaded);
        if should_load {
            let children = (self.children_models)()
                .into_iter()
                .map(|model| (self.child_model_to_child_view_model)(model))
                .collect();
            self.inner.attach_population(children, true)?;
            *lock(&self.loaded) = true;
        }
        self.inner.construct()
    }

    pub fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    pub fn reconstruct(&self) -> VmxResult<()> {
        self.inner.reconstruct()
    }

    pub fn is_constructed(&self) -> bool {
        self.inner.is_constructed()
    }

    pub fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> VmNode
    for ModeledCompositeVm<M, T, D>
{
    fn id(&self) -> usize {
        self.inner.id()
    }

    fn construct(&self) -> VmxResult<()> {
        ModeledCompositeVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner.core.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.inner.core.parent_handle()
    }

    fn set_current_flag(&self, is_current: bool) {
        self.inner.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.inner.is_current()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> PartialEq
    for ModeledCompositeVm<M, T, D>
{
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> Eq
    for ModeledCompositeVm<M, T, D>
{
}

#[derive(Clone)]
pub struct ModeledCompositeVmBuilder<
    M: Clone + PartialEq + Send + Sync + 'static,
    T: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    name: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    children_models: Option<ModelFactory<M>>,
    child_model_to_child_view_model: Option<ChildModelMapper<M, T>>,
    async_selection: bool,
    current_selector: Option<CurrentSelector<T>>,
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher> Default
    for ModeledCompositeVmBuilder<M, T, D>
{
    fn default() -> Self {
        Self {
            name: None,
            hub: None,
            dispatcher: None,
            children_models: None,
            child_model_to_child_view_model: None,
            async_selection: false,
            current_selector: None,
        }
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static, T: VmNode, D: Dispatcher>
    ModeledCompositeVmBuilder<M, T, D>
{
    pub fn name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    pub fn services(mut self, hub: MessageHub, dispatcher: D) -> Self {
        self.hub = Some(hub);
        self.dispatcher = Some(dispatcher);
        self
    }

    pub fn children_models<F>(mut self, children_models: F) -> Self
    where
        F: Fn() -> Vec<M> + Send + Sync + 'static,
    {
        self.children_models = Some(Arc::new(children_models));
        self
    }

    pub fn child_model_to_child_view_model<G>(mut self, mapper: G) -> Self
    where
        G: Fn(M) -> T + Send + Sync + 'static,
    {
        self.child_model_to_child_view_model = Some(Arc::new(mapper));
        self
    }

    pub fn async_selection(mut self, enabled: bool) -> Self {
        self.async_selection = enabled;
        self
    }

    pub fn current<F>(mut self, selector: F) -> Self
    where
        F: Fn(Vec<T>) -> Option<T> + Send + Sync + 'static,
    {
        self.current_selector = Some(Arc::new(selector));
        self
    }

    pub fn build(self) -> VmxResult<ModeledCompositeVm<M, T, D>> {
        let name = self
            .name
            .ok_or_else(|| VmxError::BuilderValidation("name is required".to_string()))?;
        let hub = self
            .hub
            .ok_or_else(|| VmxError::BuilderValidation("hub is required".to_string()))?;
        let dispatcher = self
            .dispatcher
            .ok_or_else(|| VmxError::BuilderValidation("dispatcher is required".to_string()))?;
        let children_models = self.children_models.ok_or_else(|| {
            VmxError::BuilderValidation("children_models is required".to_string())
        })?;
        let child_model_to_child_view_model =
            self.child_model_to_child_view_model.ok_or_else(|| {
                VmxError::BuilderValidation(
                    "child_model_to_child_view_model is required".to_string(),
                )
            })?;
        let vm = ModeledCompositeVm {
            inner: CompositeVm::with_services(name, hub, dispatcher),
            children_models,
            child_model_to_child_view_model,
            loaded: Arc::new(Mutex::new(false)),
        };
        vm.inner.set_async_selection(self.async_selection);
        if let Some(selector) = self.current_selector {
            vm.inner.set_current_selector(move |items| selector(items));
        }
        Ok(vm)
    }
}

mod groups;
pub use groups::{GroupVm, GroupVmBuilder, GroupVmOptions};

mod paged_composition;
pub use paged_composition::PagedComposition;

mod searchable_state;
pub use searchable_state::SearchableState;

mod modeled_crud;
pub use modeled_crud::ModeledCrudCommands;

mod derived_property;
pub use derived_property::DerivedProperty;

mod notifications;
pub use notifications::{
    make_confirm, Notification, NotificationHub, NotificationReaction, NotificationType,
    NotificationWaiter, NullNotificationHub,
};
mod dialogs;
pub use dialogs::{
    DialogService, FileFilter, Localizer, NotificationSeverity, NullDialogService, NullLocalizer,
};
mod forms;
pub use forms::{FormVm, FormVmBuilder};

mod discriminator;
pub use discriminator::DiscriminatorVm;

mod hierarchical;
pub use hierarchical::{
    find, walk, walk_expanded, BatchAttachRejection, BatchAttachRejectionReason, BatchAttachResult,
    HierarchicalVm, HierarchicalVmBuilder, MissingParentPolicy,
};
pub fn lifecycle_transition_fixture() -> &'static str {
    include_str!("fixtures/lifecycle-transitions.json")
}

mod capabilities;
pub use capabilities::{
    Approvable, Cancelable, Closable, Collapsible, Constructable, CurrentDeletable,
    CurrentUpdatable, Deletable, Deselectable, Destructable, Expandable, ExpandableState,
    ExpansionTogglable, Filterable, Managable, NewCreatable, Pageable, Reconstructable, Savable,
    Searchable, Selectable, SelectionTogglable, Updatable,
};
mod aggregates;
pub use aggregates::{
    AggregateVm, AggregateVm1, AggregateVm1Builder, AggregateVm2, AggregateVm2Builder,
    AggregateVm3, AggregateVm3Builder, AggregateVm4, AggregateVm4Builder, AggregateVm5,
    AggregateVm5Builder, AggregateVm6, AggregateVm6Builder,
};
mod forwarding;
pub use forwarding::{ForwardingComponentVm, ForwardingCompositeVm};

mod token_paging;
pub use token_paging::TokenPagedComposition;

mod specialized_vms;
pub use specialized_vms::{ConfirmationVm, ModalVm, NotificationVm};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn component_constructs_and_disposes() {
        let vm = ComponentVm::new("test");
        vm.construct().unwrap();
        assert_eq!(vm.status(), ConstructionStatus::Constructed);
        vm.dispose().unwrap();
        assert_eq!(vm.status(), ConstructionStatus::Disposed);
    }

    #[test]
    fn failed_dispose_hook_still_completes_property_changed() {
        let vm = ComponentVm::new("test");
        let completions = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&completions);
        let _subscription = vm.property_changed().subscribe_with_completion(
            |_| {},
            move || {
                observed.fetch_add(1, Ordering::SeqCst);
            },
        );
        vm.on_dispose(|| Err(VmxError::Other("boom".to_string())));

        assert!(vm.dispose().is_err());

        assert_eq!(vm.status(), ConstructionStatus::Disposed);
        assert_eq!(completions.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn form_dispose_completes_component_property_changed() {
        let form = FormVm::new("form", 1);
        let completions = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&completions);
        let _subscription = form.component.property_changed().subscribe_with_completion(
            |_| {},
            move || {
                observed.fetch_add(1, Ordering::SeqCst);
            },
        );

        form.dispose();

        assert_eq!(completions.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn message_hub_is_hot_and_resilient() {
        let hub = MessageHub::new();
        hub.send(Message::Custom {
            sender_id: 1,
            name: "before".to_string(),
        });
        let seen = Arc::new(Mutex::new(Vec::new()));
        let seen_clone = seen.clone();
        let _sub = hub.subscribe(move |message| lock(&seen_clone).push(message.clone()));
        hub.send(Message::Custom {
            sender_id: 1,
            name: "after".to_string(),
        });
        assert_eq!(lock(&seen).len(), 1);
    }
}
