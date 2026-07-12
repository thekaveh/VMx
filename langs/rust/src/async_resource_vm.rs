//! One cancellable asynchronously acquired presentation value.
//!
//! Spec: `spec/23-async-resource-vm.md`; ADR-0100.

use crate::{
    lock, AsyncRelayCommand, CancellationToken, ComponentVm, MessageHub, NullDispatcher,
    PropertyChangedStream, RelayCommand, VmxError, VmxResult,
};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AsyncResourceStatus {
    Idle,
    Loading,
    Ready,
    Error,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AsyncResourceRetention {
    DiscardPrevious,
    RetainPrevious,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AsyncResourceState<T> {
    Idle,
    Loading {
        previous: Option<T>,
    },
    Ready {
        value: T,
    },
    Error {
        previous: Option<T>,
        error: VmxError,
    },
}

impl<T> AsyncResourceState<T> {
    pub fn status(&self) -> AsyncResourceStatus {
        match self {
            Self::Idle => AsyncResourceStatus::Idle,
            Self::Loading { .. } => AsyncResourceStatus::Loading,
            Self::Ready { .. } => AsyncResourceStatus::Ready,
            Self::Error { .. } => AsyncResourceStatus::Error,
        }
    }

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

struct Commands {
    load: AsyncRelayCommand,
    reload: AsyncRelayCommand,
    cancel: RelayCommand,
}

type Loader<T> = Arc<dyn Fn(CancellationToken) -> VmxResult<T> + Send + Sync + 'static>;
type Cleanup<T> = Arc<dyn Fn(T) + Send + Sync + 'static>;

struct Inner<T> {
    component: ComponentVm<(), NullDispatcher>,
    loader: Loader<T>,
    retention: AsyncResourceRetention,
    cleanup: Option<Cleanup<T>>,
    machine: Mutex<Machine<T>>,
    commands: Mutex<Option<Commands>>,
}

#[derive(Clone)]
pub struct AsyncResourceVm<T> {
    inner: Arc<Inner<T>>,
    load_command: AsyncRelayCommand,
    reload_command: AsyncRelayCommand,
    cancel_command: RelayCommand,
}

#[derive(Clone, Copy)]
enum StartIntent {
    Load,
    Reload,
}

impl<T> AsyncResourceVm<T>
where
    T: Clone + Send + 'static,
{
    pub fn new<F>(name: impl Into<String>, loader: F) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<T> + Send + Sync + 'static,
    {
        Self::with_options(name, loader, AsyncResourceRetention::DiscardPrevious, None)
    }

    pub fn with_options<F>(
        name: impl Into<String>,
        loader: F,
        retention: AsyncResourceRetention,
        cleanup: Option<Cleanup<T>>,
    ) -> Self
    where
        F: Fn(CancellationToken) -> VmxResult<T> + Send + Sync + 'static,
    {
        let inner = Arc::new(Inner {
            component: ComponentVm::new(name),
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

        let load_inner = inner.clone();
        let load_predicate = inner.clone();
        let load_command = AsyncRelayCommand::new(move |token| {
            run_intent(load_inner.clone(), StartIntent::Load, token)
        })
        .with_can_execute(move || can_load(&load_predicate));

        let reload_inner = inner.clone();
        let reload_predicate = inner.clone();
        let reload_command = AsyncRelayCommand::new(move |token| {
            run_intent(reload_inner.clone(), StartIntent::Reload, token)
        })
        .with_can_execute(move || can_reload(&reload_predicate));

        let cancel_inner = inner.clone();
        let cancel_predicate = inner.clone();
        let cancel_command = RelayCommand::new(move || cancel_current(&cancel_inner))
            .with_can_execute(move || can_cancel(&cancel_predicate));

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

    pub fn state(&self) -> AsyncResourceState<T> {
        lock(&self.inner.machine).state.clone()
    }

    pub fn status(&self) -> AsyncResourceStatus {
        lock(&self.inner.machine).state.status()
    }

    pub fn value(&self) -> Option<T> {
        lock(&self.inner.machine).state.value().cloned()
    }

    pub fn error(&self) -> Option<VmxError> {
        lock(&self.inner.machine).state.error().cloned()
    }

    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.component.property_changed()
    }

    pub fn hub(&self) -> MessageHub {
        self.inner.component.hub()
    }

    pub fn load_command(&self) -> AsyncRelayCommand {
        self.load_command.clone()
    }

    pub fn reload_command(&self) -> AsyncRelayCommand {
        self.reload_command.clone()
    }

    pub fn cancel_command(&self) -> RelayCommand {
        self.cancel_command.clone()
    }

    pub fn load_async(&self) -> JoinHandle<VmxResult<()>> {
        let inner = self.inner.clone();
        thread::spawn(move || run_intent(inner, StartIntent::Load, CancellationToken::new()))
    }

    pub fn reload_async(&self) -> JoinHandle<VmxResult<()>> {
        let inner = self.inner.clone();
        thread::spawn(move || run_intent(inner, StartIntent::Reload, CancellationToken::new()))
    }

    pub fn cancel(&self) {
        cancel_current(&self.inner);
        self.load_command.cancel();
        self.reload_command.cancel();
    }

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
        if let Some(commands) = lock(&self.inner.commands).as_ref() {
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

fn can_load<T>(inner: &Inner<T>) -> bool {
    let machine = lock(&inner.machine);
    !machine.disposed && machine.state.status() == AsyncResourceStatus::Idle
}

fn can_reload<T>(inner: &Inner<T>) -> bool {
    let machine = lock(&inner.machine);
    !machine.disposed && machine.state.status() != AsyncResourceStatus::Idle
}

fn can_cancel<T>(inner: &Inner<T>) -> bool {
    let machine = lock(&inner.machine);
    !machine.disposed && machine.state.status() == AsyncResourceStatus::Loading
}

fn run_intent<T>(
    inner: Arc<Inner<T>>,
    intent: StartIntent,
    external_token: CancellationToken,
) -> VmxResult<()>
where
    T: Clone + Send + 'static,
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
    notify_state(&inner);

    let (done_send, done_receive) = mpsc::channel();
    let loader_inner = inner.clone();
    let loader_operation = operation.clone();
    thread::spawn(move || {
        let result = (loader_inner.loader)(loader_operation.token.clone());
        complete_operation(&loader_inner, &loader_operation, result);
        let _ = done_send.send(());
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
            Ok(()) | Err(RecvTimeoutError::Disconnected) => return Ok(()),
            Err(RecvTimeoutError::Timeout) => {}
        }
    }
}

fn cancel_current<T>(inner: &Inner<T>)
where
    T: Clone + Send + 'static,
{
    let identity = lock(&inner.machine)
        .operation
        .as_ref()
        .map(|operation| operation.identity);
    if let Some(identity) = identity {
        cancel_operation(inner, identity);
    }
}

fn cancel_operation<T>(inner: &Inner<T>, identity: u64)
where
    T: Clone + Send + 'static,
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

fn complete_operation<T>(inner: &Inner<T>, operation: &Operation<T>, result: VmxResult<T>)
where
    T: Clone + Send + 'static,
{
    match result {
        Ok(value) => {
            let previous = {
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
                owned_value(stable)
            };
            if let Some(previous) = previous {
                cleanup(inner, previous);
            }
            notify_state(inner);
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

fn cleanup<T>(inner: &Inner<T>, value: T) {
    if let Some(cleanup) = &inner.cleanup {
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| cleanup(value)));
    }
}

fn notify_state<T>(inner: &Inner<T>) {
    inner.component.notify_property_changed("state");
    if let Some(commands) = lock(&inner.commands).as_ref() {
        commands.load.raise_can_execute_changed();
        commands.reload.raise_can_execute_changed();
        commands.cancel.raise_can_execute_changed();
    }
}
