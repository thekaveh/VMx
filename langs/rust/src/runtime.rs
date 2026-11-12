//! Core errors, messages, lifecycle, dispatch, and tree ownership contracts.
//!
//! Spec: `spec/02-lifecycle.md`, `spec/03-messages.md`, and `spec/11-threading.md`.

use super::{
    catch_unwind, resume_unwind, thread, Arc, AssertUnwindSafe, AtomicBool, AtomicUsize, BTreeMap,
    Condvar, Deserialize, HashMap, HashSet, Mutex, MutexGuard, OnceLock, Ordering, Serialize,
    ThreadId, VecDeque, Weak,
};
use crate::wait_for_graph::{waits, Resource};
use crate::{ValueStream, ValueSubscription};
use std::sync::atomic::AtomicU8;
use std::sync::mpsc;

static NEXT_ID: AtomicUsize = AtomicUsize::new(1);
pub(crate) static HIERARCHY_TOPOLOGY_GATE: Mutex<()> = Mutex::new(());

thread_local! {
    static MESSAGE_HUB_DELIVERY_SENDERS: std::cell::RefCell<Vec<(usize, usize)>> = const { std::cell::RefCell::new(Vec::new()) };
}

struct MessageHubDeliveryGuard;

impl MessageHubDeliveryGuard {
    fn enter(hub_id: usize, sender_id: usize) -> Self {
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
    }
}

/// Waits on `condition` for `owner`'s hold on `resource`, recording the wait
/// in the process-wide wait-for graph (spec/03 §4.1, ADR-0172). Returns the
/// guard and `true`, without waiting, when the wait would close a live
/// wait-for cycle; the caller then takes its refused-wait result.
///
/// `waiters` counts the threads that wait on this guard's state, so a releaser
/// with no waiter skips the graph. The releasing owner removes the edge before
/// it wakes the waiter; the waiter removes any edge that a wake for another
/// reason left, and records its wait again if it must still wait.
pub(crate) fn wait_for_owner<'a, T>(
    mutex: &'a Mutex<T>,
    condition: &Condvar,
    mut guard: MutexGuard<'a, T>,
    waiters: fn(&mut T) -> &mut usize,
    resource: Resource,
    owner: ThreadId,
) -> (MutexGuard<'a, T>, bool) {
    let current = thread::current().id();
    let graph = waits();
    if !graph.try_begin_wait_for(resource, owner, current) {
        return (guard, true);
    }
    *waiters(&mut guard) += 1;
    guard = wait(condition, guard);
    #[cfg(test)]
    if wake_hold::armed(current) {
        drop(guard);
        wake_hold::run(current);
        guard = lock(mutex);
    }
    #[cfg(not(test))]
    let _ = mutex;
    *waiters(&mut guard) -= 1;
    graph.end_wait(current);
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

/// Stores `value` behind `mutex` and drops the previous value only after the
/// guard is released, so a user `Drop` that re-enters the owner cannot
/// deadlock on this mutex.
pub(crate) fn replace_locked<T>(mutex: &Mutex<T>, value: T) {
    let previous = std::mem::replace(&mut *lock(mutex), value);
    drop(previous);
}

/// Clones the value behind `mutex`.
///
/// A panicking `Clone` resumes only after the guard is released, so it
/// cannot poison the mutex.
pub(crate) fn clone_locked<T: Clone>(mutex: &Mutex<T>) -> T {
    let guard = lock(mutex);
    match catch_unwind(AssertUnwindSafe(|| T::clone(&guard))) {
        Ok(value) => value,
        Err(panic) => {
            drop(guard);
            resume_unwind(panic)
        }
    }
}

pub(crate) fn wait<'a, T>(condition: &Condvar, guard: MutexGuard<'a, T>) -> MutexGuard<'a, T> {
    #[cfg(test)]
    wait_observation::entered(condition);
    condition
        .wait(guard)
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Spawns a VMx-owned worker thread.
///
/// Library workers go through this helper so unit tests can count, on the
/// spawning thread, how many workers an operation started.
pub(crate) fn spawn_worker<F, T>(work: F) -> thread::JoinHandle<T>
where
    F: FnOnce() -> T + Send + 'static,
    T: Send + 'static,
{
    #[cfg(test)]
    worker_spawns::record();
    thread::spawn(work)
}

// Unit-test instrumentation only: counts the workers the current thread spawns.
#[cfg(test)]
pub(crate) mod worker_spawns {
    use std::cell::Cell;

    thread_local! {
        static SPAWNED: Cell<usize> = const { Cell::new(0) };
    }

    pub(super) fn record() {
        SPAWNED.with(|spawned| spawned.set(spawned.get() + 1));
    }

    /// Runs `work` and returns its result with the number of workers this
    /// thread spawned meanwhile.
    pub(crate) fn counted<R>(work: impl FnOnce() -> R) -> (R, usize) {
        let before = SPAWNED.with(Cell::get);
        let result = work();
        (result, SPAWNED.with(Cell::get) - before)
    }
}

pub(crate) fn evaluate_command_predicate(predicate: impl FnOnce() -> bool) -> bool {
    catch_unwind(AssertUnwindSafe(predicate)).unwrap_or(false)
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
/// Errors produced by VMx lifecycle, ownership, validation, and service contracts.
pub enum VmxError {
    #[error("invalid lifecycle transition from {from:?} via {operation}")]
    /// A lifecycle operation is invalid for the current status (spec/02
    /// §2.1, ADR-0203).
    ///
    /// Every illegal `construct`, `destruct`, or `reconstruct` returns this
    /// variant: from `Disposed` (also once the inline dispose cascade has
    /// started), during another transition (`from` is the transient status,
    /// LIFE-008), and from any other status that does not admit the call.
    InvalidLifecycleTransition {
        /// Status from which the operation was attempted.
        from: ConstructionStatus,
        /// Stable operation name used in the diagnostic: `"construct"`,
        /// `"destruct"`, or `"reconstruct"`.
        operation: &'static str,
    },
    #[error("viewmodel is disposed")]
    /// A non-lifecycle operation targets a disposed view model or a container
    /// whose disposal is pending. An illegal lifecycle call from `Disposed`
    /// returns [`VmxError::InvalidLifecycleTransition`] instead.
    Disposed,
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
    #[error(
        "container change failed: {original}; lifecycle compensation also failed: {compensation}"
    )]
    /// A failed add, insert, replacement or population whose lifecycle
    /// compensation also failed (spec/06 §4.2, ADR-0218). `original` is the
    /// failure that started the rollback, and `compensation` is the first
    /// compensation failure.
    ContainerRollback {
        /// The failure that started the rollback.
        original: Box<VmxError>,
        /// The first failure of the lifecycle compensation.
        compensation: Box<VmxError>,
    },
}

/// The error of a failed container change: `original`, or
/// [`VmxError::ContainerRollback`] when the compensation also failed
/// (ADR-0218 rule 1).
pub(crate) fn rollback_error(original: VmxError, compensation: Option<VmxError>) -> VmxError {
    match compensation {
        Some(compensation) => VmxError::ContainerRollback {
            original: Box::new(original),
            compensation: Box::new(compensation),
        },
        None => original,
    }
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

/// A container's child cascade: disposes its children and returns the first
/// failure. It must not hold the container or its core (#750).
pub(crate) type DisposalCascade = Box<dyn FnOnce() -> Option<FirstFailure> + Send + 'static>;

fn run_disposal_cascade(cascade: DisposalCascade) -> Option<FirstFailure> {
    catch_unwind(AssertUnwindSafe(cascade))
        .unwrap_or_else(|payload| Some(FirstFailure::Panic(payload)))
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
    /// This thread holds a current-publication lease (spec/06 §4.3 rule 5).
    /// The disposal is deferred before any wait for a foreign transaction.
    PublishingThread,
}

type DeferredDispose = Box<dyn FnOnce() -> VmxResult<()> + Send>;

struct MembershipTransactionState {
    owner: Option<ThreadId>,
    finishing_owner: Option<ThreadId>,
    deferred_dispose: Option<DeferredDispose>,
    /// One entry per active current-publication lease, by holding thread.
    /// Leases nest, so a thread can appear more than once.
    publishers: Vec<ThreadId>,
    /// Deferred disposals taken for running that have not returned yet. The
    /// deferral stays visible until the disposal admits itself.
    running_deferred: usize,
}

impl MembershipTransactionState {
    /// Takes the deferred disposal when nothing holds it back: no open or
    /// finishing transaction and no publication lease.
    fn take_runnable_deferred(&mut self) -> Option<DeferredDispose> {
        if self.owner.is_some() || self.finishing_owner.is_some() || !self.publishers.is_empty() {
            return None;
        }
        let action = self.deferred_dispose.take()?;
        self.running_deferred += 1;
        Some(action)
    }
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
                publishers: Vec::new(),
                running_deferred: 0,
            }),
            ready: Condvar::new(),
        }
    }

    /// Identifies this control in the wait-for graph.
    pub(crate) fn resource(&self) -> Resource {
        Resource::Membership(self as *const Self as usize)
    }

    fn begin(&self) {
        let mut state = lock(&self.state);
        debug_assert!(state.owner.is_none());
        debug_assert!(state.finishing_owner.is_none());
        let current = thread::current().id();
        state.owner = Some(current);
        waits().acquire(self.resource(), current);
    }

    pub(crate) fn dispose_disposition(&self) -> MembershipDisposeDisposition {
        let current = thread::current().id();
        let state = lock(&self.state);
        if state.publishers.contains(&current) {
            return MembershipDisposeDisposition::PublishingThread;
        }
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

    /// Reports a deferred disposal that is recorded or running but has not
    /// admitted itself yet (spec/06 §4.3 rule 5).
    pub(crate) fn disposal_deferred(&self) -> bool {
        let state = lock(&self.state);
        state.deferred_dispose.is_some() || state.running_deferred > 0
    }

    /// Records `action` as the deferred disposal while another thread holds
    /// a current-publication lease, and returns `None`. The last lease to end
    /// runs it. Returns `action` when no lease is active. The check and the
    /// record are one step, so a lease cannot end in between.
    pub(crate) fn defer_while_publishing<F>(&self, action: F) -> Option<F>
    where
        F: FnOnce() -> VmxResult<()> + Send + 'static,
    {
        let mut state = lock(&self.state);
        if state.publishers.is_empty() {
            return Some(action);
        }
        if state.deferred_dispose.is_none() {
            state.deferred_dispose = Some(Box::new(action));
        }
        None
    }

    /// Begins a current-publication lease on this thread (spec/06 §4.3
    /// rule 5). Callers begin it while they hold the membership gate that
    /// committed the change, so a disposal that checks under the gate sees it.
    pub(crate) fn begin_publication(self: &Arc<Self>) -> PublicationLease {
        lock(&self.state).publishers.push(thread::current().id());
        PublicationLease {
            control: Some(Arc::clone(self)),
        }
    }

    fn end_publication(&self) -> VmxResult<()> {
        let current = thread::current().id();
        let action = {
            let mut state = lock(&self.state);
            if let Some(index) = state.publishers.iter().rposition(|id| *id == current) {
                state.publishers.swap_remove(index);
            }
            state.take_runnable_deferred()
        };
        self.run_deferred(action)
    }

    fn run_deferred(&self, action: Option<DeferredDispose>) -> VmxResult<()> {
        let Some(action) = action else {
            return Ok(());
        };
        let outcome = catch_unwind(AssertUnwindSafe(action));
        lock(&self.state).running_deferred -= 1;
        match outcome {
            Ok(result) => result,
            Err(payload) => resume_unwind(payload),
        }
    }

    /// Waits until no membership transaction is active (ADR-0122), unless the
    /// wait would close a wait-for cycle (ADR-0153).
    ///
    /// Returns `action` once the transaction has ended, so the caller retries.
    /// Returns `None` when the wait would close a cycle: the transaction owner
    /// then runs `action` when its transaction ends. An owner that is already
    /// finishing is running this container's deferred disposal, so nothing
    /// more is recorded.
    pub(crate) fn wait_until_inactive_or_defer<F>(&self, action: F) -> Option<F>
    where
        F: FnOnce() -> VmxResult<()> + Send + 'static,
    {
        let current = thread::current().id();
        let graph = waits();
        let mut state = lock(&self.state);
        while state.owner.is_some() || state.finishing_owner.is_some() {
            if !graph.try_begin_wait(self.resource(), current) {
                if state.owner.is_some() && state.deferred_dispose.is_none() {
                    state.deferred_dispose = Some(Box::new(action));
                }
                return None;
            }
            state = wait(&self.ready, state);
            graph.end_wait(current);
        }
        Some(action)
    }

    fn finish(&self, active: &AtomicBool) -> VmxResult<()> {
        let current = thread::current().id();
        let action = {
            let mut state = lock(&self.state);
            state.owner = None;
            state.finishing_owner = Some(current);
            // The finishing thread holds the transaction until it clears.
            waits().acquire(self.resource(), current);
            // An active publication lease keeps the disposal deferred; the
            // last lease to end runs it (spec/06 §4.3 rule 5).
            if state.publishers.is_empty() {
                let action = state.deferred_dispose.take();
                if action.is_some() {
                    state.running_deferred += 1;
                }
                action
            } else {
                None
            }
        };
        let outcome = action.map(|action| catch_unwind(AssertUnwindSafe(action)));
        let late = {
            let mut state = lock(&self.state);
            if outcome.is_some() {
                state.running_deferred -= 1;
            }
            state.finishing_owner = None;
            waits().release(self.resource());
            // Only now may a new transaction begin, so its owner record cannot be
            // released above.
            active.store(false, Ordering::Release);
            self.ready.notify_all();
            // A lease that ended while this thread was finishing left the
            // deferred disposal for it.
            state.take_runnable_deferred()
        };
        // Run the late disposal before re-raising a panic from the first one,
        // so its deferral does not stay recorded as running.
        let late_result = self.run_deferred(late);
        let result = match outcome {
            Some(Ok(result)) => result,
            Some(Err(payload)) => resume_unwind(payload),
            None => Ok(()),
        };
        result.and(late_result)
    }
}

impl Drop for MembershipTransactionControl {
    fn drop(&mut self) {
        // A transaction that never finished must not leave its owner behind
        // for a later control at the same address.
        waits().release(self.resource());
    }
}

/// A current-publication lease (spec/06 §4.3 rule 5). While it is active,
/// a disposal of the composite is deferred. Ending the last lease runs a
/// deferred disposal when no membership transaction is open. Dropping the
/// lease without [`PublicationLease::finish`], as on a panic, ends it too.
pub(crate) struct PublicationLease {
    control: Option<Arc<MembershipTransactionControl>>,
}

impl PublicationLease {
    /// Ends the lease and returns the result of a deferred disposal that it
    /// ran.
    pub(crate) fn finish(mut self) -> VmxResult<()> {
        match self.control.take() {
            Some(control) => control.end_publication(),
            None => Ok(()),
        }
    }
}

impl Drop for PublicationLease {
    fn drop(&mut self) {
        if let Some(control) = self.control.take() {
            if thread::panicking() {
                // Never panic while unwinding: a failing deferred disposal is
                // dropped here.
                let _ = catch_unwind(AssertUnwindSafe(|| control.end_publication()));
            } else {
                let _ = control.end_publication();
            }
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

impl LifecycleOperation {
    /// The stable operation name that
    /// [`VmxError::InvalidLifecycleTransition`] carries.
    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Construct => "construct",
            Self::Destruct => "destruct",
            Self::Dispose => "dispose",
        }
    }
}

/// The lifecycle transition error for `operation` attempted from `from`
/// (spec/02 §2.1, ADR-0203).
pub(crate) fn invalid_transition(from: ConstructionStatus, operation: &'static str) -> VmxError {
    VmxError::InvalidLifecycleTransition { from, operation }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash)]
/// The order in which a [`crate::GroupVm`] or [`crate::CompositeVm`] destructs
/// and disposes its children (ADR-0161).
///
/// Construct order is never affected: construction always walks the children
/// from the first index to the last. Disposal stays depth-first in both orders:
/// every child is disposed before the container publishes `Disposed`. When a
/// construct or destruct hook of the container runs on another thread, the
/// container publishes `Disposed` first. It disposes its children after that
/// hook returns (LIFE-015).
pub enum ChildOrder {
    #[default]
    /// Destruct and dispose children from the first index to the last, as
    /// construct does. This is the default.
    Insertion,
    /// Destruct and dispose children from the last index to the first, so a
    /// later child is torn down before the earlier children it depends on.
    Reverse,
}

impl ChildOrder {
    /// Returns `children` in this destruct and dispose order.
    pub(crate) fn arrange<T>(self, mut children: Vec<T>) -> Vec<T> {
        if self == ChildOrder::Reverse {
            children.reverse();
        }
        children
    }
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
    /// Human-readable identity of the publishing owner. A `CompositeVm` or
    /// `GroupVm` message carries the container's `name()`. A plain collection
    /// or dictionary message carries its type name (ADR-0194).
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

/// One hub subscriber: its handler and the flag that admits it to delivery.
///
/// The flag is cleared, under the hub's state lock, on every path that
/// removes the subscriber from the hub, so a drain that copied the subscriber
/// list skips a subscriber detached earlier in the same delivery with one
/// atomic load instead of a lock and lookup per handler (#766).
struct SubscriberSlot<F> {
    active: AtomicBool,
    handler: F,
}

trait HubSubscriber: Send + Sync {
    /// Runs the handler unless the subscriber was removed from the hub.
    fn deliver(&self, message: &Message);

    /// Callers hold the hub's state lock.
    fn deactivate(&self);

    fn is_active(&self) -> bool;
}

impl<F> HubSubscriber for SubscriberSlot<F>
where
    F: Fn(&Message) + Send + Sync,
{
    fn deliver(&self, message: &Message) {
        if self.active.load(Ordering::Acquire) {
            (self.handler)(message);
        }
    }

    fn deactivate(&self) {
        self.active.store(false, Ordering::Release);
    }

    fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }
}

type Subscriber = Arc<dyn HubSubscriber + 'static>;

fn subscriber<F>(handler: F) -> Subscriber
where
    F: Fn(&Message) + Send + Sync + 'static,
{
    Arc::new(SubscriberSlot {
        active: AtomicBool::new(true),
        handler,
    })
}

type MessageHubCompletion = Arc<dyn Fn() + Send + Sync + 'static>;

#[derive(Clone, Default)]
/// A hot synchronous message stream with FIFO, batching, and resilient delivery.
///
/// Re-entrant sends join the active FIFO drain, subscriber panics are
/// isolated, and disposal makes the hub inert. A hub retains no message after
/// delivering it; attach a bounded [`MessageRecorder`] with
/// [`record`](Self::record) to keep accepted messages (ADR-0141).
pub struct MessageHub {
    inner: Arc<MessageHubShared>,
}

#[derive(Default)]
struct MessageHubShared {
    state: Mutex<MessageHubInner>,
    ready: Condvar,
}

/// Hub state taken out under the lock by disposal, released after it.
#[derive(Default)]
struct HubTeardown {
    completions: Vec<MessageHubCompletion>,
    released: Option<(BTreeMap<usize, Subscriber>, VecDeque<Message>)>,
}

#[derive(Default)]
struct MessageHubInner {
    next_subscription_id: usize,
    subscribers: BTreeMap<usize, Subscriber>,
    completion_subscribers: BTreeMap<usize, MessageHubCompletion>,
    recorders: BTreeMap<usize, Weak<Mutex<RecorderState>>>,
    pending: VecDeque<Message>,
    batch_owner: Option<ThreadId>,
    batch_depth: usize,
    /// Each thread with an open borrowed batch scope and its nesting depth
    /// (spec/03 §4.2). A borrower is a wait-for owner of the hub.
    borrowers: Vec<(ThreadId, usize)>,
    draining_owner: Option<ThreadId>,
    dispose_requested: bool,
    disposed: bool,
    /// Threads blocked in a recorded wait on this hub.
    waiters: usize,
}

impl MessageHubInner {
    fn is_borrower(&self, thread: ThreadId) -> bool {
        self.borrowers
            .iter()
            .any(|(borrower, _)| *borrower == thread)
    }

    fn has_borrowers(&self) -> bool {
        !self.borrowers.is_empty()
    }

    /// The one owner that a `send`, `batch` or `dispose` by `current` waits
    /// for: the batch owner, then the drainer, then a borrower other than
    /// `current` (spec/03 §4.1 rule 2). `None` once the hub is disposed or its
    /// disposal is requested: such a call is a no-op, or runs without a
    /// scope, so it never waits (spec/03 §3.3, #1224).
    fn foreign_owner(&self, current: ThreadId) -> Option<ThreadId> {
        if self.disposed || self.dispose_requested {
            return None;
        }
        self.batch_owner
            .filter(|owner| *owner != current)
            .or_else(|| self.draining_owner.filter(|owner| *owner != current))
            .or_else(|| self.foreign_borrower(current))
    }

    fn foreign_borrower(&self, current: ThreadId) -> Option<ThreadId> {
        self.borrowers
            .iter()
            .map(|(borrower, _)| *borrower)
            .find(|borrower| *borrower != current)
    }

    fn waiters(&mut self) -> &mut usize {
        &mut self.waiters
    }

    /// Opens one more borrowed scope for `current`.
    fn enter_borrow(&mut self, current: ThreadId) {
        match self
            .borrowers
            .iter_mut()
            .find(|(borrower, _)| *borrower == current)
        {
            Some((_, depth)) => *depth += 1,
            None => self.borrowers.push((current, 1)),
        }
    }

    /// Closes one borrowed scope of `current`. Returns whether `current`
    /// left its last borrowed scope.
    fn exit_borrow(&mut self, current: ThreadId) -> bool {
        let index = self
            .borrowers
            .iter()
            .position(|(borrower, _)| *borrower == current)
            .expect("a borrowed scope exits on the thread that opened it");
        self.borrowers[index].1 -= 1;
        if self.borrowers[index].1 > 0 {
            return false;
        }
        self.borrowers.swap_remove(index);
        true
    }
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
    /// Creates an active hub with no subscribers or recorders.
    pub fn new() -> Self {
        Self::default()
    }

    /// Starts recording the messages this hub accepts, keeping the newest
    /// `capacity` of them.
    ///
    /// A message is recorded when the hub accepts it, before delivery, so a
    /// recorder holds messages in acceptance order: messages queued in a
    /// [`batch`](Self::batch) and re-entrant sends accepted during delivery
    /// appear in the order the hub will deliver them. Recording runs no
    /// callback and cannot change delivery. When the recorder is full, the
    /// oldest message is evicted and counted by
    /// [`dropped`](MessageRecorder::dropped). A recorder made on a disposed hub
    /// is inactive and records nothing.
    ///
    /// ```
    /// use vmx::{Message, MessageHub};
    ///
    /// let hub = MessageHub::new();
    /// let recorder = hub.record(2);
    /// for name in ["first", "second", "third"] {
    ///     hub.send(Message::Custom {
    ///         sender_id: 1,
    ///         sender_name: "demo".into(),
    ///         name: name.into(),
    ///     });
    /// }
    ///
    /// let names: Vec<String> = recorder
    ///     .messages()
    ///     .into_iter()
    ///     .map(|message| match message {
    ///         Message::Custom { name, .. } => name,
    ///         _ => unreachable!(),
    ///     })
    ///     .collect();
    /// assert_eq!(names, ["second", "third"]);
    /// assert_eq!(recorder.dropped(), 1);
    /// ```
    pub fn record(&self, capacity: usize) -> MessageRecorder {
        let state = Arc::new(Mutex::new(RecorderState {
            capacity,
            messages: VecDeque::new(),
            dropped: 0,
            active: false,
        }));
        let mut inner = lock(&self.inner.state);
        if inner.disposed || inner.dispose_requested {
            return MessageRecorder {
                id: 0,
                state,
                hub: Weak::new(),
            };
        }
        inner.next_subscription_id += 1;
        let id = inner.next_subscription_id;
        lock(&state).active = true;
        inner.recorders.insert(id, Arc::downgrade(&state));
        MessageRecorder {
            id,
            state,
            hub: Arc::downgrade(&self.inner),
        }
    }

    fn accept(inner: &mut MessageHubInner, message: Message) {
        if !inner.recorders.is_empty() {
            inner
                .recorders
                .retain(|_, recorder| match recorder.upgrade() {
                    Some(recorder) => {
                        lock(&recorder).push(&message);
                        true
                    }
                    None => false,
                });
        }
        inner.pending.push_back(message);
    }

    /// Identity of this hub's shared state. It stays unique while any handle
    /// or subscription keeps that state allocated.
    pub(crate) fn identity(&self) -> usize {
        Arc::as_ptr(&self.inner) as usize
    }

    /// Reports whether a `ConstructionStatusChanged` message of `sender_id`
    /// with `status` is queued for delivery on this hub.
    pub(crate) fn has_pending_status(&self, sender_id: usize, status: ConstructionStatus) -> bool {
        lock(&self.inner.state).pending.iter().any(|message| {
            matches!(
                message,
                Message::ConstructionStatusChanged(change)
                    if change.sender_id == sender_id && change.status == status
            )
        })
    }

    pub(crate) fn is_delivering_from(&self, sender_id: usize) -> bool {
        let hub_id = self.identity();
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
        inner.subscribers.insert(id, subscriber(handler));
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
        inner.subscribers.insert(id, subscriber(handler));
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
        let mut inner = self.wait_to_publish(current);
        if inner.disposed || inner.dispose_requested {
            return;
        }
        Self::accept(&mut inner, message);
        if inner.batch_owner.is_some() || inner.has_borrowers() || inner.draining_owner.is_some() {
            return;
        }
        inner.draining_owner = Some(current);
        drop(inner);
        self.drain(current);
    }

    /// Waits until `current` may publish: no other thread holds the hub's
    /// batch, drain or a borrowed scope. A borrower's own send does not wait,
    /// and it enqueues for the drain at the last borrowed scope's exit. A wait
    /// that would close a wait-for cycle is refused, and the send enqueues for
    /// the active owner (spec/03 §4, §4.2, ADR-0119, ADR-0172). A send to a
    /// disposed hub, or to one whose disposal is requested, is a no-op, so it
    /// never waits (spec/03 §3.3, #1224).
    fn wait_to_publish(&self, current: ThreadId) -> MutexGuard<'_, MessageHubInner> {
        let mut inner = lock(&self.inner.state);
        if inner.is_borrower(current) {
            return inner;
        }
        while let Some(owner) = inner.foreign_owner(current) {
            let refused;
            (inner, refused) = self.wait_for(inner, owner);
            if refused {
                break;
            }
        }
        inner
    }

    /// Waits on this hub for `owner`, recording the wait in the wait-for graph.
    fn wait_for<'a>(
        &'a self,
        inner: MutexGuard<'a, MessageHubInner>,
        owner: ThreadId,
    ) -> (MutexGuard<'a, MessageHubInner>, bool) {
        wait_for_owner(
            &self.inner.state,
            &self.inner.ready,
            inner,
            MessageHubInner::waiters,
            Resource::MessageHub(self.identity()),
            owner,
        )
    }

    /// Wakes this hub's waiters. Edges that name a thread no longer holding the
    /// hub's batch, drain or a borrowed scope are removed first, so a woken
    /// waiter's stale edge cannot close a cycle (spec/03 §4.1 rule 4).
    /// Once the hub is disposed or its disposal is requested, every edge
    /// goes: no waiter waits for it again.
    fn wake(&self, inner: &mut MessageHubInner) {
        if inner.waiters > 0 {
            let holders = if inner.disposed || inner.dispose_requested {
                Vec::new()
            } else {
                inner
                    .batch_owner
                    .into_iter()
                    .chain(inner.draining_owner)
                    .chain(inner.borrowers.iter().map(|(borrower, _)| *borrower))
                    .collect::<Vec<_>>()
            };
            waits().release_waiters(Resource::MessageHub(self.identity()), &holders);
        }
        self.inner.ready.notify_all();
    }

    pub(crate) fn send_prepared<R, F>(&self, prepare: F) -> R
    where
        F: FnOnce() -> (R, Option<Message>),
    {
        let current = thread::current().id();
        let mut inner = self.wait_to_publish(current);

        let (result, message) = prepare();
        if let Some(message) = message.filter(|_| !inner.disposed && !inner.dispose_requested) {
            Self::accept(&mut inner, message);
        }
        let should_drain = !inner.pending.is_empty()
            && inner.batch_owner.is_none()
            && !inner.has_borrowers()
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
        // A borrower nests another borrowed scope without waiting (spec/03
        // §4.2 rule 3). Every other batch, the batch owner's nested batch
        // too, waits for a foreign owner, and a borrowed scope is one; a
        // refused wait borrows (§4.1, #1223).
        let borrowed = if inner.is_borrower(current) {
            true
        } else {
            loop {
                let Some(owner) = inner.foreign_owner(current) else {
                    break false;
                };
                let refused;
                (inner, refused) = self.wait_for(inner, owner);
                if refused {
                    break true;
                }
            }
        };
        // A batch on a disposed hub, or on one whose disposal is requested,
        // runs its body without a scope: it owns nothing that another call
        // could wait for, and its sends are no-ops (spec/03 §3.3, #1224).
        if inner.disposed || inner.dispose_requested {
            drop(inner);
            return transaction();
        }
        // The scope opens under the lock that decided it.
        if borrowed {
            inner.enter_borrow(current);
        } else if inner.batch_owner == Some(current) {
            inner.batch_depth += 1;
        } else {
            inner.batch_owner = Some(current);
            inner.batch_depth = 1;
        }
        drop(inner);
        self.run_scope(current, borrowed, transaction)
    }

    /// Runs `transaction` in the scope that the caller opened, an owned batch
    /// or, when `borrowed`, a borrowed scope, then closes it: the outermost
    /// exit finishes a requested disposal and drains the queue when no other
    /// thread holds the hub.
    fn run_scope<F, R>(&self, current: ThreadId, borrowed: bool, transaction: F) -> R
    where
        F: FnOnce() -> R,
    {
        let callback_result = catch_unwind(AssertUnwindSafe(transaction));
        let mut inner = lock(&self.inner.state);
        let (outermost, released) = if borrowed {
            let left = inner.exit_borrow(current);
            (!inner.has_borrowers(), left)
        } else {
            inner.batch_depth -= 1;
            let outermost = inner.batch_depth == 0;
            if outermost {
                inner.batch_owner = None;
            }
            (outermost, outermost)
        };
        // The last of the batch owner, the drainer and the borrowers to
        // release the hub finishes a requested disposal. A drain that is
        // still delivering finishes it at its end (spec/03 §4.2 rule 3).
        let completions = if outermost
            && inner.dispose_requested
            && inner.batch_owner.is_none()
            && !inner.has_borrowers()
            && inner.draining_owner.is_none()
        {
            Self::finish_dispose(&mut inner)
        } else {
            HubTeardown::default()
        };
        let should_drain = outermost
            && !inner.disposed
            && !inner.pending.is_empty()
            && inner.batch_owner.is_none()
            && !inner.has_borrowers()
            && inner.draining_owner.is_none();
        if should_drain {
            inner.draining_owner = Some(current);
        }
        // A borrower that leaves its last scope while others remain also wakes
        // the waiters (spec/03 §4.1 rule 4).
        if released {
            self.wake(&mut inner);
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

    fn finish_dispose(inner: &mut MessageHubInner) -> HubTeardown {
        // Subscriber closures and queued messages may own other subscriptions
        // on this hub, whose Drop re-enters this hub's lock: hand them to the
        // caller to drop after the lock is released.
        let subscribers = std::mem::take(&mut inner.subscribers);
        for subscriber in subscribers.values() {
            subscriber.deactivate();
        }
        let pending = std::mem::take(&mut inner.pending);
        for recorder in std::mem::take(&mut inner.recorders).into_values() {
            if let Some(recorder) = recorder.upgrade() {
                lock(&recorder).active = false;
            }
        }
        inner.dispose_requested = false;
        inner.disposed = true;
        HubTeardown {
            completions: std::mem::take(&mut inner.completion_subscribers)
                .into_values()
                .collect(),
            released: Some((subscribers, pending)),
        }
    }

    /// Drops the released subscribers and messages, then runs completions.
    /// Callers invoke this only after releasing the hub's state lock.
    fn notify_completions(teardown: HubTeardown) {
        let HubTeardown {
            completions,
            released,
        } = teardown;
        drop(released);
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
            // A borrowed scope defers delivery. With an empty queue, the drain
            // is released, and the last borrowed scope's exit drains what the
            // bodies enqueue (spec/03 §4.2 rule 2). With queued messages, the
            // drainer waits for the borrowers; when that wait would close a
            // cycle, it releases the drain to the last borrowed scope's exit,
            // which delivers the queue in FIFO order (§4.2 rule 5). Once a
            // disposal is requested, the drainer stops waiting and leaves the
            // disposal to the last borrowed scope's exit (§4.2 rule 3).
            while let Some(borrower) = inner.foreign_borrower(current) {
                let release = inner.pending.is_empty() || inner.dispose_requested || {
                    let refused;
                    (inner, refused) = self.wait_for(inner, borrower);
                    refused
                };
                if release {
                    inner.draining_owner = None;
                    self.wake(&mut inner);
                    return;
                }
            }
            let completions = if inner.dispose_requested {
                Self::finish_dispose(&mut inner)
            } else {
                HubTeardown::default()
            };
            if inner.disposed || inner.pending.is_empty() {
                inner.draining_owner = None;
                self.wake(&mut inner);
                drop(inner);
                Self::notify_completions(completions);
                return;
            }
            debug_assert_eq!(inner.draining_owner, Some(current));
            let message = inner.pending.pop_front().expect("queue checked non-empty");
            let subscribers = inner
                .subscribers
                .values()
                .map(Arc::clone)
                .collect::<Vec<_>>();
            drop(inner);
            Self::notify_completions(completions);

            #[cfg(debug_assertions)]
            message_types.insert(message.type_name());
            // A subscriber detached by an earlier handler of this same message
            // is skipped inside `deliver`; a handler that detaches itself
            // still finishes the message it is handling. Only handlers run
            // inside the delivery guard. The copy may hold the last reference
            // to a detached handler, so the guard is left while that copy
            // drops: the handler drops after its own turn, as before (#766).
            {
                let hub_id = Arc::as_ptr(&self.inner) as usize;
                let sender_id = message.sender_id();
                let mut delivery = Some(MessageHubDeliveryGuard::enter(hub_id, sender_id));
                for subscriber in subscribers {
                    let _ = catch_unwind(AssertUnwindSafe(|| subscriber.deliver(&message)));
                    if !subscriber.is_active() {
                        drop(delivery.take());
                        drop(subscriber);
                        delivery = Some(MessageHubDeliveryGuard::enter(hub_id, sender_id));
                    }
                }
                drop(delivery);
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
                        self.wake(&mut inner);
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

    /// Returns an empty list: a hub no longer retains accepted messages.
    ///
    /// Attach a [`MessageRecorder`] with [`record`](Self::record) before the
    /// sends to observe, and read [`MessageRecorder::messages`] (ADR-0141).
    #[deprecated(
        since = "0.31.0",
        note = "a hub no longer retains messages, so this is always empty; record with `record(capacity)`"
    )]
    pub fn history(&self) -> Vec<Message> {
        Vec::new()
    }

    /// Removes subscribers and pending messages and makes future sends inert.
    pub fn dispose(&self) {
        let current = thread::current().id();
        let mut inner = lock(&self.inner.state);
        // A disposed hub, or one whose disposal is already requested, needs
        // nothing more, so the call returns without a wait (#1224).
        if inner.disposed || inner.dispose_requested {
            return;
        }
        // The drainer and a borrower record terminal intent: the drain or the
        // last borrowed scope's exit finishes the disposal (spec/03 §4.2
        // rule 3).
        if inner.draining_owner == Some(current) || inner.is_borrower(current) {
            inner.dispose_requested = true;
            self.wake(&mut inner);
            return;
        }
        while let Some(owner) = inner.foreign_owner(current) {
            let refused;
            (inner, refused) = self.wait_for(inner, owner);
            if refused {
                inner.dispose_requested = true;
                self.wake(&mut inner);
                return;
            }
        }
        // Another thread disposed the hub, or requested its disposal, while
        // this call waited.
        if inner.disposed || inner.dispose_requested {
            return;
        }
        let completions = Self::finish_dispose(&mut inner);
        self.wake(&mut inner);
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

struct RecorderState {
    capacity: usize,
    messages: VecDeque<Message>,
    dropped: u64,
    active: bool,
}

impl RecorderState {
    fn push(&mut self, message: &Message) {
        if !self.active {
            return;
        }
        if self.capacity == 0 {
            self.dropped += 1;
            return;
        }
        if self.messages.len() == self.capacity {
            self.messages.pop_front();
            self.dropped += 1;
        }
        self.messages.push_back(message.clone());
    }
}

/// A bounded record of the messages a [`MessageHub`] accepts, made by
/// [`MessageHub::record`].
///
/// The recorder owns its messages, and the hub refers to it only weakly, so a
/// recorder never keeps its hub alive and dropping it frees what it recorded.
/// Dropping the recorder or calling [`dispose`](Self::dispose) stops
/// recording. When the hub is disposed, the recorder keeps the messages it
/// already recorded and records nothing more.
pub struct MessageRecorder {
    id: usize,
    state: Arc<Mutex<RecorderState>>,
    hub: Weak<MessageHubShared>,
}

impl MessageRecorder {
    /// Returns the retained messages, oldest first.
    pub fn messages(&self) -> Vec<Message> {
        lock(&self.state).messages.iter().cloned().collect()
    }

    /// Returns the number of retained messages, at most
    /// [`capacity`](Self::capacity).
    pub fn len(&self) -> usize {
        lock(&self.state).messages.len()
    }

    /// Reports whether no message is retained.
    pub fn is_empty(&self) -> bool {
        lock(&self.state).messages.is_empty()
    }

    /// Returns the maximum number of retained messages.
    pub fn capacity(&self) -> usize {
        lock(&self.state).capacity
    }

    /// Returns how many accepted messages were evicted, or never stored
    /// because the capacity is zero, while recording.
    pub fn dropped(&self) -> u64 {
        lock(&self.state).dropped
    }

    /// Removes the retained messages. The [`dropped`](Self::dropped) count is
    /// unchanged, and recording continues.
    pub fn clear(&self) {
        lock(&self.state).messages.clear();
    }

    /// Reports whether the recorder still records accepted messages: it has
    /// not been disposed, and its hub is alive and not disposed.
    pub fn is_active(&self) -> bool {
        lock(&self.state).active && self.hub.strong_count() > 0
    }

    /// Stops recording and detaches from the hub; repeated calls are inert.
    /// The retained messages stay readable.
    pub fn dispose(&self) {
        lock(&self.state).active = false;
        if let Some(hub) = self.hub.upgrade() {
            let removed = lock(&hub.state).recorders.remove(&self.id);
            drop(removed);
        }
    }
}

impl Drop for MessageRecorder {
    fn drop(&mut self) {
        self.dispose();
    }
}

impl std::fmt::Debug for MessageRecorder {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let state = lock(&self.state);
        formatter
            .debug_struct("MessageRecorder")
            .field("capacity", &state.capacity)
            .field("len", &state.messages.len())
            .field("dropped", &state.dropped)
            .field("active", &state.active)
            .finish()
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
            // The removed closures may own other subscriptions on this hub;
            // drop them only after the hub's lock is released.
            let removed = {
                let mut state = lock(&hub.state);
                let subscriber = state.subscribers.remove(&self.id);
                if let Some(subscriber) = &subscriber {
                    subscriber.deactivate();
                }
                (subscriber, state.completion_subscribers.remove(&self.id))
            };
            drop(removed);
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

    /// Returns the number of live change handlers on this stream, so a test
    /// can detect a subscription that was never released (#1300).
    ///
    /// Production code never calls it. Only the non-default `test-seams`
    /// feature exports it.
    #[cfg(feature = "test-seams")]
    #[doc(hidden)]
    pub fn subscriber_count_for_testing(&self) -> usize {
        lock(&self.inner).subscribers.len()
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

    /// Sends `property_name` to the current subscribers unless the stream is
    /// disposed. Subscriber panics are isolated.
    pub(crate) fn notify(&self, property_name: &str) {
        if !self.begin_notification() {
            return;
        }
        self.send_admitted(property_name);
        self.end_notification();
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
        let released = {
            let mut inner = lock(&self.inner);
            inner.active_notifications -= 1;
            if inner.active_notifications == 0 && inner.teardown_pending {
                inner.teardown_pending = false;
                std::mem::take(&mut inner.subscribers)
            } else {
                BTreeMap::new()
            }
        };
        drop(released);
    }

    fn dispose(&self) {
        let (completions, released) = {
            let mut inner = lock(&self.inner);
            if inner.disposed {
                return;
            }
            inner.disposed = true;
            let completions = std::mem::take(&mut inner.completion_subscribers)
                .into_values()
                .collect::<Vec<_>>();
            let released = if inner.active_notifications == 0 {
                std::mem::take(&mut inner.subscribers)
            } else {
                inner.teardown_pending = true;
                BTreeMap::new()
            };
            (completions, released)
        };
        drop(released);
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
            let removed = {
                let mut stream = lock(&stream);
                (
                    stream.subscribers.remove(&self.id),
                    stream.completion_subscribers.remove(&self.id),
                )
            };
            drop(removed);
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

    /// Runs queued foreground actions in FIFO order. The queue lock is
    /// released before each action runs, so an action may dispatch to the
    /// same queue (#746).
    pub fn drain_foreground(&self) {
        loop {
            let next = lock(&self.foreground).pop_front();
            let Some(action) = next else { break };
            action();
        }
    }

    /// Runs queued background actions in FIFO order. The queue lock is
    /// released before each action runs, as in
    /// [`drain_foreground`](Self::drain_foreground).
    pub fn drain_background(&self) {
        loop {
            let next = lock(&self.background).pop_front();
            let Some(action) = next else { break };
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
    child_disposed: ParentSelectionAction,
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

    /// The owner's registration while the owner is alive. A stored command
    /// keeps only this weak handle, so it does not keep a dropped container
    /// registered as its children's parent.
    pub(crate) fn registration(&self) -> Option<ParentRegistration> {
        self.inner
            .upgrade()
            .map(|inner| ParentRegistration { inner })
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

    /// The dispose clear (spec/06 §4.3 rule 9, ADR-0189): a child that
    /// published `Disposed` from its own `dispose()` reports it, and a
    /// selectable owner clears `current` while that child is still current.
    /// An owner without child selection, or one already dropped, does
    /// nothing.
    pub(crate) fn child_disposed(&self, child_id: usize) -> VmxResult<()> {
        let Some(inner) = self.inner.upgrade() else {
            return Ok(());
        };
        inner
            .selection
            .as_ref()
            .map_or(Ok(()), |selection| (selection.child_disposed)(child_id))
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

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new_selectable(
        id: usize,
        parent: impl Fn() -> Option<ParentHandle> + Send + Sync + 'static,
        contains: impl Fn(usize) -> bool + Send + Sync + 'static,
        detach: impl Fn(usize, ParentHandle) -> VmxResult<ParentTransfer> + Send + Sync + 'static,
        is_current: impl Fn(usize) -> bool + Send + Sync + 'static,
        select: impl Fn(usize) -> VmxResult<()> + Send + Sync + 'static,
        deselect: impl Fn(usize) -> VmxResult<()> + Send + Sync + 'static,
        child_disposed: impl Fn(usize) -> VmxResult<()> + Send + Sync + 'static,
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
                    child_disposed: Arc::new(child_disposed),
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

/// Reports whether an ownership transaction holds `child_id` now. The check
/// never waits for that transaction.
pub(crate) fn ownership_claim_active(child_id: usize) -> bool {
    lock(active_ownership_claims()).contains(&child_id)
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

/// Reports whether a child is still a member of the container whose
/// construct walk asks, read under that container's membership gate
/// (spec/06 §5.1, ADR-0186).
type MemberCheck = Arc<dyn Fn(usize) -> bool + Send + Sync>;

/// The settle result of a child a construct walk joined. A child that is no
/// longer a member settles without effect on the container (ADR-0186).
fn walk_child_result<N: VmNode>(
    child: &N,
    expected: ConstructionStatus,
    member: Option<&MemberCheck>,
) -> VmxResult<()> {
    if member.is_some_and(|member| !member(child.id())) {
        return Ok(());
    }
    child_settled_result(child, expected)
}

/// A child that settled at the expected status, or that is `Disposed`, ends
/// the wait as a success (spec/02 §6, ADR-0189).
fn child_settled_result<N: VmNode>(child: &N, expected: ConstructionStatus) -> VmxResult<()> {
    let status = child.status();
    if status == expected || status == ConstructionStatus::Disposed {
        return Ok(());
    }
    Err(VmxError::Other(format!(
        "child {} settled at {status:?} instead of {expected:?}",
        child.id()
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
    /// Commits the container-owned current flag without publishing it, and
    /// reports whether [`VmNode::publish_current_flag`] must run.
    ///
    /// A container commits the flag under its membership gate, so two
    /// selections that commit in turn leave the flags in commit order
    /// (spec/06 §4.3). It publishes after releasing the gate. Built-in view
    /// models commit silently here and return whether the flag changed;
    /// wrapper nodes should forward both methods. The default commits nothing
    /// and returns `true`, so `publish_current_flag` sets the flag through
    /// [`VmNode::set_current_flag`].
    #[doc(hidden)]
    fn commit_current_flag(&self, _is_current: bool) -> bool {
        true
    }
    /// Publishes a flag that [`VmNode::commit_current_flag`] committed. The
    /// default calls [`VmNode::set_current_flag`].
    #[doc(hidden)]
    fn publish_current_flag(&self, is_current: bool) {
        self.set_current_flag(is_current);
    }
    /// Reports whether the node is current in its container.
    fn is_current(&self) -> bool {
        false
    }
    /// Registers `callback` to run once the node's in-flight construct or
    /// destruct settles and its terminal status is published. Returns `false`
    /// (dropping `callback`) when no transition is in flight.
    ///
    /// Containers use this hook to stay transient until a background child
    /// settles (spec/02 §6). Wrapper nodes should forward it to the wrapped
    /// VM. The default returns `false`. A container then falls back to its
    /// own message hub (spec/11 §4, ADR-0205): when it started the node and,
    /// by the time the start call returned, the hub delivered or queued the
    /// node's Constructing/Destructing status, it waits on that hub for a
    /// status of the node that arrives once the node is no longer in flight,
    /// and rolls back when the node settles anywhere else. Otherwise (the
    /// node publishes on another hub, or the container joined a node
    /// already in flight) it accepts the node while it is still
    /// Constructing/Destructing instead of waiting for it.
    fn when_lifecycle_settled(&self, _callback: LifecycleSettleCallback) -> bool {
        false
    }
    /// Reports whether the node's Constructed state is committed but its
    /// publication has not started yet (a container's sealed construct walk,
    /// spec/06 §5.1). The lifecycle predicates are false meanwhile, so they
    /// agree with the operations, which still see a transition in flight.
    /// Wrapper nodes should forward it. The default returns `false`.
    #[doc(hidden)]
    fn lifecycle_publication_pending(&self) -> bool {
        false
    }
    /// Returns the stream on which the node reports a failed fire-and-forget
    /// background hook. A failed deferred compensation destruct of the node
    /// goes there too (spec/06 §4.2, ADR-0218 rule 7). Wrapper nodes should
    /// forward it. The default returns `None`, and that failure is dropped.
    #[doc(hidden)]
    fn background_failure_stream(&self) -> Option<LifecycleErrorStream> {
        None
    }
}

/// Continuation run after a node's in-flight lifecycle transition settles.
pub type LifecycleSettleCallback = Box<dyn FnOnce() + Send + 'static>;

/// A child wait's settle callback is being registered.
const WAIT_REGISTERING: u8 = 0;
/// The settle callback ran while it was being registered: the wait ended at
/// once (ADR-0218 rule 3).
const WAIT_ENDED_AT_ONCE: u8 = 1;
/// The registration returned before the settle callback ran.
const WAIT_PENDING: u8 = 2;

type ChildStep = Box<dyn FnOnce() -> VmxResult<()> + Send + 'static>;

/// The step a construct walk runs once every member joined (for example a
/// composite's selector). It receives the container core, so it need not
/// capture one: a captured core would keep a waiting container alive (#750).
pub(crate) type WalkThen<D> = Box<dyn FnOnce(&ComponentCore<D>) -> VmxResult<()> + Send + 'static>;

/// Reports whether the child a container waits on settled at the expected
/// status. The container keeps it, so the settle callback the child holds
/// does not hold the child itself (#750).
type AwaitedChild = Box<dyn FnOnce() -> VmxResult<()> + Send + 'static>;

struct StartRecordState {
    done: bool,
    waiter: Option<LifecycleSettleCallback>,
}

/// An add's attempt to auto-start the child it attached while its container
/// was Constructing (spec/06 §5.1). The construct walk never starts a late
/// child: it waits until the attempt is done, then joins the child.
pub(crate) struct StartRecord {
    state: Mutex<StartRecordState>,
}

impl StartRecord {
    fn new() -> Self {
        Self {
            state: Mutex::new(StartRecordState {
                done: false,
                waiter: None,
            }),
        }
    }

    /// Registers `callback` to run once the attempt is done. Returns `false`
    /// (dropping `callback`) when it already is.
    fn when_done(&self, callback: LifecycleSettleCallback) -> bool {
        let mut state = lock(&self.state);
        if state.done {
            return false;
        }
        state.waiter = Some(callback);
        true
    }

    /// Marks the attempt done and returns the walk continuation waiting on it.
    fn finish(&self) -> Option<LifecycleSettleCallback> {
        let mut state = lock(&self.state);
        state.done = true;
        state.waiter.take()
    }
}

type StartRecords = HashMap<usize, Arc<StartRecord>>;

/// The start records of one construct walk (spec/06 §5.1). Only that walk
/// takes them, and they drop with it, so a stale walk (failed, abandoned, or
/// superseded by a later construct) never takes or clears another walk's
/// records.
pub(crate) struct WalkScope {
    records: Mutex<StartRecords>,
}

impl WalkScope {
    fn take(&self, child_id: usize) -> Option<Arc<StartRecord>> {
        lock(&self.records).remove(&child_id)
    }

    fn forget(&self, child_id: usize, record: &Arc<StartRecord>) {
        let mut records = lock(&self.records);
        if records
            .get(&child_id)
            .is_some_and(|registered| Arc::ptr_eq(registered, record))
        {
            records.remove(&child_id);
        }
    }
}

/// A container's start records (spec/06 §5.1). An add registers one, under
/// the membership gate that attaches the child, only when it will auto-start
/// the child: auto-construct-on-add is on and the container is Constructing.
/// The record goes into the scope of the walk that is current then. That
/// walk takes the record of each late member, under the same gate: without
/// one, no add tried to start the member, so the walk skips it; with one, the
/// walk waits until the attempt is done and then joins the member. A failed
/// attempt ends only after its add undid the attach, so the walk ignores that
/// child (ADR-0186).
#[derive(Clone)]
pub(crate) struct LateStarts {
    /// The container's membership gate.
    gate: Arc<Mutex<()>>,
    /// The scope of the walk that still scans for late members, if any.
    current: Arc<Mutex<Option<Arc<WalkScope>>>>,
    /// Test-only seam: runs after a walk's last late scan, outside the gate.
    /// Only the `test-seams` feature compiles it.
    #[cfg(feature = "test-seams")]
    last_scan_probe: Arc<Mutex<Option<LastScanProbe>>>,
    /// Test-only seam: runs after a walk's commit step wrote Constructed and
    /// before the publication, outside the gate. Only the `test-seams`
    /// feature compiles it.
    #[cfg(feature = "test-seams")]
    seal_probe: Arc<Mutex<Option<LastScanProbe>>>,
}

/// A test-only callback a construct walk runs at one of its seams.
#[cfg(feature = "test-seams")]
type LastScanProbe = Arc<dyn Fn() + Send + Sync>;

impl LateStarts {
    /// Start records guarded by the container's membership `gate`.
    pub(crate) fn new(gate: Arc<Mutex<()>>) -> Self {
        Self {
            gate,
            current: Arc::default(),
            #[cfg(feature = "test-seams")]
            last_scan_probe: Arc::default(),
            #[cfg(feature = "test-seams")]
            seal_probe: Arc::default(),
        }
    }

    /// Test-only seam: sets the callback a construct walk runs after its last
    /// late scan, outside the membership gate. Production code never sets it.
    #[cfg(feature = "test-seams")]
    pub(crate) fn set_last_scan_probe(&self, probe: LastScanProbe) {
        *lock(&self.last_scan_probe) = Some(probe);
    }

    /// Runs the test-only probe, if one is set. Without the `test-seams`
    /// feature it does nothing, so a default build takes no lock here.
    fn run_last_scan_probe(&self) {
        #[cfg(feature = "test-seams")]
        {
            let probe = lock(&self.last_scan_probe).clone();
            if let Some(probe) = probe {
                probe();
            }
        }
    }

    /// Test-only seam: sets the callback a construct walk runs after its
    /// commit step and before the publication, outside the membership gate
    /// (spec/02 §2.4, ADR-0186). Production code never sets it.
    #[cfg(feature = "test-seams")]
    pub(crate) fn set_seal_probe(&self, probe: LastScanProbe) {
        *lock(&self.seal_probe) = Some(probe);
    }

    /// Runs the test-only seal probe, if one is set. Without the
    /// `test-seams` feature it does nothing, so a default build takes no
    /// lock here.
    fn run_seal_probe(&self) {
        #[cfg(feature = "test-seams")]
        {
            let probe = lock(&self.seal_probe).clone();
            if let Some(probe) = probe {
                probe();
            }
        }
    }

    /// Records the attach of `child_id`; call it under the membership gate
    /// that attaches the child. With `will_start` it returns the add's
    /// attempt, registered in the current walk's scope if a walk still scans;
    /// otherwise it drops any record of the child from that scope.
    pub(crate) fn attach(&self, child_id: usize, will_start: bool) -> Option<StartAttempt> {
        let scope = lock(&self.current).clone();
        if !will_start {
            if let Some(scope) = scope {
                lock(&scope.records).remove(&child_id);
            }
            return None;
        }
        let record = Arc::new(StartRecord::new());
        if let Some(scope) = &scope {
            lock(&scope.records).insert(child_id, Arc::clone(&record));
        }
        Some(StartAttempt {
            scope,
            child_id,
            record,
            finished: false,
        })
    }

    /// Opens the scope of a new walk; an older walk's scope is orphaned.
    fn begin_walk(&self, generation: u64) -> LateWalk {
        let scope = Arc::new(WalkScope {
            records: Mutex::default(),
        });
        *lock(&self.current) = Some(Arc::clone(&scope));
        LateWalk {
            starts: self.clone(),
            scope,
            generation,
        }
    }
}

/// The next unvisited member with a start record in `walk`'s scope, taking
/// that record; a member without one was not started by an add (for example,
/// auto-construct-on-add was off), so it is skipped. Call it under the
/// container's membership gate.
fn next_late_member<N: VmNode>(
    visited: &mut HashSet<usize>,
    members: &Arc<dyn Fn() -> Vec<N> + Send + Sync>,
    walk: &LateWalk,
) -> Option<(N, Arc<StartRecord>)> {
    loop {
        let child = members()
            .into_iter()
            .find(|child| !visited.contains(&child.id()))?;
        visited.insert(child.id());
        if let Some(record) = walk.scope.take(child.id()) {
            return Some((child, record));
        }
    }
}

/// One construct walk's hold on its scope. Ending it (at the walk's final
/// late scan, or when the walk's steps drop because it failed or was
/// abandoned) retires only this walk's scope.
struct LateWalk {
    starts: LateStarts,
    scope: Arc<WalkScope>,
    /// The container transition this walk belongs to.
    generation: u64,
}

impl LateWalk {
    fn end(&self) {
        {
            let mut current = lock(&self.starts.current);
            if current
                .as_ref()
                .is_some_and(|scope| Arc::ptr_eq(scope, &self.scope))
            {
                *current = None;
            }
        }
        lock(&self.scope.records).clear();
    }
}

impl Drop for LateWalk {
    fn drop(&mut self) {
        self.end();
    }
}

/// Constructs `child` for an add or a walk that read it `Destructed`. When
/// another starter began its construct after that read, the call fails as an
/// invalid transition; the construct is then left to that starter and this
/// returns `Ok(())` (ADR-0218 rule 6).
fn start_unless_started<N: VmNode>(child: &N) -> VmxResult<()> {
    match child.construct() {
        Err(VmxError::InvalidLifecycleTransition { .. }) if construct_started(child) => Ok(()),
        result => result,
    }
}

/// Whether a destruct of `child` is in flight or done: it is Destructing or
/// Destructed (ADR-0228). A destruct refused while the child is in either
/// state was started by another thread.
fn destruct_started<N: VmNode>(child: &N) -> bool {
    matches!(
        child.status(),
        ConstructionStatus::Destructing | ConstructionStatus::Destructed
    )
}

/// Whether a construct of `child` is in flight or done: it is Constructing,
/// publishing a sealed construct, or Constructed.
fn construct_started<N: VmNode>(child: &N) -> bool {
    matches!(
        child.status(),
        ConstructionStatus::Constructing | ConstructionStatus::Constructed
    ) || child.lifecycle_publication_pending()
}

/// Compensates the auto-start of `child` after a failed container change
/// and returns the compensation failure (spec/06 §4.2, ADR-0218 rule 7).
/// Only a child that was `Destructed` before the change is compensated. A
/// `Constructed` child is destructed now. A child whose construct is still
/// in flight is not awaited: once it settles `Constructed` with no parent,
/// its `destruct()` runs. A failure of that call goes to the child's own
/// background-failure stream while that stream is open, never to the
/// container. A child that settles elsewhere, or that has a parent by then,
/// is left alone.
pub(crate) fn compensate_auto_start<N: VmNode>(
    child: &N,
    original_status: ConstructionStatus,
) -> Option<VmxError> {
    if original_status != ConstructionStatus::Destructed {
        return None;
    }
    let in_flight =
        child.status() == ConstructionStatus::Constructing || child.lifecycle_publication_pending();
    if in_flight {
        let settled = child.clone();
        if child.when_lifecycle_settled(Box::new(move || {
            if let Some(error) = destruct_if_orphaned(&settled) {
                if let Some(errors) = settled.background_failure_stream() {
                    if let Some(emission) = errors.begin_emission() {
                        errors.send(error);
                        drop(emission);
                    }
                }
            }
        })) {
            return None;
        }
    }
    (child.status() == ConstructionStatus::Constructed)
        .then(|| child.destruct().err())
        .flatten()
}

/// Destructs `child` when it is `Constructed` with no parent, and returns the
/// failure of that call.
fn destruct_if_orphaned<N: VmNode>(child: &N) -> Option<VmxError> {
    (child.status() == ConstructionStatus::Constructed && child.parent_handle().is_none())
        .then(|| child.destruct().err())
        .flatten()
}

/// An add's attempt to auto-start the child it attached; see [`LateStarts`].
pub(crate) struct StartAttempt {
    /// The walk scope the record was registered in, if a walk still scanned.
    scope: Option<Arc<WalkScope>>,
    child_id: usize,
    record: Arc<StartRecord>,
    finished: bool,
}

impl StartAttempt {
    /// Constructs `item` when it is Destructed. A construct that another
    /// starter began after the status read is left to it, without a wait
    /// (ADR-0218 rule 6). The attempt stays open: the add ends it when it
    /// drops the attempt after it ended its membership transaction, on
    /// success or after its undo (ADR-0218 rule 4). So a walk waiting on the
    /// attempt resumes outside that transaction, and after a failed add it
    /// sees a non-member (ADR-0186). A panic still marks the attempt done
    /// here.
    pub(crate) fn run<N: VmNode, D: Dispatcher>(
        &mut self,
        core: &ComponentCore<D>,
        item: &N,
    ) -> VmxResult<()> {
        let attempt = catch_unwind(AssertUnwindSafe(|| {
            if item.status() == ConstructionStatus::Destructed {
                start_unless_started(item)
            } else {
                Ok(())
            }
        }));
        if core.status() != ConstructionStatus::Constructing {
            self.forget();
        }
        match attempt {
            Ok(result) => result,
            Err(payload) => {
                self.finish();
                resume_unwind(payload)
            }
        }
    }

    /// Ends a failed add: its record no longer stands for an attached child.
    /// It only removes the record; a pending attempt still finishes when it
    /// drops, outside the caller's membership gate.
    pub(crate) fn forget(&mut self) {
        if let Some(scope) = &self.scope {
            scope.forget(self.child_id, &self.record);
        }
    }

    fn finish(&mut self) {
        self.finished = true;
        if let Some(waiter) = self.record.finish() {
            waiter();
        }
    }
}

impl Drop for StartAttempt {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        self.finished = true;
        // An attempt dropped without running (an early return) still ends,
        // so a waiting walk never hangs. While unwinding, the walk resumes on
        // its own thread, where a second panic cannot abort.
        if let Some(waiter) = self.record.finish() {
            if thread::panicking() {
                thread::spawn(waiter);
            } else {
                waiter();
            }
        }
    }
}

/// A container transition waiting for children that settle asynchronously
/// (spec/02 §6): later child steps queue behind the child being awaited, and
/// the container publishes its terminal status only after the queue drains.
/// What a container's transition does once its own action returned.
enum ChildWalkOutcome {
    /// No child step is pending; the action publishes the terminal status.
    Settled,
    /// A child step is pending; the settle continuation publishes.
    Deferred,
    /// A child failed while the action ran; the caller publishes the
    /// rollback status.
    Failed(VmxError),
}

struct ChildSettle {
    generation: u64,
    waiting: bool,
    draining: bool,
    armed: bool,
    /// A child failure that arrived while the container's own action was
    /// still running; applied once the action returns.
    failure: Option<VmxError>,
    /// Set with `failure` and kept after the action takes it, so no other
    /// settle path publishes the success status in the meantime.
    failed: bool,
    queue: VecDeque<ChildStep>,
    /// The child being waited on, checked when its settle callback runs.
    awaited: Option<AwaitedChild>,
}

impl ChildSettle {
    fn new(generation: u64) -> Self {
        Self {
            generation,
            waiting: false,
            draining: false,
            armed: false,
            failure: None,
            failed: false,
            queue: VecDeque::new(),
            awaited: None,
        }
    }

    fn busy(&self) -> bool {
        self.failed || self.waiting || self.draining || !self.queue.is_empty()
    }
}

#[derive(Default)]
struct ChildObserverState {
    /// The container's hub delivered the child's transient status.
    seen: bool,
    /// The hub delivered a later status of the child, or the hub completed.
    settled: bool,
    callback: Option<LifecycleSettleCallback>,
}

/// Watches the container's own hub for the status of a child the container
/// starts, for a node that does not forward
/// [`VmNode::when_lifecycle_settled`] (spec/11 §4, ADR-0205). It subscribes
/// before the child's start call. A container waits on the child only when,
/// by the time that call returned, the hub delivered or queued the child's
/// transient status: the child then publishes on this hub, so its next
/// status arrives here too, and the wait is bounded. The hub's completion
/// also ends the wait.
///
/// The hub can still hold statuses of the child's earlier transitions,
/// queued before the start call (a hub batch, a borrowed scope, or another
/// thread's drain). A message cannot tell which transition it belongs to,
/// so a non-transient status settles the wait only when the child itself
/// is no longer at the transient status; otherwise it is an earlier
/// transition's status and the observer ignores it.
struct ChildObserver {
    hub: MessageHub,
    child_id: usize,
    transient: ConstructionStatus,
    state: Arc<Mutex<ChildObserverState>>,
    subscription: Subscription,
}

impl ChildObserver {
    fn start<N: VmNode>(hub: MessageHub, child: &N, transient: ConstructionStatus) -> Self {
        let child_id = child.id();
        // The subscription ends when the awaited check runs or the settle is
        // dropped, so this clone does not outlive the container's wait.
        let probe = child.clone();
        let state = Arc::new(Mutex::new(ChildObserverState::default()));
        let on_message = Arc::clone(&state);
        let on_completion = Arc::clone(&state);
        let subscription = hub.subscribe_with_completion(
            move |message| {
                let Message::ConstructionStatusChanged(change) = message else {
                    return;
                };
                if change.sender_id != child_id {
                    return;
                }
                if change.status == transient {
                    lock(&on_message).seen = true;
                } else if probe.status() != transient {
                    Self::settle(&on_message);
                }
                // Otherwise the child is still in flight: the message is a
                // status of an earlier transition that the hub queued
                // before this start call.
            },
            move || Self::settle(&on_completion),
        );
        Self {
            hub,
            child_id,
            transient,
            state,
            subscription,
        }
    }

    /// Records a transient status the hub has queued but not yet delivered
    /// (the start call ran inside a hub batch, a borrowed scope, or this
    /// thread's drain). Call after the start call returns.
    fn note_queued_transient(&self) {
        if !lock(&self.state).seen && self.hub.has_pending_status(self.child_id, self.transient) {
            lock(&self.state).seen = true;
        }
    }

    fn settle(state: &Mutex<ChildObserverState>) {
        let callback = {
            let mut state = lock(state);
            state.settled = true;
            state.callback.take()
        };
        if let Some(callback) = callback {
            callback();
        }
    }

    /// Registers `callback` to run when the hub delivers a status of the
    /// child that finds it no longer at the transient status. Returns `false` (dropping `callback`) when the hub never
    /// delivered the transient status or already delivered the next one.
    fn arm(state: &Mutex<ChildObserverState>, callback: LifecycleSettleCallback) -> bool {
        let mut state = lock(state);
        if !state.seen || state.settled {
            return false;
        }
        state.callback = Some(callback);
        true
    }
}

/// A VM node that the tree walks can visit (spec/13, ADR-0207).
///
/// A container lists its members as type-erased [`TreeNodeRef`] handles, so
/// a walk crosses containers whose children have other types: a
/// [`CompositeVm`](crate::CompositeVm) or [`GroupVm`](crate::GroupVm) lists
/// its children, an aggregate lists its present components in
/// `component_1`, `component_2`, … order, and a
/// [`HierarchicalVm`](crate::HierarchicalVm) lists its children. A leaf keeps
/// the default, which lists no children.
pub trait TreeNode: VmNode {
    /// Returns the node's children in traversal order, or the error that
    /// stops their materialization.
    ///
    /// [`walk`](crate::walk), [`walk_expanded`](crate::walk_expanded) and
    /// [`find`](crate::find) read children only through this method, so a
    /// node whose children can fail to load reports that failure to the
    /// caller (spec/13 §6.1, ADR-0170). The default returns no children.
    fn try_children_nodes(&self) -> VmxResult<Vec<TreeNodeRef>> {
        Ok(Vec::new())
    }

    /// Returns the node's opt-in expansion capability, when present.
    /// [`walk_expanded`](crate::walk_expanded) does not descend into a node
    /// whose capability reports collapsed.
    fn expandable(&self) -> Option<&dyn crate::Expandable> {
        None
    }
}

/// The object-safe view of a [`TreeNode`] behind a [`TreeNodeRef`].
trait ErasedTreeNode: Send + Sync {
    fn node_id(&self) -> usize;
    fn node_status(&self) -> ConstructionStatus;
    fn node_children(&self) -> VmxResult<Vec<TreeNodeRef>>;
    fn node_expandable(&self) -> Option<&dyn crate::Expandable>;
    fn as_any(&self) -> &dyn std::any::Any;
    fn node_type_name(&self) -> &'static str;
}

impl<T: TreeNode> ErasedTreeNode for T {
    fn node_id(&self) -> usize {
        self.id()
    }

    fn node_status(&self) -> ConstructionStatus {
        self.status()
    }

    fn node_children(&self) -> VmxResult<Vec<TreeNodeRef>> {
        self.try_children_nodes()
    }

    fn node_expandable(&self) -> Option<&dyn crate::Expandable> {
        self.expandable()
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }

    fn node_type_name(&self) -> &'static str {
        std::any::type_name::<T>()
    }
}

/// A type-erased handle to a [`TreeNode`], which the tree walks yield.
///
/// A handle shares the node it wraps, as a clone of the node does. It
/// compares equal to another handle for the same node identity.
/// [`downcast`](Self::downcast) returns the concrete node.
///
/// ```
/// use vmx::{walk, ComponentVm, CompositeVm, TreeNodeRef};
///
/// let root = CompositeVm::new("root");
/// let leaf = ComponentVm::new("leaf");
/// root.add(leaf.clone()).unwrap();
///
/// let nodes = walk(&root).unwrap();
/// assert_eq!(nodes, vec![TreeNodeRef::new(root.clone()), TreeNodeRef::new(leaf.clone())]);
/// assert!(nodes[1].downcast::<ComponentVm>() == Some(leaf));
/// assert!(nodes[0].downcast::<ComponentVm>().is_none());
/// ```
#[derive(Clone)]
pub struct TreeNodeRef {
    node: Arc<dyn ErasedTreeNode>,
}

impl TreeNodeRef {
    /// Wraps `node`.
    pub fn new<T: TreeNode>(node: T) -> Self {
        Self {
            node: Arc::new(node),
        }
    }

    /// Returns the wrapped node's identity.
    pub fn id(&self) -> usize {
        self.node.node_id()
    }

    /// Returns the wrapped node's lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.node.node_status()
    }

    /// Returns the wrapped node's Rust type name, for diagnostics.
    pub fn type_name(&self) -> &'static str {
        self.node.node_type_name()
    }

    /// Reports whether the wrapped node is a `T`.
    pub fn is<T: TreeNode>(&self) -> bool {
        self.node.as_any().is::<T>()
    }

    /// Returns the wrapped node as a `T`, or `None` for another type.
    pub fn downcast_ref<T: TreeNode>(&self) -> Option<&T> {
        self.node.as_any().downcast_ref::<T>()
    }

    /// Returns a clone of the wrapped node as a `T`, or `None` for another
    /// type.
    pub fn downcast<T: TreeNode>(&self) -> Option<T> {
        self.downcast_ref::<T>().cloned()
    }

    /// Returns the wrapped node's children, as
    /// [`TreeNode::try_children_nodes`] does.
    ///
    /// # Errors
    ///
    /// Returns the error of [`TreeNode::try_children_nodes`].
    pub fn try_children_nodes(&self) -> VmxResult<Vec<TreeNodeRef>> {
        self.node.node_children()
    }

    /// Returns the wrapped node's expansion capability, when present.
    pub fn expandable(&self) -> Option<&dyn crate::Expandable> {
        self.node.node_expandable()
    }
}

impl PartialEq for TreeNodeRef {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl Eq for TreeNodeRef {}

impl std::fmt::Debug for TreeNodeRef {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("TreeNodeRef")
            .field("type", &self.type_name())
            .field("id", &self.id())
            .finish()
    }
}

type Hook = Arc<Mutex<dyn FnMut() -> VmxResult<()> + Send + 'static>>;

/// Work a construct or destruct runs after the hook succeeds, inside the
/// transition: a component's member walk (spec/02 §6.1, ADR-0203). For a
/// background component it runs on the background dispatcher.
pub(crate) type TransitionBody<D> = Box<dyn FnOnce(&ComponentCore<D>) -> VmxResult<()> + Send>;
type OwnedCleanup = Box<dyn FnOnce() + Send + 'static>;
/// Disposes one member registered through `ComponentVm::own_member`.
pub(crate) type MemberDisposal = Box<dyn FnOnce() -> VmxResult<()> + Send + 'static>;

/// Where a component's member disposal stands (spec/02 §7.1).
#[derive(Clone, Copy, PartialEq, Eq)]
enum MemberPhase {
    /// No dispose has started: registrations are kept.
    Open,
    /// A dispose is disposing the members; any other dispose is a no-op.
    Running,
    /// The members are disposed: a registration disposes its member now.
    Done,
}
pub(crate) type ModelHint<M> = Arc<dyn Fn(&M) -> String + Send + Sync>;

#[derive(Clone)]
pub(crate) struct ComponentCore<D: Dispatcher = NullDispatcher> {
    inner: Arc<Mutex<ComponentCoreInner<D>>>,
    hook_ready: Arc<Condvar>,
}

/// A core reference that does not keep the core alive. A container's child
/// steps and settle callbacks hold one: the core stores the steps, and the
/// child stores the callback, so a strong reference would keep a container
/// waiting on a child that never settles alive after its last handle drops
/// (#750).
pub(crate) struct WeakComponentCore<D: Dispatcher = NullDispatcher> {
    inner: Weak<Mutex<ComponentCoreInner<D>>>,
    hook_ready: Arc<Condvar>,
}

impl<D: Dispatcher> Clone for WeakComponentCore<D> {
    fn clone(&self) -> Self {
        Self {
            inner: Weak::clone(&self.inner),
            hook_ready: Arc::clone(&self.hook_ready),
        }
    }
}

impl<D: Dispatcher> WeakComponentCore<D> {
    /// The core, while any strong reference keeps it alive.
    pub(crate) fn upgrade(&self) -> Option<ComponentCore<D>> {
        Some(ComponentCore {
            inner: self.inner.upgrade()?,
            hook_ready: Arc::clone(&self.hook_ready),
        })
    }
}

struct ComponentCoreInner<D: Dispatcher> {
    id: usize,
    name: String,
    hint: String,
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
    terminal_cleanups: Vec<OwnedCleanup>,
    disposal_complete: bool,
    /// Set once this core reported its `Disposed` publication to its owner,
    /// so the owner's dispose clear runs once (spec/06 §4.3 rule 9).
    disposal_reported: bool,
    active_hook_owner: Option<ThreadId>,
    /// Threads blocked in a recorded wait for the active hook.
    hook_waiters: usize,
    deferred_core_disposal: bool,
    /// Set once a container's or a leaf-with-members' disposal starts: no
    /// construct or destruct is admitted after it, and no status other than
    /// `Disposed` commits (LIFE-015, LIFE-021, spec/02 §7.2).
    hook_admission_closed: bool,
    /// A container's child cascade that waits for a hook admitted on another
    /// thread; the thread that finishes the disposal runs it (LIFE-015).
    disposal_cascade: Option<DisposalCascade>,
    selected: bool,
    expanded: bool,
    child_settle: Option<ChildSettle>,
    settle_waiters: Vec<LifecycleSettleCallback>,
    /// Members disposed before this component, in registration order.
    members: Vec<(usize, MemberDisposal)>,
    member_phase: MemberPhase,
}

impl<D: Dispatcher> ComponentCoreInner<D> {
    fn hook_waiters(&mut self) -> &mut usize {
        &mut self.hook_waiters
    }
}

/// Admits `reconstruct` from `status` with the error the lifecycle core
/// returns: `InvalidLifecycleTransition` naming `status` and `reconstruct`
/// from every status but `Constructed` (spec/02 §2.1, LIFE-008, ADR-0203).
pub(crate) fn reconstruct_admission(status: ConstructionStatus) -> VmxResult<()> {
    match status {
        ConstructionStatus::Constructed => Ok(()),
        other => Err(invalid_transition(other, "reconstruct")),
    }
}

/// The status an illegal call names: a sealed construct whose `Constructed`
/// publication has not started yet is still `Constructing` to every observer
/// (spec/06 §5.1).
fn observed_status<D: Dispatcher>(inner: &ComponentCoreInner<D>) -> ConstructionStatus {
    if inner.transitioning && inner.status == ConstructionStatus::Constructed {
        ConstructionStatus::Constructing
    } else {
        inner.status
    }
}

/// Releases a component's settle waiters when dropped, so a transition body
/// that unwinds from a panicking hook still runs them; otherwise a container
/// waiting on the component stays transient (#738).
struct ReleaseSettleWaiters<'a, D: Dispatcher>(&'a ComponentCore<D>);

impl<D: Dispatcher> Drop for ReleaseSettleWaiters<'_, D> {
    fn drop(&mut self) {
        self.0.release_settle_waiters();
    }
}

impl<D: Dispatcher> ComponentCore<D> {
    pub(crate) fn new(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        Self {
            inner: Arc::new(Mutex::new(ComponentCoreInner {
                id: next_id(),
                name: name.into(),
                hint: String::new(),
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
                terminal_cleanups: Vec::new(),
                disposal_complete: false,
                disposal_reported: false,
                active_hook_owner: None,
                hook_waiters: 0,
                deferred_core_disposal: false,
                hook_admission_closed: false,
                disposal_cascade: None,
                selected: false,
                expanded: false,
                child_settle: None,
                settle_waiters: Vec::new(),
                members: Vec::new(),
                member_phase: MemberPhase::Open,
            })),
            hook_ready: Arc::new(Condvar::new()),
        }
    }

    pub(crate) fn id(&self) -> usize {
        lock(&self.inner).id
    }

    /// Identifies this core's hook lease in the wait-for graph.
    fn hook_resource(&self) -> Resource {
        Resource::Hook(Arc::as_ptr(&self.inner) as *const () as usize)
    }

    /// Wakes the threads that wait for this core's hook. A hook thread calls
    /// it after it clears `active_hook_owner`: the edges that name a released
    /// owner are removed first, so a woken waiter's stale edge cannot close a
    /// cycle (spec/02 §2.4, spec/03 §4.1 rule 4).
    fn release_hook_waiters(&self, inner: &mut ComponentCoreInner<D>) {
        if inner.hook_waiters > 0 {
            waits().release_waiters(self.hook_resource(), inner.active_hook_owner.as_slice());
        }
        self.hook_ready.notify_all();
    }

    /// A reference to this core that does not keep it alive.
    pub(crate) fn downgrade(&self) -> WeakComponentCore<D> {
        WeakComponentCore {
            inner: Arc::downgrade(&self.inner),
            hook_ready: Arc::clone(&self.hook_ready),
        }
    }

    /// A child step that runs `step` on this core, holding the core weakly
    /// while queued (#750). Once the core is gone or disposed, the step does
    /// nothing. So a disposed container's walk starts no further child and
    /// does not run its `then` (LIFE-015).
    fn weak_step<F>(&self, step: F) -> ChildStep
    where
        F: FnOnce(&Self) -> VmxResult<()> + Send + 'static,
    {
        let core = self.downgrade();
        Box::new(move || {
            core.upgrade().map_or(Ok(()), |core| {
                if core.status() == ConstructionStatus::Disposed {
                    return Ok(());
                }
                step(&core)
            })
        })
    }

    pub(crate) fn name(&self) -> String {
        lock(&self.inner).name.clone()
    }

    pub(crate) fn hint(&self) -> String {
        lock(&self.inner).hint.clone()
    }

    pub(crate) fn set_hint(&self, hint: String) {
        lock(&self.inner).hint = hint;
    }

    pub(crate) fn set_background(&self, background: bool) {
        lock(&self.inner).background = background;
    }

    pub(crate) fn status(&self) -> ConstructionStatus {
        lock(&self.inner).status
    }

    /// Whether a sealed construct walk already flipped the state to
    /// Constructed and its publication has not started yet (spec/06 §5.1).
    /// Only a container's seal produces this state; the publication clears it
    /// as it starts, before any subscriber sees Constructed.
    pub(crate) fn publication_pending(&self) -> bool {
        let inner = lock(&self.inner);
        inner.status == ConstructionStatus::Constructed && inner.transitioning
    }

    /// Whether `reconstruct` is admitted now: Constructed, and not a sealed
    /// construct still publishing.
    pub(crate) fn can_reconstruct(&self) -> bool {
        let inner = lock(&self.inner);
        inner.status == ConstructionStatus::Constructed && !inner.transitioning
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
            return self.transition_background(operation, None);
        }
        self.transition_with(operation, || Ok(()))
    }

    /// Runs a construct or destruct with `body` after the hook, where the
    /// hook runs: on the background dispatcher for a background component,
    /// otherwise on the calling thread (spec/02 §6.1, spec/11 §4, ADR-0203).
    /// A rejected transition runs nothing.
    pub(crate) fn transition_with_walk(
        &self,
        operation: LifecycleOperation,
        body: TransitionBody<D>,
    ) -> VmxResult<()> {
        if operation != LifecycleOperation::Dispose && lock(&self.inner).background {
            return self.transition_background(operation, Some(body));
        }
        self.transition_with(operation, || body(self))
    }

    pub(crate) fn reconstruct(&self) -> VmxResult<()> {
        let _release = ReleaseSettleWaiters(self);
        self.reconstruct_sync()
    }

    /// Admits `reconstruct` as [`reconstruct_admission`] does, after the
    /// refusal of the inline dispose cascade: once that cascade has started,
    /// the call fails as from `Disposed` whatever `Status` reads (spec/02
    /// §7.2).
    pub(crate) fn admit_reconstruct(&self) -> VmxResult<()> {
        let status = {
            let inner = lock(&self.inner);
            if inner.hook_admission_closed {
                return Err(invalid_transition(
                    ConstructionStatus::Disposed,
                    "reconstruct",
                ));
            }
            if inner.transitioning {
                return Err(invalid_transition(observed_status(&inner), "reconstruct"));
            }
            inner.status
        };
        reconstruct_admission(status)
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
            self.release_hook_waiters(&mut inner);
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

    /// Publishes one hub `ConstructionStatusChanged` prepared by `prepare`,
    /// then — when a status message was produced — the VM-local `status` and
    /// `is_constructed` notifications (spec/01 §1, spec/02 §6). Computed
    /// lifecycle properties raise only the local notification, never a hub
    /// `PropertyChanged`.
    fn send_status<R, F>(&self, hub: &MessageHub, prepare: F) -> R
    where
        F: FnOnce() -> (R, Option<Message>),
    {
        let mut published = false;
        let result = hub.send_prepared(|| {
            let (result, message) = prepare();
            published = message.is_some();
            (result, message)
        });
        if published {
            self.raise_status_properties();
        }
        result
    }

    fn raise_status_properties(&self) {
        let local = lock(&self.inner).property_changed.clone();
        if !local.begin_notification() {
            return;
        }
        local.send_admitted("status");
        local.send_admitted("is_constructed");
        local.end_notification();
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
        self.send_status(hub, || {
            let mut inner = lock(&self.inner);
            if inner.transition_generation != generation
                || inner.status == ConstructionStatus::Disposed
            {
                return (false, None);
            }
            if inner.hook_admission_closed {
                // The inline dispose cascade has started: neither phase
                // commits, and no construct hook is claimed (spec/02 §7.2).
                inner.transitioning = false;
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
        let (sender_id, sender_name, destruct_hook, construct_hook, generation) = self
            .send_status(&hub, || {
                let mut inner = lock(&self.inner);
                // The inline dispose cascade refuses the call first (spec/02
                // §7.2).
                if inner.status == ConstructionStatus::Disposed || inner.hook_admission_closed {
                    return (
                        Err(invalid_transition(
                            ConstructionStatus::Disposed,
                            "reconstruct",
                        )),
                        None,
                    );
                }
                if inner.transitioning || inner.status != ConstructionStatus::Constructed {
                    return (
                        Err(invalid_transition(observed_status(&inner), "reconstruct")),
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

    fn run_background_hook(
        &self,
        hook: Option<Hook>,
        body: Option<TransitionBody<D>>,
        generation: u64,
    ) -> Option<VmxResult<()>> {
        {
            let mut inner = lock(&self.inner);
            if inner.transition_generation != generation
                || inner.status == ConstructionStatus::Disposed
            {
                return None;
            }
            if inner.hook_admission_closed {
                // No hook is admitted once the inline dispose cascade has
                // started (spec/02 §7.2).
                inner.transitioning = false;
                return None;
            }
            inner.active_hook_owner = Some(thread::current().id());
        }
        // The body (a member walk) runs after the hook inside the same hook
        // admission, as in the foreground transition (LIFE-015).
        let execution = catch_unwind(AssertUnwindSafe(|| {
            hook.map(|hook| (lock(&hook))())
                .unwrap_or(Ok(()))
                .and_then(|()| {
                    let body_allowed = {
                        let inner = lock(&self.inner);
                        inner.transition_generation == generation
                            && inner.status != ConstructionStatus::Disposed
                    };
                    match body {
                        Some(body) if body_allowed => body(self),
                        _ => Ok(()),
                    }
                })
        }));
        let deferred = {
            let mut inner = lock(&self.inner);
            if inner.active_hook_owner == Some(thread::current().id()) {
                inner.active_hook_owner = None;
            }
            let deferred = inner.deferred_core_disposal;
            inner.deferred_core_disposal = false;
            self.release_hook_waiters(&mut inner);
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
        let mut inner = lock(&self.inner);
        if inner.transition_generation != generation || inner.status == ConstructionStatus::Disposed
        {
            return None;
        }
        if inner.hook_admission_closed {
            inner.transitioning = false;
            return None;
        }
        drop(inner);
        Some(result)
    }

    fn transition_background(
        &self,
        operation: LifecycleOperation,
        body: Option<TransitionBody<D>>,
    ) -> VmxResult<()> {
        let hub = lock(&self.inner).hub.clone();
        let started = self.send_status(&hub, || {
            let mut inner = lock(&self.inner);
            // The inline dispose cascade refuses the call before the
            // idempotent no-op (spec/02 §7.2).
            if inner.hook_admission_closed || inner.status == ConstructionStatus::Disposed {
                return (
                    Err(invalid_transition(
                        ConstructionStatus::Disposed,
                        operation.name(),
                    )),
                    None,
                );
            }
            match (inner.status, operation) {
                (ConstructionStatus::Constructed, LifecycleOperation::Construct)
                | (ConstructionStatus::Destructed, LifecycleOperation::Destruct) => {
                    return (Ok(None), None)
                }
                _ => {}
            }
            if inner.transitioning {
                return (
                    Err(invalid_transition(
                        observed_status(&inner),
                        operation.name(),
                    )),
                    None,
                );
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
            let Some(result) = core.run_background_hook(hook, body, generation) else {
                return;
            };
            // A member walk still waiting on a child hands the terminal
            // publication to the settle continuation (spec/02 §6.1). A
            // member failure recorded while the walk ran rolls back through
            // the foreground publication below (spec/11 §3).
            let result = match result {
                Ok(()) => match core.arm_children_settle(generation) {
                    ChildWalkOutcome::Settled => Ok(()),
                    ChildWalkOutcome::Deferred => return,
                    ChildWalkOutcome::Failed(error) => Err(error),
                },
                Err(error) => Err(error),
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
                // A failed walk can leave a settle with queued steps; they
                // drop after `send_status` releases the hub and core locks.
                let mut cleared = None;
                publication_core.send_status(&hub, || {
                    let mut inner = lock(&publication_core.inner);
                    if inner.transition_generation != generation
                        || inner.status == ConstructionStatus::Disposed
                    {
                        return ((), None);
                    }
                    if inner.hook_admission_closed {
                        // A commit queued before the inline dispose cascade
                        // started publishes nothing (spec/02 §7.2).
                        inner.transitioning = false;
                        return ((), None);
                    }
                    cleared = inner.child_settle.take();
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
                drop(cleared);
                publication_core.release_settle_waiters();
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
        let recovered = self.send_status(hub, || {
            let mut inner = lock(&self.inner);
            if inner.transition_generation != generation
                || inner.status == ConstructionStatus::Disposed
                || !inner.transitioning
            {
                return (false, None);
            }
            if inner.hook_admission_closed {
                inner.transitioning = false;
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
        self.release_settle_waiters();
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
        let _release = ReleaseSettleWaiters(self);
        self.transition_with_body(operation, action)
    }

    fn transition_with_body<F>(&self, operation: LifecycleOperation, action: F) -> VmxResult<()>
    where
        F: FnOnce() -> VmxResult<()>,
    {
        let hub = lock(&self.inner).hub.clone();
        // A stale settle can still queue a step that owns a view-model's last
        // handle; it drops after `send_status` releases the hub lock.
        let mut stale_settle = None;
        let started = self.send_status(&hub, || {
            let (sender_id, sender_name, hook, transition_status, target, generation) = {
                let mut inner = lock(&self.inner);
                // Once the inline dispose cascade has started, a construct or
                // destruct fails as from Disposed, before the idempotent
                // no-op, the legality check, and the concurrent-operation
                // check (spec/02 §7.2, LIFE-021).
                if operation != LifecycleOperation::Dispose
                    && (inner.hook_admission_closed || inner.status == ConstructionStatus::Disposed)
                {
                    return (
                        Err(invalid_transition(
                            ConstructionStatus::Disposed,
                            operation.name(),
                        )),
                        None,
                    );
                }
                match (inner.status, operation) {
                    // A sealed construct still publishing Constructed is in
                    // flight: a second construct is concurrent, not idempotent.
                    (ConstructionStatus::Constructed, LifecycleOperation::Construct)
                        if inner.transitioning =>
                    {
                        return (
                            Err(invalid_transition(
                                ConstructionStatus::Constructing,
                                operation.name(),
                            )),
                            None,
                        )
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
                    return (
                        Err(invalid_transition(
                            observed_status(&inner),
                            operation.name(),
                        )),
                        None,
                    );
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
                stale_settle = inner.child_settle.take();
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
        drop(stale_settle);
        let Some((sender_id, sender_name, hook, target, generation)) = started else {
            return Ok(());
        };

        let mut cascade_failure = None;
        if operation == LifecycleOperation::Dispose {
            let current = thread::current().id();
            let mut inner = lock(&self.inner);
            while let Some(owner) = inner.active_hook_owner {
                if owner == current {
                    inner.deferred_core_disposal = true;
                    return Ok(());
                }
                let cyclic;
                (inner, cyclic) = wait_for_owner(
                    &self.inner,
                    &self.hook_ready,
                    inner,
                    ComponentCoreInner::hook_waiters,
                    self.hook_resource(),
                    owner,
                );
                if cyclic {
                    inner.deferred_core_disposal = true;
                    return Ok(());
                }
            }
            // The hook has returned: a child cascade that waited for it runs
            // now, before the dispose hook (LIFE-015).
            let cascade = inner.disposal_cascade.take();
            drop(inner);
            cascade_failure = cascade.and_then(run_disposal_cascade);
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
            self.release_hook_waiters(&mut inner);
            deferred
        };
        #[cfg(test)]
        if operation != LifecycleOperation::Dispose {
            commit_pause::run(sender_id);
        }
        let (mut operation_result, mut panic_payload) = match execution {
            Ok(result) => (result, None),
            Err(payload) => (Ok(()), Some(payload)),
        };
        match cascade_failure {
            Some(FirstFailure::Error(error)) => {
                (operation_result, panic_payload) = (Err(error), None)
            }
            Some(FirstFailure::Panic(payload)) => panic_payload = Some(payload),
            None => {}
        }
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
            self.complete_disposal();
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
        // Disposal supersedes the transition once it published Disposed or
        // started its inline cascade (spec/02 §2.4, §7.2): the transition
        // commits nothing more and returns its own result.
        let superseded = {
            let mut inner = lock(&self.inner);
            let superseded = inner.transition_generation != generation
                || inner.status == ConstructionStatus::Disposed
                || inner.hook_admission_closed;
            if inner.transition_generation == generation && inner.hook_admission_closed {
                inner.transitioning = false;
            }
            superseded
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
            // The rollback commits and publishes under one guard, so an
            // inline dispose cascade that starts in between drops it
            // (spec/02 §7.2).
            let mut cleared = None;
            self.send_status(&hub, || {
                let mut inner = lock(&self.inner);
                if inner.transition_generation != generation {
                    return ((), None);
                }
                inner.transitioning = false;
                if inner.status == ConstructionStatus::Disposed || inner.hook_admission_closed {
                    return ((), None);
                }
                inner.status = rollback;
                cleared = inner.child_settle.take();
                (
                    (),
                    Some(Message::ConstructionStatusChanged(
                        ConstructionStatusChangedMessage {
                            sender_id,
                            sender_name: sender_name.clone(),
                            status: rollback,
                        },
                    )),
                )
            });
            drop(cleared);
            if let Some(payload) = panic_payload {
                resume_unwind(payload);
            }
            return operation_result;
        }

        if self.defer_until_children_settle(generation) {
            return Ok(());
        }
        // Dispose returned above, so `target` is Constructed or Destructed.
        // The commit and its publication run under one guard: an inline
        // dispose cascade that starts first drops both (spec/02 §7.2).
        self.send_status(&hub, || {
            let mut inner = lock(&self.inner);
            if inner.transition_generation != generation {
                return ((), None);
            }
            inner.transitioning = false;
            if inner.status == ConstructionStatus::Disposed || inner.hook_admission_closed {
                return ((), None);
            }
            inner.status = target;
            (
                (),
                Some(Message::ConstructionStatusChanged(
                    ConstructionStatusChangedMessage {
                        sender_id,
                        sender_name: sender_name.clone(),
                        status: target,
                    },
                )),
            )
        });
        Ok(())
    }

    fn finish_deferred_core_disposal(&self) -> VmxResult<()> {
        let (cascade, hook, property_changed, background_errors) = {
            let mut inner = lock(&self.inner);
            (
                inner.disposal_cascade.take(),
                inner.on_dispose.clone(),
                inner.property_changed.clone(),
                inner.background_errors.clone(),
            )
        };
        // A child cascade deferred behind this thread's hook runs before the
        // dispose hook, and its failure comes first (LIFE-015).
        let cascade_failure = cascade.and_then(run_disposal_cascade);
        let result = catch_unwind(AssertUnwindSafe(|| {
            hook.map(|hook| (lock(&hook))()).unwrap_or(Ok(()))
        }));
        self.dispose_owned();
        property_changed.dispose();
        background_errors.dispose();
        self.complete_disposal();
        if cascade_failure.is_some() {
            return finish_with_first_failure(cascade_failure);
        }
        match result {
            Ok(result) => result,
            Err(payload) => resume_unwind(payload),
        }
    }

    /// Registers `callback` to run after the in-flight construct or destruct
    /// publishes its terminal status; `false` when nothing is in flight.
    pub(crate) fn when_settled(&self, callback: LifecycleSettleCallback) -> bool {
        let mut inner = lock(&self.inner);
        if !inner.transitioning || inner.status == ConstructionStatus::Disposed {
            return false;
        }
        inner.settle_waiters.push(callback);
        true
    }

    /// Runs `continuation` after the in-flight construct or destruct settles,
    /// or immediately when nothing is in flight.
    pub(crate) fn then_after_settle(&self, continuation: LifecycleSettleCallback) {
        let continuation = {
            let mut inner = lock(&self.inner);
            if inner.transitioning && inner.status != ConstructionStatus::Disposed {
                inner.settle_waiters.push(continuation);
                None
            } else {
                Some(continuation)
            }
        };
        if let Some(continuation) = continuation {
            continuation();
        }
    }

    /// Completes a container reconstruct after its destruct: constructs now
    /// when the destruct settled synchronously, otherwise once the deferred
    /// destruct reaches Destructed. A deferred construct failure that does
    /// not surface through the settle path reaches `background_errors`.
    /// `construct` receives this core and must not hold it: the deferred
    /// continuation is stored on the core and holds it weakly, so a
    /// container whose destruct never settles stays collectable (#750).
    ///
    /// Once the inline dispose cascade has started, the construct phase does
    /// not start: the reconstruct is superseded by the disposal and returns
    /// `Ok(())`, as the leaf reconstruct does (spec/02 §7.2, ADR-0175 §2.3
    /// (b)). The deferred continuation skips it the same way and reports
    /// nothing to `background_errors`.
    pub(crate) fn construct_after_destruct<F>(&self, construct: F) -> VmxResult<()>
    where
        F: FnOnce(&Self) -> VmxResult<()> + Send + 'static,
    {
        let (status, superseded) = {
            let inner = lock(&self.inner);
            (inner.status, inner.hook_admission_closed)
        };
        if superseded {
            return Ok(());
        }
        if status == ConstructionStatus::Destructed {
            return construct(self);
        }
        let core = self.downgrade();
        self.then_after_settle(Box::new(move || {
            let Some(core) = core.upgrade() else {
                return;
            };
            let (status, superseded) = {
                let inner = lock(&core.inner);
                (inner.status, inner.hook_admission_closed)
            };
            if status == ConstructionStatus::Destructed && !superseded {
                if let Err(error) = construct(&core) {
                    let errors = core.background_errors();
                    let emission = errors.begin_emission();
                    errors.send(error);
                    drop(emission);
                }
            }
        }));
        Ok(())
    }

    /// Abandons a construct/destruct waiting on children, so a container
    /// disposing its children does not publish a rollback for the children
    /// it is about to dispose itself; the container then settles at Disposed.
    pub(crate) fn abandon_child_settle(&self) {
        // A queued step can own the last handle to a view-model whose `Drop`
        // reads this container; drop it after the core guard is released.
        let abandoned = lock(&self.inner).child_settle.take();
        drop(abandoned);
    }

    /// Runs settle continuations once no construct or destruct is in flight.
    /// Called after every terminal publication, outside every lock.
    fn release_settle_waiters(&self) {
        let waiters = {
            let mut inner = lock(&self.inner);
            if inner.transitioning && inner.status != ConstructionStatus::Disposed {
                return;
            }
            std::mem::take(&mut inner.settle_waiters)
        };
        for waiter in waiters {
            let _ = catch_unwind(AssertUnwindSafe(waiter));
        }
    }

    /// Runs `step` now, or queues it behind a child this transition is still
    /// waiting on so children keep transitioning in order (spec/02 §6).
    pub(crate) fn child_step(&self, step: ChildStep) -> VmxResult<()> {
        let step = {
            let mut inner = lock(&self.inner);
            let generation = inner.transition_generation;
            match inner.child_settle.as_mut() {
                Some(settle) if settle.generation == generation && settle.busy() => {
                    settle.queue.push_back(step);
                    None
                }
                _ => Some(step),
            }
        };
        step.map_or(Ok(()), |step| step())
    }

    /// Constructs or destructs `child` as one step of this container's
    /// transition. A child that is still Constructing/Destructing when its
    /// call returns (background lifecycle) holds the container transient
    /// until it settles; a child that settles at any other status fails the
    /// container transition.
    pub(crate) fn transition_child<N: VmNode>(
        &self,
        child: &N,
        operation: LifecycleOperation,
    ) -> VmxResult<()> {
        let child = child.clone();
        self.child_step(self.weak_step(move |core| core.run_child_transition(&child, operation)))
    }

    /// Runs `after` as one step of the supported child-transition walk, once
    /// the earlier steps settled. A disposed component skips it (LIFE-015).
    pub(crate) fn child_then<F>(&self, after: F) -> VmxResult<()>
    where
        F: FnOnce() -> VmxResult<()> + Send + 'static,
    {
        self.child_step(self.weak_step(move |_| after()))
    }

    /// Constructs or destructs `child` as one step of the supported
    /// child-transition walk (spec/02 §6.1). At its turn the step skips a
    /// child already at the target, joins one already in the transient
    /// status (or publishing a sealed construct), and otherwise runs the
    /// transition like [`Self::transition_child`].
    pub(crate) fn transition_or_join_child<N: VmNode>(
        &self,
        child: &N,
        operation: LifecycleOperation,
    ) -> VmxResult<()> {
        let (transient, target) = match operation {
            LifecycleOperation::Construct => (
                ConstructionStatus::Constructing,
                ConstructionStatus::Constructed,
            ),
            LifecycleOperation::Destruct => (
                ConstructionStatus::Destructing,
                ConstructionStatus::Destructed,
            ),
            LifecycleOperation::Dispose => return Ok(()),
        };
        let child = child.clone();
        self.child_step(self.weak_step(move |core| {
            let status = child.status();
            if status == transient || child.lifecycle_publication_pending() {
                core.await_child(&child, target, None)
            } else if status == target {
                Ok(())
            } else {
                core.run_child_transition(&child, operation)
            }
        }))
    }

    /// Registers a member disposed before this component (spec/02 §7.1).
    /// A registration after the members were disposed disposes the member
    /// now. The component itself is rejected; a member already registered
    /// is kept once.
    pub(crate) fn own_member(&self, member_id: usize, dispose: MemberDisposal) -> VmxResult<()> {
        let (now, duplicate) = {
            let mut inner = lock(&self.inner);
            if member_id == inner.id {
                return Err(VmxError::OwnershipCycle);
            }
            if inner.member_phase != MemberPhase::Open
                || inner.status == ConstructionStatus::Disposed
            {
                (Some(dispose), None)
            } else if inner.members.iter().any(|(id, _)| *id == member_id) {
                (None, Some(dispose))
            } else {
                inner.members.push((member_id, dispose));
                (None, None)
            }
        };
        // A member handle can be the last one; drop it outside the guard.
        drop(duplicate);
        now.map_or(Ok(()), |dispose| dispose())
    }

    /// Takes the registered members for disposal, in registration order,
    /// and marks the member cascade running under the core lock (spec/02
    /// §7.1). While it runs, every other dispose, re-entrant or from another
    /// thread, gets `None` and returns at once without waiting: waiting could
    /// deadlock against a member hook that disposes this component. The
    /// first dispose disposes the members and then the component. A
    /// component with no members never marks a cascade, so its disposal is
    /// unchanged.
    pub(crate) fn begin_member_disposal(&self) -> Option<Vec<MemberDisposal>> {
        let mut inner = lock(&self.inner);
        match inner.member_phase {
            MemberPhase::Open if inner.members.is_empty() => {
                inner.member_phase = MemberPhase::Done;
                Some(Vec::new())
            }
            MemberPhase::Open => {
                inner.member_phase = MemberPhase::Running;
                let members = std::mem::take(&mut inner.members);
                Some(members.into_iter().map(|(_, dispose)| dispose).collect())
            }
            MemberPhase::Running => None,
            MemberPhase::Done => Some(Vec::new()),
        }
    }

    /// Marks the member cascade finished.
    pub(crate) fn finish_member_disposal(&self) {
        lock(&self.inner).member_phase = MemberPhase::Done;
    }

    /// Whether auto-construct-on-add constructs a child added now without a
    /// start record: only while the container is Constructed. While it is
    /// Constructing, only an add that registered a start record starts its
    /// child (see [`LateStarts`]).
    pub(crate) fn auto_constructs_when_constructed(&self, enabled: bool) -> bool {
        enabled && self.status() == ConstructionStatus::Constructed
    }

    /// The construct walk of a container: constructs each current member
    /// (joining one already Constructing), then joins each member added while
    /// the walk runs until none remain, then runs `then`.
    /// The walk never starts a late member (spec/02 §6, spec/06 §5.1). It
    /// takes the member's start record from `late` (see [`LateStarts`]):
    /// without one, no add tried to start the member, so the walk skips it;
    /// with one, it waits until that add's attempt is done and then joins the
    /// member, so a member whose construct failed rolls the container back.
    /// A failed add undoes its attach before its attempt ends. The walk
    /// counts members only (ADR-0186): it skips a child that is no longer a
    /// member when its turn comes, and ignores the settle result of a child
    /// that stopped being a member while the walk waited on it.
    pub(crate) fn construct_children<N: VmNode>(
        &self,
        members: Arc<dyn Fn() -> Vec<N> + Send + Sync>,
        late: LateStarts,
        then: WalkThen<D>,
    ) -> VmxResult<()> {
        // This walk's own scope: an add that registered a record before this
        // point attached a member of the snapshot below.
        let generation = lock(&self.inner).transition_generation;
        let walk = Arc::new(late.begin_walk(generation));
        let member: MemberCheck = {
            let gate = Arc::clone(&late.gate);
            let members = Arc::clone(&members);
            Arc::new(move |child_id| {
                let _gate = lock(&gate);
                members().iter().any(|child| child.id() == child_id)
            })
        };
        let snapshot = members();
        let visited: HashSet<usize> = snapshot.iter().map(VmNode::id).collect();
        for child in snapshot {
            let member = Arc::clone(&member);
            self.child_step(self.weak_step(move |core| core.construct_member(&child, &member)))?;
        }
        self.child_step(
            self.weak_step(move |core| {
                core.join_late_children(visited, members, member, walk, then)
            }),
        )
    }

    /// One snapshot step of a construct walk. A child that is no longer a
    /// member is skipped (ADR-0186). A member already Constructing (started
    /// by an auto-construct add before this walk began) is joined, not
    /// restarted; a Constructed one passes and a Destructed one is
    /// constructed (spec/02 §6). A construct failure of a child that is no
    /// longer a member does not fail the walk. A `Disposed` child is skipped
    /// with no lifecycle call (spec/02 §6, ADR-0189).
    fn construct_member<N: VmNode>(&self, child: &N, member: &MemberCheck) -> VmxResult<()> {
        if !member(child.id()) || child.status() == ConstructionStatus::Disposed {
            return Ok(());
        }
        if child.status() == ConstructionStatus::Constructing {
            return self.await_child(child, ConstructionStatus::Constructed, Some(member));
        }
        // Subscribed before the start call, as in `run_child_transition`, so
        // a node without settle notification is still waited for (ADR-0205).
        let observer = ChildObserver::start(self.hub(), child, ConstructionStatus::Constructing);
        if let Err(error) = child.construct() {
            // Another starter began the construct after the status read: the
            // walk joins it (ADR-0218 rule 6).
            if matches!(error, VmxError::InvalidLifecycleTransition { .. })
                && construct_started(child)
            {
                drop(observer);
                return self.await_child(child, ConstructionStatus::Constructed, Some(member));
            }
            return if member(child.id()) {
                Err(error)
            } else {
                Ok(())
            };
        }
        observer.note_queued_transient();
        self.await_child_observed(
            child,
            ConstructionStatus::Constructed,
            Some(member),
            Some(observer),
        )
    }

    /// Scans for the next late member under the container's membership
    /// gate, so it never sees a member whose add has not yet registered its
    /// start record. `then` and every child step run outside the gate. When
    /// no late member remains, the walk runs `then` once, then seals.
    fn join_late_children<N: VmNode>(
        &self,
        mut visited: HashSet<usize>,
        members: Arc<dyn Fn() -> Vec<N> + Send + Sync>,
        member: MemberCheck,
        walk: Arc<LateWalk>,
        then: WalkThen<D>,
    ) -> VmxResult<()> {
        let next = {
            let _gate = lock(&walk.starts.gate);
            next_late_member(&mut visited, &members, &walk)
        };
        let Some((child, record)) = next else {
            walk.starts.run_last_scan_probe();
            then(self)?;
            return self.seal_late_children(visited, members, member, walk);
        };
        let awaited = Arc::clone(&member);
        self.child_step(
            self.weak_step(move |core| core.await_add_then_child(&record, &child, awaited)),
        )?;
        self.child_step(
            self.weak_step(move |core| {
                core.join_late_children(visited, members, member, walk, then)
            }),
        )
    }

    /// Commits the walk or keeps walking (spec/02 §6, spec/06 §5.1). Under
    /// the membership gate, an add either registers its record in this
    /// walk's open scope or reads the container's status. So this step scans
    /// once more: a member an add started meanwhile is joined like a late
    /// member, then the walk seals again. With none left, it flips the core
    /// state to Constructed in the same gated section, so a later add follows
    /// the add-after-Constructed rule, and ends the walk's scope. The
    /// transition then publishes Constructed once, as before. `then` (the
    /// selector) is not run again.
    fn seal_late_children<N: VmNode>(
        &self,
        mut visited: HashSet<usize>,
        members: Arc<dyn Fn() -> Vec<N> + Send + Sync>,
        member: MemberCheck,
        walk: Arc<LateWalk>,
    ) -> VmxResult<()> {
        let next = {
            let _gate = lock(&walk.starts.gate);
            let next = next_late_member(&mut visited, &members, &walk);
            if next.is_none() {
                self.flip_constructed(walk.generation);
                walk.end();
            }
            next
        };
        let Some((child, record)) = next else {
            walk.starts.run_seal_probe();
            drop(walk);
            return Ok(());
        };
        let awaited = Arc::clone(&member);
        self.child_step(
            self.weak_step(move |core| core.await_add_then_child(&record, &child, awaited)),
        )?;
        self.child_step(
            self.weak_step(move |core| core.seal_late_children(visited, members, member, walk)),
        )
    }

    /// Flips a sealed construct walk's container to Constructed without
    /// publishing; the transition publishes it when it completes. Called
    /// under the container's membership gate.
    fn flip_constructed(&self, generation: u64) {
        let mut inner = lock(&self.inner);
        if inner.transition_generation == generation
            && inner.transitioning
            && inner.status == ConstructionStatus::Constructing
            && !inner.hook_admission_closed
        {
            inner.status = ConstructionStatus::Constructed;
        }
    }

    /// Holds the container transition until the add attempt behind `record`
    /// is done, then joins `child` like [`Self::await_child`]. A child that
    /// is no longer a member by then, such as one a failed add undid, does
    /// not change the container (ADR-0186).
    fn await_add_then_child<N: VmNode>(
        &self,
        record: &Arc<StartRecord>,
        child: &N,
        member: MemberCheck,
    ) -> VmxResult<()> {
        let (generation, stale) = {
            let mut inner = lock(&self.inner);
            let generation = inner.transition_generation;
            if !inner.transitioning || inner.status == ConstructionStatus::Disposed {
                return Ok(());
            }
            (generation, Self::begin_child_wait(&mut inner, generation))
        };
        drop(stale);
        // The record's waiter holds the core weakly: the record can outlive
        // the container (#750).
        let core = self.downgrade();
        let awaited = child.clone();
        let awaited_member = Arc::clone(&member);
        if record.when_done(Box::new(move || {
            if let Some(core) = core.upgrade() {
                core.resume_walk(move |core| {
                    core.join_after_add(generation, &awaited, awaited_member);
                });
            }
        })) {
            return Ok(());
        }
        {
            let mut inner = lock(&self.inner);
            if let Some(settle) = inner.child_settle.as_mut() {
                if settle.generation == generation {
                    settle.waiting = false;
                }
            }
        }
        self.await_child(child, ConstructionStatus::Constructed, Some(&member))
    }

    /// Marks this transition's settle as waiting on a child, replacing a
    /// stale settle of an older transition. Returns the stale settle, so the
    /// caller drops its queued steps after releasing the core guard.
    fn begin_child_wait(inner: &mut ComponentCoreInner<D>, generation: u64) -> Option<ChildSettle> {
        let settle = inner
            .child_settle
            .get_or_insert_with(|| ChildSettle::new(generation));
        let stale = (settle.generation != generation)
            .then(|| std::mem::replace(settle, ChildSettle::new(generation)));
        settle.waiting = true;
        stale
    }

    /// Continues a walk that waited for an add: joins `child`, keeping the
    /// transition waiting until it settles.
    fn join_after_add<N: VmNode>(&self, generation: u64, child: &N, member: MemberCheck) {
        {
            let inner = lock(&self.inner);
            if !self.settle_is_current(&inner, generation) {
                return;
            }
        }
        if self.watch_child(
            generation,
            child,
            ConstructionStatus::Constructed,
            Some(Arc::clone(&member)),
        ) {
            return;
        }
        {
            let mut inner = lock(&self.inner);
            if !self.settle_is_current(&inner, generation) {
                return;
            }
            if let Some(settle) = inner.child_settle.as_mut() {
                settle.waiting = false;
            }
        }
        if child.status() == ConstructionStatus::Constructing {
            // A node without settle notification is accepted in flight, as
            // `await_child` does.
            self.advance_children(generation, false);
            return;
        }
        self.after_child_settled(
            generation,
            walk_child_result(child, ConstructionStatus::Constructed, Some(&member)),
        );
    }

    /// Runs one child's transition. A walk skips a child that is `Disposed`
    /// when it reaches it and calls no lifecycle operation on it (spec/02
    /// §6, ADR-0189). A destruct refused because another thread started one
    /// after the walk read the status is joined (ADR-0218 rule 6, ADR-0228).
    fn run_child_transition<N: VmNode>(
        &self,
        child: &N,
        operation: LifecycleOperation,
    ) -> VmxResult<()> {
        if operation != LifecycleOperation::Dispose
            && child.status() == ConstructionStatus::Disposed
        {
            return Ok(());
        }
        let (transient, expected) = match operation {
            LifecycleOperation::Construct => (
                ConstructionStatus::Constructing,
                ConstructionStatus::Constructed,
            ),
            LifecycleOperation::Destruct => (
                ConstructionStatus::Destructing,
                ConstructionStatus::Destructed,
            ),
            LifecycleOperation::Dispose => return child.dispose(),
        };
        // Subscribed before the start call, so it sees the child's transient
        // status when the child publishes on this container's hub.
        let observer = ChildObserver::start(self.hub(), child, transient);
        let started = match operation {
            LifecycleOperation::Construct => child.construct(),
            _ => child.destruct(),
        };
        match started {
            Err(VmxError::InvalidLifecycleTransition { .. })
                if operation == LifecycleOperation::Destruct && destruct_started(child) =>
            {
                // Another starter began the destruct after the walk read the
                // status: the walk joins it (ADR-0218 rule 6, ADR-0228).
                drop(observer);
                self.await_child(child, expected, None)
            }
            result => {
                result?;
                observer.note_queued_transient();
                self.await_child_observed(child, expected, None, Some(observer))
            }
        }
    }

    /// Holds the container transition until `child`, already started, settles
    /// at `expected`; fails it when the child settled anywhere else. With
    /// `member`, a construct walk's check, a child that is no longer a member
    /// when it settles does not fail the transition (ADR-0186).
    fn await_child<N: VmNode>(
        &self,
        child: &N,
        expected: ConstructionStatus,
        member: Option<&MemberCheck>,
    ) -> VmxResult<()> {
        self.await_child_observed(child, expected, member, None)
    }

    /// [`Self::await_child`] with the hub observer of a child this
    /// container started. The observer is the fallback for a node without
    /// settle notification.
    fn await_child_observed<N: VmNode>(
        &self,
        child: &N,
        expected: ConstructionStatus,
        member: Option<&MemberCheck>,
        observer: Option<ChildObserver>,
    ) -> VmxResult<()> {
        let (generation, stale) = {
            let mut inner = lock(&self.inner);
            let generation = inner.transition_generation;
            if !inner.transitioning || inner.status == ConstructionStatus::Disposed {
                return Ok(());
            }
            (generation, Self::begin_child_wait(&mut inner, generation))
        };
        drop(stale);
        if self.watch_child(generation, child, expected, member.cloned()) {
            return Ok(());
        }
        let in_flight = match expected {
            ConstructionStatus::Constructed => ConstructionStatus::Constructing,
            _ => ConstructionStatus::Destructing,
        };
        // A node that does not forward `when_lifecycle_settled` is watched
        // on this container's hub when the container started it and the hub
        // delivered or queued its transient status (ADR-0205).
        if let Some(observer) = observer {
            if child.status() == in_flight
                && self.watch_observed(generation, child, expected, member.cloned(), observer)
            {
                return Ok(());
            }
        }
        {
            let mut inner = lock(&self.inner);
            if let Some(settle) = inner.child_settle.as_mut() {
                if settle.generation == generation {
                    settle.waiting = false;
                }
            }
        }
        // Otherwise the container cannot learn when the node's transition
        // settles (it joined a node already in flight, or the node publishes
        // on another hub). It accepts the node while it is still in flight
        // rather than wait without limit.
        if child.status() == in_flight {
            return Ok(());
        }
        walk_child_result(child, expected, member)
    }

    /// Like [`Self::watch_child`], with `observer` in place of the child's
    /// settle hook. The awaited check owns the observer, so its subscription
    /// ends when the check runs or the settle is dropped.
    fn watch_observed<N: VmNode>(
        &self,
        generation: u64,
        child: &N,
        expected: ConstructionStatus,
        member: Option<MemberCheck>,
        observer: ChildObserver,
    ) -> bool {
        let ChildObserver {
            state,
            subscription,
            ..
        } = observer;
        let awaited_child = child.clone();
        let awaited: AwaitedChild = Box::new(move || {
            drop(subscription);
            walk_child_result(&awaited_child, expected, member.as_ref())
        });
        let displaced = {
            let mut inner = lock(&self.inner);
            if !self.settle_is_current(&inner, generation) {
                drop(inner);
                drop(awaited);
                return true;
            }
            inner
                .child_settle
                .as_mut()
                .and_then(|settle| settle.awaited.replace(awaited))
        };
        drop(displaced);
        let (callback, wait) = self.settle_continuation(generation);
        if ChildObserver::arm(&state, callback) {
            self.end_settle_registration(&wait, generation);
            return true;
        }
        let unused = {
            let mut inner = lock(&self.inner);
            inner
                .child_settle
                .as_mut()
                .filter(|settle| settle.generation == generation)
                .and_then(|settle| settle.awaited.take())
        };
        drop(unused);
        false
    }

    /// Registers this transition's settle callback on `child`. The container
    /// keeps the awaited child and the callback holds the core weakly, so
    /// neither the child nor the container keeps itself alive while the
    /// child never settles (#750). Returns `false`, keeping nothing, when
    /// `child` has no transition in flight or no settle notification; `true`
    /// also when this transition is no longer current, as there is nothing
    /// left to wait for.
    fn watch_child<N: VmNode>(
        &self,
        generation: u64,
        child: &N,
        expected: ConstructionStatus,
        member: Option<MemberCheck>,
    ) -> bool {
        let awaited_child = child.clone();
        let awaited: AwaitedChild =
            Box::new(move || walk_child_result(&awaited_child, expected, member.as_ref()));
        let displaced = {
            let mut inner = lock(&self.inner);
            if !self.settle_is_current(&inner, generation) {
                drop(inner);
                drop(awaited);
                return true;
            }
            inner
                .child_settle
                .as_mut()
                .and_then(|settle| settle.awaited.replace(awaited))
        };
        drop(displaced);
        let (callback, wait) = self.settle_continuation(generation);
        if child.when_lifecycle_settled(callback) {
            self.end_settle_registration(&wait, generation);
            return true;
        }
        let unused = {
            let mut inner = lock(&self.inner);
            inner
                .child_settle
                .as_mut()
                .filter(|settle| settle.generation == generation)
                .and_then(|settle| settle.awaited.take())
        };
        drop(unused);
        false
    }

    /// The settle callback of a child wait, and the state that tells whether
    /// it ran while its registration was still running. Such a wait ended at
    /// once: the registering thread continues the walk when the registration
    /// returns (see [`Self::end_settle_registration`]). A later callback
    /// resumes the walk on this component's foreground (ADR-0218 rule 3).
    fn settle_continuation(&self, generation: u64) -> (LifecycleSettleCallback, Arc<AtomicU8>) {
        let wait = Arc::new(AtomicU8::new(WAIT_REGISTERING));
        let state = Arc::clone(&wait);
        let core = self.downgrade();
        let callback: LifecycleSettleCallback = Box::new(move || {
            if state
                .compare_exchange(
                    WAIT_REGISTERING,
                    WAIT_ENDED_AT_ONCE,
                    Ordering::AcqRel,
                    Ordering::Acquire,
                )
                .is_ok()
            {
                return;
            }
            if let Some(core) = core.upgrade() {
                core.resume_walk(move |core| core.child_settled(generation));
            }
        });
        (callback, wait)
    }

    /// Ends the registration of a settle callback from
    /// [`Self::settle_continuation`]. When the callback already ran, the wait
    /// ended at once, so the walk continues on this thread.
    fn end_settle_registration(&self, wait: &AtomicU8, generation: u64) {
        if wait
            .compare_exchange(
                WAIT_REGISTERING,
                WAIT_PENDING,
                Ordering::AcqRel,
                Ordering::Acquire,
            )
            .is_err()
        {
            self.child_settled(generation);
        }
    }

    /// Continues a walk that waited and did not continue at once: `resume`
    /// runs on this component's foreground dispatcher, not in the callback of
    /// the child or the add that ended the wait (spec/02 §6, ADR-0218 rule
    /// 3). The queued action holds the component weakly (#750).
    fn resume_walk(&self, resume: impl FnOnce(&Self) + Send + 'static) {
        let core = self.downgrade();
        self.dispatch(Box::new(move || {
            if let Some(core) = core.upgrade() {
                resume(&core);
            }
        }));
    }

    /// The settle callback of the child this transition waits on.
    fn child_settled(&self, generation: u64) {
        let awaited = {
            let mut inner = lock(&self.inner);
            if !self.settle_is_current(&inner, generation) {
                return;
            }
            let Some(settle) = inner.child_settle.as_mut() else {
                return;
            };
            settle.waiting = false;
            settle.awaited.take()
        };
        // The check consumes the awaited child, outside the core guard.
        let result = awaited.map_or(Ok(()), |awaited| awaited());
        self.after_child_settled(generation, result);
    }

    fn after_child_settled(&self, generation: u64, result: VmxResult<()>) {
        match result {
            Ok(()) => self.advance_children(generation, false),
            Err(error) => self.fail_children(generation, error),
        }
    }

    fn settle_is_current(&self, inner: &ComponentCoreInner<D>, generation: u64) -> bool {
        inner.transition_generation == generation
            && inner.transitioning
            && inner.status != ConstructionStatus::Disposed
            && inner
                .child_settle
                .as_ref()
                .is_some_and(|settle| settle.generation == generation)
    }

    /// Runs queued child steps until one waits again; once the queue drains
    /// after the container's own action returned, publishes the terminal
    /// status. Only one thread drains at a time: a continuation arriving
    /// while another drains leaves the queue to that drainer.
    fn advance_children(&self, generation: u64, mut resuming: bool) {
        loop {
            let step = {
                let mut inner = lock(&self.inner);
                if !self.settle_is_current(&inner, generation) {
                    return;
                }
                let Some(settle) = inner.child_settle.as_mut() else {
                    return;
                };
                if settle.draining && !resuming {
                    return;
                }
                settle.draining = false;
                if settle.waiting {
                    return;
                }
                match settle.queue.pop_front() {
                    Some(step) => {
                        settle.draining = true;
                        step
                    }
                    None => {
                        if settle.armed && !settle.failed {
                            break;
                        }
                        return;
                    }
                }
            };
            resuming = true;
            let result = catch_unwind(AssertUnwindSafe(step)).unwrap_or_else(|_| {
                Err(VmxError::Other("child lifecycle step panicked".to_string()))
            });
            if let Err(error) = result {
                self.fail_children(generation, error);
                return;
            }
        }
        self.settle_children(generation, None);
    }

    /// Records a child failure. Once the container's action has returned
    /// (armed) it settles the transition now; while the action still runs it
    /// is kept, and the remaining child steps dropped, until the action
    /// returns, so the container publishes exactly one terminal status.
    fn fail_children(&self, generation: u64, error: VmxError) {
        let (error, dropped) = {
            let mut inner = lock(&self.inner);
            if !self.settle_is_current(&inner, generation) {
                return;
            }
            let Some(settle) = inner.child_settle.as_mut() else {
                return;
            };
            if settle.failed {
                return;
            }
            if settle.armed {
                (Some(error), VecDeque::new())
            } else {
                settle.failure = Some(error);
                settle.failed = true;
                settle.waiting = false;
                settle.draining = false;
                (None, std::mem::take(&mut settle.queue))
            }
        };
        drop(dropped);
        if let Some(error) = error {
            self.settle_children(generation, Some(error));
        }
    }

    /// Hands the terminal publication to the settle continuation when a
    /// child step is still pending after the container's action returned,
    /// or applies a child failure recorded while the action ran, on the
    /// calling thread.
    fn defer_until_children_settle(&self, generation: u64) -> bool {
        match self.arm_children_settle(generation) {
            ChildWalkOutcome::Settled => false,
            ChildWalkOutcome::Deferred => true,
            ChildWalkOutcome::Failed(error) => {
                self.settle_children(generation, Some(error));
                true
            }
        }
    }

    /// Arms the settle continuation once the container's action returned.
    /// A child failure recorded while the action ran is returned, and the
    /// caller publishes the rollback; the settle stays marked failed, so no
    /// other path publishes a terminal status in the meantime.
    fn arm_children_settle(&self, generation: u64) -> ChildWalkOutcome {
        let mut inner = lock(&self.inner);
        let pending = self.settle_is_current(&inner, generation)
            && inner.child_settle.as_ref().is_some_and(ChildSettle::busy);
        match inner.child_settle.as_mut() {
            Some(settle) if pending => {
                settle.armed = true;
                settle
                    .failure
                    .take()
                    .map_or(ChildWalkOutcome::Deferred, ChildWalkOutcome::Failed)
            }
            _ => {
                let cleared = inner.child_settle.take();
                drop(inner);
                drop(cleared);
                ChildWalkOutcome::Settled
            }
        }
    }

    /// Publishes a deferred container transition's terminal status: the
    /// target on success, the rollback status after a child failure. The
    /// failure reaches `background_errors`, as for a failing background
    /// hook. Disposal or a newer transition suppresses both.
    fn settle_children(&self, generation: u64, error: Option<VmxError>) {
        let (hub, errors) = {
            let inner = lock(&self.inner);
            (inner.hub.clone(), inner.background_errors.clone())
        };
        let emission = error.as_ref().and_then(|_| errors.begin_emission());
        // A queued step can own the last handle to a view-model, whose drop
        // locks the hub; drop the cleared settle only after `send_status`
        // releases the hub and core locks.
        let mut cleared = None;
        let published = self.send_status(&hub, || {
            let mut inner = lock(&self.inner);
            if !self.settle_is_current(&inner, generation) {
                return (false, None);
            }
            if inner.hook_admission_closed {
                // The inline dispose cascade has started: the commit is
                // dropped and the in-flight guard is cleared (spec/02 §7.2,
                // rule 4); dispose publishes Disposed.
                inner.transitioning = false;
                return (false, None);
            }
            // A sealed construct walk already flipped the state to
            // Constructed (see `seal_late_children`).
            let settled = match (inner.status, error.is_some()) {
                (ConstructionStatus::Constructing, false)
                | (ConstructionStatus::Constructed, false)
                | (ConstructionStatus::Destructing, true) => ConstructionStatus::Constructed,
                _ => ConstructionStatus::Destructed,
            };
            cleared = inner.child_settle.take();
            inner.status = settled;
            inner.transitioning = false;
            (
                true,
                Some(Message::ConstructionStatusChanged(
                    ConstructionStatusChangedMessage {
                        sender_id: inner.id,
                        sender_name: inner.name.clone(),
                        status: settled,
                    },
                )),
            )
        });
        if published {
            if let Some(error) = error {
                errors.send(error);
            }
        }
        drop(emission);
        drop(cleared);
        self.release_settle_waiters();
    }

    pub(crate) fn hub(&self) -> MessageHub {
        lock(&self.inner).hub.clone()
    }

    /// Detaches the core from its injected hub, so later lifecycle and
    /// property publications go to a disposed no-op hub instead.
    pub(crate) fn detach_hub(&self) {
        lock(&self.inner).hub = NullMessageHub::hub();
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

    /// Disposes the component and then runs `terminal`, the wrapper's own
    /// last teardown step (its commands, spec/02 §7). `terminal` runs only
    /// after the dispose hook, owned resources, and streams finish: on this
    /// thread when it completes the disposal, otherwise on the thread that
    /// does, whether that finishes a disposal deferred behind an admitted hook
    /// (§2.4) or is a concurrent disposer whose hook is still running.
    pub(crate) fn dispose_then(&self, terminal: impl FnOnce() + Send + 'static) -> VmxResult<()> {
        lock(&self.inner).terminal_cleanups.push(Box::new(terminal));
        self.finish_dispose()
    }

    /// Disposes a container or a leaf with members like
    /// [`Self::dispose_then`], with `cascade`, its child or member disposals,
    /// at the admitted-hook boundary (spec/02 §2.4, §7.1, LIFE-015). Hook
    /// admission closes first. With no hook admitted on another thread,
    /// `cascade` runs now, before this core publishes `Disposed` (LIFE-013,
    /// LIFE-018): this is the inline cascade, during which a construct,
    /// destruct, or reconstruct fails as from `Disposed` and no
    /// status other than `Disposed` commits (spec/02 §7.2, LIFE-021).
    /// Otherwise this core publishes `Disposed`, and `cascade` runs after
    /// that hook returns. It runs on this thread after its wait, or on the
    /// hook's thread when the wait would close a cycle. The owner calls this
    /// once, and it is the core's only disposal; a leaf without members uses
    /// [`Self::dispose_then`] and closes no admission.
    pub(crate) fn dispose_with_cascade_then(
        &self,
        cascade: DisposalCascade,
        terminal: impl FnOnce() + Send + 'static,
    ) -> VmxResult<()> {
        let now = {
            let mut inner = lock(&self.inner);
            inner.terminal_cleanups.push(Box::new(terminal));
            inner.hook_admission_closed = true;
            match inner.active_hook_owner {
                Some(owner) if owner != thread::current().id() => {
                    inner.disposal_cascade = Some(cascade);
                    None
                }
                _ => Some(cascade),
            }
        };
        let mut first_failure = now.and_then(run_disposal_cascade);
        retain_first_failure(&mut first_failure, || self.finish_dispose());
        finish_with_first_failure(first_failure)
    }

    /// Disposes a container like [`Self::dispose_with_cascade_then`], with
    /// its registered members (spec/02 §7.1) disposed after `children`, the
    /// container's own child cascade (ADR-0179). The members are taken when
    /// the disposal starts, so a member registered later is disposed by its
    /// registration. The owner calls this once, behind its own disposal
    /// guard.
    pub(crate) fn dispose_container_then(
        &self,
        children: DisposalCascade,
        terminal: impl FnOnce() + Send + 'static,
    ) -> VmxResult<()> {
        let members = self.begin_member_disposal().unwrap_or_default();
        // The cascade can be stored on the core behind a running hook, so it
        // holds the core weakly (#750).
        let core = self.downgrade();
        self.dispose_with_cascade_then(
            Box::new(move || {
                let mut first_failure = run_disposal_cascade(children);
                for member in members {
                    retain_first_failure(&mut first_failure, member);
                }
                if let Some(core) = core.upgrade() {
                    core.finish_member_disposal();
                }
                first_failure
            }),
            terminal,
        )
    }

    fn finish_dispose(&self) -> VmxResult<()> {
        let result = catch_unwind(AssertUnwindSafe(|| {
            self.transition(LifecycleOperation::Dispose)
        }));
        if lock(&self.inner).disposal_complete {
            self.run_terminal_cleanups();
        }
        let cleared = catch_unwind(AssertUnwindSafe(|| self.report_disposal_to_parent()));
        match (result, cleared) {
            (Err(payload), _) | (Ok(_), Err(payload)) => resume_unwind(payload),
            (Ok(result), Ok(cleared)) => result.and(cleared),
        }
    }

    /// Reports the `Disposed` publication to the owner once, after it was
    /// published and before `dispose()` returns, so a composite clears a
    /// disposed `current` child (spec/06 §4.3 rule 9, ADR-0189). No lock is
    /// held while the owner clears.
    fn report_disposal_to_parent(&self) -> VmxResult<()> {
        let report = {
            let mut inner = lock(&self.inner);
            if inner.status != ConstructionStatus::Disposed || inner.disposal_reported {
                None
            } else {
                inner.disposal_reported = true;
                inner.parent.clone().map(|parent| (inner.id, parent))
            }
        };
        report.map_or(Ok(()), |(id, parent)| parent.child_disposed(id))
    }

    fn complete_disposal(&self) {
        lock(&self.inner).disposal_complete = true;
        self.run_terminal_cleanups();
    }

    fn run_terminal_cleanups(&self) {
        let cleanups = std::mem::take(&mut lock(&self.inner).terminal_cleanups);
        for cleanup in cleanups {
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

    /// Commits the current flag without publishing it; returns whether it
    /// changed (spec/06 §4.3). On a `Disposed` node a commit to `false` sets
    /// the flag and reports no change to publish, and a commit to `true`
    /// changes nothing (spec/02 §3 invariant 3, ADR-0189).
    pub(crate) fn commit_current_flag(&self, selected: bool) -> bool {
        Self::commit_selected(&mut lock(&self.inner), selected)
    }

    fn commit_selected(inner: &mut ComponentCoreInner<D>, selected: bool) -> bool {
        if inner.status == ConstructionStatus::Disposed {
            if !selected {
                inner.selected = false;
            }
            return false;
        }
        if inner.selected == selected {
            false
        } else {
            inner.selected = selected;
            true
        }
    }

    /// Publishes the change of a flag that `commit_current_flag` committed.
    pub(crate) fn publish_current_flag(&self) {
        self.notify_property_changed("is_current");
    }

    pub(crate) fn set_current_flag(&self, selected: bool) {
        let changed = Self::commit_selected(&mut lock(&self.inner), selected);
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
            // A disposed view model's expansion is inert (disposal contract).
            if inner.status == ConstructionStatus::Disposed || inner.expanded == expanded {
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

#[cfg(test)]
impl MessageHub {
    pub(crate) fn observe_owner_wait(&self) -> wait_observation::Observation<'_> {
        wait_observation::observe(&self.inner.ready)
    }

    pub(crate) fn test_draining_owner(&self) -> Option<ThreadId> {
        lock(&self.inner.state).draining_owner
    }

    /// Whether `thread` has an open borrowed scope on this hub.
    pub(crate) fn test_is_borrower(&self, thread: ThreadId) -> bool {
        lock(&self.inner.state).is_borrower(thread)
    }

    /// Runs `body` in a borrowed scope of this hub on the current thread, as
    /// if its batch wait had closed a wait-for cycle (spec/03 §4.2).
    pub(crate) fn borrow_for_testing<R>(&self, body: impl FnOnce() -> R) -> R {
        let current = thread::current().id();
        lock(&self.inner.state).enter_borrow(current);
        self.run_scope(current, true, body)
    }
}

// Unit-test instrumentation only: pauses one core's construct or destruct on
// the current thread after its hook released the hook lease and before the
// transition commits (#1167).
#[cfg(test)]
pub(crate) mod commit_pause {
    use std::cell::RefCell;

    type Pause = Box<dyn FnOnce()>;

    thread_local! {
        static PAUSE: RefCell<Option<(usize, Pause)>> = const { RefCell::new(None) };
    }

    /// Runs `pause` once, in the next transition of core `core_id` on this
    /// thread, between the hook and the commit.
    pub(crate) fn arm(core_id: usize, pause: impl FnOnce() + 'static) {
        PAUSE.with(|slot| *slot.borrow_mut() = Some((core_id, Box::new(pause))));
    }

    pub(super) fn run(core_id: usize) {
        let pause = PAUSE.with(|slot| {
            let mut slot = slot.borrow_mut();
            match slot.take() {
                Some((id, pause)) if id == core_id => Some(pause),
                other => {
                    *slot = other;
                    None
                }
            }
        });
        if let Some(pause) = pause {
            pause();
        }
    }
}

#[cfg(test)]
mod commit_after_cascade_tests;

// Unit-test instrumentation only: holds a thread that a wait-for owner has
// just woken, before it removes its own wait edge (#1180, #1183). The hold
// runs without the waited-on lock, so other threads keep running.
#[cfg(test)]
pub(crate) mod wake_hold {
    use super::{lock, HashMap, Mutex, OnceLock, ThreadId};

    type Hold = Box<dyn FnOnce() + Send>;

    static HOLDS: OnceLock<Mutex<HashMap<ThreadId, Hold>>> = OnceLock::new();

    fn holds() -> &'static Mutex<HashMap<ThreadId, Hold>> {
        HOLDS.get_or_init(Mutex::default)
    }

    /// Runs `hold` once, on `thread`, when it next wakes from a recorded
    /// wait-for-owner wait.
    pub(crate) fn arm(thread: ThreadId, hold: impl FnOnce() + Send + 'static) {
        lock(holds()).insert(thread, Box::new(hold));
    }

    pub(super) fn armed(thread: ThreadId) -> bool {
        HOLDS
            .get()
            .is_some_and(|holds| lock(holds).contains_key(&thread))
    }

    pub(super) fn run(thread: ThreadId) {
        let hold = lock(holds()).remove(&thread);
        if let Some(hold) = hold {
            hold();
        }
    }
}

#[cfg(test)]
mod wait_graph_tests;

// Unit-test instrumentation only: observing the native wait must never gate it.
#[cfg(test)]
pub(crate) mod wait_observation {
    use super::{lock, Condvar, HashMap, Mutex, OnceLock, ThreadId};
    use std::sync::mpsc::{self, Receiver, Sender};

    static OBSERVERS: OnceLock<Mutex<HashMap<usize, Sender<ThreadId>>>> = OnceLock::new();

    pub(crate) struct Observation<'a> {
        condition: &'a Condvar,
        pub(crate) entered: Receiver<ThreadId>,
    }

    pub(crate) fn observe(condition: &Condvar) -> Observation<'_> {
        let (sender, entered) = mpsc::channel();
        let mut observers = lock(OBSERVERS.get_or_init(Mutex::default));
        let key = condition as *const Condvar as usize;
        assert!(!observers.contains_key(&key), "condition already observed");
        observers.insert(key, sender);
        Observation { condition, entered }
    }

    pub(super) fn entered(condition: &Condvar) {
        let sender = OBSERVERS.get().and_then(|observers| {
            lock(observers)
                .get(&(condition as *const Condvar as usize))
                .cloned()
        });
        if let Some(sender) = sender {
            let _ = sender.send(std::thread::current().id());
        }
    }

    impl Drop for Observation<'_> {
        fn drop(&mut self) {
            lock(OBSERVERS.get().expect("registered observer"))
                .remove(&(self.condition as *const Condvar as usize));
        }
    }

    #[test]
    fn wait_observers_are_instance_scoped_and_removed_on_unwind() {
        let first = Condvar::new();
        let second = Condvar::new();
        let observed = observe(&first);
        entered(&second);
        assert!(observed.entered.try_recv().is_err());
        entered(&first);
        assert_eq!(
            observed.entered.try_recv().unwrap(),
            std::thread::current().id()
        );
        drop(observed);
        let failure = std::panic::catch_unwind(|| {
            let _observed = observe(&first);
            panic!("exercise registration cleanup");
        });
        assert!(failure.is_err());
        let observed = observe(&first);
        entered(&first);
        assert!(observed.entered.try_recv().is_ok());
    }
}

#[cfg(test)]
mod hub_subscriber_tests {
    use super::{lock, Arc, Message, MessageHub, Mutex};

    fn tick() -> Message {
        Message::Custom {
            sender_id: 1,
            sender_name: "test".into(),
            name: "tick".into(),
        }
    }

    fn counting(hub: &MessageHub) -> (Arc<Mutex<usize>>, super::Subscription) {
        let count = Arc::new(Mutex::new(0));
        let sink = Arc::clone(&count);
        let subscription = hub.subscribe(move |_| *lock(&sink) += 1);
        (count, subscription)
    }

    /// #766 — every removal path clears the flag a copied subscriber list
    /// checks, so a copy taken before the removal no longer delivers.
    #[test]
    fn every_removal_path_deactivates_a_copied_subscriber() {
        let hub = MessageHub::new();
        let (disposed_count, disposed) = counting(&hub);
        let (dropped_count, dropped) = counting(&hub);
        let (kept_count, _kept) = counting(&hub);
        let copied = lock(&hub.inner.state)
            .subscribers
            .values()
            .map(Arc::clone)
            .collect::<Vec<_>>();

        disposed.dispose();
        drop(dropped);
        for subscriber in &copied {
            subscriber.deliver(&tick());
        }
        assert_eq!(*lock(&disposed_count), 0);
        assert_eq!(*lock(&dropped_count), 0);
        assert_eq!(*lock(&kept_count), 1);

        hub.dispose();
        for subscriber in &copied {
            subscriber.deliver(&tick());
        }
        assert_eq!(*lock(&kept_count), 1);
    }
}

#[cfg(test)]
mod message_recorder_tests {
    use super::{lock, Message, MessageHub};

    fn tick() -> Message {
        Message::Custom {
            sender_id: 1,
            sender_name: "test".into(),
            name: "tick".into(),
        }
    }

    #[test]
    fn a_hub_without_recorders_holds_no_message_after_heavy_traffic() {
        let hub = MessageHub::new();
        let _subscription = hub.subscribe(|_| {});

        for _ in 0..100_000 {
            hub.send(tick());
        }

        let state = lock(&hub.inner.state);
        assert!(state.pending.is_empty());
        assert!(state.recorders.is_empty());
    }

    #[test]
    fn dropped_and_disposed_recorders_leave_no_registration() {
        let hub = MessageHub::new();
        let disposed = hub.record(4);
        drop(hub.record(4));
        disposed.dispose();

        hub.send(tick());

        assert!(lock(&hub.inner.state).recorders.is_empty());
        assert!(disposed.is_empty());
    }

    #[test]
    fn hub_disposal_releases_every_recorder_registration() {
        let hub = MessageHub::new();
        let recorder = hub.record(4);

        hub.dispose();

        assert!(lock(&hub.inner.state).recorders.is_empty());
        assert!(!recorder.is_active());
    }
}

// A deferred compensation destruct reports its failure on the child's own
// background-failure stream, never on the container's (ADR-0218 rule 7).
#[cfg(test)]
mod deferred_compensation_tests {
    use super::{
        compensate_auto_start, lock, ConstructionStatus, LifecycleErrorStream,
        LifecycleSettleCallback, VmNode, VmxError, VmxResult,
    };
    use std::sync::{Arc, Mutex};

    /// A background child whose construct is in flight and whose destruct fails.
    #[derive(Clone)]
    struct Child {
        status: Arc<Mutex<ConstructionStatus>>,
        settle: Arc<Mutex<Option<LifecycleSettleCallback>>>,
        errors: LifecycleErrorStream,
    }

    impl PartialEq for Child {
        fn eq(&self, other: &Self) -> bool {
            Arc::ptr_eq(&self.status, &other.status)
        }
    }

    impl VmNode for Child {
        fn id(&self) -> usize {
            1
        }
        fn construct(&self) -> VmxResult<()> {
            Ok(())
        }
        fn destruct(&self) -> VmxResult<()> {
            Err(VmxError::Other("destruct failed".into()))
        }
        fn dispose(&self) -> VmxResult<()> {
            Ok(())
        }
        fn status(&self) -> ConstructionStatus {
            *lock(&self.status)
        }
        fn set_parent_id(&self, _parent_id: Option<usize>) {}
        fn parent_id(&self) -> Option<usize> {
            None
        }
        fn when_lifecycle_settled(&self, callback: LifecycleSettleCallback) -> bool {
            *lock(&self.settle) = Some(callback);
            true
        }
        fn background_failure_stream(&self) -> Option<LifecycleErrorStream> {
            Some(self.errors.clone())
        }
    }

    #[test]
    fn deferred_destruct_failure_reaches_the_child_stream() {
        let child = Child {
            status: Arc::new(Mutex::new(ConstructionStatus::Constructing)),
            settle: Arc::new(Mutex::new(None)),
            errors: LifecycleErrorStream::new(),
        };
        let received = Arc::new(Mutex::new(Vec::new()));
        let _subscription = {
            let received = received.clone();
            child
                .errors
                .subscribe(move |error| lock(&received).push(error.to_string()))
        };

        assert!(compensate_auto_start(&child, ConstructionStatus::Destructed).is_none());
        *lock(&child.status) = ConstructionStatus::Constructed;
        let settle = lock(&child.settle)
            .take()
            .expect("the rollback defers the destruct");
        settle();

        let received = lock(&received);
        assert_eq!(received.len(), 1);
        assert!(received[0].contains("destruct failed"));
    }
}
