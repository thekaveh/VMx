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
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
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
    fn set_current_flag(&self, _is_current: bool) {}
    fn is_current(&self) -> bool {
        false
    }
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
        lock(&self.inner).parent_id = parent_id;
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
            self.property_changed("is_current");
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

    fn set_current_flag(&self, is_current: bool) {
        self.core.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.core.is_selected()
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
            vm.set_hint(Some(hint));
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

    pub fn trigger_can_execute_changed(&self) {
        self.can_execute_changed.send(Message::Custom {
            sender_id: 0,
            name: "can_execute_changed".to_string(),
        });
    }

    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
    }

    pub fn builder() -> RelayCommandBuilder {
        RelayCommandBuilder::default()
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
                .map(|p| p(parameter))
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
    can_execute_changed: MessageHub,
}

impl AsyncRelayCommand {
    pub fn new<F>(action: F) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<()> + Send + Sync + 'static,
    {
        Self {
            action: Some(Arc::new(action)),
            predicate: None,
            disposed: Arc::new(AtomicBool::new(false)),
            executing: Arc::new(AtomicBool::new(false)),
            active_token: Arc::new(Mutex::new(None)),
            can_execute_changed: MessageHub::new(),
        }
    }

    pub fn noop() -> Self {
        Self {
            action: None,
            predicate: None,
            disposed: Arc::new(AtomicBool::new(false)),
            executing: Arc::new(AtomicBool::new(false)),
            active_token: Arc::new(Mutex::new(None)),
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

    pub fn can_execute(&self) -> bool {
        !self.disposed.load(Ordering::SeqCst)
            && !self.executing.load(Ordering::SeqCst)
            && self.predicate.as_ref().map(|p| p()).unwrap_or(true)
    }

    pub fn execute(&self) {
        let _ = self.execute_async();
    }

    pub fn execute_async(&self) -> std::thread::JoinHandle<VmxResult<()>> {
        if !self.can_execute() {
            return std::thread::spawn(|| Ok(()));
        }
        self.executing.store(true, Ordering::SeqCst);
        let token = CancellationToken::new();
        *lock(&self.active_token) = Some(token.clone());
        let action = self.action.clone();
        let executing = self.executing.clone();
        let active_token = self.active_token.clone();
        std::thread::spawn(move || {
            let result = action.map(|action| action(token)).unwrap_or(Ok(()));
            executing.store(false, Ordering::SeqCst);
            *lock(&active_token) = None;
            result
        })
    }

    pub fn cancel(&self) {
        if let Some(token) = lock(&self.active_token).as_ref() {
            token.cancel();
        }
    }

    pub fn is_executing(&self) -> bool {
        self.executing.load(Ordering::SeqCst)
    }

    pub fn dispose(&self) {
        self.disposed.store(true, Ordering::SeqCst);
        self.cancel();
    }

    pub fn can_execute_changed(&self) -> MessageHub {
        self.can_execute_changed.clone()
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
        self.commands.iter().any(|command| command.can_execute())
    }

    fn execute(&self) {
        for command in &self.commands {
            if command.can_execute() {
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

    fn can_execute_changed(&self) -> MessageHub {
        self.inner.can_execute_changed()
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
            let result = catch_unwind(AssertUnwindSafe(|| self.inner.execute()));
            if result.is_err() {
                self.errors.send(Message::Custom {
                    sender_id: 0,
                    name: "error".to_string(),
                });
            }
        }
    }

    fn can_execute_changed(&self) -> MessageHub {
        self.inner.can_execute_changed()
    }
}

#[derive(Clone)]
pub struct ObservableList<T: Clone + Send + 'static> {
    inner: Arc<Mutex<Vec<T>>>,
    hub: MessageHub,
    owner_id: usize,
    batch_depth: Arc<Mutex<usize>>,
    batch_dirty: Arc<Mutex<bool>>,
}

impl<T: Clone + Send + 'static> ObservableList<T> {
    pub fn new(owner_id: usize, hub: MessageHub) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Vec::new())),
            hub,
            owner_id,
            batch_depth: Arc::new(Mutex::new(0)),
            batch_dirty: Arc::new(Mutex::new(false)),
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
        lock(&self.inner).push(item);
        self.publish(CollectionChangeAction::Add);
    }

    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        let mut inner = lock(&self.inner);
        if index > inner.len() {
            return Err(VmxError::InvalidArgument("index out of range".to_string()));
        }
        inner.insert(index, item);
        drop(inner);
        self.publish(CollectionChangeAction::Add);
        Ok(())
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
            let changed = {
                let mut dirty = lock(&self.batch_dirty);
                let changed = *dirty;
                *dirty = false;
                changed
            };
            if changed {
                self.publish(CollectionChangeAction::Reset);
            }
        }
    }

    fn publish(&self, action: CollectionChangeAction) {
        if *lock(&self.batch_depth) > 0 {
            *lock(&self.batch_dirty) = true;
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

type CurrentChangedCallback<T> = Arc<dyn Fn(Option<T>) + Send + Sync>;

#[derive(Clone)]
pub struct CompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    items: ObservableList<T>,
    current: Arc<Mutex<Option<T>>>,
    auto_construct_on_add: Arc<Mutex<bool>>,
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
        let items = ObservableList::new(core.id(), hub);
        Self {
            core,
            items,
            current: Arc::new(Mutex::new(None)),
            auto_construct_on_add: Arc::new(Mutex::new(false)),
            on_current_changed: Arc::new(Mutex::new(None)),
        }
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
        item.set_parent_id(Some(self.id()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            item.construct()?;
        }
        self.items.push(item);
        Ok(())
    }

    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        item.set_parent_id(Some(self.id()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            item.construct()?;
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
        removed.set_parent_id(None);
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
        removed.set_parent_id(None);
        if lock(&self.current).as_ref() == Some(&removed) {
            self.assign_current(None);
        }
        Ok(removed)
    }

    pub fn clear(&self) {
        for item in self.items() {
            item.set_parent_id(None);
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
        self.assign_current(item);
        Ok(())
    }

    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        if !self.can_select_component(item) {
            return Err(VmxError::NonChild);
        }
        self.assign_current(Some(item.clone()));
        Ok(())
    }

    pub fn deselect_component(&self, item: &T) -> VmxResult<()> {
        let mut current = lock(&self.current);
        if current.as_ref() != Some(item) {
            return Err(VmxError::NotCurrent);
        }
        *current = None;
        drop(current);
        item.set_current_flag(false);
        self.core.property_changed("current");
        self.invoke_current_changed(None);
        Ok(())
    }

    pub fn can_select_component(&self, item: &T) -> bool {
        self.items().iter().any(|candidate| candidate == item)
            && item.status() == ConstructionStatus::Constructed
    }

    pub fn set_auto_construct_on_add(&self, enabled: bool) {
        *lock(&self.auto_construct_on_add) = enabled;
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
        self.core.transition(LifecycleOperation::Construct)?;
        for item in self.items() {
            item.construct()?;
        }
        Ok(())
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.assign_current(None);
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
        self.core.property_changed("current");
        self.invoke_current_changed(next);
    }

    fn invoke_current_changed(&self, current: Option<T>) {
        if let Some(callback) = lock(&self.on_current_changed).clone() {
            callback(current);
        }
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

    fn set_current_flag(&self, is_current: bool) {
        self.core.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.core.is_selected()
    }
}

impl<T: VmNode, D: Dispatcher> PartialEq for CompositeVm<T, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T: VmNode, D: Dispatcher> Eq for CompositeVm<T, D> {}

type ChildrenFactory<T> = Arc<dyn Fn() -> Vec<T> + Send + Sync>;

#[derive(Clone)]
pub struct CompositeVmBuilder<T: VmNode, D: Dispatcher = NullDispatcher> {
    name: Option<String>,
    hint: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    children: Option<ChildrenFactory<T>>,
    auto_construct_on_add: bool,
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
        for child in children() {
            vm.add(child)?;
        }
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

#[derive(Clone)]
pub struct GroupVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    items: ObservableList<T>,
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
        let items = ObservableList::new(core.id(), hub);
        Self {
            core,
            items,
            auto_construct_on_add: Arc::new(Mutex::new(false)),
        }
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
        item.set_parent_id(Some(self.id()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            item.construct()?;
        }
        self.items.push(item);
        Ok(())
    }

    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        item.set_parent_id(Some(self.id()));
        let should_construct =
            *lock(&self.auto_construct_on_add) && self.status() == ConstructionStatus::Constructed;
        if should_construct {
            item.construct()?;
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
        removed.set_parent_id(None);
        Ok(())
    }

    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        let removed = self
            .items
            .remove_at(index)
            .ok_or_else(|| VmxError::InvalidArgument("index out of range".to_string()))?;
        removed.set_parent_id(None);
        Ok(removed)
    }

    pub fn clear(&self) {
        for item in self.items() {
            item.set_parent_id(None);
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
        for child in children() {
            vm.add(child)?;
        }
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
}

impl<T: Clone + Send + Sync + 'static> SearchableState<T> {
    pub fn new<F>(source: Vec<T>, predicate: F) -> Self
    where
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self::from_items(move || source.clone(), predicate)
    }

    pub fn from_items<S, F>(source: S, predicate: F) -> Self
    where
        S: Fn() -> Vec<T> + Send + Sync + 'static,
        F: Fn(&T, &str) -> bool + Send + Sync + 'static,
    {
        Self {
            source: Arc::new(source),
            search_term: Arc::new(Mutex::new(String::new())),
            predicate: Arc::new(predicate),
            filtered_changed: MessageHub::new(),
        }
    }

    pub fn search_term(&self) -> String {
        lock(&self.search_term).clone()
    }

    pub fn set_search_term(&self, term: impl Into<String>) {
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
        for member in &self.members {
            member.dispose()?;
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct AggregateVm1<T1: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    component1: T1,
}

impl<T1: VmNode> AggregateVm1<T1, NullDispatcher> {
    pub fn new(name: impl Into<String>, component1: T1) -> Self {
        Self::with_services(name, MessageHub::new(), NullDispatcher::new(), component1)
    }
}

impl<T1: VmNode, D: Dispatcher> AggregateVm1<T1, D> {
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
    ) -> Self {
        Self {
            core: ComponentCore::new(name, hub, dispatcher),
            component1,
        }
    }

    pub fn component1(&self) -> T1 {
        self.component1.clone()
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.component1.construct()?;
        self.core.property_changed("component1");
        self.core.transition(LifecycleOperation::Construct)
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.component1.destruct()?;
        self.core.transition(LifecycleOperation::Destruct)
    }

    pub fn dispose(&self) -> VmxResult<()> {
        self.component1.dispose()?;
        self.core.transition(LifecycleOperation::Dispose)
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
pub struct AggregateVm2<T1: VmNode, T2: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    component1: T1,
    component2: T2,
}

impl<T1: VmNode, T2: VmNode> AggregateVm2<T1, T2, NullDispatcher> {
    pub fn new(name: impl Into<String>, component1: T1, component2: T2) -> Self {
        Self::with_services(
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
        Self {
            core: ComponentCore::new(name, hub, dispatcher),
            component1,
            component2,
        }
    }

    pub fn component1(&self) -> T1 {
        self.component1.clone()
    }

    pub fn component2(&self) -> T2 {
        self.component2.clone()
    }

    pub fn id(&self) -> usize {
        self.core.id()
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.component1.construct()?;
        self.core.property_changed("component1");
        self.component2.construct()?;
        self.core.property_changed("component2");
        self.core.transition(LifecycleOperation::Construct)
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.component1.destruct()?;
        self.component2.destruct()?;
        self.core.transition(LifecycleOperation::Destruct)
    }

    pub fn dispose(&self) -> VmxResult<()> {
        self.component1.dispose()?;
        self.component2.dispose()?;
        self.core.transition(LifecycleOperation::Dispose)
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
    component1: T1,
    component2: T2,
    component3: T3,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode> AggregateVm3<T1, T2, T3, NullDispatcher> {
    pub fn new(name: impl Into<String>, component1: T1, component2: T2, component3: T3) -> Self {
        Self::with_services(
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
        Self {
            core: ComponentCore::new(name, hub, dispatcher),
            component1,
            component2,
            component3,
        }
    }

    pub fn component1(&self) -> T1 {
        self.component1.clone()
    }

    pub fn component2(&self) -> T2 {
        self.component2.clone()
    }

    pub fn component3(&self) -> T3 {
        self.component3.clone()
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.component1.construct()?;
        self.core.property_changed("component1");
        self.component2.construct()?;
        self.core.property_changed("component2");
        self.component3.construct()?;
        self.core.property_changed("component3");
        self.core.transition(LifecycleOperation::Construct)
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
    component1: T1,
    component2: T2,
    component3: T3,
    component4: T4,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode> AggregateVm4<T1, T2, T3, T4, NullDispatcher> {
    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> Self {
        Self {
            core: ComponentCore::new(name, MessageHub::new(), NullDispatcher::new()),
            component1,
            component2,
            component3,
            component4,
        }
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.component1.construct()?;
        self.component2.construct()?;
        self.component3.construct()?;
        self.component4.construct()?;
        self.core.transition(LifecycleOperation::Construct)
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
    component1: T1,
    component2: T2,
    component3: T3,
    component4: T4,
    component5: T5,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode>
    AggregateVm5<T1, T2, T3, T4, T5, NullDispatcher>
{
    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> Self {
        Self {
            core: ComponentCore::new(name, MessageHub::new(), NullDispatcher::new()),
            component1,
            component2,
            component3,
            component4,
            component5,
        }
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.component1.construct()?;
        self.component2.construct()?;
        self.component3.construct()?;
        self.component4.construct()?;
        self.component5.construct()?;
        self.core.transition(LifecycleOperation::Construct)
    }

    pub fn component5(&self) -> T5 {
        self.component5.clone()
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
    component1: T1,
    component2: T2,
    component3: T3,
    component4: T4,
    component5: T5,
    component6: T6,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode, T6: VmNode>
    AggregateVm6<T1, T2, T3, T4, T5, T6, NullDispatcher>
{
    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> Self {
        Self {
            core: ComponentCore::new(name, MessageHub::new(), NullDispatcher::new()),
            component1,
            component2,
            component3,
            component4,
            component5,
            component6,
        }
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.component1.construct()?;
        self.component2.construct()?;
        self.component3.construct()?;
        self.component4.construct()?;
        self.component5.construct()?;
        self.component6.construct()?;
        self.core.transition(LifecycleOperation::Construct)
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.component1.destruct()?;
        self.component2.destruct()?;
        self.component3.destruct()?;
        self.component4.destruct()?;
        self.component5.destruct()?;
        self.component6.destruct()?;
        self.core.transition(LifecycleOperation::Destruct)
    }

    pub fn component6(&self) -> T6 {
        self.component6.clone()
    }
}

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

    pub fn model(&self) -> M {
        self.inner.model()
    }

    pub fn set_model(&self, model: M) {
        self.inner.set_model(model);
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

    pub fn select(&self) {
        self.inner.select();
    }

    pub fn deselect(&self) {
        self.inner.deselect();
    }

    pub fn is_selected(&self) -> bool {
        self.inner.is_selected()
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

    pub fn items(&self) -> Vec<T> {
        self.inner.items()
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

    pub fn remove(&self, item: &T) -> VmxResult<()> {
        self.inner.remove(item)
    }

    pub fn current(&self) -> Option<T> {
        self.inner.current()
    }

    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        self.inner.select_component(item)
    }

    pub fn deselect_component(&self, item: &T) -> VmxResult<()> {
        self.inner.deselect_component(item)
    }

    pub fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }

    pub fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
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
