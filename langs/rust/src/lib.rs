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

/// A modeled leaf viewmodel whose name and hint are fixed at construction.
///
/// ```compile_fail
/// use vmx::ComponentVm;
///
/// let vm = ComponentVm::new("component");
/// vm.set_hint(Some("changed".to_string()));
/// ```
#[derive(Clone)]
pub struct ComponentVm<M = (), D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    model: Arc<Mutex<M>>,
    model_hint: ModelHint<M>,
}

impl ComponentVm<(), NullDispatcher> {
    pub fn new(name: impl Into<String>) -> Self {
        Self::with_services(name, MessageHub::new(), NullDispatcher::new())
    }
}

impl<D: Dispatcher> ComponentVm<(), D> {
    pub fn with_services(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        Self::with_model(name, (), hub, dispatcher)
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ComponentVm<M, D> {
    pub fn with_model(name: impl Into<String>, model: M, hub: MessageHub, dispatcher: D) -> Self {
        Self {
            core: ComponentCore::new(name, hub, dispatcher),
            model: Arc::new(Mutex::new(model)),
            model_hint: Arc::new(|_| None),
        }
    }

    pub fn with_model_hint<F>(self, hint: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        Self {
            model_hint: Arc::new(hint),
            ..self
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

    pub fn modeled_hint(&self) -> Option<String> {
        let model = lock(&self.model).clone();
        (self.model_hint)(&model)
    }

    pub fn model(&self) -> M {
        lock(&self.model).clone()
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

    pub fn republish_model(&self) {
        self.core.notify_property_changed("model");
    }

    pub fn set_model(&self, model: M) {
        if self.status() == ConstructionStatus::Disposed {
            return;
        }
        let old_hint = self.modeled_hint();
        let changed = self.replace_model(model);
        if changed {
            self.core.notify_property_changed("model");
            if self.modeled_hint() != old_hint {
                self.core.notify_property_changed("modeled_hint");
            }
        }
    }

    fn replace_model(&self, model: M) -> bool {
        let mut current = lock(&self.model);
        if *current == model {
            false
        } else {
            *current = model;
            true
        }
    }

    pub fn on_construct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Construct, Arc::new(Mutex::new(hook)));
    }

    pub fn on_destruct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Destruct, Arc::new(Mutex::new(hook)));
    }

    pub fn on_dispose<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Dispose, Arc::new(Mutex::new(hook)));
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.core.transition(LifecycleOperation::Construct)
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition(LifecycleOperation::Destruct)
    }

    pub fn reconstruct(&self) -> VmxResult<()> {
        self.destruct()?;
        self.construct()
    }

    pub fn dispose(&self) -> VmxResult<()> {
        self.core.transition(LifecycleOperation::Dispose)
    }

    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }

    pub fn is_constructed(&self) -> bool {
        self.status() == ConstructionStatus::Constructed
    }

    pub fn select(&self) {
        self.core.select();
    }

    pub fn deselect(&self) {
        self.core.deselect();
    }

    pub fn is_selected(&self) -> bool {
        self.core.is_selected()
    }

    pub fn expand(&self) {
        self.core.set_expanded(true);
    }

    pub fn collapse(&self) {
        self.core.set_expanded(false);
    }

    pub fn toggle_expansion(&self) {
        self.core.set_expanded(!self.core.is_expanded());
    }

    pub fn is_expanded(&self) -> bool {
        self.core.is_expanded()
    }

    pub fn parent_id(&self) -> Option<usize> {
        self.core.parent_id()
    }

    pub fn select_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new({
            let vm = vm.clone();
            move || vm.select()
        })
        .with_can_execute(move || !vm.is_selected())
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> VmNode for ComponentVm<M, D> {
    fn id(&self) -> usize {
        ComponentVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        ComponentVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        ComponentVm::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        ComponentVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        ComponentVm::status(self)
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

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> TreeNode for ComponentVm<M, D> {
    fn is_expanded_for_walk(&self) -> bool {
        self.is_expanded()
    }
}

impl<M, D: Dispatcher> PartialEq for ComponentVm<M, D> {
    fn eq(&self, other: &Self) -> bool {
        self.core.id() == other.core.id()
    }
}

impl<M, D: Dispatcher> Eq for ComponentVm<M, D> {}

impl<M, D: Dispatcher> fmt::Debug for ComponentVm<M, D> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ComponentVm")
            .field("id", &self.core.id())
            .field("name", &self.core.name())
            .field("status", &self.core.status())
            .finish()
    }
}

/// A modeled leaf viewmodel whose model cannot be replaced after construction.
///
/// ```compile_fail
/// use vmx::{MessageHub, NullDispatcher, ReadonlyComponentVm};
///
/// let vm = ReadonlyComponentVm::new(
///     "readonly",
///     1,
///     MessageHub::new(),
///     NullDispatcher::new(),
/// );
/// vm.as_component().set_model(2);
/// ```
#[derive(Clone)]
pub struct ReadonlyComponentVm<M: Clone + Send + 'static, D: Dispatcher = NullDispatcher> {
    inner: ComponentVm<M, D>,
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ReadonlyComponentVm<M, D> {
    pub fn new(name: impl Into<String>, model: M, hub: MessageHub, dispatcher: D) -> Self {
        Self {
            inner: ComponentVm::with_model(name, model, hub, dispatcher),
        }
    }

    pub fn with_model_hint<F>(mut self, hint: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        self.inner = self.inner.with_model_hint(hint);
        self
    }

    pub fn id(&self) -> usize {
        self.inner.id()
    }

    pub fn name(&self) -> String {
        self.inner.name()
    }

    pub fn hint(&self) -> Option<String> {
        self.inner.hint()
    }

    pub fn modeled_hint(&self) -> Option<String> {
        self.inner.modeled_hint()
    }

    pub fn model(&self) -> M {
        self.inner.model()
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

    pub fn republish_model(&self) {
        self.inner.republish_model();
    }

    pub fn on_construct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_construct(hook);
    }

    pub fn on_destruct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_destruct(hook);
    }

    pub fn on_dispose<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_dispose(hook);
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    pub fn reconstruct(&self) -> VmxResult<()> {
        self.inner.reconstruct()
    }

    pub fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
    }

    pub fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    pub fn is_constructed(&self) -> bool {
        self.inner.is_constructed()
    }

    pub fn select(&self) {
        self.inner.select();
    }

    pub fn deselect(&self) {
        self.inner.deselect();
    }

    pub fn is_selected(&self) -> bool {
        self.inner.is_selected()
    }

    pub fn expand(&self) {
        self.inner.expand();
    }

    pub fn collapse(&self) {
        self.inner.collapse();
    }

    pub fn toggle_expansion(&self) {
        self.inner.toggle_expansion();
    }

    pub fn is_expanded(&self) -> bool {
        self.inner.is_expanded()
    }

    pub fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }

    pub fn select_command(&self) -> RelayCommand {
        self.inner.select_command()
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> VmNode for ReadonlyComponentVm<M, D> {
    fn id(&self) -> usize {
        ReadonlyComponentVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        ReadonlyComponentVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        ReadonlyComponentVm::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        ReadonlyComponentVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        ReadonlyComponentVm::status(self)
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.core.set_parent_id(parent_id);
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
        self.inner.core.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.inner.is_selected()
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> TreeNode for ReadonlyComponentVm<M, D> {
    fn is_expanded_for_walk(&self) -> bool {
        self.is_expanded()
    }
}

impl<M: Clone + Send + 'static, D: Dispatcher> PartialEq for ReadonlyComponentVm<M, D> {
    fn eq(&self, other: &Self) -> bool {
        self.inner == other.inner
    }
}

impl<M: Clone + Send + 'static, D: Dispatcher> Eq for ReadonlyComponentVm<M, D> {}

impl<M: Clone + Send + 'static, D: Dispatcher> fmt::Debug for ReadonlyComponentVm<M, D> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ReadonlyComponentVm")
            .field("id", &self.inner.core.id())
            .field("name", &self.inner.core.name())
            .field("status", &self.inner.core.status())
            .finish()
    }
}

#[derive(Clone)]
pub struct ComponentVmBuilder<M: Clone + PartialEq + Send + 'static, D: Dispatcher = NullDispatcher>
{
    name: Option<String>,
    hint: Option<String>,
    model: Option<M>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    model_hint: Option<ModelHint<M>>,
}

impl<M: Clone + PartialEq + Send + 'static> Default for ComponentVmBuilder<M, NullDispatcher> {
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            model: None,
            hub: None,
            dispatcher: None,
            model_hint: None,
        }
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ComponentVmBuilder<M, D> {
    pub fn name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    pub fn hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }

    pub fn model(mut self, model: M) -> Self {
        self.model = Some(model);
        self
    }

    pub fn services(mut self, hub: MessageHub, dispatcher: D) -> Self {
        self.hub = Some(hub);
        self.dispatcher = Some(dispatcher);
        self
    }

    pub fn model_hint<F>(mut self, hint: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        self.model_hint = Some(Arc::new(hint));
        self
    }

    pub fn build(self) -> VmxResult<ComponentVm<M, D>> {
        let name = self
            .name
            .ok_or_else(|| VmxError::BuilderValidation("name is required".to_string()))?;
        let model = self
            .model
            .ok_or_else(|| VmxError::BuilderValidation("model is required".to_string()))?;
        let hub = self
            .hub
            .ok_or_else(|| VmxError::BuilderValidation("hub is required".to_string()))?;
        let dispatcher = self
            .dispatcher
            .ok_or_else(|| VmxError::BuilderValidation("dispatcher is required".to_string()))?;
        let vm = ComponentVm::with_model(name, model, hub, dispatcher);
        if let Some(hint) = self.hint {
            vm.core.set_hint(Some(hint));
        }
        if let Some(model_hint) = self.model_hint {
            Ok(vm.with_model_hint(move |model| model_hint(model)))
        } else {
            Ok(vm)
        }
    }
}

impl<M: Clone + PartialEq + Send + 'static> ComponentVm<M, NullDispatcher> {
    pub fn builder() -> ComponentVmBuilder<M, NullDispatcher> {
        ComponentVmBuilder::default()
    }

    pub fn create(options: ComponentVmOptions<M>) -> VmxResult<Self> {
        let mut builder = Self::builder();
        if let Some(name) = options.name {
            builder = builder.name(name);
        }
        if let Some(hint) = options.hint {
            builder = builder.hint(hint);
        }
        if let Some(model) = options.model {
            builder = builder.model(model);
        }
        builder.services(options.hub, options.dispatcher).build()
    }
}

pub struct ComponentVmOptions<M: Clone + PartialEq + Send + 'static> {
    pub name: Option<String>,
    pub hint: Option<String>,
    pub model: Option<M>,
    pub hub: MessageHub,
    pub dispatcher: NullDispatcher,
}

pub trait Command: Send + Sync {
    fn can_execute(&self) -> bool;
    fn execute(&self);
    fn can_execute_changed(&self) -> MessageHub {
        NullMessageHub::hub()
    }
}

pub trait CommandOf<T>: Send + Sync {
    fn can_execute(&self, parameter: &T) -> bool;
    fn execute(&self, parameter: T);
}

type CommandAction = Arc<Mutex<dyn FnMut() + Send + 'static>>;
type CommandPredicate = Arc<dyn Fn() -> bool + Send + Sync + 'static>;

#[derive(Clone)]
pub struct RelayCommand {
    action: Option<CommandAction>,
    predicate: Option<CommandPredicate>,
    disposed: Arc<Mutex<bool>>,
    can_execute_changed: MessageHub,
    _trigger_subscriptions: Arc<Vec<Subscription>>,
}

impl RelayCommand {
    pub fn new<F>(action: F) -> Self
    where
        F: FnMut() + Send + 'static,
    {
        Self {
            action: Some(Arc::new(Mutex::new(action))),
            predicate: None,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
            _trigger_subscriptions: Arc::new(Vec::new()),
        }
    }

    pub fn noop() -> Self {
        Self {
            action: None,
            predicate: None,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
            _trigger_subscriptions: Arc::new(Vec::new()),
        }
    }

    pub fn with_can_execute<F>(mut self, predicate: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    pub fn raise_can_execute_changed(&self) {
        if *lock(&self.disposed) {
            return;
        }
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            name: "can_execute_changed".to_string(),
        });
    }

    pub fn trigger_can_execute_changed(&self) {
        self.raise_can_execute_changed();
    }

    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    pub fn builder() -> RelayCommandBuilder {
        RelayCommandBuilder::default()
    }

    pub fn dispose(&self) {
        let should_dispose = {
            let mut disposed = lock(&self.disposed);
            if *disposed {
                false
            } else {
                *disposed = true;
                true
            }
        };
        if should_dispose {
            self.can_execute_changed.dispose();
        }
    }

    pub fn confirm<F>(self, confirm: F) -> ConfirmationDecoratorCommand<Self>
    where
        F: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
    {
        ConfirmationDecoratorCommand::new(self, confirm)
    }

    pub fn precede_with<C: Command + Clone + 'static>(self, other: C) -> CompositeCommand {
        CompositeCommand::new(vec![Arc::new(other), Arc::new(self)])
    }

    pub fn succeed_with<C: Command + Clone + 'static>(self, other: C) -> CompositeCommand {
        CompositeCommand::new(vec![Arc::new(self), Arc::new(other)])
    }

    pub fn wrap_with<FPre, FPost, FPred>(
        self,
        predicate: Option<FPred>,
        pre: Option<FPre>,
        post: Option<FPost>,
    ) -> DecoratorCommand<Self>
    where
        FPre: Fn() + Send + Sync + 'static,
        FPost: Fn() + Send + Sync + 'static,
        FPred: Fn() -> bool + Send + Sync + 'static,
    {
        DecoratorCommand::new(self, predicate, pre, post)
    }
}

impl Command for RelayCommand {
    fn can_execute(&self) -> bool {
        !*lock(&self.disposed)
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        if let Some(action) = &self.action {
            (lock(action))();
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }
}

type ParameterizedCommandAction<T> = Arc<Mutex<dyn FnMut(T) + Send + 'static>>;
type ParameterizedCommandPredicate<T> = Arc<dyn Fn(&T) -> bool + Send + Sync + 'static>;

#[derive(Clone)]
pub struct RelayCommandOf<T: Clone + Send + 'static> {
    action: Option<ParameterizedCommandAction<T>>,
    predicate: Option<ParameterizedCommandPredicate<T>>,
    disposed: Arc<Mutex<bool>>,
    can_execute_changed: MessageHub,
}

impl<T: Clone + Send + 'static> RelayCommandOf<T> {
    pub fn new<F>(action: F) -> Self
    where
        F: FnMut(T) + Send + 'static,
    {
        Self {
            action: Some(Arc::new(Mutex::new(action))),
            predicate: None,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
        }
    }

    pub fn noop() -> Self {
        Self {
            action: None,
            predicate: None,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
        }
    }

    pub fn with_can_execute<F>(mut self, predicate: F) -> Self
    where
        F: Fn(&T) -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    pub fn raise_can_execute_changed(&self) {
        if *lock(&self.disposed) {
            return;
        }
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            name: "can_execute_changed".to_string(),
        });
    }

    pub fn trigger_can_execute_changed(&self) {
        self.raise_can_execute_changed();
    }

    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    pub fn dispose(&self) {
        *lock(&self.disposed) = true;
    }

    pub fn can_execute(&self, parameter: &T) -> bool {
        <Self as CommandOf<T>>::can_execute(self, parameter)
    }

    pub fn execute(&self, parameter: T) {
        <Self as CommandOf<T>>::execute(self, parameter);
    }
}

impl<T: Clone + Send + 'static> CommandOf<T> for RelayCommandOf<T> {
    fn can_execute(&self, parameter: &T) -> bool {
        !*lock(&self.disposed)
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate(parameter)))
                .unwrap_or(true)
    }

    fn execute(&self, parameter: T) {
        if !self.can_execute(&parameter) {
            return;
        }
        if let Some(action) = &self.action {
            (lock(action))(parameter);
        }
    }
}

#[derive(Clone, Default)]
pub struct CancellationToken {
    cancelled: Arc<AtomicBool>,
}

impl CancellationToken {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }
}

type AsyncCommandAction = Arc<dyn Fn(CancellationToken) -> VmxResult<()> + Send + Sync + 'static>;
type AsyncCommandPredicate = Arc<dyn Fn() -> bool + Send + Sync + 'static>;

#[derive(Clone)]
pub struct AsyncRelayCommand {
    action: Option<AsyncCommandAction>,
    predicate: Option<AsyncCommandPredicate>,
    disposed: Arc<AtomicBool>,
    executing: Arc<AtomicBool>,
    active_token: Arc<Mutex<Option<CancellationToken>>>,
    cancel_pending: Arc<AtomicBool>,
    can_execute_changed: MessageHub,
    errors: MessageHub,
    throw_on_cancel: bool,
    trigger_subscriptions: Arc<Mutex<Vec<Subscription>>>,
}

struct AsyncExecutionGuard {
    executing: Arc<AtomicBool>,
    active_token: Arc<Mutex<Option<CancellationToken>>>,
    cancel_pending: Arc<AtomicBool>,
    can_execute_changed: MessageHub,
    disposed: Arc<AtomicBool>,
}

impl Drop for AsyncExecutionGuard {
    fn drop(&mut self) {
        let mut active_token = lock(&self.active_token);
        self.executing.store(false, Ordering::SeqCst);
        *active_token = None;
        self.cancel_pending.store(false, Ordering::SeqCst);
        drop(active_token);
        if !self.disposed.load(Ordering::SeqCst) {
            self.can_execute_changed.send(Message::Custom {
                sender_id: 0,
                name: "can_execute_changed".to_string(),
            });
        }
    }
}

impl AsyncRelayCommand {
    pub fn new<F>(action: F) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<()> + Send + Sync + 'static,
    {
        Self::from_parts(Some(Arc::new(action)), None, Vec::new(), false)
    }

    pub fn noop() -> Self {
        Self::from_parts(None, None, Vec::new(), false)
    }

    fn from_parts(
        action: Option<AsyncCommandAction>,
        predicate: Option<AsyncCommandPredicate>,
        triggers: Vec<MessageHub>,
        throw_on_cancel: bool,
    ) -> Self {
        let command = Self {
            action,
            predicate,
            disposed: Arc::new(AtomicBool::new(false)),
            executing: Arc::new(AtomicBool::new(false)),
            active_token: Arc::new(Mutex::new(None)),
            cancel_pending: Arc::new(AtomicBool::new(false)),
            can_execute_changed: MessageHub::new(),
            errors: MessageHub::new(),
            throw_on_cancel,
            trigger_subscriptions: Arc::new(Mutex::new(Vec::new())),
        };
        let subscriptions = triggers
            .into_iter()
            .map(|trigger| {
                let observed = command.clone();
                trigger.subscribe(move |_| observed.raise_can_execute_changed())
            })
            .collect();
        *lock(&command.trigger_subscriptions) = subscriptions;
        command
    }

    pub fn with_can_execute<F>(mut self, predicate: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    pub fn can_execute(&self) -> bool {
        !self.disposed.load(Ordering::SeqCst)
            && !self.executing.load(Ordering::SeqCst)
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
    }

    pub fn execute(&self) {
        let _ = self.start_execution(true);
    }

    pub fn execute_async(&self) -> std::thread::JoinHandle<VmxResult<()>> {
        self.start_execution(false)
    }

    fn start_execution(
        &self,
        route_fire_and_forget_errors: bool,
    ) -> std::thread::JoinHandle<VmxResult<()>> {
        if self.disposed.load(Ordering::SeqCst)
            || !self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
            || self
                .executing
                .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
                .is_err()
        {
            return std::thread::spawn(|| Ok(()));
        }
        if self.disposed.load(Ordering::SeqCst) {
            self.executing.store(false, Ordering::SeqCst);
            return std::thread::spawn(|| Ok(()));
        }
        let token = CancellationToken::new();
        {
            let mut active_token = lock(&self.active_token);
            *active_token = Some(token.clone());
            if self.cancel_pending.swap(false, Ordering::SeqCst) {
                token.cancel();
            }
        }
        if self.disposed.load(Ordering::SeqCst) {
            token.cancel();
            *lock(&self.active_token) = None;
            self.executing.store(false, Ordering::SeqCst);
            return std::thread::spawn(|| Ok(()));
        }
        self.raise_can_execute_changed();
        let action = self.action.clone();
        let errors = self.errors.clone();
        let throw_on_cancel = self.throw_on_cancel;
        let disposed = self.disposed.clone();
        let guard = AsyncExecutionGuard {
            executing: self.executing.clone(),
            active_token: self.active_token.clone(),
            cancel_pending: self.cancel_pending.clone(),
            can_execute_changed: self.can_execute_changed.clone(),
            disposed: self.disposed.clone(),
        };
        std::thread::spawn(move || {
            let _guard = guard;
            let result = action.map(|action| action(token.clone())).unwrap_or(Ok(()));
            let result = match (token.is_cancelled(), result) {
                (true, Ok(())) | (true, Err(VmxError::Cancelled)) => {
                    if throw_on_cancel {
                        Err(VmxError::Cancelled)
                    } else {
                        Ok(())
                    }
                }
                (_, result) => result,
            };

            if route_fire_and_forget_errors {
                if result.is_err()
                    && !matches!(&result, Err(VmxError::Cancelled))
                    && !disposed.load(Ordering::SeqCst)
                {
                    errors.send(Message::Custom {
                        sender_id: 0,
                        name: "error".to_string(),
                    });
                }
                Ok(())
            } else {
                result
            }
        })
    }

    pub fn cancel(&self) {
        if !self.executing.load(Ordering::SeqCst) {
            return;
        }
        let active_token = lock(&self.active_token);
        if !self.executing.load(Ordering::SeqCst) {
            return;
        }
        if let Some(token) = active_token.as_ref() {
            token.cancel();
        } else {
            self.cancel_pending.store(true, Ordering::SeqCst);
        }
    }

    pub fn is_executing(&self) -> bool {
        self.executing.load(Ordering::SeqCst)
    }

    pub fn dispose(&self) {
        if self.disposed.swap(true, Ordering::SeqCst) {
            return;
        }
        self.cancel();
        lock(&self.trigger_subscriptions).clear();
        self.can_execute_changed.dispose();
        self.errors.dispose();
    }

    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    pub fn errors(&self) -> MessageHub {
        self.errors.clone()
    }

    pub fn builder() -> AsyncRelayCommandBuilder {
        AsyncRelayCommandBuilder::default()
    }

    pub fn raise_can_execute_changed(&self) {
        if self.disposed.load(Ordering::SeqCst) {
            return;
        }
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            name: "can_execute_changed".to_string(),
        });
    }
}

#[derive(Clone, Default)]
pub struct AsyncRelayCommandBuilder {
    action: Option<AsyncCommandAction>,
    predicate: Option<AsyncCommandPredicate>,
    triggers: Vec<MessageHub>,
    throw_on_cancel: bool,
}

impl AsyncRelayCommandBuilder {
    pub fn task<F>(mut self, action: F) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<()> + Send + Sync + 'static,
    {
        self.action = Some(Arc::new(action));
        self
    }

    pub fn predicate<F>(mut self, predicate: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    pub fn trigger(mut self, trigger: MessageHub) -> Self {
        self.triggers.push(trigger);
        self
    }

    pub fn throw_on_cancel(mut self) -> Self {
        self.throw_on_cancel = true;
        self
    }

    pub fn build(self) -> AsyncRelayCommand {
        AsyncRelayCommand::from_parts(
            self.action,
            self.predicate,
            self.triggers,
            self.throw_on_cancel,
        )
    }
}

#[derive(Clone, Default)]
pub struct RelayCommandBuilder {
    action: Option<CommandAction>,
    predicate: Option<CommandPredicate>,
    triggers: Vec<MessageHub>,
}

impl RelayCommandBuilder {
    pub fn action<F>(mut self, action: F) -> Self
    where
        F: FnMut() + Send + 'static,
    {
        self.action = Some(Arc::new(Mutex::new(action)));
        self
    }

    pub fn can_execute<F>(mut self, predicate: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    pub fn trigger(mut self, trigger: MessageHub) -> Self {
        self.triggers.push(trigger);
        self
    }

    pub fn trigger_count(&self) -> usize {
        self.triggers.len()
    }

    pub fn build(self) -> RelayCommand {
        let command = RelayCommand {
            action: self.action,
            predicate: self.predicate,
            disposed: Arc::new(Mutex::new(false)),
            can_execute_changed: MessageHub::new(),
            _trigger_subscriptions: Arc::new(Vec::new()),
        };
        let subscriptions = self
            .triggers
            .into_iter()
            .map(|trigger| {
                let hub = command.can_execute_changed.clone();
                trigger.subscribe(move |_| {
                    hub.send(Message::Custom {
                        sender_id: 0,
                        name: "can_execute_changed".to_string(),
                    });
                })
            })
            .collect::<Vec<_>>();
        RelayCommand {
            _trigger_subscriptions: Arc::new(subscriptions),
            ..command
        }
    }
}

#[derive(Clone)]
pub struct CompositeCommand {
    commands: Vec<Arc<dyn Command>>,
    can_execute_changed: MessageHub,
    _subscriptions: Arc<Vec<Subscription>>,
}

impl CompositeCommand {
    pub fn new(commands: Vec<Arc<dyn Command>>) -> Self {
        let can_execute_changed = MessageHub::new();
        let subscriptions = commands
            .iter()
            .map(|command| {
                let hub = can_execute_changed.clone();
                command.can_execute_changed().subscribe(move |_| {
                    hub.send(Message::Custom {
                        sender_id: 0,
                        name: "can_execute_changed".to_string(),
                    });
                })
            })
            .collect::<Vec<_>>();
        Self {
            commands,
            can_execute_changed,
            _subscriptions: Arc::new(subscriptions),
        }
    }

    pub fn from_commands<C>(commands: Vec<C>) -> Self
    where
        C: Command + Clone + 'static,
    {
        Self::new(
            commands
                .into_iter()
                .map(|command| Arc::new(command) as Arc<dyn Command>)
                .collect(),
        )
    }
}

impl Command for CompositeCommand {
    fn can_execute(&self) -> bool {
        self.commands
            .iter()
            .any(|command| evaluate_command_predicate(|| command.can_execute()))
    }

    fn execute(&self) {
        for command in &self.commands {
            if evaluate_command_predicate(|| command.can_execute()) {
                command.execute();
            }
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }
}

#[derive(Clone)]
pub struct DecoratorCommand<C: Command + Clone> {
    inner: C,
    predicate: Option<Arc<dyn Fn() -> bool + Send + Sync>>,
    pre: Option<Arc<dyn Fn() + Send + Sync>>,
    post: Option<Arc<dyn Fn() + Send + Sync>>,
}

impl<C: Command + Clone> DecoratorCommand<C> {
    pub fn new<FPre, FPost, FPred>(
        inner: C,
        predicate: Option<FPred>,
        pre: Option<FPre>,
        post: Option<FPost>,
    ) -> Self
    where
        FPre: Fn() + Send + Sync + 'static,
        FPost: Fn() + Send + Sync + 'static,
        FPred: Fn() -> bool + Send + Sync + 'static,
    {
        Self {
            inner,
            predicate: predicate.map(|p| Arc::new(p) as Arc<dyn Fn() -> bool + Send + Sync>),
            pre: pre.map(|p| Arc::new(p) as Arc<dyn Fn() + Send + Sync>),
            post: post.map(|p| Arc::new(p) as Arc<dyn Fn() + Send + Sync>),
        }
    }
}

impl<C: Command + Clone> Command for DecoratorCommand<C> {
    fn can_execute(&self) -> bool {
        evaluate_command_predicate(|| self.inner.can_execute())
            && self
                .predicate
                .as_ref()
                .map(|predicate| evaluate_command_predicate(|| predicate()))
                .unwrap_or(true)
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        if let Some(pre) = &self.pre {
            pre();
        }
        self.inner.execute();
        if let Some(post) = &self.post {
            post();
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.inner.can_execute_changed()
    }
}

#[derive(Clone)]
pub struct ConfirmationDecoratorCommand<C: Command + Clone> {
    inner: C,
    confirm: Arc<dyn Fn() -> AsyncValue<bool> + Send + Sync>,
    errors: MessageHub,
}

impl<C: Command + Clone + 'static> ConfirmationDecoratorCommand<C> {
    pub fn new<F>(inner: C, confirm: F) -> Self
    where
        F: Fn() -> AsyncValue<bool> + Send + Sync + 'static,
    {
        Self {
            inner,
            confirm: Arc::new(confirm),
            errors: MessageHub::new(),
        }
    }

    pub fn errors(&self) -> MessageHub {
        self.errors.clone()
    }

    pub fn execute_async(&self) -> std::thread::JoinHandle<()> {
        let decision = (self.confirm)();
        let command = self.clone();
        std::thread::spawn(move || {
            if decision.wait() {
                command.inner.execute();
            }
        })
    }

    fn execute_after(&self, confirmed: bool) {
        if !confirmed {
            return;
        }
        let result = catch_unwind(AssertUnwindSafe(|| self.inner.execute()));
        if result.is_err() {
            self.errors.send(Message::Custom {
                sender_id: 0,
                name: "error".to_string(),
            });
        }
    }
}

impl<C: Command + Clone + 'static> Command for ConfirmationDecoratorCommand<C> {
    fn can_execute(&self) -> bool {
        evaluate_command_predicate(|| self.inner.can_execute())
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        let decision = (self.confirm)();
        if let Some(confirmed) = decision.try_get() {
            self.execute_after(confirmed);
        } else {
            let command = self.clone();
            std::thread::spawn(move || command.execute_after(decision.wait()));
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.inner.can_execute_changed()
    }
}

#[derive(Default)]
struct ServicedCollectionDelivery {
    state: Mutex<ServicedCollectionDeliveryState>,
    ready: Condvar,
}

#[derive(Default)]
struct ServicedCollectionDeliveryState {
    pending: VecDeque<Message>,
    draining_owner: Option<ThreadId>,
}

/// Hub-aware observable collection with a local change stream.
///
/// Effective mutations update the backing state, publish to the local stream,
/// and then publish the same message to the optional external hub.
#[derive(Clone)]
pub struct ServicedObservableCollection<T>
where
    T: Clone + Send + 'static,
{
    inner: Arc<Mutex<Vec<T>>>,
    local_hub: MessageHub,
    external_hub: Option<MessageHub>,
    delivery: Arc<ServicedCollectionDelivery>,
    owner_id: usize,
}

impl<T> ServicedObservableCollection<T>
where
    T: Clone + Send + 'static,
{
    /// Creates an empty collection without an external message hub.
    pub fn new(owner_id: usize) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            local_hub: MessageHub::new(),
            external_hub: None,
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Creates an empty collection that also publishes changes to `hub`.
    pub fn with_hub(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            local_hub: MessageHub::new(),
            external_hub: Some(hub),
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Returns the always-present local collection-change stream.
    pub fn collection_changed(&self) -> MessageHub {
        self.local_hub.clone()
    }

    pub fn len(&self) -> usize {
        lock(&self.inner).len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn get(&self, index: usize) -> Option<T> {
        lock(&self.inner).get(index).cloned()
    }

    pub fn to_vec(&self) -> Vec<T> {
        lock(&self.inner).clone()
    }

    pub fn push(&self, item: T) {
        let index = {
            let mut inner = lock(&self.inner);
            let index = inner.len();
            inner.push(item);
            index
        };
        self.publish(CollectionChangeAction::Add, None, Some(index));
    }

    /// Removes the first item equal to `item`.
    pub fn remove(&self, item: &T) -> bool
    where
        T: PartialEq,
    {
        let index = {
            let mut inner = lock(&self.inner);
            let Some(index) = inner.iter().position(|candidate| candidate == item) else {
                return false;
            };
            inner.remove(index);
            index
        };
        self.publish(CollectionChangeAction::Remove, Some(index), None);
        true
    }

    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let removed = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            inner.remove(index)
        };
        self.publish(CollectionChangeAction::Remove, Some(index), None);
        Ok(removed)
    }

    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let old = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            std::mem::replace(&mut inner[index], item)
        };
        self.publish(CollectionChangeAction::Replace, Some(index), Some(index));
        Ok(old)
    }

    pub fn replace_all<I>(&self, items: I)
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot = items.into_iter().collect::<Vec<_>>();
        {
            let mut inner = lock(&self.inner);
            if inner.is_empty() && snapshot.is_empty() {
                return;
            }
            *inner = snapshot;
        }
        self.publish(CollectionChangeAction::Reset, None, None);
    }

    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        {
            let mut inner = lock(&self.inner);
            if from_index >= inner.len() || to_index >= inner.len() {
                return Err(VmxError::InvalidArgument(
                    "move index out of range".to_string(),
                ));
            }
            if from_index == to_index {
                return Ok(());
            }
            let item = inner.remove(from_index);
            inner.insert(to_index, item);
        }
        self.publish(
            CollectionChangeAction::Move,
            Some(from_index),
            Some(to_index),
        );
        Ok(())
    }

    pub fn clear(&self) {
        {
            let mut inner = lock(&self.inner);
            if inner.is_empty() {
                return;
            }
            inner.clear();
        }
        self.publish(CollectionChangeAction::Reset, None, None);
    }

    fn publish(
        &self,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
    ) {
        let message = Message::CollectionChanged(CollectionChangedMessage {
            sender_id: self.owner_id,
            property_name: "items".to_string(),
            action,
            old_index,
            new_index,
        });

        let current = thread::current().id();
        let mut delivery = lock(&self.delivery.state);
        while delivery
            .draining_owner
            .is_some_and(|owner| owner != current)
        {
            delivery = wait(&self.delivery.ready, delivery);
        }
        delivery.pending.push_back(message);
        if delivery.draining_owner == Some(current) {
            return;
        }
        delivery.draining_owner = Some(current);
        drop(delivery);

        let result = catch_unwind(AssertUnwindSafe(|| self.drain_delivery(current)));
        if let Err(error) = result {
            let mut delivery = lock(&self.delivery.state);
            delivery.pending.clear();
            if delivery.draining_owner == Some(current) {
                delivery.draining_owner = None;
            }
            self.delivery.ready.notify_all();
            drop(delivery);
            resume_unwind(error);
        }
    }

    fn drain_delivery(&self, current: ThreadId) {
        loop {
            let message = {
                let mut delivery = lock(&self.delivery.state);
                debug_assert_eq!(delivery.draining_owner, Some(current));
                let Some(message) = delivery.pending.pop_front() else {
                    delivery.draining_owner = None;
                    self.delivery.ready.notify_all();
                    return;
                };
                message
            };

            self.local_hub.send(message.clone());
            if let Some(hub) = &self.external_hub {
                hub.send(message);
            }
        }
    }
}

impl<T> IntoIterator for &ServicedObservableCollection<T>
where
    T: Clone + Send + 'static,
{
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.to_vec().into_iter()
    }
}

struct KeyedServicedCollectionState<K, T> {
    items: Vec<T>,
    keys: Vec<Arc<K>>,
    index_by_key: HashMap<Arc<K>, usize>,
}

impl<K, T> Default for KeyedServicedCollectionState<K, T> {
    fn default() -> Self {
        Self {
            items: Vec::new(),
            keys: Vec::new(),
            index_by_key: HashMap::new(),
        }
    }
}

type KeyProjector<K, T> = Arc<dyn Fn(&T) -> VmxResult<K> + Send + Sync + 'static>;

/// An insertion-ordered serviced collection with a captured-key hash index.
///
/// The projector runs only when a membership is added or explicitly replaced.
/// Lookup, removal, and movement use the captured key and never reproject stored
/// items. Contained items remain owned by the caller.
pub struct KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    inner: Arc<Mutex<KeyedServicedCollectionState<K, T>>>,
    key_of: KeyProjector<K, T>,
    local_hub: MessageHub,
    external_hub: Option<MessageHub>,
    delivery: Arc<ServicedCollectionDelivery>,
    owner_id: usize,
}

impl<K, T> Clone for KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
            key_of: Arc::clone(&self.key_of),
            local_hub: self.local_hub.clone(),
            external_hub: self.external_hub.clone(),
            delivery: Arc::clone(&self.delivery),
            owner_id: self.owner_id,
        }
    }
}

impl<K, T> KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    /// Creates an empty keyed collection without an external message hub.
    pub fn new<F>(owner_id: usize, key_of: F) -> Self
    where
        F: Fn(&T) -> VmxResult<K> + Send + Sync + 'static,
    {
        Self {
            inner: Arc::new(Mutex::new(KeyedServicedCollectionState::default())),
            key_of: Arc::new(key_of),
            local_hub: MessageHub::new(),
            external_hub: None,
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Creates an empty keyed collection that also publishes changes to `hub`.
    pub fn with_hub<F>(owner_id: usize, hub: MessageHub, key_of: F) -> Self
    where
        F: Fn(&T) -> VmxResult<K> + Send + Sync + 'static,
    {
        Self {
            inner: Arc::new(Mutex::new(KeyedServicedCollectionState::default())),
            key_of: Arc::new(key_of),
            local_hub: MessageHub::new(),
            external_hub: Some(hub),
            delivery: Arc::new(ServicedCollectionDelivery::default()),
            owner_id,
        }
    }

    /// Returns the always-present local collection-change stream.
    pub fn collection_changed(&self) -> MessageHub {
        self.local_hub.clone()
    }

    pub fn len(&self) -> usize {
        lock(&self.inner).items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Returns the item at `index`, preserving the unkeyed collection's read API.
    pub fn get(&self, index: usize) -> Option<T> {
        lock(&self.inner).items.get(index).cloned()
    }

    /// Returns the item whose membership captured `key`.
    pub fn get_by_key(&self, key: &K) -> Option<T> {
        let inner = lock(&self.inner);
        inner
            .index_by_key
            .get(key)
            .and_then(|index| inner.items.get(*index))
            .cloned()
    }

    pub fn contains_key(&self, key: &K) -> bool {
        lock(&self.inner).index_by_key.contains_key(key)
    }

    pub fn to_vec(&self) -> Vec<T> {
        lock(&self.inner).items.clone()
    }

    pub fn push(&self, item: T) -> VmxResult<()> {
        let key = Arc::new((self.key_of)(&item)?);
        let position = {
            let mut inner = lock(&self.inner);
            if inner.index_by_key.contains_key(key.as_ref()) {
                return Err(Self::duplicate_key_error());
            }
            let position = inner.items.len();
            inner.items.push(item);
            inner.keys.push(Arc::clone(&key));
            inner.index_by_key.insert(key, position);
            position
        };
        self.publish(CollectionChangeAction::Add, None, Some(position));
        Ok(())
    }

    /// Removes the first item equal to `item`.
    pub fn remove(&self, item: &T) -> bool
    where
        T: PartialEq,
    {
        let position = {
            let mut inner = lock(&self.inner);
            let Some(position) = inner.items.iter().position(|candidate| candidate == item) else {
                return false;
            };
            Self::remove_membership(&mut inner, position);
            position
        };
        self.publish(CollectionChangeAction::Remove, Some(position), None);
        true
    }

    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let removed = {
            let mut inner = lock(&self.inner);
            if index >= inner.items.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            Self::remove_membership(&mut inner, index)
        };
        self.publish(CollectionChangeAction::Remove, Some(index), None);
        Ok(removed)
    }

    pub fn remove_key(&self, key: &K) -> Option<T> {
        let (position, removed) = {
            let mut inner = lock(&self.inner);
            let position = *inner.index_by_key.get(key)?;
            let removed = Self::remove_membership(&mut inner, position);
            (position, removed)
        };
        self.publish(CollectionChangeAction::Remove, Some(position), None);
        Some(removed)
    }

    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let key = Arc::new((self.key_of)(&item)?);
        let old = {
            let mut inner = lock(&self.inner);
            if index >= inner.items.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            if inner
                .index_by_key
                .get(key.as_ref())
                .is_some_and(|owner| *owner != index)
            {
                return Err(Self::duplicate_key_error());
            }
            let old_key = Arc::clone(&inner.keys[index]);
            inner.index_by_key.remove(old_key.as_ref());
            inner.keys[index] = Arc::clone(&key);
            inner.index_by_key.insert(key, index);
            std::mem::replace(&mut inner.items[index], item)
        };
        self.publish(CollectionChangeAction::Replace, Some(index), Some(index));
        Ok(old)
    }

    pub fn replace_all<I>(&self, items: I) -> VmxResult<()>
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot = items.into_iter().collect::<Vec<_>>();
        let mut keys = Vec::with_capacity(snapshot.len());
        let mut index_by_key = HashMap::with_capacity(snapshot.len());
        for (index, item) in snapshot.iter().enumerate() {
            let key = Arc::new((self.key_of)(item)?);
            if index_by_key.insert(Arc::clone(&key), index).is_some() {
                return Err(Self::duplicate_key_error());
            }
            keys.push(key);
        }
        {
            let mut inner = lock(&self.inner);
            if inner.items.is_empty() && snapshot.is_empty() {
                return Ok(());
            }
            inner.items = snapshot;
            inner.keys = keys;
            inner.index_by_key = index_by_key;
        }
        self.publish(CollectionChangeAction::Reset, None, None);
        Ok(())
    }

    /// Adds a missing key or replaces the existing membership in place.
    ///
    /// Returns `true` for Add and `false` for Replace.
    pub fn upsert(&self, item: T) -> VmxResult<bool> {
        let key = Arc::new((self.key_of)(&item)?);
        let (added, index) = {
            let mut inner = lock(&self.inner);
            if let Some(index) = inner.index_by_key.get(key.as_ref()).copied() {
                let old_key = Arc::clone(&inner.keys[index]);
                inner.index_by_key.remove(old_key.as_ref());
                inner.keys[index] = Arc::clone(&key);
                inner.index_by_key.insert(key, index);
                inner.items[index] = item;
                (false, index)
            } else {
                let index = inner.items.len();
                inner.items.push(item);
                inner.keys.push(Arc::clone(&key));
                inner.index_by_key.insert(key, index);
                (true, index)
            }
        };
        if added {
            self.publish(CollectionChangeAction::Add, None, Some(index));
            Ok(true)
        } else {
            self.publish(CollectionChangeAction::Replace, Some(index), Some(index));
            Ok(false)
        }
    }

    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        {
            let mut inner = lock(&self.inner);
            if from_index >= inner.items.len() || to_index >= inner.items.len() {
                return Err(VmxError::InvalidArgument(
                    "move index out of range".to_string(),
                ));
            }
            if from_index == to_index {
                return Ok(());
            }
            let item = inner.items.remove(from_index);
            let key = inner.keys.remove(from_index);
            inner.items.insert(to_index, item);
            inner.keys.insert(to_index, key);
            Self::repair_indices(&mut inner, from_index.min(to_index));
        }
        self.publish(
            CollectionChangeAction::Move,
            Some(from_index),
            Some(to_index),
        );
        Ok(())
    }

    pub fn clear(&self) {
        {
            let mut inner = lock(&self.inner);
            if inner.items.is_empty() {
                return;
            }
            inner.items.clear();
            inner.keys.clear();
            inner.index_by_key.clear();
        }
        self.publish(CollectionChangeAction::Reset, None, None);
    }

    fn duplicate_key_error() -> VmxError {
        VmxError::InvalidArgument("duplicate key".to_string())
    }

    fn remove_membership(inner: &mut KeyedServicedCollectionState<K, T>, index: usize) -> T {
        let removed = inner.items.remove(index);
        let old_key = inner.keys.remove(index);
        inner.index_by_key.remove(&old_key);
        Self::repair_indices(inner, index);
        removed
    }

    fn repair_indices(inner: &mut KeyedServicedCollectionState<K, T>, start: usize) {
        for index in start..inner.keys.len() {
            inner
                .index_by_key
                .insert(Arc::clone(&inner.keys[index]), index);
        }
    }

    fn publish(
        &self,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
    ) {
        let message = Message::CollectionChanged(CollectionChangedMessage {
            sender_id: self.owner_id,
            property_name: "items".to_string(),
            action,
            old_index,
            new_index,
        });

        let current = thread::current().id();
        let mut delivery = lock(&self.delivery.state);
        while delivery
            .draining_owner
            .is_some_and(|owner| owner != current)
        {
            delivery = wait(&self.delivery.ready, delivery);
        }
        delivery.pending.push_back(message);
        if delivery.draining_owner == Some(current) {
            return;
        }
        delivery.draining_owner = Some(current);
        drop(delivery);

        let result = catch_unwind(AssertUnwindSafe(|| self.drain_delivery(current)));
        if let Err(error) = result {
            let mut delivery = lock(&self.delivery.state);
            delivery.pending.clear();
            if delivery.draining_owner == Some(current) {
                delivery.draining_owner = None;
            }
            self.delivery.ready.notify_all();
            drop(delivery);
            resume_unwind(error);
        }
    }

    fn drain_delivery(&self, current: ThreadId) {
        loop {
            let message = {
                let mut delivery = lock(&self.delivery.state);
                debug_assert_eq!(delivery.draining_owner, Some(current));
                let Some(message) = delivery.pending.pop_front() else {
                    delivery.draining_owner = None;
                    self.delivery.ready.notify_all();
                    return;
                };
                message
            };

            self.local_hub.send(message.clone());
            if let Some(hub) = &self.external_hub {
                hub.send(message);
            }
        }
    }
}

impl<K, T> IntoIterator for &KeyedServicedObservableCollection<K, T>
where
    K: Eq + Hash + Send + 'static,
    T: Clone + Send + 'static,
{
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.to_vec().into_iter()
    }
}

#[derive(Clone)]
pub struct ObservableList<T: Clone + Send + 'static> {
    inner: Arc<Mutex<Vec<T>>>,
    hub: MessageHub,
    owner_id: usize,
    batch_depth: Arc<Mutex<usize>>,
    batch_dirty: Arc<Mutex<bool>>,
    batch_count_at_start: Arc<Mutex<usize>>,
}

impl<T: Clone + Send + 'static> ObservableList<T> {
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            owner_id,
            batch_depth: Arc::new(Mutex::new(0)),
            batch_dirty: Arc::new(Mutex::new(false)),
            batch_count_at_start: Arc::new(Mutex::new(0)),
        }
    }

    pub fn len(&self) -> usize {
        lock(&self.inner).len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn to_vec(&self) -> Vec<T> {
        lock(&self.inner).clone()
    }

    pub fn get(&self, index: usize) -> Option<T> {
        lock(&self.inner).get(index).cloned()
    }

    pub fn push(&self, item: T) {
        let index = {
            let mut inner = lock(&self.inner);
            let index = inner.len();
            inner.push(item);
            index
        };
        self.publish(CollectionChangeAction::Add, None, Some(index), true);
    }

    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        let mut inner = lock(&self.inner);
        if index > inner.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        inner.insert(index, item);
        drop(inner);
        self.publish(CollectionChangeAction::Add, None, Some(index), true);
        Ok(())
    }

    pub fn remove_at(&self, index: usize) -> Option<T> {
        let item = self.remove_at_silent(index);
        if item.is_some() {
            self.publish(CollectionChangeAction::Remove, Some(index), None, true);
        }
        item
    }

    fn remove_at_silent(&self, index: usize) -> Option<T> {
        let mut inner = lock(&self.inner);
        if index >= inner.len() {
            None
        } else {
            Some(inner.remove(index))
        }
    }

    fn insert_silent(&self, index: usize, item: T) -> VmxResult<()> {
        let mut inner = lock(&self.inner);
        if index > inner.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        inner.insert(index, item);
        Ok(())
    }

    fn publish_remove(&self, index: usize) {
        self.publish(CollectionChangeAction::Remove, Some(index), None, true);
    }

    fn publish_add(&self, index: usize) {
        self.publish(CollectionChangeAction::Add, None, Some(index), true);
    }

    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        let old = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                return Err(VmxError::InvalidArgument("index out of range".to_string()));
            }
            std::mem::replace(&mut inner[index], item)
        };
        self.publish(
            CollectionChangeAction::Replace,
            Some(index),
            Some(index),
            false,
        );
        Ok(old)
    }

    pub fn replace_all<I>(&self, items: I)
    where
        I: IntoIterator<Item = T>,
    {
        let snapshot: Vec<T> = items.into_iter().collect();
        let new_count = snapshot.len();
        let old_count = {
            let mut inner = lock(&self.inner);
            let old_count = inner.len();
            if old_count == 0 && snapshot.is_empty() {
                return;
            }
            *inner = snapshot;
            old_count
        };
        self.publish(
            CollectionChangeAction::Reset,
            None,
            None,
            old_count != new_count,
        );
    }

    fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        {
            let mut inner = lock(&self.inner);
            if from_index >= inner.len() || to_index >= inner.len() {
                return Err(VmxError::InvalidArgument(
                    "move index out of range".to_string(),
                ));
            }
            if from_index == to_index {
                return Ok(());
            }
            let item = inner.remove(from_index);
            inner.insert(to_index, item);
        }
        self.publish(
            CollectionChangeAction::Move,
            Some(from_index),
            Some(to_index),
            false,
        );
        Ok(())
    }

    pub fn clear(&self) {
        let changed = {
            let mut inner = lock(&self.inner);
            let changed = !inner.is_empty();
            inner.clear();
            changed
        };
        if changed {
            self.publish(CollectionChangeAction::Reset, None, None, true);
        }
    }

    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        let mut depth = lock(&self.batch_depth);
        if *depth == 0 {
            *lock(&self.batch_count_at_start) = self.len();
        }
        *depth += 1;
        drop(depth);
        let result = catch_unwind(AssertUnwindSafe(action));
        let mut depth = lock(&self.batch_depth);
        *depth -= 1;
        if *depth == 0 {
            drop(depth);
            let changed = {
                let mut dirty = lock(&self.batch_dirty);
                let changed = *dirty;
                *dirty = false;
                changed
            };
            if changed {
                let count_changed = self.len() != *lock(&self.batch_count_at_start);
                self.publish(CollectionChangeAction::Reset, None, None, count_changed);
            }
        }
        if let Err(error) = result {
            resume_unwind(error);
        }
    }

    fn publish(
        &self,
        action: CollectionChangeAction,
        old_index: Option<usize>,
        new_index: Option<usize>,
        count_changed: bool,
    ) {
        if *lock(&self.batch_depth) > 0 {
            *lock(&self.batch_dirty) = true;
            return;
        }
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                property_name: "items".to_string(),
                action: action.clone(),
                old_index,
                new_index,
            }));
        if count_changed {
            self.hub
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: self.owner_id,
                    property_name: "Count".to_string(),
                }));
        }
    }
}

#[derive(Clone)]
pub struct ObservableDictionary<K, V>
where
    K: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    inner: Arc<Mutex<Vec<(K, V)>>>,
    hub: MessageHub,
    owner_id: usize,
}

impl<K, V> ObservableDictionary<K, V>
where
    K: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            owner_id,
        }
    }

    pub fn insert(&self, key: K, value: V) {
        let action = {
            let mut inner = lock(&self.inner);
            if let Some((_, existing)) = inner.iter_mut().find(|(candidate, _)| *candidate == key) {
                *existing = value;
                CollectionChangeAction::Replace
            } else {
                inner.push((key, value));
                CollectionChangeAction::Add
            }
        };
        self.publish(action);
    }

    pub fn get(&self, key: &K) -> Option<V> {
        lock(&self.inner)
            .iter()
            .find(|(candidate, _)| candidate == key)
            .map(|(_, value)| value.clone())
    }

    pub fn remove(&self, key: &K) -> Option<V> {
        let removed = {
            let mut inner = lock(&self.inner);
            inner
                .iter()
                .position(|(candidate, _)| candidate == key)
                .map(|index| inner.remove(index).1)
        };
        if removed.is_some() {
            self.publish(CollectionChangeAction::Remove);
        }
        removed
    }

    pub fn clear(&self) {
        let changed = {
            let mut inner = lock(&self.inner);
            let changed = !inner.is_empty();
            inner.clear();
            changed
        };
        if changed {
            self.publish(CollectionChangeAction::Reset);
        }
    }

    pub fn keys(&self) -> Vec<K> {
        lock(&self.inner)
            .iter()
            .map(|(key, _)| key.clone())
            .collect()
    }

    fn publish(&self, action: CollectionChangeAction) {
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                property_name: "items".to_string(),
                action,
                old_index: None,
                new_index: None,
            }));
    }
}

#[derive(Clone)]
pub struct ObservableMultiDictionary<K1, K2, V>
where
    K1: Clone + Eq + Hash + Send + 'static,
    K2: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    inner: Arc<Mutex<Vec<(K1, K2, V)>>>,
    hub: MessageHub,
    owner_id: usize,
}

impl<K1, K2, V> ObservableMultiDictionary<K1, K2, V>
where
    K1: Clone + Eq + Hash + Send + 'static,
    K2: Clone + Eq + Hash + Send + 'static,
    V: Clone + Send + 'static,
{
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            owner_id,
        }
    }

    pub fn insert(&self, key1: K1, key2: K2, value: V) {
        let action = {
            let mut inner = lock(&self.inner);
            if let Some((_, _, existing)) = inner
                .iter_mut()
                .find(|(candidate1, candidate2, _)| *candidate1 == key1 && *candidate2 == key2)
            {
                *existing = value;
                CollectionChangeAction::Replace
            } else {
                inner.push((key1, key2, value));
                CollectionChangeAction::Add
            }
        };
        self.publish(action);
    }

    pub fn remove(&self, key1: &K1, key2: &K2) -> Option<V> {
        let removed = {
            let mut inner = lock(&self.inner);
            inner
                .iter()
                .position(|(candidate1, candidate2, _)| candidate1 == key1 && candidate2 == key2)
                .map(|index| inner.remove(index).2)
        };
        if removed.is_some() {
            self.publish(CollectionChangeAction::Remove);
        }
        removed
    }

    pub fn get(&self, key1: &K1, key2: &K2) -> Option<V> {
        lock(&self.inner)
            .iter()
            .find(|(candidate1, candidate2, _)| candidate1 == key1 && candidate2 == key2)
            .map(|(_, _, value)| value.clone())
    }

    pub fn contains_key(&self, key1: &K1, key2: &K2) -> bool {
        self.get(key1, key2).is_some()
    }

    pub fn count(&self) -> usize {
        lock(&self.inner).len()
    }

    pub fn keys1(&self) -> Vec<K1> {
        let mut keys = Vec::new();
        for (key, _, _) in lock(&self.inner).iter() {
            if !keys.contains(key) {
                keys.push(key.clone());
            }
        }
        keys
    }

    pub fn keys2(&self) -> Vec<K2> {
        let mut keys = Vec::new();
        for (_, key, _) in lock(&self.inner).iter() {
            if !keys.contains(key) {
                keys.push(key.clone());
            }
        }
        keys
    }

    fn publish(&self, action: CollectionChangeAction) {
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                property_name: "items".to_string(),
                action,
                old_index: None,
                new_index: None,
            }));
    }
}

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

#[derive(Clone)]
pub struct GroupVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    items: ObservableList<T>,
    ownership: ParentRegistration,
    auto_construct_on_add: Arc<Mutex<bool>>,
}

impl<T: VmNode> GroupVm<T, NullDispatcher> {
    pub fn new(name: impl Into<String>) -> Self {
        Self::with_services(name, MessageHub::new(), NullDispatcher::new())
    }
}

impl<T: VmNode, D: Dispatcher> GroupVm<T, D> {
    pub fn with_services(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        let core = ComponentCore::new(name, hub.clone(), dispatcher);
        let items: ObservableList<T> = ObservableList::new(core.id(), hub);
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
                let items = items.clone();
                move |child_id, owner_handle| {
                    let index = items
                        .to_vec()
                        .iter()
                        .position(|item| item.id() == child_id)
                        .ok_or(VmxError::InconsistentParent)?;
                    let removed = items
                        .remove_at_silent(index)
                        .ok_or(VmxError::InconsistentParent)?;
                    let commit_items = items.clone();
                    let rollback_items = items.clone();
                    Ok(ParentTransfer::new(
                        move || commit_items.publish_remove(index),
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
            auto_construct_on_add: Arc::new(Mutex::new(false)),
        }
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

    pub fn id(&self) -> usize {
        self.core.id()
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
        }
        self.items.clear();
    }

    pub fn set_auto_construct_on_add(&self, enabled: bool) {
        *lock(&self.auto_construct_on_add) = enabled;
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
                Ok(())
            })
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
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

    pub fn select(&self) {
        self.core.select();
    }

    pub fn deselect(&self) {
        self.core.deselect();
    }

    pub fn is_selected(&self) -> bool {
        self.core.is_selected()
    }

    pub fn select_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new({
            let vm = vm.clone();
            move || vm.select()
        })
        .with_can_execute(move || !vm.is_selected())
    }

    pub fn deselect_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new({
            let vm = vm.clone();
            move || vm.deselect()
        })
        .with_can_execute(move || vm.is_selected())
    }
}

impl<T: VmNode, D: Dispatcher> VmCollection<T> for GroupVm<T, D> {
    fn items(&self) -> Vec<T> {
        GroupVm::items(self)
    }
    fn get(&self, index: usize) -> Option<T> {
        GroupVm::get(self, index)
    }
    fn len(&self) -> usize {
        GroupVm::len(self)
    }
    fn is_empty(&self) -> bool {
        GroupVm::is_empty(self)
    }
    fn add(&self, item: T) -> VmxResult<()> {
        GroupVm::add(self, item)
    }
    fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        GroupVm::insert(self, index, item)
    }
    fn remove(&self, item: &T) -> VmxResult<()> {
        GroupVm::remove(self, item)
    }
    fn remove_at(&self, index: usize) -> VmxResult<T> {
        GroupVm::remove_at(self, index)
    }
    fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        GroupVm::replace(self, index, item)
    }
    fn clear(&self) {
        GroupVm::clear(self);
    }
    fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        GroupVm::move_item(self, from_index, to_index)
    }
    fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        GroupVm::batch_update(self, action);
    }
}

impl<T: VmNode, D: Dispatcher> VmNode for GroupVm<T, D> {
    fn id(&self) -> usize {
        GroupVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        GroupVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        GroupVm::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        GroupVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        GroupVm::status(self)
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

impl<T: VmNode, D: Dispatcher> PartialEq for GroupVm<T, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T: VmNode, D: Dispatcher> Eq for GroupVm<T, D> {}

#[derive(Clone)]
pub struct GroupVmBuilder<T: VmNode, D: Dispatcher = NullDispatcher> {
    name: Option<String>,
    hint: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    children: Option<ChildrenFactory<T>>,
    auto_construct_on_add: bool,
}

impl<T: VmNode> Default for GroupVmBuilder<T, NullDispatcher> {
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            hub: None,
            dispatcher: None,
            children: None,
            auto_construct_on_add: false,
        }
    }
}

impl<T: VmNode, D: Dispatcher> GroupVmBuilder<T, D> {
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

    pub fn build(self) -> VmxResult<GroupVm<T, D>> {
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
        let vm = GroupVm::with_services(name, hub, dispatcher);
        if let Some(hint) = self.hint {
            vm.core.set_hint(Some(hint));
        }
        vm.set_auto_construct_on_add(self.auto_construct_on_add);
        vm.attach_population(children(), false)?;
        Ok(vm)
    }
}

impl<T: VmNode> GroupVm<T, NullDispatcher> {
    pub fn builder() -> GroupVmBuilder<T, NullDispatcher> {
        GroupVmBuilder::default()
    }

    pub fn create(options: GroupVmOptions<T>) -> VmxResult<Self> {
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

pub struct GroupVmOptions<T: VmNode> {
    pub name: Option<String>,
    pub hint: Option<String>,
    pub hub: MessageHub,
    pub dispatcher: NullDispatcher,
    pub children: Option<Vec<T>>,
    pub auto_construct_on_add: bool,
}

#[derive(Clone)]
pub struct PagedComposition<T: Clone + Send + 'static> {
    source: Arc<Mutex<Vec<T>>>,
    page_size: Arc<Mutex<usize>>,
    current_page_index: Arc<Mutex<usize>>,
}

impl<T: Clone + Send + 'static> PagedComposition<T> {
    pub fn new(source: Vec<T>, page_size: usize) -> Self {
        Self {
            source: Arc::new(Mutex::new(source)),
            page_size: Arc::new(Mutex::new(page_size)),
            current_page_index: Arc::new(Mutex::new(0)),
        }
    }

    pub fn page_size(&self) -> usize {
        *lock(&self.page_size)
    }

    pub fn set_page_size(&self, page_size: usize) {
        *lock(&self.page_size) = page_size;
        self.clamp();
    }

    pub fn set_source(&self, source: Vec<T>) {
        *lock(&self.source) = source;
        self.clamp();
    }

    pub fn push(&self, item: T) {
        lock(&self.source).push(item);
        self.clamp();
    }

    pub fn remove_at(&self, index: usize) -> Option<T> {
        let removed = {
            let mut source = lock(&self.source);
            if index >= source.len() {
                None
            } else {
                Some(source.remove(index))
            }
        };
        self.clamp();
        removed
    }

    pub fn page_count(&self) -> usize {
        let len = lock(&self.source).len();
        let page_size = self.page_size();
        if len == 0 {
            0
        } else if page_size == 0 {
            1
        } else {
            len.div_ceil(page_size)
        }
    }

    pub fn current_page_index(&self) -> usize {
        *lock(&self.current_page_index)
    }

    pub fn current_page(&self) -> Vec<T> {
        let source = lock(&self.source);
        let page_size = self.page_size();
        if page_size == 0 {
            return source.clone();
        }
        let start = self.current_page_index() * page_size;
        source.iter().skip(start).take(page_size).cloned().collect()
    }

    pub fn next_page(&self) {
        let max_index = self.page_count().saturating_sub(1);
        let mut current = lock(&self.current_page_index);
        *current = (*current + 1).min(max_index);
    }

    pub fn previous_page(&self) {
        let mut current = lock(&self.current_page_index);
        *current = current.saturating_sub(1);
    }

    fn clamp(&self) {
        let max_index = self.page_count().saturating_sub(1);
        let mut current = lock(&self.current_page_index);
        *current = (*current).min(max_index);
    }
}

type ItemsProvider<T> = Arc<dyn Fn() -> Vec<T> + Send + Sync>;
type SearchPredicate<T> = Arc<dyn Fn(&T, &str) -> bool + Send + Sync>;

#[derive(Clone)]
pub struct SearchableState<T: Clone + Send + Sync + 'static> {
    source: ItemsProvider<T>,
    search_term: Arc<Mutex<String>>,
    predicate: SearchPredicate<T>,
    filtered_changed: MessageHub,
    source_changes_subscription: Arc<Mutex<Option<Subscription>>>,
    disposed: Arc<AtomicBool>,
}

impl<T: Clone + Send + Sync + 'static> SearchableState<T> {
    pub fn new<F>(source: Vec<T>, predicate: F) -> Self
    where
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::build(move || source.clone(), predicate, None)
    }

    pub fn new_with_changes<F>(source: Vec<T>, predicate: F, source_changes: MessageHub) -> Self
    where
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::build(move || source.clone(), predicate, Some(source_changes))
    }

    pub fn from_items<S, F>(source: S, predicate: F) -> Self
    where
        S: Fn() -> Vec<T> + Send + Sync + 'static,
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::build(source, predicate, None)
    }

    pub fn from_items_with_changes<S, F>(
        source: S,
        predicate: F,
        source_changes: MessageHub,
    ) -> Self
    where
        S: Fn() -> Vec<T> + Send + Sync + 'static,
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::build(source, predicate, Some(source_changes))
    }

    fn build<S, F>(source: S, predicate: F, source_changes: Option<MessageHub>) -> Self
    where
        S: Fn() -> Vec<T> + Send + Sync + 'static,
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        let source: ItemsProvider<T> = Arc::new(source);
        if source_changes.is_some() {
            // First half of snapshot/attach reconciliation. The Rust facade is
            // pull-based, so the constructor does not retain this projection.
            let _ = source();
        }
        let state = Self {
            source,
            search_term: Arc::new(Mutex::new(String::new())),
            predicate: Arc::new(predicate),
            filtered_changed: MessageHub::new(),
            source_changes_subscription: Arc::new(Mutex::new(None)),
            disposed: Arc::new(AtomicBool::new(false)),
        };
        if let Some(source_changes) = source_changes {
            let filtered_changed = state.filtered_changed.clone();
            let disposed = state.disposed.clone();
            let subscription = source_changes.subscribe(move |_| {
                if disposed.load(Ordering::Acquire) {
                    return;
                }
                filtered_changed.send(Message::Custom {
                    sender_id: 0,
                    name: "filtered".to_string(),
                });
            });
            *lock(&state.source_changes_subscription) = Some(subscription);

            // Second half of reconciliation: anything that changed before
            // attachment is visible to the first post-construction pull.
            let _ = state.filtered();
        }
        state
    }

    pub fn search_term(&self) -> String {
        lock(&self.search_term).clone()
    }

    pub fn set_search_term(&self, term: impl Into<String>) {
        if self.disposed.load(Ordering::Acquire) {
            return;
        }
        let changed = {
            let mut current = lock(&self.search_term);
            let next = term.into();
            if *current == next {
                false
            } else {
                *current = next;
                true
            }
        };
        if changed {
            self.filtered_changed.send(Message::Custom {
                sender_id: 0,
                name: "filtered".to_string(),
            });
        }
    }

    pub fn search(&self) -> Vec<T> {
        self.filtered()
    }

    pub fn filtered(&self) -> Vec<T> {
        let term = self.search_term();
        (self.source)()
            .into_iter()
            .filter(|item| (self.predicate)(item, &term))
            .collect()
    }

    pub fn can_search(&self) -> bool {
        !(self.source)().is_empty()
    }

    pub fn filtered_changed(&self) -> MessageHub {
        self.filtered_changed.clone()
    }

    pub fn dispose(&self) {
        if self.disposed.swap(true, Ordering::AcqRel) {
            return;
        }
        lock(&self.source_changes_subscription).take();
        self.filtered_changed.dispose();
    }
}

pub struct ModeledCrudCommands<VM: Clone + Send + 'static> {
    create_new_command: RelayCommand,
    update_current_command: RelayCommand,
    delete_current_command: RelayCommand,
    _current_changed_subscription: Option<Subscription>,
    _phantom: std::marker::PhantomData<VM>,
}

impl<VM: Clone + Send + 'static> ModeledCrudCommands<VM> {
    pub fn new<C, Create, Update, Delete>(
        current: C,
        create_new: Create,
        update_current: Update,
        delete_current: Delete,
    ) -> Self
    where
        C: Fn() -> Option<VM> + Send + Sync + 'static,
        Create: Fn() + Send + Sync + 'static,
        Update: Fn(VM) + Send + Sync + 'static,
        Delete: Fn(VM) + Send + Sync + 'static,
    {
        Self::with_current_changed(current, create_new, update_current, delete_current, None)
    }

    pub fn with_current_changed<C, Create, Update, Delete>(
        current: C,
        create_new: Create,
        update_current: Update,
        delete_current: Delete,
        current_changed: Option<MessageHub>,
    ) -> Self
    where
        C: Fn() -> Option<VM> + Send + Sync + 'static,
        Create: Fn() + Send + Sync + 'static,
        Update: Fn(VM) + Send + Sync + 'static,
        Delete: Fn(VM) + Send + Sync + 'static,
    {
        let current = Arc::new(current);
        let create_new = Arc::new(create_new);
        let update_current = Arc::new(update_current);
        let delete_current = Arc::new(delete_current);
        Self::build(
            current,
            create_new,
            update_current,
            delete_current,
            None,
            current_changed,
        )
    }

    pub fn with_confirm_delete<C, Create, Update, Delete, Confirm>(
        current: C,
        create_new: Create,
        update_current: Update,
        delete_current: Delete,
        confirm_delete: Confirm,
    ) -> Self
    where
        C: Fn() -> Option<VM> + Send + Sync + 'static,
        Create: Fn() + Send + Sync + 'static,
        Update: Fn(VM) + Send + Sync + 'static,
        Delete: Fn(VM) + Send + Sync + 'static,
        Confirm: Fn() -> bool + Send + Sync + 'static,
    {
        Self::build(
            Arc::new(current),
            Arc::new(create_new),
            Arc::new(update_current),
            Arc::new(delete_current),
            Some(Arc::new(confirm_delete)),
            None,
        )
    }

    fn build(
        current: Arc<dyn Fn() -> Option<VM> + Send + Sync>,
        create_new: Arc<dyn Fn() + Send + Sync>,
        update_current: Arc<dyn Fn(VM) + Send + Sync>,
        delete_current: Arc<dyn Fn(VM) + Send + Sync>,
        confirm_delete: Option<Arc<dyn Fn() -> bool + Send + Sync>>,
        current_changed: Option<MessageHub>,
    ) -> Self {
        let create_new_command = RelayCommand::new(move || create_new());
        let update_provider = current.clone();
        let update_predicate = current.clone();
        let update_current_command = RelayCommand::new(move || {
            if let Some(current) = update_provider() {
                update_current(current);
            }
        })
        .with_can_execute(move || update_predicate().is_some());
        let delete_provider = current.clone();
        let delete_predicate = current.clone();
        let confirm_delete = confirm_delete.unwrap_or_else(|| Arc::new(|| true));
        let delete_current_command = RelayCommand::new(move || {
            if confirm_delete() {
                if let Some(current) = delete_provider() {
                    delete_current(current);
                }
            }
        })
        .with_can_execute(move || delete_predicate().is_some());
        let subscription = current_changed.map(|trigger| {
            let update_hub = update_current_command.can_execute_changed();
            let delete_hub = delete_current_command.can_execute_changed();
            trigger.subscribe(move |_| {
                update_hub.send(Message::Custom {
                    sender_id: 0,
                    name: "can_execute_changed".to_string(),
                });
                delete_hub.send(Message::Custom {
                    sender_id: 0,
                    name: "can_execute_changed".to_string(),
                });
            })
        });
        Self {
            create_new_command,
            update_current_command,
            delete_current_command,
            _current_changed_subscription: subscription,
            _phantom: std::marker::PhantomData,
        }
    }

    pub fn create_new_command(&self) -> RelayCommand {
        self.create_new_command.clone()
    }

    pub fn update_current_command(&self) -> RelayCommand {
        self.update_current_command.clone()
    }

    pub fn delete_current_command(&self) -> RelayCommand {
        self.delete_current_command.clone()
    }
}

#[derive(Clone)]
pub struct DerivedProperty<T: Clone + PartialEq + Send + 'static> {
    value: Arc<Mutex<T>>,
    value_changed: MessageHub,
    validator: Arc<dyn Fn(&T) -> bool + Send + Sync>,
    write_back: Arc<dyn Fn(T) + Send + Sync>,
    disposed: Arc<Mutex<bool>>,
}

impl<T: Clone + PartialEq + Send + 'static> DerivedProperty<T> {
    pub fn new(value: T) -> Self {
        Self {
            value: Arc::new(Mutex::new(value)),
            value_changed: MessageHub::new(),
            validator: Arc::new(|_| false),
            write_back: Arc::new(|_| {}),
            disposed: Arc::new(Mutex::new(false)),
        }
    }

    pub fn with_write_back<Validate, WriteBack>(
        value: T,
        validator: Validate,
        write_back: WriteBack,
    ) -> Self
    where
        Validate: Fn(&T) -> bool + Send + Sync + 'static,
        WriteBack: Fn(T) + Send + Sync + 'static,
    {
        Self {
            value: Arc::new(Mutex::new(value)),
            value_changed: MessageHub::new(),
            validator: Arc::new(validator),
            write_back: Arc::new(write_back),
            disposed: Arc::new(Mutex::new(false)),
        }
    }

    pub fn value(&self) -> T {
        lock(&self.value).clone()
    }

    pub fn recompute<F>(&self, transform: F)
    where
        F: FnOnce(&T) -> T,
    {
        if *lock(&self.disposed) {
            return;
        }
        let next = transform(&lock(&self.value));
        let changed = {
            let mut value = lock(&self.value);
            if *value == next {
                false
            } else {
                *value = next;
                true
            }
        };
        if changed {
            self.value_changed
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: 0,
                    property_name: "value".to_string(),
                }));
        }
    }

    pub fn value_changed(&self) -> MessageHub {
        self.value_changed.clone()
    }

    pub fn can_set(&self, value: &T) -> bool {
        !*lock(&self.disposed) && (self.validator)(value)
    }

    pub fn set_value(&self, value: T) -> VmxResult<()> {
        if !self.can_set(&value) {
            return Err(VmxError::InvalidArgument(
                "derived property is read-only".to_string(),
            ));
        }
        (self.write_back)(value);
        Ok(())
    }

    pub fn dispose(&self) {
        *lock(&self.disposed) = true;
        self.value_changed.dispose();
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NotificationType {
    Error,
    Notification,
    Confirmation,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NotificationReaction {
    Pending,
    Approve,
    Reject,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Notification {
    pub id: u64,
    pub kind: NotificationType,
    pub message: String,
}

impl Notification {
    pub fn new(kind: NotificationType, message: impl Into<String>) -> Self {
        static NEXT_NOTIFICATION_ID: AtomicU64 = AtomicU64::new(1);
        Self {
            id: NEXT_NOTIFICATION_ID.fetch_add(1, Ordering::Relaxed),
            kind,
            message: message.into(),
        }
    }
}

#[derive(Clone)]
pub struct NotificationWaiter {
    completion: AsyncValue<NotificationReaction>,
}

impl NotificationWaiter {
    pub fn wait(&self) -> NotificationReaction {
        self.completion.wait()
    }
}

impl Future for NotificationWaiter {
    type Output = NotificationReaction;

    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        Pin::new(&mut self.completion).poll(context)
    }
}

#[derive(Default)]
struct NotificationHubState {
    pending: BTreeMap<u64, Notification>,
    reactions: HashMap<u64, NotificationReaction>,
    completions: HashMap<u64, AsyncValue<NotificationReaction>>,
    pending_snapshots: Vec<Vec<Notification>>,
    disposed: bool,
}

#[derive(Clone, Default)]
pub struct NotificationHub {
    state: Arc<Mutex<NotificationHubState>>,
    pending_changed: MessageHub,
}

impl NotificationHub {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn post_notification(&self, notification: Notification) -> NotificationWaiter {
        let notification_id = notification.id;
        let (completion, publish) = {
            let mut state = lock(&self.state);
            if state.disposed {
                state
                    .reactions
                    .insert(notification_id, NotificationReaction::Pending);
                (AsyncValue::ready(NotificationReaction::Pending), false)
            } else if let Some(completion) = state.completions.get(&notification_id).cloned() {
                (completion, false)
            } else {
                let completion = AsyncValue::pending();
                state.pending.insert(notification_id, notification);
                state
                    .reactions
                    .insert(notification_id, NotificationReaction::Pending);
                state
                    .completions
                    .insert(notification_id, completion.clone());
                let snapshot = state.pending.values().cloned().collect();
                state.pending_snapshots.push(snapshot);
                (completion, true)
            }
        };
        if publish {
            self.publish_pending();
        }
        NotificationWaiter { completion }
    }

    pub fn post(&self, kind: NotificationType, message: impl Into<String>) -> Notification {
        let notification = Notification::new(kind, message);
        self.post_notification(notification.clone());
        notification
    }

    pub fn post_with_waiter(
        &self,
        kind: NotificationType,
        message: impl Into<String>,
    ) -> (Notification, NotificationWaiter) {
        let notification = Notification::new(kind, message);
        let waiter = self.post_notification(notification.clone());
        (notification, waiter)
    }

    pub fn resolve(&self, notification_id: u64, reaction: NotificationReaction) {
        let completion = {
            let mut state = lock(&self.state);
            if state.pending.remove(&notification_id).is_none() {
                return;
            }
            state.reactions.insert(notification_id, reaction);
            let completion = state.completions.remove(&notification_id);
            let snapshot = state.pending.values().cloned().collect();
            state.pending_snapshots.push(snapshot);
            completion
        };
        if let Some(completion) = completion {
            completion.resolve(reaction);
        }
        self.publish_pending();
    }

    pub fn pending(&self) -> Vec<Notification> {
        lock(&self.state).pending.values().cloned().collect()
    }

    pub fn pending_changed(&self) -> MessageHub {
        self.pending_changed.clone()
    }

    pub fn pending_snapshots(&self) -> Vec<Vec<Notification>> {
        lock(&self.state).pending_snapshots.clone()
    }

    pub fn reaction(&self, notification_id: u64) -> NotificationReaction {
        lock(&self.state)
            .reactions
            .get(&notification_id)
            .copied()
            .unwrap_or(NotificationReaction::Pending)
    }

    pub fn dispose(&self) {
        let completions = {
            let mut state = lock(&self.state);
            if state.disposed {
                return;
            }
            state.disposed = true;
            let pending_ids = state.pending.keys().copied().collect::<Vec<_>>();
            for id in pending_ids {
                state.reactions.insert(id, NotificationReaction::Pending);
            }
            let completions = state
                .completions
                .drain()
                .map(|(_, value)| value)
                .collect::<Vec<_>>();
            state.pending.clear();
            state.pending_snapshots.push(Vec::new());
            completions
        };
        for completion in completions {
            completion.resolve(NotificationReaction::Pending);
        }
        self.publish_pending();
    }

    fn publish_pending(&self) {
        self.pending_changed.send(Message::Custom {
            sender_id: 0,
            name: "pending".to_string(),
        });
    }
}

pub struct NullNotificationHub;

impl NullNotificationHub {
    pub fn post(_notification: Notification) -> NotificationWaiter {
        NotificationWaiter {
            completion: AsyncValue::ready(NotificationReaction::Approve),
        }
    }

    pub fn post_message(message: impl Into<String>) -> (Notification, NotificationWaiter) {
        let notification = Notification {
            id: 0,
            kind: NotificationType::Notification,
            message: message.into(),
        };
        (
            notification,
            NotificationWaiter {
                completion: AsyncValue::ready(NotificationReaction::Approve),
            },
        )
    }
}

pub fn make_confirm(
    hub: NotificationHub,
    prompt: impl Into<String>,
) -> impl Fn() -> AsyncValue<bool> + Clone {
    let prompt = Arc::new(prompt.into());
    move || {
        let (_, waiter) = hub.post_with_waiter(NotificationType::Confirmation, (*prompt).clone());
        let decision = AsyncValue::pending();
        let resolved = decision.clone();
        std::thread::spawn(move || {
            resolved.resolve(waiter.wait() == NotificationReaction::Approve);
        });
        decision
    }
}

pub trait Localizer: Send + Sync {
    fn localize(&self, key: &str) -> String;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NullLocalizer;

impl Localizer for NullLocalizer {
    fn localize(&self, key: &str) -> String {
        key.to_string()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileFilter {
    pub description: String,
    pub extensions: Vec<String>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum NotificationSeverity {
    #[default]
    Info,
    Warning,
    Error,
}

pub trait DialogService: Send + Sync {
    fn pick_file_to_open(
        &self,
        filter: Option<FileFilter>,
        title: Option<&str>,
    ) -> AsyncValue<Option<String>>;
    fn pick_file_to_save(
        &self,
        filter: Option<FileFilter>,
        title: Option<&str>,
        suggested_name: Option<&str>,
    ) -> AsyncValue<Option<String>>;
    fn confirm(&self, message: &str, title: Option<&str>) -> AsyncValue<bool>;
    fn notify(
        &self,
        message: &str,
        title: Option<&str>,
        severity: NotificationSeverity,
    ) -> AsyncValue<()>;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NullDialogService;

impl DialogService for NullDialogService {
    fn pick_file_to_open(
        &self,
        _filter: Option<FileFilter>,
        _title: Option<&str>,
    ) -> AsyncValue<Option<String>> {
        AsyncValue::ready(None)
    }

    fn pick_file_to_save(
        &self,
        _filter: Option<FileFilter>,
        _title: Option<&str>,
        _suggested_name: Option<&str>,
    ) -> AsyncValue<Option<String>> {
        AsyncValue::ready(None)
    }

    fn confirm(&self, _message: &str, _title: Option<&str>) -> AsyncValue<bool> {
        AsyncValue::ready(false)
    }

    fn notify(
        &self,
        _message: &str,
        _title: Option<&str>,
        _severity: NotificationSeverity,
    ) -> AsyncValue<()> {
        AsyncValue::ready(())
    }
}

impl NullDialogService {
    pub fn present<T: Clone + Send + 'static>(&self, modal: &ModalVm<T>) -> AsyncValue<T> {
        modal.dispose();
        modal.completion()
    }
}

mod forms;
pub use forms::{FormVm, FormVmBuilder};

#[derive(Clone)]
pub struct DiscriminatorVm<K: Clone + Eq + Hash + Send + 'static> {
    current_key: Arc<Mutex<K>>,
    allowed: Arc<Mutex<HashSet<K>>>,
    active_changed: MessageHub,
    modal_stack: Arc<Mutex<Vec<K>>>,
}

impl<K: Clone + Eq + Hash + Send + 'static> DiscriminatorVm<K> {
    pub fn new(initial: K, allowed: impl IntoIterator<Item = K>) -> Self {
        let mut allowed_set = allowed.into_iter().collect::<HashSet<_>>();
        allowed_set.insert(initial.clone());
        Self {
            current_key: Arc::new(Mutex::new(initial)),
            allowed: Arc::new(Mutex::new(allowed_set)),
            active_changed: MessageHub::new(),
            modal_stack: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn current_key(&self) -> K {
        lock(&self.current_key).clone()
    }

    pub fn active_key(&self) -> K {
        self.current_key()
    }

    pub fn set_current_key(&self, key: K) -> VmxResult<()> {
        self.set_active_key(key)
    }

    pub fn set_active_key(&self, key: K) -> VmxResult<()> {
        if !lock(&self.allowed).contains(&key) {
            return Err(VmxError::InvalidArgument(
                "unknown discriminator key".to_string(),
            ));
        }
        let changed = {
            let mut current = lock(&self.current_key);
            if *current == key {
                false
            } else {
                *current = key;
                true
            }
        };
        if changed {
            self.active_changed.send(Message::Custom {
                sender_id: 0,
                name: "active_changed".to_string(),
            });
        }
        Ok(())
    }

    pub fn is_active(&self, key: &K) -> bool {
        lock(&self.current_key).eq(key)
    }

    pub fn active_changed(&self) -> MessageHub {
        self.active_changed.clone()
    }

    pub fn modal_open(&self, key: K) -> VmxResult<()> {
        lock(&self.allowed).insert(key.clone());
        let previous = self.active_key();
        lock(&self.modal_stack).push(previous);
        self.set_active_key(key)
    }

    pub fn modal_close(&self) -> VmxResult<()> {
        let previous = lock(&self.modal_stack).pop();
        if let Some(previous) = previous {
            self.set_active_key(previous)?;
        }
        Ok(())
    }
}

type HierChildrenFactory<M> =
    Arc<dyn Fn(&HierarchicalVm<M>) -> Vec<HierarchicalVm<M>> + Send + Sync>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MissingParentPolicy {
    Park,
    Reject,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BatchAttachRejectionReason {
    DuplicateExistingKey,
    DuplicateBatchKey,
    AlreadyAttached,
    MissingParent,
    Cycle,
    SelectorFailed,
    AttachmentFailed,
}

pub struct BatchAttachRejection<N> {
    pub item: N,
    pub reason: BatchAttachRejectionReason,
    pub detail: Option<String>,
}

pub struct BatchAttachResult<N> {
    pub added: Vec<N>,
    pub duplicates: Vec<N>,
    pub orphans: Vec<N>,
    pub rejections: Vec<BatchAttachRejection<N>>,
}

struct BatchAttachCandidate<N, K> {
    item: N,
    key: K,
    parent_key: Option<K>,
    retain_if_missing: bool,
}

#[derive(Clone)]
pub struct HierarchicalVm<M: Clone + PartialEq + Send + Sync + 'static> {
    inner: Arc<HierarchicalVmInner<M>>,
}

struct HierarchicalVmInner<M: Clone + PartialEq + Send + Sync + 'static> {
    component: ComponentVm<M>,
    children: Arc<Mutex<Option<Vec<HierarchicalVm<M>>>>>,
    materializing_children: Arc<(Mutex<Option<ThreadId>>, Condvar)>,
    parent: Mutex<Option<Weak<HierarchicalVmInner<M>>>>,
    children_factory: HierChildrenFactory<M>,
    eager_children: Arc<Mutex<bool>>,
    expanded_for_walk: Arc<Mutex<bool>>,
    parked_attach_items: Arc<Mutex<Vec<HierarchicalVm<M>>>>,
    hub: MessageHub,
}

impl<M: Clone + PartialEq + Send + Sync + 'static> HierarchicalVm<M> {
    pub fn new(name: impl Into<String>, model: M) -> Self {
        Self::with_children_factory(name, model, |_| Vec::new(), false, MessageHub::new())
    }

    pub fn with_children_factory<F>(
        name: impl Into<String>,
        model: M,
        children_factory: F,
        eager_children: bool,
        hub: MessageHub,
    ) -> Self
    where
        F: Fn(&Self) -> Vec<Self> + Send + Sync + 'static,
    {
        Self {
            inner: Arc::new(HierarchicalVmInner {
                component: ComponentVm::with_model(name, model, hub.clone(), NullDispatcher::new()),
                children: Arc::new(Mutex::new(None)),
                materializing_children: Arc::new((Mutex::new(None), Condvar::new())),
                parent: Mutex::new(None),
                children_factory: Arc::new(children_factory),
                eager_children: Arc::new(Mutex::new(eager_children)),
                expanded_for_walk: Arc::new(Mutex::new(true)),
                parked_attach_items: Arc::new(Mutex::new(Vec::new())),
                hub,
            }),
        }
    }

    pub fn builder() -> HierarchicalVmBuilder<M> {
        HierarchicalVmBuilder::new()
    }

    pub fn id(&self) -> usize {
        self.inner.component.id()
    }

    pub fn name(&self) -> String {
        self.inner.component.name()
    }

    pub fn model(&self) -> M {
        self.inner.component.model()
    }

    pub fn hint(&self) -> Option<String> {
        self.inner.component.hint()
    }

    pub fn hub(&self) -> MessageHub {
        self.inner.hub.clone()
    }

    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.inner.component.own(cleanup);
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.component.property_changed()
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.component.notify_property_changed(property_name);
    }

    pub fn parent(&self) -> Option<Self> {
        let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
        self.parent_unlocked()
    }

    fn parent_unlocked(&self) -> Option<Self> {
        lock(&self.inner.parent)
            .as_ref()
            .and_then(Weak::upgrade)
            .map(|inner| Self { inner })
    }

    pub fn add_child(&self, child: Self) -> VmxResult<()> {
        self.attach_child(&child)
    }

    pub fn remove_child(&self, child: &Self) -> VmxResult<()> {
        self.materialize_children();
        let removed = {
            let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
            let mut children = lock(&self.inner.children);
            let children = children.as_mut().expect("children materialized");
            let removed = children
                .iter()
                .position(|candidate| candidate == child)
                .map(|index| children.remove(index));
            if let Some(removed) = &removed {
                removed.set_parent_state(None);
            }
            removed
        }
        .ok_or(VmxError::NonChild)?;
        removed.publish_parent_changed();
        self.inner
            .hub
            .send(Message::TreeStructureChanged(TreeStructureChangedMessage {
                sender_id: self.id(),
            }));
        Ok(())
    }

    pub fn reparent_child(&self, child: &Self) -> VmxResult<()> {
        self.attach_child(child)
    }

    fn attach_child(&self, child: &Self) -> VmxResult<()> {
        // Materialize the destination before detaching so a child factory
        // failure cannot orphan an attached child.
        loop {
            self.materialize_children();
            let attached = {
                let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
                if lock(&self.inner.children).is_none() {
                    None
                } else {
                    self.ensure_not_reparenting_cycle_unlocked(child)?;
                    let old_parent = child.parent_unlocked();
                    if old_parent.as_ref() == Some(self) {
                        return Ok(());
                    }
                    if let Some(parent) = &old_parent {
                        if let Some(children) = lock(&parent.inner.children).as_mut() {
                            children.retain(|candidate| candidate != child);
                        }
                    }
                    let mut children = lock(&self.inner.children);
                    let children = children.as_mut().expect("children materialized");
                    if !children.iter().any(|candidate| candidate == child) {
                        children.push(child.clone());
                    }
                    child.set_parent_state(Some(self.clone()));
                    Some(())
                }
            };
            if attached.is_some() {
                break;
            }
        }
        child.publish_parent_changed();
        self.inner
            .hub
            .send(Message::TreeStructureChanged(TreeStructureChangedMessage {
                sender_id: self.id(),
            }));
        Ok(())
    }

    pub fn parked_attach_count(&self) -> usize {
        lock(&self.tree_root().inner.parked_attach_items).len()
    }

    pub fn attach_many<K, FKey, FParent>(
        &self,
        items: Vec<Self>,
        key_of: FKey,
        parent_key_of: FParent,
        on_missing_parent: MissingParentPolicy,
    ) -> BatchAttachResult<Self>
    where
        K: Clone + Eq + Hash,
        FKey: Fn(&Self) -> VmxResult<K>,
        FParent: Fn(&Self) -> VmxResult<Option<K>>,
    {
        let root = self.tree_root();
        let parked = std::mem::take(&mut *lock(&root.inner.parked_attach_items));
        let mut added = Vec::new();
        let mut duplicates = Vec::new();
        let mut orphans = Vec::new();
        let mut rejections = Vec::new();
        let mut existing = HashMap::<K, Self>::new();

        for materialized in root.materialized_subtree() {
            let key = match key_of(&materialized) {
                Ok(key) => key,
                Err(error) => {
                    lock(&root.inner.parked_attach_items).extend(parked.iter().cloned());
                    rejections.extend(parked.into_iter().chain(items).map(|item| {
                        BatchAttachRejection {
                            item,
                            reason: BatchAttachRejectionReason::SelectorFailed,
                            detail: Some(error.to_string()),
                        }
                    }));
                    return BatchAttachResult {
                        added,
                        duplicates,
                        orphans,
                        rejections,
                    };
                }
            };
            existing.entry(key).or_insert(materialized);
        }

        let mut candidates = Vec::<BatchAttachCandidate<Self, K>>::new();
        let mut candidate_keys = HashSet::<K>::new();
        let active = parked
            .into_iter()
            .map(|item| (item, true))
            .chain(items.into_iter().map(|item| (item, false)));
        for (item, was_parked) in active {
            let key = match key_of(&item) {
                Ok(key) => key,
                Err(error) => {
                    if was_parked {
                        lock(&root.inner.parked_attach_items).push(item.clone());
                    }
                    rejections.push(BatchAttachRejection {
                        item,
                        reason: BatchAttachRejectionReason::SelectorFailed,
                        detail: Some(error.to_string()),
                    });
                    continue;
                }
            };
            let parent_key = match parent_key_of(&item) {
                Ok(parent_key) => parent_key,
                Err(error) => {
                    if was_parked {
                        lock(&root.inner.parked_attach_items).push(item.clone());
                    }
                    rejections.push(BatchAttachRejection {
                        item,
                        reason: BatchAttachRejectionReason::SelectorFailed,
                        detail: Some(error.to_string()),
                    });
                    continue;
                }
            };

            if existing.contains_key(&key) {
                duplicates.push(item.clone());
                rejections.push(BatchAttachRejection {
                    item,
                    reason: BatchAttachRejectionReason::DuplicateExistingKey,
                    detail: None,
                });
                continue;
            }
            if candidate_keys.contains(&key) {
                duplicates.push(item.clone());
                rejections.push(BatchAttachRejection {
                    item,
                    reason: BatchAttachRejectionReason::DuplicateBatchKey,
                    detail: None,
                });
                continue;
            }
            if item.parent().is_some() {
                rejections.push(BatchAttachRejection {
                    item,
                    reason: BatchAttachRejectionReason::AlreadyAttached,
                    detail: None,
                });
                continue;
            }
            candidate_keys.insert(key.clone());
            candidates.push(BatchAttachCandidate {
                item,
                key,
                parent_key,
                retain_if_missing: was_parked || on_missing_parent == MissingParentPolicy::Park,
            });
        }

        let mut unresolved = candidates;
        loop {
            if unresolved.is_empty() {
                break;
            }
            let mut next = Vec::new();
            let mut progressed = false;
            for candidate in unresolved {
                let parent = candidate
                    .parent_key
                    .as_ref()
                    .and_then(|key| existing.get(key).cloned())
                    .or_else(|| candidate.parent_key.is_none().then(|| root.clone()));
                let Some(parent) = parent else {
                    next.push(candidate);
                    continue;
                };
                if let Err(error) = parent.add_child(candidate.item.clone()) {
                    Self::rollback_batch_attach(&parent, &candidate.item);
                    rejections.push(BatchAttachRejection {
                        item: candidate.item,
                        reason: BatchAttachRejectionReason::AttachmentFailed,
                        detail: Some(error.to_string()),
                    });
                    continue;
                }
                existing.insert(candidate.key, candidate.item.clone());
                added.push(candidate.item);
                progressed = true;
            }
            unresolved = next;
            if !progressed {
                break;
            }
        }

        let unresolved_by_key = unresolved
            .iter()
            .map(|candidate| (candidate.key.clone(), candidate.parent_key.clone()))
            .collect::<HashMap<_, _>>();
        for candidate in unresolved {
            let is_cycle = Self::batch_parent_chain_cycles(&candidate, &unresolved_by_key);
            let reason = if is_cycle {
                BatchAttachRejectionReason::Cycle
            } else {
                BatchAttachRejectionReason::MissingParent
            };
            rejections.push(BatchAttachRejection {
                item: candidate.item.clone(),
                reason,
                detail: None,
            });
            if !is_cycle {
                orphans.push(candidate.item.clone());
                if candidate.retain_if_missing {
                    lock(&root.inner.parked_attach_items).push(candidate.item);
                }
            }
        }

        BatchAttachResult {
            added,
            duplicates,
            orphans,
            rejections,
        }
    }

    pub fn children(&self) -> Vec<Self> {
        self.materialize_children()
    }

    pub fn is_children_materialized(&self) -> bool {
        let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
        lock(&self.inner.children).is_some()
    }

    pub fn is_root(&self) -> bool {
        self.parent().is_none()
    }

    pub fn is_leaf(&self) -> bool {
        self.children().is_empty()
    }

    pub fn depth(&self) -> usize {
        self.parent().map(|parent| parent.depth() + 1).unwrap_or(0)
    }

    pub fn path(&self) -> Vec<Self> {
        let mut path = self
            .parent()
            .map(|parent| parent.path())
            .unwrap_or_default();
        path.push(self.clone());
        path
    }

    pub fn is_first(&self) -> bool {
        self.parent()
            .and_then(|parent| parent.children().first().cloned())
            .map(|first| first == *self)
            .unwrap_or(false)
    }

    pub fn is_last(&self) -> bool {
        self.parent()
            .and_then(|parent| parent.children().last().cloned())
            .map(|last| last == *self)
            .unwrap_or(false)
    }

    pub fn construct(&self) -> VmxResult<()> {
        if *lock(&self.inner.eager_children) {
            for child in self.children() {
                child.construct()?;
            }
        }
        self.inner.component.construct()
    }

    pub fn status(&self) -> ConstructionStatus {
        self.inner.component.status()
    }

    pub fn invalidate_children(&self) {
        let was_materialized = {
            let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
            let discarded = lock(&self.inner.children).take();
            if let Some(children) = &discarded {
                for child in children {
                    let attached_to_self = child.parent_unlocked().as_ref() == Some(self);
                    if attached_to_self {
                        child.set_parent_state(None);
                    }
                }
            }
            discarded.is_some()
        };
        if was_materialized {
            self.inner
                .hub
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: self.id(),
                    property_name: "children".to_string(),
                }));
        }
    }

    pub fn invalidate_subtree(&self) {
        let materialized_children = lock(&self.inner.children).clone();
        if let Some(children) = materialized_children {
            for child in children {
                child.invalidate_subtree();
            }
            self.invalidate_children();
        }
    }

    pub fn dispose(&self) -> VmxResult<()> {
        lock(&self.inner.parked_attach_items).clear();
        self.inner.component.dispose()
    }

    pub fn set_expanded_for_walk(&self, expanded: bool) {
        *lock(&self.inner.expanded_for_walk) = expanded;
    }

    fn materialize_children(&self) -> Vec<Self> {
        let current = thread::current().id();
        loop {
            {
                let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
                if let Some(children) = lock(&self.inner.children).clone() {
                    return children;
                }
            }

            let (owner, ready) = &*self.inner.materializing_children;
            let mut owner = lock(owner);
            if let Some(children) = lock(&self.inner.children).clone() {
                return children;
            }
            match *owner {
                None => {
                    *owner = Some(current);
                    break;
                }
                Some(active) if active == current => return Vec::new(),
                Some(_) => {
                    drop(wait(ready, owner));
                }
            }
        }

        let generated = catch_unwind(AssertUnwindSafe(|| (self.inner.children_factory)(self)));
        let children = match generated {
            Ok(children) => children,
            Err(error) => {
                self.finish_children_materialization();
                resume_unwind(error);
            }
        };
        {
            let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
            for child in &children {
                child.set_parent_state(Some(self.clone()));
            }
            *lock(&self.inner.children) = Some(children.clone());
        }
        self.finish_children_materialization();
        for child in &children {
            child.publish_parent_changed();
        }
        children
    }

    fn tree_root(&self) -> Self {
        let mut current = self.clone();
        while let Some(parent) = current.parent() {
            current = parent;
        }
        current
    }

    fn materialized_subtree(&self) -> Vec<Self> {
        let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
        let mut result = Vec::new();
        let mut stack = vec![self.clone()];
        while let Some(current) = stack.pop() {
            result.push(current.clone());
            if let Some(children) = lock(&current.inner.children).clone() {
                stack.extend(children.into_iter().rev());
            }
        }
        result
    }

    fn batch_parent_chain_cycles<K: Clone + Eq + Hash>(
        candidate: &BatchAttachCandidate<Self, K>,
        unresolved: &HashMap<K, Option<K>>,
    ) -> bool {
        let mut seen = HashSet::new();
        let mut current_key = candidate.key.clone();
        loop {
            if !seen.insert(current_key.clone()) {
                return true;
            }
            match unresolved.get(&current_key) {
                Some(Some(parent_key)) => current_key = parent_key.clone(),
                Some(None) | None => return false,
            }
        }
    }

    fn rollback_batch_attach(parent: &Self, child: &Self) {
        let _topology = lock(&HIERARCHY_TOPOLOGY_GATE);
        if let Some(children) = lock(&parent.inner.children).as_mut() {
            children.retain(|item| item.id() != child.id());
        }
        child.set_parent_state(None);
    }

    fn set_parent_state(&self, parent: Option<Self>) {
        *lock(&self.inner.parent) = parent.as_ref().map(|parent| Arc::downgrade(&parent.inner));
        self.inner
            .component
            .core
            .set_parent_id(parent.as_ref().map(|parent| parent.id()));
    }

    fn publish_parent_changed(&self) {
        self.inner
            .hub
            .send(Message::PropertyChanged(PropertyChangedMessage {
                sender_id: self.id(),
                property_name: "Parent".to_string(),
            }));
    }

    fn ensure_not_reparenting_cycle_unlocked(&self, child: &Self) -> VmxResult<()> {
        let mut current = Some(self.clone());
        while let Some(node) = current {
            if node == *child {
                return Err(VmxError::InvalidArgument(
                    "cannot reparent self or ancestor".to_string(),
                ));
            }
            current = node.parent_unlocked();
        }
        if child.id() == self.id() {
            return Err(VmxError::InvalidArgument(
                "cannot reparent self or ancestor".to_string(),
            ));
        }
        Ok(())
    }

    fn finish_children_materialization(&self) {
        let (owner, ready) = &*self.inner.materializing_children;
        *lock(owner) = None;
        ready.notify_all();
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> PartialEq for HierarchicalVm<M> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> Eq for HierarchicalVm<M> {}

impl<M: Clone + PartialEq + Send + Sync + 'static> VmNode for HierarchicalVm<M> {
    fn id(&self) -> usize {
        HierarchicalVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        HierarchicalVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        self.inner.component.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        HierarchicalVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        HierarchicalVm::status(self)
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.component.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.inner.component.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner.component.core.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.inner.component.core.parent_handle()
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> TreeNode for HierarchicalVm<M> {
    fn children_nodes(&self) -> Vec<Self> {
        self.children()
    }

    fn is_expanded_for_walk(&self) -> bool {
        *lock(&self.inner.expanded_for_walk)
    }
}

#[derive(Clone)]
pub struct HierarchicalVmBuilder<M: Clone + PartialEq + Send + Sync + 'static> {
    model: Option<M>,
    children_factory: Option<HierChildrenFactory<M>>,
    services: Option<(MessageHub, NullDispatcher)>,
    hint: Option<String>,
    eager_children: bool,
}

impl<M: Clone + PartialEq + Send + Sync + 'static> Default for HierarchicalVmBuilder<M> {
    fn default() -> Self {
        Self {
            model: None,
            children_factory: None,
            services: None,
            hint: None,
            eager_children: false,
        }
    }
}

impl<M: Clone + PartialEq + Send + Sync + 'static> HierarchicalVmBuilder<M> {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn model(mut self, model: M) -> Self {
        self.model = Some(model);
        self
    }

    pub fn children_factory<F>(mut self, factory: F) -> Self
    where
        F: Fn(&HierarchicalVm<M>) -> Vec<HierarchicalVm<M>> + Send + Sync + 'static,
    {
        self.children_factory = Some(Arc::new(factory));
        self
    }

    pub fn services(mut self, hub: MessageHub, dispatcher: NullDispatcher) -> Self {
        self.services = Some((hub, dispatcher));
        self
    }

    pub fn hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }

    pub fn eager_children(mut self, eager: bool) -> Self {
        self.eager_children = eager;
        self
    }

    pub fn build(self) -> VmxResult<HierarchicalVm<M>> {
        let model = self
            .model
            .ok_or_else(|| VmxError::BuilderValidation("model is required".to_string()))?;
        let factory = self.children_factory.ok_or_else(|| {
            VmxError::BuilderValidation("children_factory is required".to_string())
        })?;
        let (hub, _dispatcher) = self
            .services
            .ok_or_else(|| VmxError::BuilderValidation("services are required".to_string()))?;
        let node = HierarchicalVm::with_children_factory(
            "HierarchicalVm",
            model,
            move |parent| factory(parent),
            self.eager_children,
            hub,
        );
        if let Some(hint) = self.hint {
            node.inner.component.core.set_hint(Some(hint));
        }
        Ok(node)
    }
}

pub fn walk<T: TreeNode>(root: &T) -> Vec<T> {
    let mut nodes = vec![root.clone()];
    for child in root.children_nodes() {
        nodes.extend(walk(&child));
    }
    nodes
}

pub fn find<T: TreeNode, F>(root: &T, predicate: F) -> Option<T>
where
    F: Fn(&T) -> bool,
{
    find_inner(root, &predicate)
}

fn find_inner<T: TreeNode, F>(root: &T, predicate: &F) -> Option<T>
where
    F: Fn(&T) -> bool,
{
    if predicate(root) {
        return Some(root.clone());
    }
    for child in root.children_nodes() {
        if let Some(found) = find_inner(&child, predicate) {
            return Some(found);
        }
    }
    None
}

pub fn walk_expanded<T: TreeNode>(root: &T) -> Vec<T> {
    let mut nodes = vec![root.clone()];
    if root.is_expanded_for_walk() {
        for child in root.children_nodes() {
            nodes.extend(walk_expanded(&child));
        }
    }
    nodes
}

pub fn lifecycle_transition_fixture() -> &'static str {
    include_str!("fixtures/lifecycle-transitions.json")
}

pub trait Selectable {
    fn can_select(&self) -> bool;
    fn select(&self);
}

pub trait Deselectable {
    fn can_deselect(&self) -> bool;
    fn deselect(&self);
}

pub trait SelectionTogglable {
    fn can_toggle_selection(&self) -> bool;
    fn toggle_selection(&self);
}

pub trait Expandable {
    fn can_expand(&self) -> bool;
    fn expand(&self);
}

pub trait Collapsible {
    fn can_collapse(&self) -> bool;
    fn collapse(&self);
}

pub trait ExpansionTogglable {
    fn can_toggle_expansion(&self) -> bool;
    fn toggle_expansion(&self);
}

pub trait Closable {
    fn can_close(&self) -> bool;
    fn close(&self);
}

pub trait Searchable {
    fn can_search(&self) -> bool;
    fn search_term(&self) -> String;
    fn search(&self);
}

pub trait Approvable {
    fn can_approve(&self) -> bool;
    fn approve(&self);
}

pub trait Cancelable {
    fn can_cancel(&self) -> bool;
    fn cancel(&self);
}

pub trait Savable<T> {
    fn can_save(&self, item: &T) -> bool;
    fn save(&self, item: T);
}

pub trait Managable<T> {
    fn can_manage(&self, item: &T) -> bool;
    fn manage(&self, item: T);
}

pub trait NewCreatable {
    fn can_create_new(&self) -> bool;
    fn create_new(&self);
}

pub trait Deletable<T> {
    fn can_delete(&self, item: &T) -> bool;
    fn delete(&self, item: T);
}

pub trait Updatable<T> {
    fn can_update(&self, item: &T) -> bool;
    fn update(&self, item: T);
}

pub trait CurrentDeletable {
    fn can_delete_current(&self) -> bool;
    fn delete_current(&self);
}

pub trait CurrentUpdatable {
    fn can_update_current(&self) -> bool;
    fn update_current(&self);
}

pub trait Constructable {
    fn can_construct(&self) -> bool;
    fn construct(&self);
}

pub trait Destructable {
    fn can_destruct(&self) -> bool;
    fn destruct(&self);
}

pub trait Reconstructable {
    fn can_reconstruct(&self) -> bool;
    fn reconstruct(&self);
}

pub trait Filterable<T> {
    fn filter_term(&self) -> String;
    fn set_filter_term(&mut self, term: impl Into<String>);
    fn accepts(&self, item: &T) -> bool;
}

pub trait Pageable {
    fn page_index(&self) -> usize;
    fn page_count(&self) -> usize;
    fn set_page_index(&mut self, index: usize);
}

#[derive(Clone, Default)]
pub struct ExpandableState {
    expanded: Arc<Mutex<bool>>,
    expanded_changed: MessageHub,
}

impl ExpandableState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn is_expanded(&self) -> bool {
        *lock(&self.expanded)
    }

    pub fn can_expand(&self) -> bool {
        !self.is_expanded()
    }

    pub fn can_collapse(&self) -> bool {
        self.is_expanded()
    }

    pub fn expand(&self) {
        self.set_expanded(true);
    }

    pub fn collapse(&self) {
        self.set_expanded(false);
    }

    pub fn toggle_expansion(&self) {
        self.set_expanded(!self.is_expanded());
    }

    pub fn expanded_changed(&self) -> MessageHub {
        self.expanded_changed.clone()
    }

    fn set_expanded(&self, expanded: bool) {
        let changed = {
            let mut current = lock(&self.expanded);
            if *current == expanded {
                false
            } else {
                *current = expanded;
                true
            }
        };
        if changed {
            self.expanded_changed.send(Message::Custom {
                sender_id: 0,
                name: expanded.to_string(),
            });
        }
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Selectable for ComponentVm<M, D> {
    fn can_select(&self) -> bool {
        !self.is_selected()
    }

    fn select(&self) {
        ComponentVm::select(self);
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Deselectable for ComponentVm<M, D> {
    fn can_deselect(&self) -> bool {
        self.is_selected()
    }

    fn deselect(&self) {
        ComponentVm::deselect(self);
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> SelectionTogglable
    for ComponentVm<M, D>
{
    fn can_toggle_selection(&self) -> bool {
        true
    }

    fn toggle_selection(&self) {
        if self.is_selected() {
            self.deselect();
        } else {
            self.select();
        }
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Expandable for ComponentVm<M, D> {
    fn can_expand(&self) -> bool {
        !self.is_expanded()
    }

    fn expand(&self) {
        ComponentVm::expand(self);
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Collapsible for ComponentVm<M, D> {
    fn can_collapse(&self) -> bool {
        self.is_expanded()
    }

    fn collapse(&self) {
        ComponentVm::collapse(self);
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ExpansionTogglable
    for ComponentVm<M, D>
{
    fn can_toggle_expansion(&self) -> bool {
        true
    }

    fn toggle_expansion(&self) {
        ComponentVm::toggle_expansion(self);
    }
}

#[derive(Clone)]
pub struct AggregateVm<T: VmNode> {
    members: Vec<T>,
}

impl<T: VmNode> AggregateVm<T> {
    pub fn new(members: impl IntoIterator<Item = T>) -> Self {
        Self {
            members: members.into_iter().collect(),
        }
    }

    pub fn members(&self) -> Vec<T> {
        self.members.clone()
    }

    pub fn construct(&self) -> VmxResult<()> {
        for member in &self.members {
            member.construct()?;
        }
        Ok(())
    }

    pub fn destruct(&self) -> VmxResult<()> {
        for member in &self.members {
            member.destruct()?;
        }
        Ok(())
    }

    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        for member in &self.members {
            retain_first_error(&mut first_error, member.dispose());
        }
        finish_with_first_error(first_error)
    }
}

fn validate_fixed_aggregate_child<T: VmNode>(
    child: &T,
    seen: &mut HashSet<usize>,
) -> VmxResult<()> {
    if !seen.insert(child.id()) {
        return Err(VmxError::DuplicateChild);
    }
    if child.parent_handle().is_some() || child.parent_id().is_some() {
        return Err(VmxError::InconsistentParent);
    }
    Ok(())
}

fn validate_fixed_aggregate_candidate<T: VmNode>(
    child: &T,
    seen: &mut HashSet<usize>,
    owner: &ParentHandle,
) -> VmxResult<()> {
    if !seen.insert(child.id()) {
        return Err(VmxError::DuplicateChild);
    }
    match child.parent_handle() {
        Some(parent) if parent.same_owner(owner) => Ok(()),
        Some(_) => Err(VmxError::InconsistentParent),
        None if child.parent_id().is_some() => Err(VmxError::InconsistentParent),
        None => Ok(()),
    }
}

type AggregateFactory<T> = Arc<dyn Fn() -> T + Send + Sync>;

#[derive(Clone)]
struct AggregateSlot<T: VmNode> {
    factory: Option<AggregateFactory<T>>,
    value: Arc<Mutex<Option<T>>>,
}

impl<T: VmNode> AggregateSlot<T> {
    fn eager(value: T) -> Self {
        Self {
            factory: None,
            value: Arc::new(Mutex::new(Some(value))),
        }
    }

    fn lazy(factory: AggregateFactory<T>) -> Self {
        Self {
            factory: Some(factory),
            value: Arc::new(Mutex::new(None)),
        }
    }

    fn value(&self) -> Option<T> {
        lock(&self.value).clone()
    }

    fn is_lazy(&self) -> bool {
        self.factory.is_some()
    }

    fn next(&self) -> VmxResult<T> {
        self.factory
            .as_ref()
            .map(|factory| factory())
            .or_else(|| self.value())
            .ok_or_else(|| VmxError::InvalidArgument("aggregate slot is empty".to_string()))
    }

    fn replace(&self, value: T) -> Option<T> {
        lock(&self.value).replace(value)
    }
}

#[derive(Clone)]
struct FixedAggregateOwnership {
    registration: ParentRegistration,
    child_ids: Arc<Mutex<HashSet<usize>>>,
}

impl FixedAggregateOwnership {
    fn handle(&self) -> ParentHandle {
        self.registration.handle()
    }

    fn replace_ids(&self, ids: HashSet<usize>) {
        *lock(&self.child_ids) = ids;
    }
}

fn fixed_aggregate_parent<D: Dispatcher>(
    core: &ComponentCore<D>,
    child_ids: HashSet<usize>,
) -> FixedAggregateOwnership {
    let child_ids = Arc::new(Mutex::new(child_ids));
    let registration = ParentRegistration::new(
        core.id(),
        {
            let core = core.clone();
            move || core.parent_handle()
        },
        {
            let child_ids = Arc::clone(&child_ids);
            move |child_id| lock(&child_ids).contains(&child_id)
        },
        move |_child_id, _owner_handle| Err(VmxError::InconsistentParent),
    );
    FixedAggregateOwnership {
        registration,
        child_ids,
    }
}

fn attach_fixed_aggregate_child<T: VmNode>(child: &T, parent: &ParentHandle) {
    child.set_parent_handle(Some(parent.clone()));
}

fn replace_fixed_aggregate_child<T: VmNode>(
    slot: &AggregateSlot<T>,
    next: T,
    parent: &ParentHandle,
) -> VmxResult<()> {
    let mut result = Ok(());
    if let Some(previous) = slot.replace(next.clone()) {
        previous.set_parent_handle(None);
        result = previous.dispose();
    }
    attach_fixed_aggregate_child(&next, parent);
    result
}

#[derive(Clone)]
pub struct AggregateVm1<T1: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
}

impl<T1: VmNode> AggregateVm1<T1, NullDispatcher> {
    pub fn builder() -> AggregateVm1Builder<T1, NullDispatcher> {
        AggregateVm1Builder::default()
    }

    pub fn new(name: impl Into<String>, component1: T1) -> Self {
        Self::try_new(name, component1)
            .expect("aggregate component must be unowned and identity-unique")
    }

    pub fn try_new(name: impl Into<String>, component1: T1) -> VmxResult<Self> {
        Self::try_with_services(name, MessageHub::new(), NullDispatcher::new(), component1)
    }
}

impl<T1: VmNode, D: Dispatcher> AggregateVm1<T1, D> {
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
    ) -> Self {
        Self::try_with_services(name, hub, dispatcher, component1)
            .expect("aggregate component must be unowned and identity-unique")
    }

    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        attach_fixed_aggregate_child(&component1, &ownership.handle());
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
        })
    }

    fn from_factory(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
        }
    }

    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }

    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let mut ids = HashSet::new();
                let parent = self.ownership.handle();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()
            })
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            Ok(())
        })
    }

    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
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
}

impl<T1: VmNode, D: Dispatcher> VmNode for AggregateVm1<T1, D> {
    fn id(&self) -> usize {
        AggregateVm1::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        AggregateVm1::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        AggregateVm1::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        AggregateVm1::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        AggregateVm1::status(self)
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

impl<T1: VmNode, D: Dispatcher> PartialEq for AggregateVm1<T1, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T1: VmNode, D: Dispatcher> Eq for AggregateVm1<T1, D> {}

#[derive(Clone)]
pub struct AggregateVm1Builder<T1: VmNode, D: Dispatcher = NullDispatcher> {
    name: Option<String>,
    hint: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    factory1: Option<AggregateFactory<T1>>,
}

impl<T1: VmNode> Default for AggregateVm1Builder<T1, NullDispatcher> {
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            hub: None,
            dispatcher: None,
            factory1: None,
        }
    }
}

impl<T1: VmNode, D: Dispatcher> AggregateVm1Builder<T1, D> {
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

    pub fn component_1<F>(mut self, factory: F) -> Self
    where
        F: Fn() -> T1 + Send + Sync + 'static,
    {
        self.factory1 = Some(Arc::new(factory));
        self
    }

    pub fn build(self) -> VmxResult<AggregateVm1<T1, D>> {
        let name = self
            .name
            .ok_or_else(|| VmxError::BuilderValidation("name is required".to_string()))?;
        let hub = self
            .hub
            .ok_or_else(|| VmxError::BuilderValidation("hub is required".to_string()))?;
        let dispatcher = self
            .dispatcher
            .ok_or_else(|| VmxError::BuilderValidation("dispatcher is required".to_string()))?;
        let factory1 = self
            .factory1
            .ok_or_else(|| VmxError::BuilderValidation("component_1 is required".to_string()))?;
        Ok(AggregateVm1::from_factory(
            name, self.hint, hub, dispatcher, factory1,
        ))
    }
}

#[derive(Clone)]
pub struct AggregateVm2<T1: VmNode, T2: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
}

impl<T1: VmNode, T2: VmNode> AggregateVm2<T1, T2, NullDispatcher> {
    pub fn builder() -> AggregateVm2Builder<T1, T2, NullDispatcher> {
        AggregateVm2Builder::default()
    }

    pub fn new(name: impl Into<String>, component1: T1, component2: T2) -> Self {
        Self::try_new(name, component1, component2)
            .expect("aggregate components must be unowned and identity-unique")
    }

    pub fn try_new(name: impl Into<String>, component1: T1, component2: T2) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
        )
    }
}

impl<T1: VmNode, T2: VmNode, D: Dispatcher> AggregateVm2<T1, T2, D> {
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
    ) -> Self {
        Self::try_with_services(name, hub, dispatcher, component1, component2)
            .expect("aggregate components must be unowned and identity-unique")
    }

    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
        })
    }

    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
        }
    }

    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }

    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }

    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }

    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                }
                if self.component2.is_lazy() {
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()
            })
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            Ok(())
        })
    }

    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
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
}

impl<T1: VmNode, T2: VmNode, D: Dispatcher> VmNode for AggregateVm2<T1, T2, D> {
    fn id(&self) -> usize {
        AggregateVm2::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        AggregateVm2::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        AggregateVm2::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        AggregateVm2::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        AggregateVm2::status(self)
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

impl<T1: VmNode, T2: VmNode, D: Dispatcher> PartialEq for AggregateVm2<T1, T2, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T1: VmNode, T2: VmNode, D: Dispatcher> Eq for AggregateVm2<T1, T2, D> {}

#[derive(Clone)]
pub struct AggregateVm3<T1: VmNode, T2: VmNode, T3: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
    component3: AggregateSlot<T3>,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode> AggregateVm3<T1, T2, T3, NullDispatcher> {
    pub fn builder() -> AggregateVm3Builder<T1, T2, T3, NullDispatcher> {
        AggregateVm3Builder::default()
    }

    pub fn new(name: impl Into<String>, component1: T1, component2: T2, component3: T3) -> Self {
        Self::try_new(name, component1, component2, component3)
            .expect("aggregate components must be unowned and identity-unique")
    }

    pub fn try_new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
    ) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
            component3,
        )
    }
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, D: Dispatcher> AggregateVm3<T1, T2, T3, D> {
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
    ) -> Self {
        Self::try_with_services(name, hub, dispatcher, component1, component2, component3)
            .expect("aggregate components must be unowned and identity-unique")
    }

    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        validate_fixed_aggregate_child(&component3, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        attach_fixed_aggregate_child(&component3, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
            component3: AggregateSlot::eager(component3),
        })
    }

    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
        factory3: AggregateFactory<T3>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
            component3: AggregateSlot::lazy(factory3),
        }
    }

    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }

    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }

    pub fn component_3(&self) -> Option<T3> {
        self.component3.value()
    }

    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }

    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }

    pub fn component3(&self) -> Option<T3> {
        self.component_3()
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.core.own(cleanup);
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let next3 = self.component3.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next3, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component3, next3.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()?;
                self.core.notify_property_changed("component_3");
                next3.construct()
            })
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            if let Some(component3) = self.component_3() {
                component3.destruct()?;
            }
            Ok(())
        })
    }

    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        if let Some(component3) = self.component_3() {
            retain_first_error(&mut first_error, component3.dispose());
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
}

#[derive(Clone)]
pub struct AggregateVm4<
    T1: VmNode,
    T2: VmNode,
    T3: VmNode,
    T4: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
    component3: AggregateSlot<T3>,
    component4: AggregateSlot<T4>,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode> AggregateVm4<T1, T2, T3, T4, NullDispatcher> {
    pub fn builder() -> AggregateVm4Builder<T1, T2, T3, T4, NullDispatcher> {
        AggregateVm4Builder::default()
    }

    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> Self {
        Self::try_new(name, component1, component2, component3, component4)
            .expect("aggregate components must be unowned and identity-unique")
    }

    pub fn try_new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
            component3,
            component4,
        )
    }
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, D: Dispatcher>
    AggregateVm4<T1, T2, T3, T4, D>
{
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> Self {
        Self::try_with_services(
            name, hub, dispatcher, component1, component2, component3, component4,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        validate_fixed_aggregate_child(&component3, &mut ids)?;
        validate_fixed_aggregate_child(&component4, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        attach_fixed_aggregate_child(&component3, &parent);
        attach_fixed_aggregate_child(&component4, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
            component3: AggregateSlot::eager(component3),
            component4: AggregateSlot::eager(component4),
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
        factory3: AggregateFactory<T3>,
        factory4: AggregateFactory<T4>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
            component3: AggregateSlot::lazy(factory3),
            component4: AggregateSlot::lazy(factory4),
        }
    }

    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }

    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }

    pub fn component_3(&self) -> Option<T3> {
        self.component3.value()
    }

    pub fn component_4(&self) -> Option<T4> {
        self.component4.value()
    }

    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }
    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }
    pub fn component3(&self) -> Option<T3> {
        self.component_3()
    }
    pub fn component4(&self) -> Option<T4> {
        self.component_4()
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.core.own(cleanup);
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let next3 = self.component3.next()?;
                let next4 = self.component4.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next3, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next4, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component3, next3.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component4, next4.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()?;
                self.core.notify_property_changed("component_3");
                next3.construct()?;
                self.core.notify_property_changed("component_4");
                next4.construct()
            })
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            if let Some(component3) = self.component_3() {
                component3.destruct()?;
            }
            if let Some(component4) = self.component_4() {
                component4.destruct()?;
            }
            Ok(())
        })
    }

    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        if let Some(component3) = self.component_3() {
            retain_first_error(&mut first_error, component3.dispose());
        }
        if let Some(component4) = self.component_4() {
            retain_first_error(&mut first_error, component4.dispose());
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
}

#[derive(Clone)]
pub struct AggregateVm5<
    T1: VmNode,
    T2: VmNode,
    T3: VmNode,
    T4: VmNode,
    T5: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
    component3: AggregateSlot<T3>,
    component4: AggregateSlot<T4>,
    component5: AggregateSlot<T5>,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode>
    AggregateVm5<T1, T2, T3, T4, T5, NullDispatcher>
{
    pub fn builder() -> AggregateVm5Builder<T1, T2, T3, T4, T5, NullDispatcher> {
        AggregateVm5Builder::default()
    }

    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> Self {
        Self::try_new(
            name, component1, component2, component3, component4, component5,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    pub fn try_new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
            component3,
            component4,
            component5,
        )
    }
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode, D: Dispatcher>
    AggregateVm5<T1, T2, T3, T4, T5, D>
{
    #[allow(clippy::too_many_arguments)]
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> Self {
        Self::try_with_services(
            name, hub, dispatcher, component1, component2, component3, component4, component5,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    #[allow(clippy::too_many_arguments)]
    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        validate_fixed_aggregate_child(&component3, &mut ids)?;
        validate_fixed_aggregate_child(&component4, &mut ids)?;
        validate_fixed_aggregate_child(&component5, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        attach_fixed_aggregate_child(&component3, &parent);
        attach_fixed_aggregate_child(&component4, &parent);
        attach_fixed_aggregate_child(&component5, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
            component3: AggregateSlot::eager(component3),
            component4: AggregateSlot::eager(component4),
            component5: AggregateSlot::eager(component5),
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
        factory3: AggregateFactory<T3>,
        factory4: AggregateFactory<T4>,
        factory5: AggregateFactory<T5>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
            component3: AggregateSlot::lazy(factory3),
            component4: AggregateSlot::lazy(factory4),
            component5: AggregateSlot::lazy(factory5),
        }
    }

    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }
    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }
    pub fn component_3(&self) -> Option<T3> {
        self.component3.value()
    }
    pub fn component_4(&self) -> Option<T4> {
        self.component4.value()
    }
    pub fn component_5(&self) -> Option<T5> {
        self.component5.value()
    }
    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }
    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }
    pub fn component3(&self) -> Option<T3> {
        self.component_3()
    }
    pub fn component4(&self) -> Option<T4> {
        self.component_4()
    }
    pub fn component5(&self) -> Option<T5> {
        self.component_5()
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.core.own(cleanup);
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let next3 = self.component3.next()?;
                let next4 = self.component4.next()?;
                let next5 = self.component5.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next3, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next4, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next5, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component3, next3.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component4, next4.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component5, next5.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()?;
                self.core.notify_property_changed("component_3");
                next3.construct()?;
                self.core.notify_property_changed("component_4");
                next4.construct()?;
                self.core.notify_property_changed("component_5");
                next5.construct()
            })
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            if let Some(component3) = self.component_3() {
                component3.destruct()?;
            }
            if let Some(component4) = self.component_4() {
                component4.destruct()?;
            }
            if let Some(component5) = self.component_5() {
                component5.destruct()?;
            }
            Ok(())
        })
    }

    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        if let Some(component3) = self.component_3() {
            retain_first_error(&mut first_error, component3.dispose());
        }
        if let Some(component4) = self.component_4() {
            retain_first_error(&mut first_error, component4.dispose());
        }
        if let Some(component5) = self.component_5() {
            retain_first_error(&mut first_error, component5.dispose());
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
}

#[derive(Clone)]
pub struct AggregateVm6<
    T1: VmNode,
    T2: VmNode,
    T3: VmNode,
    T4: VmNode,
    T5: VmNode,
    T6: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
    component3: AggregateSlot<T3>,
    component4: AggregateSlot<T4>,
    component5: AggregateSlot<T5>,
    component6: AggregateSlot<T6>,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode, T6: VmNode>
    AggregateVm6<T1, T2, T3, T4, T5, T6, NullDispatcher>
{
    pub fn builder() -> AggregateVm6Builder<T1, T2, T3, T4, T5, T6, NullDispatcher> {
        AggregateVm6Builder::default()
    }

    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> Self {
        Self::try_new(
            name, component1, component2, component3, component4, component5, component6,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    pub fn try_new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
            component3,
            component4,
            component5,
            component6,
        )
    }
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode, T6: VmNode, D: Dispatcher>
    AggregateVm6<T1, T2, T3, T4, T5, T6, D>
{
    #[allow(clippy::too_many_arguments)]
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> Self {
        Self::try_with_services(
            name, hub, dispatcher, component1, component2, component3, component4, component5,
            component6,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    #[allow(clippy::too_many_arguments)]
    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        validate_fixed_aggregate_child(&component3, &mut ids)?;
        validate_fixed_aggregate_child(&component4, &mut ids)?;
        validate_fixed_aggregate_child(&component5, &mut ids)?;
        validate_fixed_aggregate_child(&component6, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        attach_fixed_aggregate_child(&component3, &parent);
        attach_fixed_aggregate_child(&component4, &parent);
        attach_fixed_aggregate_child(&component5, &parent);
        attach_fixed_aggregate_child(&component6, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
            component3: AggregateSlot::eager(component3),
            component4: AggregateSlot::eager(component4),
            component5: AggregateSlot::eager(component5),
            component6: AggregateSlot::eager(component6),
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
        factory3: AggregateFactory<T3>,
        factory4: AggregateFactory<T4>,
        factory5: AggregateFactory<T5>,
        factory6: AggregateFactory<T6>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
            component3: AggregateSlot::lazy(factory3),
            component4: AggregateSlot::lazy(factory4),
            component5: AggregateSlot::lazy(factory5),
            component6: AggregateSlot::lazy(factory6),
        }
    }

    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }
    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }
    pub fn component_3(&self) -> Option<T3> {
        self.component3.value()
    }
    pub fn component_4(&self) -> Option<T4> {
        self.component4.value()
    }
    pub fn component_5(&self) -> Option<T5> {
        self.component5.value()
    }
    pub fn component_6(&self) -> Option<T6> {
        self.component6.value()
    }
    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }
    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }
    pub fn component3(&self) -> Option<T3> {
        self.component_3()
    }
    pub fn component4(&self) -> Option<T4> {
        self.component_4()
    }
    pub fn component5(&self) -> Option<T5> {
        self.component_5()
    }
    pub fn component6(&self) -> Option<T6> {
        self.component_6()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.core.own(cleanup);
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let next3 = self.component3.next()?;
                let next4 = self.component4.next()?;
                let next5 = self.component5.next()?;
                let next6 = self.component6.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next3, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next4, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next5, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next6, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component3, next3.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component4, next4.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component5, next5.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component6, next6.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()?;
                self.core.notify_property_changed("component_3");
                next3.construct()?;
                self.core.notify_property_changed("component_4");
                next4.construct()?;
                self.core.notify_property_changed("component_5");
                next5.construct()?;
                self.core.notify_property_changed("component_6");
                next6.construct()
            })
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            if let Some(component3) = self.component_3() {
                component3.destruct()?;
            }
            if let Some(component4) = self.component_4() {
                component4.destruct()?;
            }
            if let Some(component5) = self.component_5() {
                component5.destruct()?;
            }
            if let Some(component6) = self.component_6() {
                component6.destruct()?;
            }
            Ok(())
        })
    }

    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        if let Some(component3) = self.component_3() {
            retain_first_error(&mut first_error, component3.dispose());
        }
        if let Some(component4) = self.component_4() {
            retain_first_error(&mut first_error, component4.dispose());
        }
        if let Some(component5) = self.component_5() {
            retain_first_error(&mut first_error, component5.dispose());
        }
        if let Some(component6) = self.component_6() {
            retain_first_error(&mut first_error, component6.dispose());
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
}

macro_rules! impl_fixed_aggregate_vm_node {
    ($name:ident, $($component:ident),+) => {
        impl<$($component: VmNode,)+ D: Dispatcher> VmNode
            for $name<$($component,)+ D>
        {
            fn id(&self) -> usize { self.core.id() }
            fn construct(&self) -> VmxResult<()> { $name::construct(self) }
            fn destruct(&self) -> VmxResult<()> { $name::destruct(self) }
            fn dispose(&self) -> VmxResult<()> { $name::dispose(self) }
            fn status(&self) -> ConstructionStatus { $name::status(self) }
            fn set_parent_id(&self, parent_id: Option<usize>) {
                self.core.set_parent_id(parent_id);
            }
            fn parent_id(&self) -> Option<usize> { self.core.parent_id() }
            fn set_parent_handle(&self, parent: Option<ParentHandle>) {
                self.core.set_parent_handle(parent);
            }
            fn parent_handle(&self) -> Option<ParentHandle> { self.core.parent_handle() }
            fn set_current_flag(&self, is_current: bool) {
                self.core.set_current_flag(is_current);
            }
            fn is_current(&self) -> bool { self.core.is_selected() }
        }

        impl<$($component: VmNode,)+ D: Dispatcher> PartialEq
            for $name<$($component,)+ D>
        {
            fn eq(&self, other: &Self) -> bool { self.core.id() == other.core.id() }
        }

        impl<$($component: VmNode,)+ D: Dispatcher> Eq for $name<$($component,)+ D> {}
    };
}

impl_fixed_aggregate_vm_node!(AggregateVm3, T1, T2, T3);
impl_fixed_aggregate_vm_node!(AggregateVm4, T1, T2, T3, T4);
impl_fixed_aggregate_vm_node!(AggregateVm5, T1, T2, T3, T4, T5);
impl_fixed_aggregate_vm_node!(AggregateVm6, T1, T2, T3, T4, T5, T6);

macro_rules! define_aggregate_builder {
    ($builder:ident, $aggregate:ident, $(($component:ident, $factory:ident, $setter:ident)),+) => {
        #[derive(Clone)]
        pub struct $builder<$($component: VmNode,)+ D: Dispatcher = NullDispatcher> {
            name: Option<String>,
            hint: Option<String>,
            hub: Option<MessageHub>,
            dispatcher: Option<D>,
            $($factory: Option<AggregateFactory<$component>>,)+
        }

        impl<$($component: VmNode,)+> Default
            for $builder<$($component,)+ NullDispatcher>
        {
            fn default() -> Self {
                Self {
                    name: None,
                    hint: Some(String::new()),
                    hub: None,
                    dispatcher: None,
                    $($factory: None,)+
                }
            }
        }

        impl<$($component: VmNode,)+ D: Dispatcher> $builder<$($component,)+ D> {
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

            $(
                pub fn $setter<F>(mut self, factory: F) -> Self
                where
                    F: Fn() -> $component + Send + Sync + 'static,
                {
                    self.$factory = Some(Arc::new(factory));
                    self
                }
            )+

            pub fn build(self) -> VmxResult<$aggregate<$($component,)+ D>> {
                let name = self.name.ok_or_else(|| {
                    VmxError::BuilderValidation("name is required".to_string())
                })?;
                let hub = self.hub.ok_or_else(|| {
                    VmxError::BuilderValidation("hub is required".to_string())
                })?;
                let dispatcher = self.dispatcher.ok_or_else(|| {
                    VmxError::BuilderValidation("dispatcher is required".to_string())
                })?;
                $(
                    let $factory = self.$factory.ok_or_else(|| {
                        VmxError::BuilderValidation(
                            concat!(stringify!($setter), " is required").to_string(),
                        )
                    })?;
                )+
                Ok($aggregate::from_factories(
                    name,
                    self.hint,
                    hub,
                    dispatcher,
                    $($factory,)+
                ))
            }
        }
    };
}

define_aggregate_builder!(
    AggregateVm2Builder,
    AggregateVm2,
    (T1, factory1, component_1),
    (T2, factory2, component_2)
);
define_aggregate_builder!(
    AggregateVm3Builder,
    AggregateVm3,
    (T1, factory1, component_1),
    (T2, factory2, component_2),
    (T3, factory3, component_3)
);
define_aggregate_builder!(
    AggregateVm4Builder,
    AggregateVm4,
    (T1, factory1, component_1),
    (T2, factory2, component_2),
    (T3, factory3, component_3),
    (T4, factory4, component_4)
);
define_aggregate_builder!(
    AggregateVm5Builder,
    AggregateVm5,
    (T1, factory1, component_1),
    (T2, factory2, component_2),
    (T3, factory3, component_3),
    (T4, factory4, component_4),
    (T5, factory5, component_5)
);
define_aggregate_builder!(
    AggregateVm6Builder,
    AggregateVm6,
    (T1, factory1, component_1),
    (T2, factory2, component_2),
    (T3, factory3, component_3),
    (T4, factory4, component_4),
    (T5, factory5, component_5),
    (T6, factory6, component_6)
);

macro_rules! impl_fixed_aggregate_baseline {
    ($name:ident, $($component:ident),+) => {
        impl<$($component: VmNode,)+ D: Dispatcher> $name<$($component,)+ D> {
            pub fn name(&self) -> String {
                self.core.name()
            }

            pub fn hint(&self) -> Option<String> {
                self.core.hint()
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

            pub fn select(&self) {
                self.core.select();
            }

            pub fn deselect(&self) {
                self.core.deselect();
            }

            pub fn is_selected(&self) -> bool {
                self.core.is_selected()
            }

            pub fn select_command(&self) -> RelayCommand {
                let vm = self.clone();
                RelayCommand::new({
                    let vm = vm.clone();
                    move || vm.select()
                })
                .with_can_execute(move || !vm.is_selected())
            }

            pub fn deselect_command(&self) -> RelayCommand {
                let vm = self.clone();
                RelayCommand::new({
                    let vm = vm.clone();
                    move || vm.deselect()
                })
                .with_can_execute(move || vm.is_selected())
            }
        }
    };
}

impl_fixed_aggregate_baseline!(AggregateVm1, T1);
impl_fixed_aggregate_baseline!(AggregateVm2, T1, T2);
impl_fixed_aggregate_baseline!(AggregateVm3, T1, T2, T3);
impl_fixed_aggregate_baseline!(AggregateVm4, T1, T2, T3, T4);
impl_fixed_aggregate_baseline!(AggregateVm5, T1, T2, T3, T4, T5);
impl_fixed_aggregate_baseline!(AggregateVm6, T1, T2, T3, T4, T5, T6);

#[derive(Clone)]
pub struct ForwardingComponentVm<
    M: Clone + PartialEq + Send + 'static,
    D: Dispatcher = NullDispatcher,
> {
    inner: ComponentVm<M, D>,
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ForwardingComponentVm<M, D> {
    pub fn new(inner: ComponentVm<M, D>) -> Self {
        Self { inner }
    }

    pub fn inner(&self) -> &ComponentVm<M, D> {
        &self.inner
    }

    pub fn id(&self) -> usize {
        self.inner.id()
    }

    pub fn name(&self) -> String {
        self.inner.name()
    }

    pub fn hint(&self) -> Option<String> {
        self.inner.hint()
    }

    pub fn modeled_hint(&self) -> Option<String> {
        self.inner.modeled_hint()
    }

    pub fn model(&self) -> M {
        self.inner.model()
    }

    pub fn set_model(&self, model: M) {
        self.inner.set_model(model);
    }

    pub fn republish_model(&self) {
        self.inner.republish_model();
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    pub fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
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

    pub fn select_command(&self) -> RelayCommand {
        self.inner.select_command()
    }

    pub fn select(&self) {
        self.inner.select();
    }

    pub fn deselect(&self) {
        self.inner.deselect();
    }

    pub fn is_selected(&self) -> bool {
        self.inner.is_selected()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.property_changed()
    }

    pub fn hub(&self) -> MessageHub {
        self.inner.hub()
    }

    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.inner.own(cleanup);
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.notify_property_changed(property_name);
    }
}

#[derive(Clone)]
pub struct ForwardingCompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    inner: CompositeVm<T, D>,
}

impl<T: VmNode, D: Dispatcher> ForwardingCompositeVm<T, D> {
    pub fn new(inner: CompositeVm<T, D>) -> Self {
        Self { inner }
    }

    pub fn inner(&self) -> &CompositeVm<T, D> {
        &self.inner
    }

    pub fn id(&self) -> usize {
        self.inner.id()
    }

    pub fn name(&self) -> String {
        self.inner.name()
    }

    pub fn hint(&self) -> Option<String> {
        self.inner.hint()
    }

    pub fn items(&self) -> Vec<T> {
        self.inner.items()
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

    pub fn add(&self, item: T) -> VmxResult<()> {
        self.inner.add(item)
    }

    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        self.inner.insert(index, item)
    }

    pub fn remove(&self, item: &T) -> VmxResult<()> {
        self.inner.remove(item)
    }

    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        self.inner.remove_at(index)
    }

    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        self.inner.replace(index, item)
    }

    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        self.inner.move_item(from_index, to_index)
    }

    pub fn clear(&self) {
        self.inner.clear();
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

    pub fn deselect_component(&self, item: &T) -> VmxResult<()> {
        self.inner.deselect_component(item)
    }

    pub fn can_select_component(&self, item: &T) -> bool {
        self.inner.can_select_component(item)
    }

    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        self.inner.batch_update(action);
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    pub fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
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

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.property_changed()
    }

    pub fn hub(&self) -> MessageHub {
        self.inner.hub()
    }

    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.inner.own(cleanup);
    }

    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.notify_property_changed(property_name);
    }
}

impl<T: VmNode, D: Dispatcher> IntoIterator for ForwardingCompositeVm<T, D> {
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.items().into_iter()
    }
}

impl<T: VmNode, D: Dispatcher> IntoIterator for &ForwardingCompositeVm<T, D> {
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.items().into_iter()
    }
}

#[derive(Clone)]
pub struct TokenPagedComposition<
    T: Clone + PartialEq + Send + 'static,
    Token: Clone + Send + 'static,
> {
    id: usize,
    items: Arc<Mutex<Vec<T>>>,
    next_token: Arc<Mutex<Option<Token>>>,
    has_more: Arc<Mutex<bool>>,
    hub: MessageHub,
    load_more_command: RelayCommand,
    refresh_command: RelayCommand,
}

impl<T: Clone + PartialEq + Send + 'static, Token: Clone + Send + 'static>
    TokenPagedComposition<T, Token>
{
    pub fn new(initial_token: Option<Token>) -> Self {
        Self::with_loader(initial_token, |_token| (Vec::new(), None))
    }

    pub fn with_loader<F>(initial_token: Option<Token>, loader: F) -> Self
    where
        F: Fn(Option<Token>) -> (Vec<T>, Option<Token>) + Send + Sync + 'static,
    {
        Self::build(initial_token, loader, MessageHub::new())
    }

    pub fn with_loader_and_hub<F>(initial_token: Option<Token>, loader: F, hub: MessageHub) -> Self
    where
        F: Fn(Option<Token>) -> (Vec<T>, Option<Token>) + Send + Sync + 'static,
    {
        Self::build(initial_token, loader, hub)
    }

    fn build<F>(initial_token: Option<Token>, loader: F, hub: MessageHub) -> Self
    where
        F: Fn(Option<Token>) -> (Vec<T>, Option<Token>) + Send + Sync + 'static,
    {
        let id = next_id();
        let items = Arc::new(Mutex::new(Vec::new()));
        let initial_token = Arc::new(Mutex::new(initial_token));
        let next_token = Arc::new(Mutex::new(None));
        let has_more = Arc::new(Mutex::new(true));
        let loader = Arc::new(loader);

        let load_more_items = items.clone();
        let load_more_token = next_token.clone();
        let load_more_has_more = has_more.clone();
        let load_more_loader = loader.clone();
        let load_more_hub = hub.clone();
        let load_more_command = RelayCommand::new(move || {
            let token = lock(&load_more_token).clone();
            let (page, next) = load_more_loader(token);
            let mut changed = false;
            if !page.is_empty() {
                lock(&load_more_items).extend(page);
                changed = true;
            }
            *lock(&load_more_token) = next.clone();
            *lock(&load_more_has_more) = next.is_some();
            if changed {
                load_more_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
        })
        .with_can_execute({
            let has_more = has_more.clone();
            move || *lock(&has_more)
        });

        let refresh_items = items.clone();
        let refresh_initial_token = initial_token.clone();
        let refresh_next_token = next_token.clone();
        let refresh_has_more = has_more.clone();
        let refresh_loader = loader.clone();
        let refresh_hub = hub.clone();
        let refresh_command = RelayCommand::new(move || {
            let token = lock(&refresh_initial_token).clone();
            let (page, next) = refresh_loader(token);
            let changed = {
                let mut items = lock(&refresh_items);
                if items.iter().take(page.len()).eq(page.iter()) {
                    false
                } else {
                    *items = page;
                    true
                }
            };
            *lock(&refresh_next_token) = next.clone();
            *lock(&refresh_has_more) = next.is_some();
            if changed {
                refresh_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
        });

        Self {
            id,
            items,
            next_token,
            has_more,
            hub,
            load_more_command,
            refresh_command,
        }
    }

    pub fn id(&self) -> usize {
        self.id
    }

    pub fn items(&self) -> Vec<T> {
        lock(&self.items).clone()
    }

    pub fn current_token(&self) -> Option<Token> {
        lock(&self.next_token).clone()
    }

    pub fn has_more(&self) -> bool {
        *lock(&self.has_more)
    }

    pub fn can_load_more(&self) -> bool {
        self.load_more_command.can_execute()
    }

    pub fn load_more_command(&self) -> RelayCommand {
        self.load_more_command.clone()
    }

    pub fn refresh_command(&self) -> RelayCommand {
        self.refresh_command.clone()
    }

    pub fn hub(&self) -> MessageHub {
        self.hub.clone()
    }

    pub fn refresh(&self) {
        self.refresh_command.execute();
    }

    pub fn load_more<F>(&self, loader: F)
    where
        F: FnOnce(Option<Token>) -> (Vec<T>, Option<Token>),
    {
        let token = lock(&self.next_token).clone();
        let (items, next_token) = loader(token);
        let changed = !items.is_empty();
        if changed {
            lock(&self.items).extend(items);
        }
        *lock(&self.next_token) = next_token.clone();
        *lock(&self.has_more) = next_token.is_some();
        if changed {
            self.hub
                .send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: self.id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
        }
    }

    pub fn load_next(&self) {
        self.load_more_command.execute();
    }
}

impl<T: VmNode, Token: Clone + Send + 'static> TokenPagedComposition<T, Token> {
    pub fn with_auto_construct_loader<F>(initial_token: Option<Token>, loader: F) -> Self
    where
        F: Fn(Option<Token>) -> (Vec<T>, Option<Token>) + Send + Sync + 'static,
    {
        let hub = MessageHub::new();
        let id = next_id();
        let items = Arc::new(Mutex::new(Vec::new()));
        let initial_token = Arc::new(Mutex::new(initial_token));
        let next_token = Arc::new(Mutex::new(None));
        let has_more = Arc::new(Mutex::new(true));
        let loader = Arc::new(loader);

        let load_items = items.clone();
        let load_token = next_token.clone();
        let load_has_more = has_more.clone();
        let load_loader = loader.clone();
        let load_hub = hub.clone();
        let load_more_command = RelayCommand::new(move || {
            let token = lock(&load_token).clone();
            let (page, next) = load_loader(token);
            let changed = !page.is_empty();
            if changed {
                for item in &page {
                    let _ = item.construct();
                }
                lock(&load_items).extend(page);
            }
            *lock(&load_token) = next.clone();
            *lock(&load_has_more) = next.is_some();
            if changed {
                load_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
        })
        .with_can_execute({
            let has_more = has_more.clone();
            move || *lock(&has_more)
        });

        let refresh_items = items.clone();
        let refresh_initial_token = initial_token.clone();
        let refresh_next_token = next_token.clone();
        let refresh_has_more = has_more.clone();
        let refresh_loader = loader.clone();
        let refresh_hub = hub.clone();
        let refresh_command = RelayCommand::new(move || {
            let token = lock(&refresh_initial_token).clone();
            let (page, next) = refresh_loader(token);
            let changed = {
                let mut items = lock(&refresh_items);
                if items.iter().take(page.len()).eq(page.iter()) {
                    false
                } else {
                    for item in &page {
                        let _ = item.construct();
                    }
                    *items = page;
                    true
                }
            };
            *lock(&refresh_next_token) = next.clone();
            *lock(&refresh_has_more) = next.is_some();
            if changed {
                refresh_hub.send(Message::CollectionChanged(CollectionChangedMessage {
                    sender_id: id,
                    property_name: "items".to_string(),
                    action: CollectionChangeAction::Reset,
                    old_index: None,
                    new_index: None,
                }));
            }
        });

        Self {
            id,
            items,
            next_token,
            has_more,
            hub,
            load_more_command,
            refresh_command,
        }
    }
}

#[derive(Clone)]
pub struct ModalVm<T: Clone + Send + 'static> {
    cancellation_result: T,
    result: Arc<Mutex<Option<T>>>,
    dismissed: Arc<Mutex<bool>>,
    completion: AsyncValue<T>,
}

impl<T: Clone + Send + 'static> ModalVm<T> {
    pub fn new(cancellation_result: T) -> Self {
        Self {
            cancellation_result,
            result: Arc::new(Mutex::new(None)),
            dismissed: Arc::new(Mutex::new(false)),
            completion: AsyncValue::pending(),
        }
    }

    pub fn open(&self) {
        *lock(&self.dismissed) = false;
    }

    pub fn close(&self, result: Option<T>) {
        self.dismiss(result.unwrap_or_else(|| self.cancellation_result.clone()));
    }

    pub fn result(&self) -> Option<T> {
        lock(&self.result).clone()
    }

    pub fn cancellation_result(&self) -> T {
        self.cancellation_result.clone()
    }

    pub fn is_dismissed(&self) -> bool {
        *lock(&self.dismissed)
    }

    pub fn dismiss(&self, result: T) {
        let should_set = {
            let mut dismissed = lock(&self.dismissed);
            if *dismissed {
                false
            } else {
                *dismissed = true;
                true
            }
        };
        if should_set {
            *lock(&self.result) = Some(result.clone());
            self.completion.resolve(result);
        }
    }

    pub fn dispose(&self) {
        self.dismiss(self.cancellation_result.clone());
    }

    pub fn completion(&self) -> AsyncValue<T> {
        self.completion.clone()
    }
}

#[derive(Clone)]
pub struct NotificationVm {
    notification: Notification,
    hub: NotificationHub,
    resolved: Arc<Mutex<bool>>,
    elapsed_ms: Arc<Mutex<u64>>,
    lifespan_ms: u64,
}

impl NotificationVm {
    pub fn new(notification: Notification) -> Self {
        Self::with_hub(notification, NotificationHub::new(), 60_000)
    }

    pub fn with_hub(notification: Notification, hub: NotificationHub, lifespan_ms: u64) -> Self {
        Self {
            notification,
            hub,
            resolved: Arc::new(Mutex::new(false)),
            elapsed_ms: Arc::new(Mutex::new(0)),
            lifespan_ms,
        }
    }

    pub fn notification(&self) -> Notification {
        self.notification.clone()
    }

    pub fn dismiss(&self) {
        let should_resolve = {
            let mut resolved = lock(&self.resolved);
            if *resolved {
                false
            } else {
                *resolved = true;
                true
            }
        };
        if should_resolve {
            self.hub
                .resolve(self.notification.id, NotificationReaction::Approve);
        }
    }

    pub fn is_resolved(&self) -> bool {
        *lock(&self.resolved)
            || self.hub.reaction(self.notification.id) != NotificationReaction::Pending
    }

    pub fn remaining_time_ms(&self) -> u64 {
        self.lifespan_ms.saturating_sub(*lock(&self.elapsed_ms))
    }

    pub fn opacity(&self) -> f64 {
        if self.lifespan_ms == 0 {
            return 0.0;
        }
        self.remaining_time_ms() as f64 / self.lifespan_ms as f64
    }

    pub fn advance_by_ms(&self, millis: u64) {
        if self.is_resolved() {
            return;
        }
        let remaining = {
            let mut elapsed = lock(&self.elapsed_ms);
            *elapsed = (*elapsed + millis).min(self.lifespan_ms);
            self.lifespan_ms.saturating_sub(*elapsed)
        };
        if remaining == 0 {
            self.dismiss();
        }
    }

    pub fn dismiss_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new(move || vm.dismiss())
    }
}

#[derive(Clone)]
pub struct ConfirmationVm {
    notification_vm: NotificationVm,
}

impl ConfirmationVm {
    pub fn new(notification: Notification) -> Self {
        Self::with_hub(notification, NotificationHub::new())
    }

    pub fn with_hub(notification: Notification, hub: NotificationHub) -> Self {
        Self {
            notification_vm: NotificationVm::with_hub(notification, hub, 300_000),
        }
    }

    pub fn approve(&self) {
        self.resolve(NotificationReaction::Approve);
    }

    pub fn reject(&self) {
        self.resolve(NotificationReaction::Reject);
    }

    pub fn reaction(&self) -> NotificationReaction {
        self.notification_vm
            .hub
            .reaction(self.notification_vm.notification.id)
    }

    pub fn is_resolved(&self) -> bool {
        self.notification_vm.is_resolved()
    }

    pub fn approve_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new(move || vm.approve())
    }

    pub fn reject_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new(move || vm.reject())
    }

    fn resolve(&self, reaction: NotificationReaction) {
        let should_resolve = {
            let mut resolved = lock(&self.notification_vm.resolved);
            if *resolved {
                false
            } else {
                *resolved = true;
                true
            }
        };
        if should_resolve {
            self.notification_vm
                .hub
                .resolve(self.notification_vm.notification.id, reaction);
        }
    }
}

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
