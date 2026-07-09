//! VMx Rust flavor.
//!
//! The Rust flavor mirrors the VMx language-neutral specification while using
//! Rust naming and error handling. Rust has no inheritance, so the class-family
//! hierarchy used by other flavors is represented by cloneable handles,
//! trait-based contracts, and shared lifecycle/message cores.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::fmt;
use std::hash::Hash;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, Weak};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
pub const MIN_SPEC_VERSION: &str = "3.1.0";

static NEXT_ID: AtomicUsize = AtomicUsize::new(1);

fn next_id() -> usize {
    NEXT_ID.fetch_add(1, Ordering::Relaxed)
}

fn lock<T: ?Sized>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
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
    #[error("component is not current")]
    NotCurrent,
    #[error("builder validation failed: {0}")]
    BuilderValidation(String),
    #[error("readonly model cannot be changed")]
    ReadonlyModel,
    #[error("dialog already active")]
    DialogReentrancy,
    #[error("invalid argument: {0}")]
    InvalidArgument(String),
    #[error("{0}")]
    Other(String),
}

pub type VmxResult<T> = Result<T, VmxError>;

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
    Reset,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollectionChangedMessage {
    pub sender_id: usize,
    pub property_name: String,
    pub action: CollectionChangeAction,
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
}

type Subscriber = Arc<dyn Fn(&Message) + Send + Sync + 'static>;

#[derive(Clone, Default)]
pub struct MessageHub {
    inner: Arc<Mutex<MessageHubInner>>,
}

#[derive(Default)]
struct MessageHubInner {
    next_subscription_id: usize,
    subscribers: BTreeMap<usize, Subscriber>,
    history: Vec<Message>,
    disposed: bool,
}

impl MessageHub {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn subscribe<F>(&self, handler: F) -> Subscription
    where
        F: Fn(&Message) + Send + Sync + 'static,
    {
        let mut inner = lock(&self.inner);
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

    pub fn send(&self, message: Message) {
        let subscribers = {
            let mut inner = lock(&self.inner);
            if inner.disposed {
                return;
            }
            inner.history.push(message.clone());
            inner.subscribers.values().cloned().collect::<Vec<_>>()
        };
        for subscriber in subscribers {
            let _ = catch_unwind(AssertUnwindSafe(|| subscriber(&message)));
        }
    }

    pub fn history(&self) -> Vec<Message> {
        lock(&self.inner).history.clone()
    }

    pub fn dispose(&self) {
        let mut inner = lock(&self.inner);
        inner.subscribers.clear();
        inner.disposed = true;
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
    hub: Weak<Mutex<MessageHubInner>>,
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
            lock(&hub).subscribers.remove(&self.id);
        }
    }
}

impl Drop for Subscription {
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

pub trait VmNode: Clone + PartialEq + Send + Sync + 'static {
    fn id(&self) -> usize;
    fn construct(&self) -> VmxResult<()>;
    fn destruct(&self) -> VmxResult<()>;
    fn dispose(&self) -> VmxResult<()>;
    fn status(&self) -> ConstructionStatus;
    fn set_parent_id(&self, parent_id: Option<usize>);
    fn parent_id(&self) -> Option<usize>;
}

type Hook = Arc<Mutex<dyn FnMut() -> VmxResult<()> + Send + 'static>>;
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
    parent_id: Option<usize>,
    hub: MessageHub,
    foreground: D,
    on_construct: Option<Hook>,
    on_destruct: Option<Hook>,
    on_dispose: Option<Hook>,
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
                parent_id: None,
                hub,
                foreground: dispatcher,
                on_construct: None,
                on_destruct: None,
                on_dispose: None,
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
        let (sender_id, hub, foreground, hook, target) = {
            let mut inner = lock(&self.inner);
            if inner.transitioning {
                return Err(VmxError::ConcurrentOperation);
            }
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
            )
        };

        hub.send(Message::ConstructionStatusChanged(
            ConstructionStatusChangedMessage {
                sender_id,
                status: self.status(),
            },
        ));

        let hook_result = hook.map(|hook| (lock(&hook))()).unwrap_or(Ok(()));
        if let Err(error) = hook_result {
            let rollback = match operation {
                LifecycleOperation::Construct => ConstructionStatus::Destructed,
                LifecycleOperation::Destruct => ConstructionStatus::Constructed,
                LifecycleOperation::Dispose => ConstructionStatus::Disposed,
            };
            let mut inner = lock(&self.inner);
            inner.status = rollback;
            inner.transitioning = false;
            return Err(error);
        }

        {
            let mut inner = lock(&self.inner);
            inner.status = target;
            inner.transitioning = false;
        }
        foreground.dispatch(Box::new(move || {
            hub.send(Message::ConstructionStatusChanged(
                ConstructionStatusChangedMessage {
                    sender_id,
                    status: target,
                },
            ));
        }));
        Ok(())
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        let (sender_id, hub) = {
            let mut inner = lock(&self.inner);
            if inner.parent_id == parent_id {
                return;
            }
            inner.parent_id = parent_id;
            (inner.id, inner.hub.clone())
        };
        hub.send(Message::PropertyChanged(PropertyChangedMessage {
            sender_id,
            property_name: "parent".to_string(),
        }));
    }

    fn parent_id(&self) -> Option<usize> {
        lock(&self.inner).parent_id
    }

    fn property_changed(&self, property_name: impl Into<String>) {
        let inner = lock(&self.inner);
        inner
            .hub
            .send(Message::PropertyChanged(PropertyChangedMessage {
                sender_id: inner.id,
                property_name: property_name.into(),
            }));
    }

    fn is_selected(&self) -> bool {
        lock(&self.inner).selected
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
            self.property_changed("is_selected");
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
            self.property_changed("is_selected");
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
            self.property_changed("is_expanded");
        }
    }
}

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
        self.core
            .hint()
            .or_else(|| (self.model_hint)(&lock(&self.model)))
    }

    pub fn set_hint(&self, hint: Option<String>) {
        self.core.set_hint(hint);
    }

    pub fn model(&self) -> M {
        lock(&self.model).clone()
    }

    pub fn set_model(&self, model: M) {
        let changed = {
            let mut current = lock(&self.model);
            if *current == model {
                false
            } else {
                *current = model;
                true
            }
        };
        if changed {
            self.core.property_changed("model");
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

    pub fn model(&self) -> M {
        self.inner.model()
    }

    pub fn as_component(&self) -> &ComponentVm<M, D> {
        &self.inner
    }
}

pub trait Command: Send + Sync {
    fn can_execute(&self) -> bool;
    fn execute(&self);
}

type CommandAction = Arc<Mutex<dyn FnMut() + Send + 'static>>;
type CommandPredicate = Arc<dyn Fn() -> bool + Send + Sync + 'static>;

#[derive(Clone)]
pub struct RelayCommand {
    action: Option<CommandAction>,
    predicate: Option<CommandPredicate>,
    disposed: Arc<Mutex<bool>>,
    can_execute_changed: MessageHub,
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
        F: Fn() -> bool + Send + Sync + 'static,
    {
        self.predicate = Some(Arc::new(predicate));
        self
    }

    pub fn trigger_can_execute_changed(&self) {
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            name: "can_execute_changed".to_string(),
        });
    }

    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    pub fn dispose(&self) {
        *lock(&self.disposed) = true;
    }

    pub fn confirm<F>(self, confirm: F) -> ConfirmationDecoratorCommand<Self>
    where
        F: Fn() -> bool + Send + Sync + 'static,
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
        !*lock(&self.disposed) && self.predicate.as_ref().map(|p| p()).unwrap_or(true)
    }

    fn execute(&self) {
        if !self.can_execute() {
            return;
        }
        if let Some(action) = &self.action {
            (lock(action))();
        }
    }
}

#[derive(Clone)]
pub struct CompositeCommand {
    commands: Vec<Arc<dyn Command>>,
}

impl CompositeCommand {
    pub fn new(commands: Vec<Arc<dyn Command>>) -> Self {
        Self { commands }
    }
}

impl Command for CompositeCommand {
    fn can_execute(&self) -> bool {
        self.commands.iter().any(|command| command.can_execute())
    }

    fn execute(&self) {
        for command in &self.commands {
            if command.can_execute() {
                command.execute();
            }
        }
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
        self.inner.can_execute() && self.predicate.as_ref().map(|p| p()).unwrap_or(true)
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
}

#[derive(Clone)]
pub struct ConfirmationDecoratorCommand<C: Command + Clone> {
    inner: C,
    confirm: Arc<dyn Fn() -> bool + Send + Sync>,
    errors: MessageHub,
}

impl<C: Command + Clone> ConfirmationDecoratorCommand<C> {
    pub fn new<F>(inner: C, confirm: F) -> Self
    where
        F: Fn() -> bool + Send + Sync + 'static,
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
}

impl<C: Command + Clone> Command for ConfirmationDecoratorCommand<C> {
    fn can_execute(&self) -> bool {
        self.inner.can_execute()
    }

    fn execute(&self) {
        if self.can_execute() && (self.confirm)() {
            self.inner.execute();
        }
    }
}

#[derive(Clone)]
pub struct ObservableList<T: Clone + Send + 'static> {
    inner: Arc<Mutex<Vec<T>>>,
    hub: MessageHub,
    owner_id: usize,
    batch_depth: Arc<Mutex<usize>>,
}

impl<T: Clone + Send + 'static> ObservableList<T> {
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            owner_id,
            batch_depth: Arc::new(Mutex::new(0)),
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

    pub fn push(&self, item: T) {
        lock(&self.inner).push(item);
        self.publish(CollectionChangeAction::Add);
    }

    pub fn remove_at(&self, index: usize) -> Option<T> {
        let item = {
            let mut inner = lock(&self.inner);
            if index >= inner.len() {
                None
            } else {
                Some(inner.remove(index))
            }
        };
        if item.is_some() {
            self.publish(CollectionChangeAction::Remove);
        }
        item
    }

    pub fn clear(&self) {
        lock(&self.inner).clear();
        self.publish(CollectionChangeAction::Reset);
    }

    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        *lock(&self.batch_depth) += 1;
        action();
        let mut depth = lock(&self.batch_depth);
        *depth -= 1;
        if *depth == 0 {
            drop(depth);
            self.publish(CollectionChangeAction::Reset);
        }
    }

    fn publish(&self, action: CollectionChangeAction) {
        if *lock(&self.batch_depth) > 0 {
            return;
        }
        self.hub
            .send(Message::CollectionChanged(CollectionChangedMessage {
                sender_id: self.owner_id,
                property_name: "items".to_string(),
                action,
            }));
        self.hub
            .send(Message::PropertyChanged(PropertyChangedMessage {
                sender_id: self.owner_id,
                property_name: "Count".to_string(),
            }));
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
            }));
    }
}

#[derive(Clone)]
pub struct CompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    items: ObservableList<T>,
    current: Arc<Mutex<Option<T>>>,
    auto_construct_on_add: Arc<Mutex<bool>>,
}

impl<T: VmNode> CompositeVm<T, NullDispatcher> {
    pub fn new(name: impl Into<String>) -> Self {
        Self::with_services(name, MessageHub::new(), NullDispatcher::new())
    }
}

impl<T: VmNode, D: Dispatcher> CompositeVm<T, D> {
    pub fn with_services(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        let core = ComponentCore::new(name, hub.clone(), dispatcher);
        let items = ObservableList::new(core.id(), hub);
        Self {
            core,
            items,
            current: Arc::new(Mutex::new(None)),
            auto_construct_on_add: Arc::new(Mutex::new(false)),
        }
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn items(&self) -> Vec<T> {
        self.items.to_vec()
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    pub fn add(&self, item: T) -> VmxResult<()> {
        item.set_parent_id(Some(self.id()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        self.items.push(item.clone());
        if should_construct {
            item.construct()?;
        }
        if lock(&self.current).is_none() {
            *lock(&self.current) = Some(item);
        }
        Ok(())
    }

    pub fn remove(&self, item: &T) -> VmxResult<()> {
        let index = self
            .items()
            .iter()
            .position(|candidate| candidate == item)
            .ok_or(VmxError::NonChild)?;
        let removed = self.items.remove_at(index).expect("index checked");
        removed.set_parent_id(None);
        let mut current = lock(&self.current);
        if current.as_ref() == Some(&removed) {
            *current = self.items().first().cloned();
        }
        Ok(())
    }

    pub fn current(&self) -> Option<T> {
        lock(&self.current).clone()
    }

    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        if !self.items().iter().any(|candidate| candidate == item) {
            return Err(VmxError::NonChild);
        }
        *lock(&self.current) = Some(item.clone());
        self.core.property_changed("current");
        Ok(())
    }

    pub fn deselect_component(&self, item: &T) -> VmxResult<()> {
        let mut current = lock(&self.current);
        if current.as_ref() != Some(item) {
            return Err(VmxError::NotCurrent);
        }
        *current = None;
        drop(current);
        self.core.property_changed("current");
        Ok(())
    }

    pub fn can_select_component(&self, item: &T) -> bool {
        self.items().iter().any(|candidate| candidate == item)
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
        self.core.transition(LifecycleOperation::Construct)?;
        for item in self.items() {
            item.construct()?;
        }
        Ok(())
    }

    pub fn destruct(&self) -> VmxResult<()> {
        for item in self.items() {
            item.destruct()?;
        }
        self.core.transition(LifecycleOperation::Destruct)
    }

    pub fn dispose(&self) -> VmxResult<()> {
        for item in self.items() {
            item.dispose()?;
        }
        self.core.transition(LifecycleOperation::Dispose)
    }

    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
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
}

impl<T: VmNode, D: Dispatcher> PartialEq for CompositeVm<T, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T: VmNode, D: Dispatcher> Eq for CompositeVm<T, D> {}

pub type GroupVm<T, D = NullDispatcher> = CompositeVm<T, D>;

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

type SearchPredicate<T> = Arc<dyn Fn(&T, &str) -> bool + Send + Sync>;

#[derive(Clone)]
pub struct SearchableState<T: Clone + Send + 'static> {
    source: Arc<Mutex<Vec<T>>>,
    search_term: Arc<Mutex<String>>,
    predicate: SearchPredicate<T>,
}

impl<T: Clone + Send + 'static> SearchableState<T> {
    pub fn new<F>(source: Vec<T>, predicate: F) -> Self
    where
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self {
            source: Arc::new(Mutex::new(source)),
            search_term: Arc::new(Mutex::new(String::new())),
            predicate: Arc::new(predicate),
        }
    }

    pub fn search_term(&self) -> String {
        lock(&self.search_term).clone()
    }

    pub fn set_search_term(&self, term: impl Into<String>) {
        *lock(&self.search_term) = term.into();
    }

    pub fn search(&self) -> Vec<T> {
        let term = self.search_term();
        lock(&self.source)
            .iter()
            .filter(|item| (self.predicate)(item, &term))
            .cloned()
            .collect()
    }
}

#[derive(Clone)]
pub struct DerivedProperty<T: Clone + PartialEq + Send + 'static> {
    value: Arc<Mutex<T>>,
    value_changed: MessageHub,
}

impl<T: Clone + PartialEq + Send + 'static> DerivedProperty<T> {
    pub fn new(value: T) -> Self {
        Self {
            value: Arc::new(Mutex::new(value)),
            value_changed: MessageHub::new(),
        }
    }

    pub fn value(&self) -> T {
        lock(&self.value).clone()
    }

    pub fn recompute<F>(&self, transform: F)
    where
        F: FnOnce(&T) -> T,
    {
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

#[derive(Clone, Default)]
pub struct NotificationHub {
    pending: Arc<Mutex<BTreeMap<u64, Notification>>>,
    reactions: Arc<Mutex<HashMap<u64, NotificationReaction>>>,
}

impl NotificationHub {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn post(&self, kind: NotificationType, message: impl Into<String>) -> Notification {
        static NEXT_NOTIFICATION_ID: AtomicU64 = AtomicU64::new(1);
        let notification = Notification {
            id: NEXT_NOTIFICATION_ID.fetch_add(1, Ordering::Relaxed),
            kind,
            message: message.into(),
        };
        lock(&self.pending).insert(notification.id, notification.clone());
        lock(&self.reactions).insert(notification.id, NotificationReaction::Pending);
        notification
    }

    pub fn resolve(&self, notification_id: u64, reaction: NotificationReaction) {
        lock(&self.pending).remove(&notification_id);
        lock(&self.reactions).insert(notification_id, reaction);
    }

    pub fn pending(&self) -> Vec<Notification> {
        lock(&self.pending).values().cloned().collect()
    }

    pub fn reaction(&self, notification_id: u64) -> NotificationReaction {
        lock(&self.reactions)
            .get(&notification_id)
            .copied()
            .unwrap_or(NotificationReaction::Pending)
    }
}

pub struct NullNotificationHub;

impl NullNotificationHub {
    pub fn post(message: impl Into<String>) -> Notification {
        Notification {
            id: 0,
            kind: NotificationType::Notification,
            message: message.into(),
        }
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

pub trait DialogService: Send + Sync {
    fn confirm(&self, message: &str) -> bool;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NullDialogService;

impl DialogService for NullDialogService {
    fn confirm(&self, _message: &str) -> bool {
        false
    }
}

type FormValidator<M> = Arc<dyn Fn(&M) -> Vec<String> + Send + Sync>;

#[derive(Clone)]
pub struct FormVm<M: Clone + PartialEq + Send + 'static> {
    component: ComponentVm<M>,
    snapshot: Arc<Mutex<M>>,
    validator: FormValidator<M>,
}

impl<M: Clone + PartialEq + Send + 'static> FormVm<M> {
    pub fn new(name: impl Into<String>, model: M) -> Self {
        Self {
            component: ComponentVm::with_model(
                name,
                model.clone(),
                MessageHub::new(),
                NullDispatcher::new(),
            ),
            snapshot: Arc::new(Mutex::new(model)),
            validator: Arc::new(|_| Vec::new()),
        }
    }

    pub fn with_validator<F>(mut self, validator: F) -> Self
    where
        F: Fn(&M) -> Vec<String> + Send + Sync + 'static,
    {
        self.validator = Arc::new(validator);
        self
    }

    pub fn model(&self) -> M {
        self.component.model()
    }

    pub fn set_model(&self, model: M) {
        self.component.set_model(model);
    }

    pub fn is_dirty(&self) -> bool {
        self.model() != *lock(&self.snapshot)
    }

    pub fn errors(&self) -> Vec<String> {
        (self.validator)(&self.model())
    }

    pub fn is_valid(&self) -> bool {
        self.errors().is_empty()
    }

    pub fn approve(&self) -> VmxResult<()> {
        if !self.is_valid() {
            return Err(VmxError::InvalidArgument("form is invalid".to_string()));
        }
        *lock(&self.snapshot) = self.model();
        Ok(())
    }

    pub fn revert(&self) {
        self.component.set_model(lock(&self.snapshot).clone());
    }
}

#[derive(Clone)]
pub struct DiscriminatorVm<K: Clone + Eq + Hash + Send + 'static> {
    current_key: Arc<Mutex<K>>,
    allowed: Arc<Mutex<HashSet<K>>>,
}

impl<K: Clone + Eq + Hash + Send + 'static> DiscriminatorVm<K> {
    pub fn new(initial: K, allowed: impl IntoIterator<Item = K>) -> Self {
        Self {
            current_key: Arc::new(Mutex::new(initial)),
            allowed: Arc::new(Mutex::new(allowed.into_iter().collect())),
        }
    }

    pub fn current_key(&self) -> K {
        lock(&self.current_key).clone()
    }

    pub fn set_current_key(&self, key: K) -> VmxResult<()> {
        if !lock(&self.allowed).contains(&key) {
            return Err(VmxError::InvalidArgument(
                "unknown discriminator key".to_string(),
            ));
        }
        *lock(&self.current_key) = key;
        Ok(())
    }
}

#[derive(Clone)]
pub struct HierarchicalVm<M: Clone + PartialEq + Send + 'static> {
    component: ComponentVm<M>,
    children: Arc<Mutex<Vec<Self>>>,
}

impl<M: Clone + PartialEq + Send + 'static> HierarchicalVm<M> {
    pub fn new(name: impl Into<String>, model: M) -> Self {
        Self {
            component: ComponentVm::with_model(
                name,
                model,
                MessageHub::new(),
                NullDispatcher::new(),
            ),
            children: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn id(&self) -> usize {
        self.component.id()
    }

    pub fn add_child(&self, child: Self) -> VmxResult<()> {
        if child.id() == self.id() || child.contains_descendant(self.id()) {
            return Err(VmxError::InvalidArgument(
                "cannot reparent self or ancestor".to_string(),
            ));
        }
        child.component.core.set_parent_id(Some(self.id()));
        lock(&self.children).push(child);
        Ok(())
    }

    pub fn children(&self) -> Vec<Self> {
        lock(&self.children).clone()
    }

    pub fn is_root(&self) -> bool {
        self.component.parent_id().is_none()
    }

    pub fn is_leaf(&self) -> bool {
        lock(&self.children).is_empty()
    }

    pub fn depth(&self) -> usize {
        0
    }

    fn contains_descendant(&self, id: usize) -> bool {
        self.children()
            .iter()
            .any(|child| child.id() == id || child.contains_descendant(id))
    }
}

impl<M: Clone + PartialEq + Send + 'static> PartialEq for HierarchicalVm<M> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<M: Clone + PartialEq + Send + 'static> Eq for HierarchicalVm<M> {}

pub fn walk<T: VmNode>(root: &T) -> Vec<T> {
    vec![root.clone()]
}

pub fn find<T: VmNode, F>(root: &T, predicate: F) -> Option<T>
where
    F: Fn(&T) -> bool,
{
    if predicate(root) {
        Some(root.clone())
    } else {
        None
    }
}

pub fn lifecycle_transition_fixture() -> &'static str {
    include_str!("../../../spec/fixtures/lifecycle-transitions.json")
}

pub trait Selectable {
    fn select(&self);
}

pub trait Deselectable {
    fn deselect(&self);
}

pub trait Expandable {
    fn expand(&self);
}

pub trait Collapsible {
    fn collapse(&self);
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Selectable for ComponentVm<M, D> {
    fn select(&self) {
        ComponentVm::select(self);
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Deselectable for ComponentVm<M, D> {
    fn deselect(&self) {
        ComponentVm::deselect(self);
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Expandable for ComponentVm<M, D> {
    fn expand(&self) {
        ComponentVm::expand(self);
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Collapsible for ComponentVm<M, D> {
    fn collapse(&self) {
        ComponentVm::collapse(self);
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
        for member in &self.members {
            member.dispose()?;
        }
        Ok(())
    }
}

pub type AggregateVm1<T> = AggregateVm<T>;
pub type AggregateVm2<T> = AggregateVm<T>;
pub type AggregateVm3<T> = AggregateVm<T>;
pub type AggregateVm4<T> = AggregateVm<T>;
pub type AggregateVm5<T> = AggregateVm<T>;
pub type AggregateVm6<T> = AggregateVm<T>;

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
}

#[derive(Clone)]
pub struct TokenPagedComposition<T: Clone + Send + 'static, Token: Clone + Send + 'static> {
    items: Arc<Mutex<Vec<T>>>,
    next_token: Arc<Mutex<Option<Token>>>,
}

impl<T: Clone + Send + 'static, Token: Clone + Send + 'static> TokenPagedComposition<T, Token> {
    pub fn new(initial_token: Option<Token>) -> Self {
        Self {
            items: Arc::new(Mutex::new(Vec::new())),
            next_token: Arc::new(Mutex::new(initial_token)),
        }
    }

    pub fn items(&self) -> Vec<T> {
        lock(&self.items).clone()
    }

    pub fn can_load_more(&self) -> bool {
        lock(&self.next_token).is_some()
    }

    pub fn load_more<F>(&self, loader: F)
    where
        F: FnOnce(Option<Token>) -> (Vec<T>, Option<Token>),
    {
        let token = lock(&self.next_token).clone();
        let (items, next_token) = loader(token);
        lock(&self.items).extend(items);
        *lock(&self.next_token) = next_token;
    }
}

#[derive(Clone)]
pub struct ModalVm<T: Clone + Send + 'static> {
    result: Arc<Mutex<Option<T>>>,
    is_open: Arc<Mutex<bool>>,
}

impl<T: Clone + Send + 'static> ModalVm<T> {
    pub fn new() -> Self {
        Self {
            result: Arc::new(Mutex::new(None)),
            is_open: Arc::new(Mutex::new(false)),
        }
    }

    pub fn open(&self) {
        *lock(&self.is_open) = true;
    }

    pub fn close(&self, result: Option<T>) {
        *lock(&self.result) = result;
        *lock(&self.is_open) = false;
    }

    pub fn result(&self) -> Option<T> {
        lock(&self.result).clone()
    }
}

impl<T: Clone + Send + 'static> Default for ModalVm<T> {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Clone)]
pub struct NotificationVm {
    notification: Notification,
    resolved: Arc<Mutex<bool>>,
}

impl NotificationVm {
    pub fn new(notification: Notification) -> Self {
        Self {
            notification,
            resolved: Arc::new(Mutex::new(false)),
        }
    }

    pub fn notification(&self) -> Notification {
        self.notification.clone()
    }

    pub fn dismiss(&self) {
        *lock(&self.resolved) = true;
    }

    pub fn is_resolved(&self) -> bool {
        *lock(&self.resolved)
    }
}

#[derive(Clone)]
pub struct ConfirmationVm {
    notification_vm: NotificationVm,
    reaction: Arc<Mutex<NotificationReaction>>,
}

impl ConfirmationVm {
    pub fn new(notification: Notification) -> Self {
        Self {
            notification_vm: NotificationVm::new(notification),
            reaction: Arc::new(Mutex::new(NotificationReaction::Pending)),
        }
    }

    pub fn approve(&self) {
        *lock(&self.reaction) = NotificationReaction::Approve;
        self.notification_vm.dismiss();
    }

    pub fn reject(&self) {
        *lock(&self.reaction) = NotificationReaction::Reject;
        self.notification_vm.dismiss();
    }

    pub fn reaction(&self) -> NotificationReaction {
        *lock(&self.reaction)
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
