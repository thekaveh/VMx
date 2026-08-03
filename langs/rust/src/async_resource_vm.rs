//! One cancellable asynchronously acquired presentation value.
//!
//! Spec: `spec/23-async-resource-vm.md`; ADR-0100.

use crate::{
    lock, AsyncRelayCommand, CancellationToken, ComponentVm, ConstructionStatus, Dispatcher,
    MessageHub, NullDispatcher, ParentHandle, PropertyChangedStream, RelayCommand, TreeNode,
    VmNode, VmxError, VmxResult,
};
use std::fmt;
use std::panic::{catch_unwind, resume_unwind, AssertUnwindSafe};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// The current acquisition phase of an [`AsyncResourceVm`].
pub enum AsyncResourceStatus {
    /// No acquisition has completed or is running.
    Idle,
    /// A loader invocation is currently in flight.
    Loading,
    /// The latest acquisition completed with a value.
    Ready,
    /// The latest acquisition failed.
    Error,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
/// Controls whether a reload exposes the previous stable value while loading.
pub enum AsyncResourceRetention {
    /// Discard and clean up the previous value before starting the next load.
    DiscardPrevious,
    /// Retain the previous value until the next load reaches a stable state.
    RetainPrevious,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// Observable acquisition state, including any retained value or failure.
pub enum AsyncResourceState<T> {
    /// No value or operation is present.
    Idle,
    /// Acquisition is in progress.
    Loading {
        /// The retained stable value, when retention is enabled.
        previous: Option<T>,
    },
    /// Acquisition completed successfully.
    Ready {
        /// The accepted resource value.
        value: T,
    },
    /// Acquisition completed with an error.
    Error {
        /// The retained stable value, when available.
        previous: Option<T>,
        /// The loader failure.
        error: VmxError,
    },
}

impl<T> AsyncResourceState<T> {
    /// Returns this state's phase without cloning its payload.
    pub fn status(&self) -> AsyncResourceStatus {
        match self {
            Self::Idle => AsyncResourceStatus::Idle,
            Self::Loading { .. } => AsyncResourceStatus::Loading,
            Self::Ready { .. } => AsyncResourceStatus::Ready,
            Self::Error { .. } => AsyncResourceStatus::Error,
        }
    }

    /// Borrows the ready or retained value, when one is present.
    pub fn value(&self) -> Option<&T> {
        match self {
            Self::Loading {
                previous: Some(value),
            }
            | Self::Ready { value }
            | Self::Error {
                previous: Some(value),
                ..
            } => Some(value),
            _ => None,
        }
    }

    /// Borrows the loader failure when this is an error state.
    pub fn error(&self) -> Option<&VmxError> {
        match self {
            Self::Error { error, .. } => Some(error),
            _ => None,
        }
    }
}

#[derive(Clone)]
enum StableState<T> {
    Idle,
    Ready(T),
    Error(Option<T>, VmxError),
}

impl<T> StableState<T> {
    fn value(&self) -> Option<&T> {
        match self {
            Self::Ready(value) | Self::Error(Some(value), _) => Some(value),
            _ => None,
        }
    }
}

#[derive(Clone)]
struct Operation<T> {
    identity: u64,
    token: CancellationToken,
    baseline: StableState<T>,
}

struct Machine<T> {
    state: AsyncResourceState<T>,
    stable: StableState<T>,
    operation: Option<Operation<T>>,
    identity: u64,
    disposed: bool,
}

#[derive(Clone)]
struct Commands {
    load: AsyncRelayCommand,
    reload: AsyncRelayCommand,
    cancel: RelayCommand,
}

type Loader<T> = Arc<dyn Fn(CancellationToken) -> VmxResult<T> + Send + Sync + 'static>;
type Cleanup<T> = Arc<dyn Fn(T) + Send + Sync + 'static>;

struct Inner<T, D: Dispatcher> {
    component: ComponentVm<(), D>,
    loader: Loader<T>,
    retention: AsyncResourceRetention,
    cleanup: Option<Cleanup<T>>,
    machine: Mutex<Machine<T>>,
    commands: Mutex<Option<Commands>>,
}

#[derive(Clone)]
/// A cancellable, command-backed asynchronous resource state machine.
pub struct AsyncResourceVm<T, D: Dispatcher = NullDispatcher> {
    inner: Arc<Inner<T, D>>,
    load_command: AsyncRelayCommand,
    reload_command: AsyncRelayCommand,
    cancel_command: RelayCommand,
}

#[derive(Clone, Copy)]
enum StartIntent {
    Load,
    Reload,
}

impl<T> AsyncResourceVm<T, NullDispatcher>
where
    T: Clone + Send + 'static,
{
    /// Creates a resource VM that discards previous values and needs no cleanup.
    pub fn new<F>(name: impl Into<String>, loader: F) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<T> + Send + Sync + 'static,
    {
        Self::with_options(name, loader, AsyncResourceRetention::DiscardPrevious, None)
    }

    /// Creates a resource VM with explicit retention and optional value cleanup.
    pub fn with_options<F>(
        name: impl Into<String>,
        loader: F,
        retention: AsyncResourceRetention,
        cleanup: Option<Cleanup<T>>,
    ) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<T> + Send + Sync + 'static,
    {
        Self::with_services_and_options(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            loader,
            retention,
            cleanup,
        )
    }
}

impl<T, D> AsyncResourceVm<T, D>
where
    T: Clone + Send + 'static,
    D: Dispatcher,
{
    /// Creates a resource VM with explicit component services.
    pub fn with_services<F>(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        loader: F,
    ) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<T> + Send + Sync + 'static,
    {
        Self::with_services_and_options(
            name,
            hub,
            dispatcher,
            loader,
            AsyncResourceRetention::DiscardPrevious,
            None,
        )
    }

    /// Creates a resource VM with explicit services, retention, and cleanup.
    pub fn with_services_and_options<F>(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        loader: F,
        retention: AsyncResourceRetention,
        cleanup: Option<Cleanup<T>>,
    ) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<T> + Send + Sync + 'static,
    {
        let inner = Arc::new(Inner {
            component: ComponentVm::with_services(name, hub, dispatcher),
            loader: Arc::new(loader),
            retention,
            cleanup,
            machine: Mutex::new(Machine {
                state: AsyncResourceState::Idle,
                stable: StableState::Idle,
                operation: None,
                identity: 0,
                disposed: false,
            }),
            commands: Mutex::new(None),
        });

        let load_inner = Arc::downgrade(&inner);
        let load_predicate = Arc::downgrade(&inner);
        let load_command = AsyncRelayCommand::new(move |token| {
            load_inner
                .upgrade()
                .map_or(Ok(()), |inner| run_intent(inner, StartIntent::Load, token))
        })
        .with_can_execute(move || {
            load_predicate
                .upgrade()
                .is_some_and(|inner| can_load(&inner))
        });

        let reload_inner = Arc::downgrade(&inner);
        let reload_predicate = Arc::downgrade(&inner);
        let reload_command = AsyncRelayCommand::new(move |token| {
            reload_inner.upgrade().map_or(Ok(()), |inner| {
                run_intent(inner, StartIntent::Reload, token)
            })
        })
        .with_can_execute(move || {
            reload_predicate
                .upgrade()
                .is_some_and(|inner| can_reload(&inner))
        });

        let cancel_inner = Arc::downgrade(&inner);
        let cancel_predicate = Arc::downgrade(&inner);
        let cancel_command = RelayCommand::new(move || {
            if let Some(inner) = cancel_inner.upgrade() {
                cancel_current(&inner);
            }
        })
        .with_can_execute(move || {
            cancel_predicate
                .upgrade()
                .is_some_and(|inner| can_cancel(&inner))
        });

        *lock(&inner.commands) = Some(Commands {
            load: load_command.clone(),
            reload: reload_command.clone(),
            cancel: cancel_command.clone(),
        });

        Self {
            inner,
            load_command,
            reload_command,
            cancel_command,
        }
    }

    /// Returns the canonical component family discriminator.
    pub fn view_model_type(&self) -> crate::ViewModelType {
        self.inner.component.view_model_type()
    }

    /// Returns the stable component identity.
    pub fn id(&self) -> usize {
        self.inner.component.id()
    }

    /// Returns the immutable component name.
    pub fn name(&self) -> String {
        self.inner.component.name()
    }

    /// Returns the immutable static presentation hint.
    pub fn hint(&self) -> Option<String> {
        self.inner.component.hint()
    }

    /// Returns a snapshot of the complete current acquisition state.
    pub fn state(&self) -> AsyncResourceState<T> {
        lock(&self.inner.machine).state.clone()
    }

    /// Returns the current acquisition phase.
    pub fn resource_status(&self) -> AsyncResourceStatus {
        lock(&self.inner.machine).state.status()
    }

    /// Clones the ready or retained value, when available.
    pub fn value(&self) -> Option<T> {
        lock(&self.inner.machine).state.value().cloned()
    }

    /// Clones the current loader failure, when present.
    pub fn error(&self) -> Option<VmxError> {
        lock(&self.inner.machine).state.error().cloned()
    }

    /// Returns the VM-local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.component.property_changed()
    }

    /// Returns the message hub used for state notifications.
    pub fn hub(&self) -> MessageHub {
        self.inner.component.hub()
    }

    /// Registers cleanup work that runs during component disposal.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.inner.component.own(cleanup);
    }

    /// Publishes a change for an application-defined property name.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.component.notify_property_changed(property_name);
    }

    /// Replaces the hook invoked during construction.
    pub fn on_construct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.component.on_construct(hook);
    }

    /// Replaces the hook invoked during destruction.
    pub fn on_destruct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.component.on_destruct(hook);
    }

    /// Replaces the hook invoked during disposal.
    pub fn on_dispose<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.component.on_dispose(hook);
    }

    /// Transitions the component to constructed state without starting a load.
    pub fn construct(&self) -> VmxResult<()> {
        self.inner.component.construct()
    }

    /// Transitions the component to destructed state without cancelling a load.
    pub fn destruct(&self) -> VmxResult<()> {
        self.inner.component.destruct()
    }

    /// Destructs and then reconstructs the component.
    pub fn reconstruct(&self) -> VmxResult<()> {
        self.inner.component.reconstruct()
    }

    /// Returns the current component lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.inner.component.status()
    }

    /// Reports whether the component is constructed.
    pub fn is_constructed(&self) -> bool {
        self.inner.component.is_constructed()
    }

    /// Reports whether this constructed component can select itself through its parent.
    pub fn can_select(&self) -> bool {
        self.inner.component.can_select()
    }

    /// Selects this component through its owning selectable parent.
    pub fn select(&self) {
        self.inner.component.select();
    }

    /// Reports whether this component can deselect itself through its parent.
    pub fn can_deselect(&self) -> bool {
        self.inner.component.can_deselect()
    }

    /// Deselects this component through its owning selectable parent.
    pub fn deselect(&self) {
        self.inner.component.deselect();
    }

    /// Reports whether this component is current in its owning container.
    pub fn is_current(&self) -> bool {
        self.inner.component.is_current()
    }

    /// Compatibility alias for [`Self::is_current`].
    pub fn is_selected(&self) -> bool {
        self.is_current()
    }

    /// Marks this component as expanded.
    pub fn expand(&self) {
        self.inner.component.expand();
    }

    /// Marks this component as collapsed.
    pub fn collapse(&self) {
        self.inner.component.collapse();
    }

    /// Toggles this component's expansion state.
    pub fn toggle_expansion(&self) {
        self.inner.component.toggle_expansion();
    }

    /// Reports whether this component is expanded.
    pub fn is_expanded(&self) -> bool {
        self.inner.component.is_expanded()
    }

    /// Returns the current parent identity, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.inner.component.parent_id()
    }

    /// Returns the stable command that selects this component through its parent.
    pub fn select_command(&self) -> RelayCommand {
        self.inner.component.select_command()
    }

    /// Returns the stable command that deselects this component through its parent.
    pub fn deselect_command(&self) -> RelayCommand {
        self.inner.component.deselect_command()
    }

    /// Returns the inert baseline next-sibling command.
    pub fn select_next_command(&self) -> RelayCommand {
        self.inner.component.select_next_command()
    }

    /// Returns the inert baseline previous-sibling command.
    pub fn select_previous_command(&self) -> RelayCommand {
        self.inner.component.select_previous_command()
    }

    /// Returns the stable component reconstruction command.
    pub fn reconstruct_command(&self) -> RelayCommand {
        self.inner.component.reconstruct_command()
    }

    /// Returns the command that starts the initial load.
    pub fn load_command(&self) -> AsyncRelayCommand {
        self.load_command.clone()
    }

    /// Returns the command that reloads from a non-idle state.
    pub fn reload_command(&self) -> AsyncRelayCommand {
        self.reload_command.clone()
    }

    /// Returns the command that cancels the active acquisition.
    pub fn cancel_command(&self) -> RelayCommand {
        self.cancel_command.clone()
    }

    /// Starts a load on a dedicated thread and returns its join handle.
    pub fn load_async(&self) -> JoinHandle<VmxResult<()>> {
        let inner = self.inner.clone();
        thread::spawn(move || run_intent(inner, StartIntent::Load, CancellationToken::new()))
    }

    /// Starts a reload on a dedicated thread and returns its join handle.
    pub fn reload_async(&self) -> JoinHandle<VmxResult<()>> {
        let inner = self.inner.clone();
        thread::spawn(move || run_intent(inner, StartIntent::Reload, CancellationToken::new()))
    }

    /// Cancels the active acquisition, if any.
    pub fn cancel(&self) {
        cancel_current(&self.inner);
        self.load_command.cancel();
        self.reload_command.cancel();
    }

    /// Cancels work, cleans up the retained value, and disposes owned commands.
    pub fn dispose(&self) -> VmxResult<()> {
        let (operation, accepted, first) = {
            let mut machine = lock(&self.inner.machine);
            if machine.disposed {
                (None, None, false)
            } else {
                machine.disposed = true;
                machine.identity = machine.identity.wrapping_add(1);
                let operation = machine.operation.take();
                let stable = std::mem::replace(&mut machine.stable, StableState::Idle);
                (operation, owned_value(stable), true)
            }
        };
        if !first {
            return Ok(());
        }
        if let Some(operation) = operation {
            operation.token.cancel();
        }
        let commands = lock(&self.inner.commands).clone();
        if let Some(commands) = commands {
            commands.load.dispose();
            commands.reload.dispose();
            commands.cancel.dispose();
        }
        if let Some(value) = accepted {
            cleanup(&self.inner, value);
        }
        self.inner.component.dispose()
    }
}

impl<T, D: Dispatcher> PartialEq for AsyncResourceVm<T, D> {
    fn eq(&self, other: &Self) -> bool {
        self.inner.component.id() == other.inner.component.id()
    }
}

impl<T, D: Dispatcher> Eq for AsyncResourceVm<T, D> {}

impl<T, D: Dispatcher> fmt::Debug for AsyncResourceVm<T, D> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AsyncResourceVm")
            .field("id", &self.inner.component.id())
            .field("name", &self.inner.component.name())
            .field("status", &self.inner.component.status())
            .finish()
    }
}

impl<T, D> VmNode for AsyncResourceVm<T, D>
where
    T: Clone + Send + 'static,
    D: Dispatcher,
{
    fn id(&self) -> usize {
        AsyncResourceVm::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        AsyncResourceVm::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        AsyncResourceVm::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        AsyncResourceVm::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        AsyncResourceVm::status(self)
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.component.core.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.inner.component.core.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner.component.core.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.inner.component.core.parent_handle()
    }

    fn set_current_flag(&self, is_current: bool) {
        self.inner.component.core.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.inner.component.core.is_selected()
    }
}

impl<T, D> TreeNode for AsyncResourceVm<T, D>
where
    T: Clone + Send + 'static,
    D: Dispatcher,
{
}

fn can_load<T, D: Dispatcher>(inner: &Inner<T, D>) -> bool {
    let machine = lock(&inner.machine);
    !machine.disposed && machine.state.status() == AsyncResourceStatus::Idle
}

fn can_reload<T, D: Dispatcher>(inner: &Inner<T, D>) -> bool {
    let machine = lock(&inner.machine);
    !machine.disposed && machine.state.status() != AsyncResourceStatus::Idle
}

fn can_cancel<T, D: Dispatcher>(inner: &Inner<T, D>) -> bool {
    let machine = lock(&inner.machine);
    !machine.disposed && machine.state.status() == AsyncResourceStatus::Loading
}

fn run_intent<T, D>(
    inner: Arc<Inner<T, D>>,
    intent: StartIntent,
    external_token: CancellationToken,
) -> VmxResult<()>
where
    T: Clone + Send + 'static,
    D: Dispatcher,
{
    let (operation, previous, discarded) = {
        let mut machine = lock(&inner.machine);
        if machine.disposed
            || (matches!(intent, StartIntent::Load)
                && machine.state.status() != AsyncResourceStatus::Idle)
            || (matches!(intent, StartIntent::Reload)
                && machine.state.status() == AsyncResourceStatus::Idle)
        {
            return Ok(());
        }

        machine.identity = machine.identity.wrapping_add(1);
        let previous = machine.operation.take();
        let discarded = if inner.retention == AsyncResourceRetention::DiscardPrevious
            && machine.stable.value().is_some()
        {
            let stable = std::mem::replace(&mut machine.stable, StableState::Idle);
            owned_value(stable)
        } else {
            None
        };
        let baseline = machine.stable.clone();
        let operation = Operation {
            identity: machine.identity,
            token: CancellationToken::new(),
            baseline: baseline.clone(),
        };
        let previous_value = if inner.retention == AsyncResourceRetention::RetainPrevious {
            baseline.value().cloned()
        } else {
            None
        };
        machine.state = AsyncResourceState::Loading {
            previous: previous_value,
        };
        machine.operation = Some(operation.clone());
        (operation, previous, discarded)
    };

    if let Some(previous) = previous {
        previous.token.cancel();
    }
    if let Some(value) = discarded {
        cleanup(&inner, value);
    }
    {
        let machine = lock(&inner.machine);
        if machine.disposed
            || machine
                .operation
                .as_ref()
                .is_none_or(|current| current.identity != operation.identity)
        {
            return Ok(());
        }
    }
    notify_state(&inner);

    let should_start = {
        let machine = lock(&inner.machine);
        !machine.disposed
            && machine
                .operation
                .as_ref()
                .is_some_and(|current| current.identity == operation.identity)
    };
    if !should_start {
        return Ok(());
    }

    let (done_send, done_receive) = mpsc::channel();
    let loader_inner = inner.clone();
    let loader_operation = operation.clone();
    thread::spawn(move || {
        let outcome = catch_unwind(AssertUnwindSafe(|| {
            let result = (loader_inner.loader)(loader_operation.token.clone());
            complete_operation(&loader_inner, &loader_operation, result);
        }));
        if outcome.is_err() {
            rollback_panicked_operation(&loader_inner, &loader_operation);
        }
        let _ = done_send.send(outcome);
    });

    loop {
        if external_token.is_cancelled() {
            cancel_operation(&inner, operation.identity);
            return Ok(());
        }
        if operation.token.is_cancelled() {
            return Ok(());
        }
        match done_receive.recv_timeout(Duration::from_millis(1)) {
            Ok(Ok(())) => return Ok(()),
            Ok(Err(panic)) => resume_unwind(panic),
            Err(RecvTimeoutError::Disconnected) => {
                panic!("async resource loader worker disconnected before reporting completion")
            }
            Err(RecvTimeoutError::Timeout) => {}
        }
    }
}

fn rollback_panicked_operation<T, D>(inner: &Inner<T, D>, operation: &Operation<T>)
where
    T: Clone + Send + 'static,
    D: Dispatcher,
{
    let notify = {
        let mut machine = lock(&inner.machine);
        if machine.disposed
            || machine.operation.as_ref().map(|current| current.identity)
                != Some(operation.identity)
        {
            false
        } else {
            machine.operation = None;
            machine.state = state_from_stable(&operation.baseline);
            true
        }
    };
    if notify {
        notify_state(inner);
    }
}

fn cancel_current<T, D>(inner: &Inner<T, D>)
where
    T: Clone + Send + 'static,
    D: Dispatcher,
{
    let identity = lock(&inner.machine)
        .operation
        .as_ref()
        .map(|operation| operation.identity);
    if let Some(identity) = identity {
        cancel_operation(inner, identity);
    }
}

fn cancel_operation<T, D>(inner: &Inner<T, D>, identity: u64)
where
    T: Clone + Send + 'static,
    D: Dispatcher,
{
    let operation = {
        let mut machine = lock(&inner.machine);
        if machine.disposed
            || machine
                .operation
                .as_ref()
                .map(|operation| operation.identity)
                != Some(identity)
        {
            return;
        }
        machine.identity = machine.identity.wrapping_add(1);
        let operation = machine.operation.take().expect("operation checked above");
        machine.state = state_from_stable(&operation.baseline);
        operation
    };
    operation.token.cancel();
    notify_state(inner);
}

fn complete_operation<T, D>(inner: &Inner<T, D>, operation: &Operation<T>, result: VmxResult<T>)
where
    T: Clone + Send + 'static,
    D: Dispatcher,
{
    match result {
        Ok(value) => {
            let (previous, committed_identity) = {
                let mut machine = lock(&inner.machine);
                if machine.disposed
                    || machine.operation.as_ref().map(|current| current.identity)
                        != Some(operation.identity)
                {
                    drop(machine);
                    cleanup(inner, value);
                    return;
                }
                machine.operation = None;
                let stable =
                    std::mem::replace(&mut machine.stable, StableState::Ready(value.clone()));
                machine.state = AsyncResourceState::Ready { value };
                (owned_value(stable), machine.identity)
            };
            if let Some(previous) = previous {
                cleanup(inner, previous);
            }
            let notify = {
                let machine = lock(&inner.machine);
                !machine.disposed
                    && machine.identity == committed_identity
                    && machine.operation.is_none()
            };
            if notify {
                notify_state(inner);
            }
        }
        Err(error) => {
            let notify = {
                let mut machine = lock(&inner.machine);
                if machine.disposed
                    || machine.operation.as_ref().map(|current| current.identity)
                        != Some(operation.identity)
                {
                    false
                } else {
                    machine.operation = None;
                    let previous = if inner.retention == AsyncResourceRetention::RetainPrevious {
                        machine.stable.value().cloned()
                    } else {
                        None
                    };
                    machine.stable = StableState::Error(previous.clone(), error.clone());
                    machine.state = AsyncResourceState::Error { previous, error };
                    true
                }
            };
            if notify {
                notify_state(inner);
            }
        }
    }
}

fn state_from_stable<T: Clone>(state: &StableState<T>) -> AsyncResourceState<T> {
    match state {
        StableState::Idle => AsyncResourceState::Idle,
        StableState::Ready(value) => AsyncResourceState::Ready {
            value: value.clone(),
        },
        StableState::Error(previous, error) => AsyncResourceState::Error {
            previous: previous.clone(),
            error: error.clone(),
        },
    }
}

fn owned_value<T>(state: StableState<T>) -> Option<T> {
    match state {
        StableState::Ready(value) | StableState::Error(Some(value), _) => Some(value),
        _ => None,
    }
}

fn cleanup<T, D: Dispatcher>(inner: &Inner<T, D>, value: T) {
    if let Some(cleanup) = &inner.cleanup {
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| cleanup(value)));
    }
}

fn notify_state<T, D: Dispatcher>(inner: &Inner<T, D>) {
    inner.component.notify_property_changed("state");
    let commands = lock(&inner.commands).clone();
    if let Some(commands) = commands {
        commands.load.raise_can_execute_changed();
        commands.reload.raise_can_execute_changed();
        commands.cancel.raise_can_execute_changed();
    }
}
