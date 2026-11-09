use crate::runtime::wait_for_owner;
use crate::wait_for_graph::{waits, Resource};

use super::{
    catch_unwind, clone_locked, lock, resume_unwind, thread, wait, Arc, AssertUnwindSafe,
    AtomicBool, AtomicU64, BTreeMap, ComponentVm, Condvar, FormRevertedMessage, Message,
    MessageHub, Mutex, NullDispatcher, NullMessageHub, OnceLock, Ordering, RelayCommand,
    RelayCommandBuilder, ThreadId, VmxError, VmxResult, Weak,
};

type FormPersister<M> = Arc<dyn Fn(&M) -> VmxResult<()> + Send + Sync>;
type FormSnapshotter<M> = Arc<dyn Fn(&M) -> M + Send + Sync>;
type FormResetOnApproved<M> = Arc<dyn Fn(&M) -> VmxResult<M> + Send + Sync>;
type FieldValidator<M> = Arc<dyn Fn(&M) -> Option<String> + Send + Sync>;
type ModelValidator<M> = Arc<dyn Fn(&M) -> BTreeMap<String, Option<String>> + Send + Sync>;
type ApprovedCallback<M> = Arc<dyn Fn(M) + Send + Sync>;

/// Approval callbacks keyed by registration, so one can detach without
/// disturbing the others. Disposal sets `closed` under the same lock, so a
/// registration racing disposal is rejected instead of retained.
struct ApprovedRegistry<M> {
    next_id: u64,
    entries: Vec<(u64, ApprovedCallback<M>)>,
    closed: bool,
}

impl<M> ApprovedRegistry<M> {
    fn new() -> Self {
        Self {
            next_id: 0,
            entries: Vec::new(),
            closed: false,
        }
    }

    fn register(&mut self, callback: ApprovedCallback<M>) -> Result<u64, ApprovedCallback<M>> {
        if self.closed {
            return Err(callback);
        }
        let id = self.next_id;
        self.next_id += 1;
        self.entries.push((id, callback));
        Ok(id)
    }

    fn is_registered(&self, id: u64) -> bool {
        self.entries.iter().any(|(entry, _)| *entry == id)
    }

    fn remove(&mut self, id: u64) -> Option<ApprovedCallback<M>> {
        let index = self.entries.iter().position(|(entry, _)| *entry == id)?;
        Some(self.entries.remove(index).1)
    }
}

/// A detachable registration made by [`FormVm::subscribe_approved`].
///
/// [`dispose`](Self::dispose) or dropping the handle removes only this
/// registration and releases the callback and its captures, unless an
/// approval is invoking it at that moment. Repeated disposal is inert. A
/// registration made after the form is disposed is inactive from the start.
pub struct ApprovalSubscription {
    active: AtomicBool,
    registered: Box<dyn Fn() -> bool + Send + Sync>,
    detach: Box<dyn Fn() + Send + Sync>,
}

impl ApprovalSubscription {
    fn new<M: Send + 'static>(id: u64, registry: Weak<Mutex<ApprovedRegistry<M>>>) -> Self {
        let observed = registry.clone();
        Self {
            active: AtomicBool::new(true),
            registered: Box::new(move || {
                observed
                    .upgrade()
                    .is_some_and(|registry| lock(&registry).is_registered(id))
            }),
            detach: Box::new(move || {
                if let Some(registry) = registry.upgrade() {
                    // Drop the callback after releasing the lock: its
                    // captures may run code that touches the form.
                    let removed = lock(&registry).remove(id);
                    drop(removed);
                }
            }),
        }
    }

    fn inactive() -> Self {
        Self {
            active: AtomicBool::new(false),
            registered: Box::new(|| false),
            detach: Box::new(|| {}),
        }
    }

    /// Reports whether this registration still receives approvals.
    ///
    /// Becomes `false` after [`dispose`](Self::dispose) or when the form is
    /// disposed.
    pub fn is_active(&self) -> bool {
        self.active.load(Ordering::SeqCst) && (self.registered)()
    }

    /// Detaches the callback; repeated calls are inert.
    pub fn dispose(&self) {
        if self.active.swap(false, Ordering::SeqCst) {
            (self.detach)();
        }
    }
}

impl Drop for ApprovalSubscription {
    fn drop(&mut self) {
        self.dispose();
    }
}

fn error_updates(errors: BTreeMap<String, String>) -> BTreeMap<String, Option<String>> {
    errors
        .into_iter()
        .map(|(field, error)| (field, Some(error)))
        .collect()
}

/// A `set_model` or revert queued in an approval's pre-publication window
/// (spec/20 §5.3, ADR-0174), or a refused call of another thread (spec/20
/// §5.5, ADR-0176). It replays as a new call.
enum QueuedUpdate<M> {
    Assign(M),
    Revert,
    /// The revalidation of a validator registration whose wait was refused.
    /// The validator is already registered; only its revalidation waits.
    Revalidate,
}

/// A form's publication state (spec/20 §5.3 and §5.5, ADR-0174, ADR-0176).
///
/// A *publication scope* is a span in which one thread, the publisher,
/// delivers form notifications while other threads' form calls wait. An
/// update holds one over its `errors_changed` send, and a settlement holds one
/// from settlement step 1 until its approval subscribers have run, or, when it
/// failed, until its eligibility change returns. Scopes nest on the
/// publisher's thread, and a call never waits for a scope its own thread
/// holds.
///
/// Each publisher keeps its own queue: the updates of its pre-publication
/// windows, and the updates of other threads whose wait for its scope would
/// have closed a wait-for cycle. Only that thread replays it, when its
/// outermost publication ends, so another thread's settlement never replays
/// it (#1160).
struct Publications<M> {
    publishers: Vec<Publisher<M>>,
    /// Counts the threads waiting for a scope, so a closing scope with no
    /// waiter skips the wait-for graph.
    waiters: usize,
    /// Counts the [`Delivery`] spans in progress on any thread.
    deliveries: usize,
    /// The threads whose update [`Delivery`] spans are still preparing, once
    /// per span.
    preparing: Vec<ThreadId>,
    /// The deferred teardown of a disposed form. A `dispose()` leaves it here
    /// when its wait for a scope was refused, or when a delivery outside a
    /// scope was in progress. It runs when no publication and no delivery
    /// remains, on the thread that ends the last one (spec/20 §5.5).
    teardown: Option<Teardown>,
}

/// The deferred §10 teardown of a `dispose()`.
type Teardown = Box<dyn FnOnce() + Send>;

/// One thread's entry in [`Publications::publishers`].
struct Publisher<M> {
    thread: ThreadId,
    /// The thread's open publications: approval windows, from the start of
    /// the post-persist commit until the settlement ends, and updates that
    /// opened a scope, until they return. The queue replays when it reaches
    /// zero (#1061).
    depth: usize,
    /// The thread's open publication scopes. While it is above zero, other
    /// threads' calls wait.
    scopes: usize,
    /// Whether the thread's innermost settlement is in its pre-publication
    /// window: from the start of the post-persist commit until `OnApproved`
    /// delivery starts. It is a flag, not a depth: each settlement saves the
    /// enclosing value, clears the flag before its subscribers run and
    /// restores it when it ends. A nested settlement's subscribers therefore
    /// edit at once, even when the settlement started in an outer
    /// settlement's notifications (#1160).
    pre_publishing: bool,
    /// The queued updates, in the order they joined.
    queued: Vec<QueuedUpdate<M>>,
}

impl<M> Publications<M> {
    fn entry(&mut self, thread: ThreadId) -> Option<&mut Publisher<M>> {
        self.publishers
            .iter_mut()
            .find(|entry| entry.thread == thread)
    }

    fn pre_publishing(&self, thread: ThreadId) -> bool {
        self.publishers
            .iter()
            .any(|entry| entry.thread == thread && entry.pre_publishing)
    }

    fn holds_scope(&self, thread: ThreadId) -> bool {
        self.publishers
            .iter()
            .any(|entry| entry.thread == thread && entry.scopes > 0)
    }

    /// Returns a thread other than `current` that holds a scope.
    fn foreign_publisher(&self, current: ThreadId) -> Option<ThreadId> {
        self.publishers
            .iter()
            .find(|entry| entry.thread != current && entry.scopes > 0)
            .map(|entry| entry.thread)
    }

    fn waiters(&mut self) -> &mut usize {
        &mut self.waiters
    }
}

/// The shared publication state of a form and the condition its waiters
/// wait on.
struct PublicationControl<M> {
    state: Mutex<Publications<M>>,
    closed: Condvar,
}

impl<M> PublicationControl<M> {
    fn new() -> Self {
        Self {
            state: Mutex::new(Publications {
                publishers: Vec::new(),
                waiters: 0,
                deliveries: 0,
                preparing: Vec::new(),
                teardown: None,
            }),
            closed: Condvar::new(),
        }
    }

    /// The form's publication scopes, as one wait-for graph resource.
    fn resource(&self) -> Resource {
        Resource::FormPublication(std::ptr::from_ref(self) as usize)
    }

    /// Waits until `owner` no longer holds a scope, recording the wait in
    /// the wait-for graph (spec/20 §5.5, ADR-0176). Returns `false`, without
    /// waiting, when the wait would close a live wait-for cycle. Returns
    /// `true` at once when `owner` holds no scope or the form is disposed. A
    /// wake for any reason returns `true`, and the caller checks again.
    fn wait_for_scope(&self, owner: ThreadId, disposed: &Mutex<bool>) -> bool {
        let state = lock(&self.state);
        // Disposal is checked under the state lock, which a disposal holds
        // while it marks the form and wakes the waiters, so no wake is lost.
        if !state.holds_scope(owner) || *lock(disposed) {
            return true;
        }
        let (_state, refused) = wait_for_owner(
            &self.state,
            &self.closed,
            state,
            Publications::waiters,
            self.resource(),
            owner,
        );
        !refused
    }

    /// Closes one of `thread`'s scopes. The last one removes the edges that
    /// name the thread before it wakes the waiters (ADR-0172 rule 3).
    fn close_scope(&self, thread: ThreadId) {
        let mut state = lock(&self.state);
        let Some(entry) = state.entry(thread) else {
            return;
        };
        entry.scopes -= 1;
        if entry.scopes > 0 {
            return;
        }
        if state.waiters > 0 {
            let holders = state
                .publishers
                .iter()
                .filter(|entry| entry.scopes > 0)
                .map(|entry| entry.thread)
                .collect::<Vec<_>>();
            waits().release_waiters(self.resource(), &holders);
        }
        drop(state);
        self.closed.notify_all();
    }
}

/// What a publication hands to its thread when it was the outermost one: the
/// queued updates to replay, and a deferred teardown to run after them.
struct Finished<M> {
    queued: Vec<QueuedUpdate<M>>,
    teardown: Option<Teardown>,
}

/// One publication on this thread: an approval window, or an update that
/// opened a scope. It counts in [`Publisher::depth`] until it finishes, also
/// when a notification observer panics, and then restores the enclosing
/// settlement's pre-publication flag.
struct Publication<M> {
    control: Arc<PublicationControl<M>>,
    thread: ThreadId,
    outer_pre_publishing: bool,
    scope_open: bool,
    finished: bool,
}

impl<M> Publication<M> {
    /// Starts a publication on this thread. An approval window passes
    /// `Some(true)`, which opens its pre-publication window; an update passes
    /// `None`, which keeps the enclosing flag.
    fn enter(control: &Arc<PublicationControl<M>>, pre_publishing: Option<bool>) -> Self {
        let thread = thread::current().id();
        let mut state = lock(&control.state);
        let outer_pre_publishing = if let Some(entry) = state.entry(thread) {
            entry.depth += 1;
            entry.pre_publishing
        } else {
            state.publishers.push(Publisher {
                thread,
                depth: 1,
                scopes: 0,
                pre_publishing: false,
                queued: Vec::new(),
            });
            false
        };
        if let Some(pre_publishing) = pre_publishing {
            if let Some(entry) = state.entry(thread) {
                entry.pre_publishing = pre_publishing;
            }
        }
        drop(state);
        Self {
            control: Arc::clone(control),
            thread,
            outer_pre_publishing,
            scope_open: false,
            finished: false,
        }
    }

    /// Opens this publication's scope. The caller holds the update lock, and
    /// it checked under that lock that no other thread holds a scope, unless
    /// its wait was refused.
    fn open_scope(&mut self) {
        if self.scope_open {
            return;
        }
        if let Some(entry) = lock(&self.control.state).entry(self.thread) {
            entry.scopes += 1;
            self.scope_open = true;
        }
    }

    fn close_scope(&mut self) {
        if std::mem::take(&mut self.scope_open) {
            self.control.close_scope(self.thread);
        }
    }

    /// Ends the pre-publication window and keeps the publication open.
    fn end_pre_publication(&self) {
        if let Some(entry) = lock(&self.control.state).entry(self.thread) {
            entry.pre_publishing = false;
        }
    }

    /// Ends this publication. Returns the thread's queue when it was the
    /// thread's outermost publication, and a deferred teardown when no
    /// publication and no [`Delivery`] remains on any thread.
    fn finish(mut self) -> Finished<M> {
        self.finished = true;
        self.leave()
    }

    fn leave(&mut self) -> Finished<M> {
        self.close_scope();
        let mut state = lock(&self.control.state);
        let mut finished = Finished {
            queued: Vec::new(),
            teardown: None,
        };
        let Some(index) = state
            .publishers
            .iter()
            .position(|entry| entry.thread == self.thread)
        else {
            return finished;
        };
        let entry = &mut state.publishers[index];
        entry.pre_publishing = self.outer_pre_publishing;
        entry.depth -= 1;
        if entry.depth > 0 {
            return finished;
        }
        finished.queued = state.publishers.swap_remove(index).queued;
        if state.publishers.is_empty() && state.deliveries == 0 {
            finished.teardown = state.teardown.take();
        }
        finished
    }
}

impl<M> Drop for Publication<M> {
    fn drop(&mut self) {
        if !self.finished {
            // Only an unexpected unwind gets here. The thread's queue cannot
            // replay during it and is dropped; a deferred teardown still runs.
            let Finished { queued, teardown } = self.leave();
            drop(queued);
            if let Some(teardown) = teardown {
                let _ = catch_unwind(AssertUnwindSafe(teardown));
            }
        }
    }
}

/// A span in which a form call delivers notifications outside a publication
/// scope (spec/20 §5.5, ADR-0176 §2.2): an approval's admission notification,
/// an update or a validator registration from its admission until it
/// returns, or an `approve_errors` send. An update counts from its admission,
/// so a `dispose()` on another thread during its preparation defers the
/// teardown until it returns (spec/20 §5.4, ADR-0215).
///
/// Other threads' calls do not wait for it. A `dispose()` meanwhile marks the
/// form disposed at once, but its teardown waits until no delivery and no
/// publication remains, so no channel completes during a delivery. A
/// `dispose()` from a preparation callback on the preparing thread is the
/// exception: it tears down at once, as no notification is in progress. The
/// span that ends last hands the teardown to its thread. Dropping an unended
/// span during an unwind runs that teardown under an unwind guard.
struct Delivery<M> {
    control: Arc<PublicationControl<M>>,
    /// The thread of an update span that is still preparing.
    preparing: Option<ThreadId>,
    ended: bool,
}

impl<M> Delivery<M> {
    /// Starts a delivery, unless the form is disposed. Disposal is checked
    /// under the state lock, which a disposal holds while it marks the form,
    /// so a disposal either sees this delivery or this call sees the mark.
    fn begin(control: &Arc<PublicationControl<M>>, disposed: &Mutex<bool>) -> Option<Self> {
        Self::start(control, disposed, None)
    }

    /// Starts an update's span in its preparation, unless the form is
    /// disposed.
    fn begin_preparation(
        control: &Arc<PublicationControl<M>>,
        disposed: &Mutex<bool>,
    ) -> Option<Self> {
        Self::start(control, disposed, Some(thread::current().id()))
    }

    fn start(
        control: &Arc<PublicationControl<M>>,
        disposed: &Mutex<bool>,
        preparing: Option<ThreadId>,
    ) -> Option<Self> {
        let mut state = lock(&control.state);
        if *lock(disposed) {
            return None;
        }
        state.deliveries += 1;
        state.preparing.extend(preparing);
        Some(Self {
            control: Arc::clone(control),
            preparing,
            ended: false,
        })
    }

    /// Ends the preparation of an update's span. The span then delivers.
    fn prepared(&mut self) {
        if let Some(thread) = self.preparing.take() {
            Self::leave_preparation(&mut lock(&self.control.state), thread);
        }
    }

    fn leave_preparation(state: &mut Publications<M>, thread: ThreadId) {
        if let Some(index) = state.preparing.iter().position(|entry| *entry == thread) {
            state.preparing.swap_remove(index);
        }
    }

    /// Ends the delivery. Returns the deferred teardown for the caller to run
    /// when this was the last delivery and no publication remains.
    fn end(mut self) -> Option<Teardown> {
        self.ended = true;
        self.release()
    }

    fn release(&mut self) -> Option<Teardown> {
        let mut state = lock(&self.control.state);
        if let Some(thread) = self.preparing.take() {
            Self::leave_preparation(&mut state, thread);
        }
        state.deliveries -= 1;
        if state.deliveries == 0 && state.publishers.is_empty() {
            state.teardown.take()
        } else {
            None
        }
    }
}

impl<M> Drop for Delivery<M> {
    fn drop(&mut self) {
        if !self.ended {
            if let Some(teardown) = self.release() {
                let _ = catch_unwind(AssertUnwindSafe(teardown));
            }
        }
    }
}

/// How a form call proceeds after its wait for other threads' publication
/// scopes (spec/20 §5.5), with the update lock held.
struct Serialized<'a> {
    guard: UpdateGuard<'a>,
    /// The publisher whose scope the call's refused wait named, when that
    /// wait would have closed a wait-for cycle.
    refused_by: Option<ThreadId>,
}

/// Where a prepared update goes (spec/20 §5.3 and §5.5).
enum Placement<M> {
    /// No queue takes it: the caller commits it.
    Commit(QueuedUpdate<M>),
    /// It joined a queue, or its preparation was stale.
    Done,
    /// The publisher that refused its wait ended its publications during the
    /// preparation, so the call runs again.
    Retry(QueuedUpdate<M>),
}

/// A panic payload kept to resume after the queued updates replay.
type PanicPayload = Box<dyn std::any::Any + Send>;

/// The queued notifications of nested calls (spec/20 §5.4, ADR-0180).
///
/// A call is nested when it comes from a preparation callback of a
/// `set_model`, `revert` or validator registration, or from an
/// `errors_changed` subscriber that the outermost update on its thread
/// delivers. It sends nothing before it returns: it adds its notifications to
/// the queue of the outermost update, which sends them with no form lock held.
struct NestedUpdates<M> {
    /// The threads that run update frames. Only the owning thread adds to,
    /// changes or removes its entry.
    frames: Vec<Frames<M>>,
    /// The threads that send the error maps of their outermost update, each
    /// with the notifications that its `errors_changed` subscribers' calls
    /// queued. Only the owning thread adds to or takes from an entry.
    error_deliveries: Vec<(ThreadId, Notices<M>)>,
}

/// One thread's update frames (spec/20 §5.4, ADR-0215). The entry exists
/// while at least one frame runs on the thread.
struct Frames<M> {
    thread: ThreadId,
    /// The frames that run on the thread, nested ones included.
    depth: usize,
    /// The notifications that nested frames queued for the outermost one.
    pending: Notices<M>,
    /// Counts the commits that the thread made. A preparation that saw it
    /// move was overtaken by a nested update, so it is stale.
    commits: u64,
    /// Counts the updates that the thread queued, with the same effect.
    queued: u64,
}

impl<M> NestedUpdates<M> {
    fn new() -> Self {
        Self {
            frames: Vec::new(),
            error_deliveries: Vec::new(),
        }
    }

    /// The frames of `thread`, while one runs.
    fn frames(&mut self, thread: ThreadId) -> Option<&mut Frames<M>> {
        self.frames.iter_mut().find(|entry| entry.thread == thread)
    }

    /// Starts a frame on `thread`.
    fn enter(&mut self, thread: ThreadId) {
        if let Some(entry) = self.frames(thread) {
            entry.depth += 1;
        } else {
            self.frames.push(Frames {
                thread,
                depth: 1,
                pending: Notices::default(),
                commits: 0,
                queued: 0,
            });
        }
    }

    /// The queue that a nested call on `thread` adds its notifications to:
    /// the pending queue of its frames, else the queue of its
    /// `errors_changed` delivery. `None` when the call is not nested.
    fn nested_queue(&mut self, thread: ThreadId) -> Option<&mut Notices<M>> {
        if let Some(index) = self.frames.iter().position(|entry| entry.thread == thread) {
            return Some(&mut self.frames[index].pending);
        }
        self.error_delivery(thread)
    }

    /// The queue of `thread`'s `errors_changed` delivery, when it makes one.
    fn error_delivery(&mut self, thread: ThreadId) -> Option<&mut Notices<M>> {
        self.error_deliveries
            .iter_mut()
            .rev()
            .find(|(entry, _)| *entry == thread)
            .map(|(_, notices)| notices)
    }
}

/// Notifications that an update sends with no form lock held.
struct Notices<M> {
    /// The update scopes of commits that changed the errors, in commit order.
    /// Each sends one `errors_changed` inside its scope (spec/20 §5.5).
    errors: Vec<Publication<M>>,
    /// The other notifications, in the order the calls committed or were
    /// admitted.
    after: Vec<Notice>,
    /// The admitted nested approvals, whose persisters start after the
    /// notifications (spec/20 §5.4 rule 4).
    starts: Vec<(ApprovalFlight, M)>,
}

impl<M> Default for Notices<M> {
    fn default() -> Self {
        Self {
            errors: Vec::new(),
            after: Vec::new(),
            starts: Vec::new(),
        }
    }
}

impl<M> Notices<M> {
    fn append(&mut self, other: Self) {
        self.errors.extend(other.errors);
        self.after.extend(other.after);
        self.starts.extend(other.starts);
    }

    /// Marks these notifications as queued by a nested call, so they are
    /// dropped once the form is disposed (spec/20 §5.4 rule 6).
    fn nested(mut self) -> Self {
        for notice in &mut self.after {
            if let Notice::Reverted { nested } = notice {
                *nested = true;
            }
        }
        self
    }
}

/// A queued notification other than `errors_changed`. Every kind but
/// [`Notice::Reverted`] already sends nothing on a disposed form.
enum Notice {
    /// The approve command's eligibility change of an update, when its gates
    /// moved from the first value to the second.
    Eligibility(bool, bool),
    /// The `"model"` hub message.
    Model,
    /// The [`FormRevertedMessage`] of a revert. A nested one is dropped once
    /// the form is disposed; the outermost update's own one is not.
    Reverted { nested: bool },
    /// The eligibility change of a nested approval's admission.
    Admission,
    /// The eligibility change of a revalidation, when [`FormVm::can_approve`]
    /// moved from this value.
    Revalidated(bool),
}

/// What an update's preparation and commit hand to [`FormVm::run_update`].
struct Step<M> {
    /// The update's own notifications.
    notices: Notices<M>,
    /// The update to run again, because the publisher that refused its wait
    /// ended its publications during the preparation.
    retry: Option<QueuedUpdate<M>>,
    /// An uncommitted preparation, dropped after the update lock is released.
    discarded: Option<PreparedUpdate<M>>,
}

impl<M> Default for Step<M> {
    fn default() -> Self {
        Self {
            notices: Notices::default(),
            retry: None,
            discarded: None,
        }
    }
}

/// The in-flight mark of the one admitted approval (spec/20 §5.3,
/// ADR-0143).
///
/// [`admit`](Self::admit) sets the mark only when it was clear. Dropping the
/// flight clears it, so every exit path clears it, including a panicking
/// persister, reset, or snapshotter.
struct ApprovalFlight {
    in_flight: Arc<AtomicBool>,
}

impl ApprovalFlight {
    fn admit(in_flight: &Arc<AtomicBool>) -> Option<Self> {
        in_flight
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .ok()
            .map(|_| Self {
                in_flight: Arc::clone(in_flight),
            })
    }
}

impl Drop for ApprovalFlight {
    fn drop(&mut self) {
        self.in_flight.store(false, Ordering::SeqCst);
    }
}

/// Serializes a form's commits, approval admission and disposal (spec/20
/// §5.4, ADR-0144, ADR-0215).
///
/// No consumer callback runs while it is held, so another thread waits only
/// for a short commit. The lock is re-entrant, and [`UpdateGuard`] releases it
/// on every exit path, a panic included. Its state mutex is held only to
/// change the owner and depth.
struct UpdateLock {
    owner: Mutex<UpdateOwner>,
    released: Condvar,
}

struct UpdateOwner {
    thread: Option<ThreadId>,
    depth: usize,
}

impl UpdateLock {
    fn new() -> Self {
        Self {
            owner: Mutex::new(UpdateOwner {
                thread: None,
                depth: 0,
            }),
            released: Condvar::new(),
        }
    }

    /// Reports whether this thread holds the lock.
    fn is_held_by_current(&self) -> bool {
        lock(&self.owner).thread == Some(thread::current().id())
    }

    fn acquire(&self) -> UpdateGuard<'_> {
        let current = thread::current().id();
        let mut owner = lock(&self.owner);
        while owner.thread.is_some_and(|thread| thread != current) {
            owner = wait(&self.released, owner);
        }
        owner.thread = Some(current);
        owner.depth += 1;
        UpdateGuard { lock: self }
    }
}

/// One acquisition of an [`UpdateLock`]; dropping it releases that level.
struct UpdateGuard<'a> {
    lock: &'a UpdateLock,
}

impl Drop for UpdateGuard<'_> {
    fn drop(&mut self) {
        // Taken during an unwind, the state mutex is not poisoned on release.
        let mut owner = lock(&self.lock.owner);
        owner.depth -= 1;
        if owner.depth == 0 {
            owner.thread = None;
            drop(owner);
            self.lock.released.notify_all();
        }
    }
}

/// The next form state computed by a model update's preparation, before any
/// of it is committed (spec/20 §5.4, ADR-0144).
struct PreparedUpdate<M> {
    model: M,
    errors: BTreeMap<String, String>,
    /// Whether the validity and strict-mode gates admitted approval before
    /// the update.
    was_eligible: bool,
    /// Whether they admit approval after it.
    eligible: bool,
}

/// What a preparation read before its first callback (spec/20 §5.4,
/// ADR-0215).
#[derive(Clone, Copy)]
struct Base {
    /// The form's commit generation.
    generation: u64,
    /// The thread's own commit and queue counts (see [`Frames`]).
    commits: u64,
    queued: u64,
}

/// The validation errors, kept in step with the model they belong to (#770).
///
/// The model lives in the component's mutex, so a commit cannot replace both
/// under one lock without nesting the two mutexes. A user `Clone` runs under
/// the model mutex and may read the errors, so nesting them could deadlock.
/// A commit therefore stages the next errors with the model generation read
/// before it installs the model. Readers use the staged errors once the
/// generation has moved past that value, which is when they can see the new
/// model.
struct ErrorState {
    committed: BTreeMap<String, String>,
    staged: Option<(u64, BTreeMap<String, String>)>,
}

impl ErrorState {
    fn new() -> Self {
        Self {
            committed: BTreeMap::new(),
            staged: None,
        }
    }
}

#[derive(Clone)]
/// Editable model state with validation, persistence, approval, and revert commands.
///
/// A validator registration made after [`dispose`](Self::dispose)
/// ([`with_validator`](Self::with_validator),
/// [`with_field_validator`](Self::with_field_validator),
/// [`with_model_validator`](Self::with_model_validator),
/// [`with_clearing_model_validator`](Self::with_clearing_model_validator))
/// has no effect.
///
/// # Re-entrant `Clone`
///
/// The form runs `M::clone` while it holds the lock of the value that it
/// clones, the live model or the snapshot. These locks are not re-entrant. A
/// model `Clone` must therefore not call a method of its own form that reads
/// the model or the snapshot on the same thread, for example
/// [`model`](Self::model), [`snapshot`](Self::snapshot),
/// [`is_dirty`](Self::is_dirty) and [`set_model`](Self::set_model).
/// [`approve`](Self::approve), [`revert`](Self::revert) and the
/// [`approve_command`](Self::approve_command) and
/// [`deny_command`](Self::deny_command) commands also read the model or the
/// snapshot. [`can_approve`](Self::can_approve) calls `is_dirty` in strict
/// mode, so the same limit applies to it there. Such a call never returns.
///
/// A model `Clone` can read the validation errors through
/// [`is_valid`](Self::is_valid), [`errors`](Self::errors),
/// [`error_map`](Self::error_map) and [`field_error`](Self::field_error).
/// These reads take only the error lock, never the model or snapshot lock.
pub struct FormVm<M: Clone + PartialEq + Send + 'static> {
    pub(crate) component: ComponentVm<M>,
    snapshot: Arc<Mutex<M>>,
    persister: FormPersister<M>,
    snapshotter: FormSnapshotter<M>,
    reset_on_approved: Option<FormResetOnApproved<M>>,
    strict: Arc<Mutex<bool>>,
    errors: Arc<Mutex<ErrorState>>,
    field_validators: Arc<Mutex<BTreeMap<String, FieldValidator<M>>>>,
    model_validators: Arc<Mutex<Vec<ModelValidator<M>>>>,
    errors_changed: MessageHub,
    approve_errors: MessageHub,
    approve_can_execute_changed: MessageHub,
    approve_command: Arc<OnceLock<RelayCommand>>,
    deny_command: Arc<OnceLock<RelayCommand>>,
    approved_callbacks: Arc<Mutex<ApprovedRegistry<M>>>,
    /// Publication scopes, pre-publication windows and their queues
    /// (spec/20 §5.3 and §5.5).
    publication: Arc<PublicationControl<M>>,
    approval_in_flight: Arc<AtomicBool>,
    /// Serializes commits, approval admission, and disposal across threads
    /// (spec/20 §5.4, ADR-0144). No callback runs while it is held
    /// (ADR-0215).
    update_lock: Arc<UpdateLock>,
    /// The notifications that nested calls queue for the outermost update
    /// (spec/20 §5.4, ADR-0180).
    nested: Arc<Mutex<NestedUpdates<M>>>,
    /// Counts the commits of model, snapshot, and error state, each made
    /// under the update lock. A preparation that saw another thread advance
    /// it runs again (spec/20 §5.4, ADR-0215).
    commit_generation: Arc<AtomicU64>,
    /// Counts the revalidations that validator registrations start. An
    /// approval that saw it move while it validated its reset model
    /// validates again (#1046).
    revalidations: Arc<AtomicU64>,
    /// Odd while an approval commit replaces the snapshot, and for a reset
    /// also the model, under separate mutexes. `is_dirty` reads a pair that no
    /// such commit overlapped (#1073). No user code runs while it is odd.
    pair_version: Arc<AtomicU64>,
    disposed: Arc<Mutex<bool>>,
    hub: MessageHub,
}

impl<M: Clone + PartialEq + Send + 'static> FormVm<M> {
    /// Returns the canonical component family discriminator.
    pub fn view_model_type(&self) -> crate::ViewModelType {
        self.component.view_model_type()
    }

    /// Creates a non-strict form with a no-op persister and a private hub.
    pub fn new(name: impl Into<String>, model: M) -> Self {
        Self::with_options(name, model, |_| Ok(()), false, MessageHub::new())
    }

    /// Creates a form with explicit persistence, strictness, and message hub.
    pub fn with_options<F>(
        name: impl Into<String>,
        model: M,
        persister: F,
        strict: bool,
        hub: MessageHub,
    ) -> Self
    where
        F: Fn(&M) -> VmxResult<()> + Send + Sync + 'static,
    {
        let component =
            ComponentVm::with_model(name, model.clone(), hub.clone(), NullDispatcher::new());
        let form = Self {
            component,
            snapshot: Arc::new(Mutex::new(model)),
            persister: Arc::new(persister),
            snapshotter: Arc::new(|model| model.clone()),
            reset_on_approved: None,
            strict: Arc::new(Mutex::new(strict)),
            errors: Arc::new(Mutex::new(ErrorState::new())),
            field_validators: Arc::new(Mutex::new(BTreeMap::new())),
            model_validators: Arc::new(Mutex::new(Vec::new())),
            errors_changed: MessageHub::new(),
            approve_errors: MessageHub::new(),
            approve_can_execute_changed: MessageHub::new(),
            approve_command: Arc::new(OnceLock::new()),
            deny_command: Arc::new(OnceLock::new()),
            approved_callbacks: Arc::new(Mutex::new(ApprovedRegistry::new())),
            publication: Arc::new(PublicationControl::new()),
            approval_in_flight: Arc::new(AtomicBool::new(false)),
            update_lock: Arc::new(UpdateLock::new()),
            nested: Arc::new(Mutex::new(NestedUpdates::new())),
            commit_generation: Arc::new(AtomicU64::new(0)),
            revalidations: Arc::new(AtomicU64::new(0)),
            pair_version: Arc::new(AtomicU64::new(0)),
            disposed: Arc::new(Mutex::new(false)),
            hub,
        };
        form.with_initial_validation()
    }

    /// Creates an empty immutable builder for a form.
    pub fn builder() -> FormVmBuilder<M> {
        FormVmBuilder::new()
    }

    /// Adds a whole-model validator that returns an ordered error list.
    ///
    /// Each registration keys its errors `$model.<registration>.<index>`, so a
    /// second validator adds to the errors of the first instead of replacing
    /// them. A registration after dispose is inactive (see the type docs).
    pub fn with_validator<F>(self, validator: F) -> Self
    where
        F: Fn(&M) -> Vec<String> + Send + Sync + 'static,
    {
        if *lock(&self.disposed) {
            return self;
        }
        let mut validators = lock(&self.model_validators);
        let registration = validators.len();
        validators.push(Arc::new(move |model| {
            validator(model)
                .into_iter()
                .enumerate()
                .map(|(index, error)| (format!("$model.{registration:04}.{index:04}"), Some(error)))
                .collect()
        }));
        drop(validators);
        self.revalidate();
        self
    }

    /// Adds or replaces validation for one named field and revalidates immediately.
    ///
    /// The validator is registered at once. Its revalidation is an update: it
    /// waits while another thread holds a publication scope, and it sends
    /// `errors_changed` in its own scope (spec/20 §5.5, ADR-0176). When that
    /// wait would close a wait-for cycle, the revalidation joins the
    /// publishing thread's queue, and the call returns before the errors
    /// change. A registration from a preparation callback or an
    /// `errors_changed` subscriber of an update is nested (spec/20 §5.4,
    /// ADR-0216): its revalidation commits at once, and the call returns
    /// before its notifications, which the outermost update sends. The other
    /// registration methods behave the same way.
    pub fn with_field_validator<F>(&self, field: impl Into<String>, validator: F)
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        // A registration after dispose is inactive (see the type docs).
        if *lock(&self.disposed) {
            return;
        }
        let replaced = lock(&self.field_validators).insert(field.into(), Arc::new(validator));
        // A replaced validator is dropped after the lock is released.
        drop(replaced);
        self.revalidate();
    }

    /// Adds a validator that returns a field-keyed error map.
    ///
    /// This string-map form can only add or replace errors. It is the
    /// compatibility path for [`FormVm::with_clearing_model_validator`]: every
    /// returned entry becomes `Some(error)`.
    pub fn with_model_validator<F>(&self, validator: F)
    where
        F: Fn(&M) -> BTreeMap<String, String> + Send + Sync + 'static,
    {
        self.with_clearing_model_validator(move |model| error_updates(validator(model)));
    }

    /// Adds a model validator that can add, replace, or clear field errors.
    ///
    /// Model validators run after every field validator, in registration order.
    /// `Some(error)` sets the field's error (an empty string is still an error),
    /// `None` removes an error set by a field validator or an earlier model
    /// validator, and an omitted field keeps its current entry.
    pub fn with_clearing_model_validator<F>(&self, validator: F)
    where
        F: Fn(&M) -> BTreeMap<String, Option<String>> + Send + Sync + 'static,
    {
        // A registration after dispose is inactive (see the type docs).
        if *lock(&self.disposed) {
            return;
        }
        lock(&self.model_validators).push(Arc::new(validator));
        self.revalidate();
    }

    /// Returns a clone of the current editable model.
    ///
    /// `M::clone` runs while this call holds the model lock, and that lock
    /// is not re-entrant. A model `Clone` that calls this method, or another
    /// method that reads the model, on its own thread never returns. See
    /// [Re-entrant `Clone`](Self#re-entrant-clone).
    pub fn model(&self) -> M {
        self.component.model()
    }

    /// Replaces the editable model and publishes resulting validation changes.
    ///
    /// A model equal to the live one, or any call after
    /// [`dispose`](Self::dispose), does nothing. Otherwise the update prepares
    /// before it commits (spec/20 §5.2 and §5.4, ADR-0144). Preparation
    /// compares the model with the live model and, in strict mode, with the
    /// snapshot, and runs the validators. It changes nothing, so a callback
    /// that reads the form sees the previous state. The commit then installs
    /// the model and its errors together, and the call publishes
    /// `errors_changed`, the approve command's eligibility change, and the
    /// `"model"` hub message, in that order.
    ///
    /// A reader on another thread never pairs one model with another model's
    /// errors. After it reads the new model, [`is_valid`](Self::is_valid),
    /// [`errors`](Self::errors), [`error_map`](Self::error_map), and
    /// [`field_error`](Self::field_error) report that model's errors, or a
    /// later model's.
    /// Before the new model is installed, they report the previous model's
    /// errors. An approval that resets the model gives the same guarantee.
    ///
    /// No lock is held while `PartialEq` or a validator runs (spec/20 §5.4,
    /// ADR-0215). Another thread's reads, updates, approval calls, and
    /// disposal do not wait for this preparation. Commits stay serialized.
    /// When the preparation completes, the call checks three cases in order:
    ///
    /// 1. The form was disposed: the call commits and publishes nothing.
    /// 2. A callback on this thread committed or queued another update: the
    ///    call commits and publishes nothing, and the newer state stands.
    /// 3. Another thread committed meanwhile: the call runs again as a new
    ///    call, so its validators can run more than once.
    ///
    /// A panic in a validator or in `PartialEq` unwinds with the form
    /// unchanged, nothing published, and no lock poisoned or held, so the form
    /// stays usable.
    ///
    /// A call made while an approval commits its post-persist state or
    /// publishes the notifications that precede its approval subscribers
    /// (from `reset_on_approved`, the snapshotter, a validator, or an
    /// `errors_changed` or eligibility-change observer) is queued (spec/20
    /// §5.3, ADR-0174). It prepares at once, so a panic still reaches this
    /// caller and queues nothing, but a model equal to the live one is still
    /// queued. It changes and publishes nothing until it replays, as a new
    /// call, after the approval subscribers have run.
    ///
    /// While another thread delivers this form's notifications in a
    /// publication scope, the call waits until no other thread holds one
    /// (spec/20 §5.5, ADR-0176). An update holds a scope over its
    /// `errors_changed` send, and a settlement from its first step until its
    /// approval subscribers have run. The wait is recorded in the process-wide
    /// wait-for graph. When it would close a wait-for cycle, the call prepares
    /// at once, joins the publishing thread's queue, and returns before it
    /// takes effect; that thread replays it when its publication ends. A
    /// call made in this thread's own pre-publication window does not wait:
    /// it joins this thread's queue at once.
    ///
    /// A call from a preparation callback of a `set_model`,
    /// [`revert`](Self::revert) or validator registration, or from an
    /// `errors_changed` subscriber of one, is nested (spec/20 §5.4,
    /// ADR-0180). It commits at once, but it returns before its
    /// notifications. The outermost update on the thread
    /// sends them before it returns, with no form lock held: every
    /// `errors_changed` first, in commit order, then the other notifications.
    /// Once the form is disposed, they are dropped. A nested call never waits
    /// for another thread's publication scope: while one is open, it joins
    /// that thread's queue at once.
    ///
    /// ```
    /// use std::panic::{catch_unwind, AssertUnwindSafe};
    /// use vmx::FormVm;
    ///
    /// let form = FormVm::builder()
    ///     .initial(1)
    ///     .persister(|_| Ok(()))
    ///     .validator("value", |model: &i32| {
    ///         assert_ne!(*model, 13, "a validator bug");
    ///         (*model < 0).then(|| "negative".to_string())
    ///     })
    ///     .build()
    ///     .unwrap();
    ///
    /// assert!(catch_unwind(AssertUnwindSafe(|| form.set_model(13))).is_err());
    /// assert_eq!(form.model(), 1);
    ///
    /// form.set_model(-1);
    /// assert_eq!(form.field_error("value").as_deref(), Some("negative"));
    /// ```
    pub fn set_model(&self, model: M) {
        if *lock(&self.disposed) {
            return;
        }
        let Some(refused_by) = self.begin_update(true) else {
            return;
        };
        self.run_update(|| self.assign(model, refused_by));
    }

    /// Prepares a `set_model` with no lock held, then places or commits it
    /// under the update lock, and returns its notifications.
    fn assign(&self, model: M, refused_by: Option<ThreadId>) -> Step<M> {
        let base = self.preparation_base();
        let queueing = refused_by.is_some() || self.pre_publishing_here();
        let live = self.model();
        // A queued call compares too, but never skips the enqueue: earlier
        // queued updates can change the live model before it replays.
        let unchanged = live == model;
        if unchanged && !queueing {
            return Step::default();
        }
        let PreparedUpdate {
            model,
            errors,
            was_eligible,
            eligible,
        } = self.prepare_update(Some(live), None, model);
        let guard = self.update_lock.acquire();
        let model = match self.place_prepared(base, QueuedUpdate::Assign(model), refused_by, true) {
            Placement::Commit(QueuedUpdate::Assign(model)) => model,
            Placement::Retry(update) => {
                return Step {
                    retry: Some(update),
                    ..Step::default()
                }
            }
            _ => return Step::default(),
        };
        // A queue that closed during the preparation leaves an equal
        // candidate with nothing to do.
        if unchanged {
            drop(guard);
            return Step::default();
        }
        let errors_changed = self.commit_update(model, errors);
        let step = self.committed(
            errors_changed,
            vec![Notice::Eligibility(was_eligible, eligible), Notice::Model],
        );
        drop(guard);
        step
    }

    /// The notifications of a committed update: `errors_changed` in a scope
    /// opened now, when the errors changed, then `after`. The caller holds
    /// the update lock.
    fn committed(&self, errors_changed: bool, after: Vec<Notice>) -> Step<M> {
        Step {
            notices: Notices {
                errors: self.open_update_scope(errors_changed).into_iter().collect(),
                after,
                starts: Vec::new(),
            },
            ..Step::default()
        }
    }

    /// Runs one `set_model`, `revert` or revalidation frame (spec/20 §5.4,
    /// ADR-0180, ADR-0215). `update` prepares with no lock held, and takes
    /// the update lock only to place or commit.
    ///
    /// A frame nested in another frame's preparation, or in an outermost
    /// update's `errors_changed` delivery, queues its notifications for the
    /// outermost update and returns. The outermost frame then sends the whole
    /// queue. A panic in `update` still lets the notifications of the nested
    /// calls it made go out, and then resumes.
    ///
    /// The frame counts as a delivery from its start, so a `dispose()` on
    /// another thread during the preparation defers its teardown until the
    /// frame returns (spec/20 §5.4 and §10).
    fn run_update(&self, update: impl FnOnce() -> Step<M>) {
        lock(&self.nested).enter(thread::current().id());
        let mut delivery = Delivery::begin_preparation(&self.publication, &self.disposed);
        let prepared = if delivery.is_some() {
            catch_unwind(AssertUnwindSafe(update))
        } else {
            Ok(Step::default())
        };
        let (step, failure) = match prepared {
            Ok(step) => (step, None),
            Err(payload) => (Step::default(), Some(payload)),
        };
        let Step {
            notices,
            retry,
            discarded,
        } = step;
        let notices = self.take_notices(notices);
        if let Some(delivery) = delivery.as_mut() {
            delivery.prepared();
        }
        drop(discarded);
        let notified = self.deliver(notices, delivery);
        if let Some(payload) = failure {
            drop(notified);
            resume_unwind(payload);
        }
        match retry {
            Some(QueuedUpdate::Assign(model)) => self.set_model(model),
            Some(QueuedUpdate::Revert) => self.revert(),
            Some(QueuedUpdate::Revalidate) => self.revalidate(),
            None => {}
        }
        if let Some(payload) = notified {
            resume_unwind(payload);
        }
    }

    /// Ends a frame's preparation and returns what it must send: nothing for
    /// a nested frame, which queues `own` for the outermost update, and the
    /// whole queue for the outermost frame.
    fn take_notices(&self, own: Notices<M>) -> Notices<M> {
        let current = thread::current().id();
        let mut state = lock(&self.nested);
        let Some(index) = state
            .frames
            .iter()
            .position(|entry| entry.thread == current)
        else {
            return own;
        };
        let frames = &mut state.frames[index];
        frames.depth -= 1;
        if frames.depth > 0 {
            frames.pending.append(own.nested());
            return Notices::default();
        }
        let mut notices = state.frames.swap_remove(index).pending;
        if let Some(scoped) = state.error_delivery(current) {
            scoped.append(notices);
            scoped.append(own.nested());
            return Notices::default();
        }
        notices.append(own);
        notices
    }

    /// Queues the admission notification and the persister start of an
    /// approval admitted from a nested call, and returns `None`. Returns the
    /// approval when the call is not nested. The caller holds the update
    /// lock.
    fn queue_nested_approval(
        &self,
        flight: ApprovalFlight,
        model: M,
    ) -> Option<(ApprovalFlight, M)> {
        let mut state = lock(&self.nested);
        let Some(queue) = state.nested_queue(thread::current().id()) else {
            return Some((flight, model));
        };
        queue.after.push(Notice::Admission);
        queue.starts.push((flight, model));
        None
    }

    /// Reports whether a call on this thread is nested (spec/20 §5.4): it
    /// comes from a preparation callback of a frame on this thread, or from
    /// this thread's `errors_changed` delivery.
    fn nested_here(&self) -> bool {
        lock(&self.nested)
            .nested_queue(thread::current().id())
            .is_some()
    }

    /// Sends the notifications an outermost update took, with no form lock
    /// held (spec/20 §5.4 and §5.5, ADR-0180), and ends `delivery`.
    ///
    /// Each `errors_changed` goes out in commit order, inside the update
    /// scope its commit opened. An update made from one of those
    /// subscribers queues its notifications here, and its error map follows
    /// in a scope that is still open. The scopes then close, and the other
    /// notifications follow in queue order. Nested approvals then start their
    /// persisters, unless the form is disposed, and route a failure to
    /// `approve_errors`. The thread's queue replays last. Returns the first
    /// panic of the notifications, an approval, a replay, or the teardown.
    ///
    /// A panic in a send stops the later sends (spec/20 §5.4 rule 7,
    /// ADR-0216). Each nested approval is then released: its in-flight mark
    /// clears, its persister is never called, and the eligibility change is
    /// raised once more when its admission change was sent.
    fn deliver(&self, notices: Notices<M>, delivery: Option<Delivery<M>>) -> Option<PanicPayload> {
        let current = thread::current().id();
        let Notices {
            errors: mut publications,
            mut after,
            mut starts,
        } = notices;
        // Read after the unwind guard, which a panic can leave with it set.
        let delivering_errors = std::cell::Cell::new(false);
        // Admissions and starts join the queue in the same order, so the
        // first `announced` starts had their admission change sent or tried.
        let announced = std::cell::Cell::new(0_usize);
        let notified = catch_unwind(AssertUnwindSafe(|| {
            if !publications.is_empty() {
                lock(&self.nested)
                    .error_deliveries
                    .push((current, Notices::default()));
                delivering_errors.set(true);
                let mut sent = 0;
                while sent < publications.len() {
                    self.publish_validation_changed();
                    sent += 1;
                    if sent == publications.len() {
                        let scoped = lock(&self.nested)
                            .error_delivery(current)
                            .map(std::mem::take)
                            .unwrap_or_default();
                        publications.extend(scoped.errors);
                        after.extend(scoped.after);
                        starts.extend(scoped.starts);
                    }
                }
                delivering_errors.set(false);
                self.end_error_delivery(current, &mut publications, &mut starts);
                for publication in &mut publications {
                    publication.close_scope();
                }
            }
            for notice in after.drain(..) {
                match notice {
                    Notice::Eligibility(was_eligible, eligible) => {
                        self.publish_eligibility_change(was_eligible, eligible);
                    }
                    Notice::Model => self.publish_model_changed(),
                    Notice::Reverted { nested } => {
                        if !(nested && *lock(&self.disposed)) {
                            self.hub.send(Message::FormReverted(FormRevertedMessage {
                                sender_id: self.component.id(),
                                sender_name: "FormVm".to_string(),
                            }));
                        }
                    }
                    Notice::Admission => {
                        // A failed admission send counts as sent, so the
                        // release raises the change again, as in every
                        // flavor. The approve command's forwarding
                        // subscription isolates subscriber panics, so this
                        // send fails only on an internal panic.
                        announced.set(announced.get() + 1);
                        self.raise_approve_can_execute_changed();
                    }
                    Notice::Revalidated(could_approve) => {
                        self.publish_approve_state_change(could_approve);
                    }
                }
            }
        }));
        // An unexpected unwind can leave the error delivery open.
        if delivering_errors.get() {
            self.end_error_delivery(current, &mut publications, &mut starts);
        }
        let mut first_panic = notified.err();
        let failed = first_panic.is_some();
        for (index, (flight, model)) in starts.into_iter().enumerate() {
            if failed {
                drop(flight);
                drop(model);
                if index < announced.get() {
                    // A failure of this send is discarded.
                    let _ = catch_unwind(AssertUnwindSafe(|| {
                        self.raise_approve_can_execute_changed();
                    }));
                }
                continue;
            }
            // A disposal before the persister starts prevents the call, and
            // the approval settles silently (spec/20 §10, ADR-0180).
            if *lock(&self.disposed) {
                drop(flight);
                continue;
            }
            let approved = catch_unwind(AssertUnwindSafe(|| {
                if let Err(error) = self.run_approval(flight, model) {
                    self.publish_approve_error(&error);
                }
            }));
            if let Err(payload) = approved {
                first_panic.get_or_insert(payload);
            }
        }
        for publication in publications {
            if let Some(payload) = self.finish_publication(publication) {
                first_panic.get_or_insert(payload);
            }
        }
        let teardown_panic = delivery
            .and_then(Delivery::end)
            .and_then(|teardown| catch_unwind(AssertUnwindSafe(teardown)).err());
        first_panic.or(teardown_panic)
    }

    /// Ends this thread's `errors_changed` delivery, when it is open, and
    /// keeps the scopes and approvals that its subscribers' calls queued
    /// after the last error map, so they still close and settle.
    fn end_error_delivery(
        &self,
        current: ThreadId,
        publications: &mut Vec<Publication<M>>,
        starts: &mut Vec<(ApprovalFlight, M)>,
    ) {
        let rest = {
            let mut state = lock(&self.nested);
            let index = state
                .error_deliveries
                .iter()
                .rposition(|(entry, _)| *entry == current);
            index.map(|index| state.error_deliveries.remove(index).1)
        };
        if let Some(rest) = rest {
            publications.extend(rest.errors);
            starts.extend(rest.starts);
        }
    }

    /// Returns a clone of the last approved or initial snapshot.
    ///
    /// `M::clone` runs while this call holds the snapshot lock, and that lock
    /// is not re-entrant. A model `Clone` that calls this method, or another
    /// method that reads the snapshot, on its own thread never returns. See
    /// [Re-entrant `Clone`](Self#re-entrant-clone).
    pub fn snapshot(&self) -> M {
        clone_locked(&self.snapshot)
    }

    /// Reports whether the current model differs from the snapshot.
    pub fn is_dirty(&self) -> bool {
        // Compare copies, so no lock is held while `PartialEq` runs. The model
        // is read first, so only a snapshot write between the two reads can
        // pair values that never coexisted. Read the pair again when an
        // approval commit, the only snapshot writer, overlapped them (#1073).
        loop {
            let version = self.pair_version.load(Ordering::SeqCst);
            if version % 2 == 1 {
                thread::yield_now();
                continue;
            }
            let model = self.model();
            let snapshot = self.snapshot();
            if self.pair_version.load(Ordering::SeqCst) == version {
                return model != snapshot;
            }
        }
    }

    /// Returns the current validation messages in field-key order.
    pub fn errors(&self) -> Vec<String> {
        self.read_errors(|errors| errors.values().cloned().collect())
    }

    /// Returns the current validation errors keyed by field.
    pub fn error_map(&self) -> BTreeMap<String, String> {
        self.read_errors(BTreeMap::clone)
    }

    /// Returns the current error for `field`, when present.
    pub fn field_error(&self, field: &str) -> Option<String> {
        self.read_errors(|errors| errors.get(field).cloned())
    }

    /// Reports whether no validation errors are present.
    pub fn is_valid(&self) -> bool {
        self.read_errors(BTreeMap::is_empty)
    }

    /// Reports whether approval is currently admitted.
    ///
    /// This is the approve command's predicate: the form is not disposed, no
    /// approval is in flight, the model is valid, and, in strict mode, it is
    /// dirty.
    pub fn can_approve(&self) -> bool {
        if *lock(&self.disposed)
            || self.approval_in_flight.load(Ordering::SeqCst)
            || !self.is_valid()
        {
            return false;
        }
        // Read the flag first, so no lock is held while `is_dirty` runs
        // `PartialEq`.
        let strict = *lock(&self.strict);
        !strict || self.is_dirty()
    }

    /// Persists the captured model and advances or resets the pristine snapshot.
    ///
    /// One approval runs at a time (spec/20 §5.3, ADR-0143). The call returns
    /// `Ok(())` without invoking the persister, changing state, or emitting
    /// anything when the form is disposed, invalid, or already has an approval
    /// in flight, whether that call comes from the persister, an observer, or
    /// another thread. [`set_model`](Self::set_model) and
    /// [`revert`](Self::revert) are not blocked by an approval in flight.
    ///
    /// While another thread holds a publication scope on the form, admission
    /// waits until no other thread holds one, and so does the settlement
    /// before its first step (spec/20 §5.5, ADR-0176). Each wait is recorded
    /// in the process-wide wait-for graph. When an admission wait would close
    /// a wait-for cycle, the call is admitted without it. When a settlement
    /// wait would, the settlement commits at once and holds its own scope.
    ///
    /// An admitted approval raises the approve command's eligibility change
    /// once, then persists. Its settlement clears the in-flight mark first, so
    /// every observer it notifies sees an idle form and may approve again.
    /// Settlement then publishes `errors_changed` when the commit changed the
    /// errors, raises the eligibility change exactly once, and finally
    /// notifies the approval subscribers, or returns the failure to this
    /// caller. A panic in the persister, reset, or snapshotter settles the
    /// same way before it resumes. Disposal during the approval suppresses
    /// settlement.
    ///
    /// A [`set_model`](Self::set_model) or [`revert`](Self::revert) made on
    /// this thread from the post-persist commit (`reset_on_approved`, the
    /// snapshotter, or a validator) or from a settlement `errors_changed` or
    /// eligibility-change observer is queued, so the approval subscribers see
    /// the committed state (spec/20 §5.3, ADR-0174). The queue replays in call
    /// order after the subscribers return, or, when the commit fails, after
    /// the failed settlement's eligibility change and before the failure is
    /// returned. A panicking replay does not stop the later ones and does not
    /// unsettle the approval. After the last replay, the first replay panic
    /// resumes, unless the approval already carries a failure: a failed
    /// commit or a panicking subscriber wins.
    ///
    /// A call from a preparation callback of [`set_model`](Self::set_model)
    /// or [`revert`](Self::revert), or from an `errors_changed` subscriber of
    /// one, is nested (spec/20 §5.4, ADR-0180). It is admitted at once and
    /// returns `Ok(())`. Its eligibility change and its persister follow
    /// after the outermost update on the thread has sent its notifications,
    /// before that update returns. A failure then goes to
    /// [`approve_errors`](Self::approve_errors), and a panic resumes from the
    /// outermost update after its queued updates replay. A disposal before
    /// the persister starts prevents the persister call (spec/20 §10).
    ///
    /// ```
    /// use std::sync::{Arc, Mutex};
    /// use vmx::FormVm;
    ///
    /// let slot = Arc::new(Mutex::new(None::<FormVm<i32>>));
    /// let persisted = Arc::new(Mutex::new(Vec::new()));
    /// let form = FormVm::builder()
    ///     .initial(1)
    ///     .persister({
    ///         let slot = slot.clone();
    ///         let persisted = persisted.clone();
    ///         move |model: &i32| {
    ///             persisted.lock().unwrap().push(*model);
    ///             // A second approval while this one is in flight does nothing.
    ///             let form = slot.lock().unwrap().take();
    ///             if let Some(form) = form {
    ///                 assert!(!form.can_approve());
    ///                 assert_eq!(form.approve(), Ok(()));
    ///             }
    ///             Ok(())
    ///         }
    ///     })
    ///     .build()
    ///     .unwrap();
    /// *slot.lock().unwrap() = Some(form.clone());
    ///
    /// form.set_model(2);
    /// form.approve().unwrap();
    ///
    /// assert_eq!(*persisted.lock().unwrap(), vec![2]);
    /// assert_eq!(form.snapshot(), 2);
    /// assert!(form.can_approve());
    /// ```
    pub fn approve(&self) -> VmxResult<()> {
        let Some((flight, model)) = self.admit_approval() else {
            return Ok(());
        };
        self.run_approval(flight, model)
    }

    /// Persists an admitted approval and settles it.
    fn run_approval(&self, flight: ApprovalFlight, model: M) -> VmxResult<()> {
        // No lock is held while the persister runs. A panic is caught only to
        // settle the approval before it resumes. The pre-publication window
        // opens when the post-persist commit starts (spec/20 §5.3).
        let mut window = None;
        let outcome = catch_unwind(AssertUnwindSafe(|| {
            self.persist_and_commit(&model, &mut window)
        }));
        match outcome {
            Ok(Ok(Some(errors_changed))) => {
                let window = window.expect("a committed approval opened its window");
                // Settlement step 1: every settlement observer sees an idle
                // form. The commit already opened the settlement scope.
                drop(flight);
                self.settle_approved(model, errors_changed, window);
                Ok(())
            }
            // Disposal during the approval suppressed the commit and
            // settlement. Updates queued before it replay as no-ops.
            Ok(Ok(None)) => {
                drop(flight);
                if let Some(window) = window {
                    drop(self.finish_publication(window));
                }
                Ok(())
            }
            // A failed post-persist commit wins over any replay panic.
            Ok(Err(error)) => {
                self.settle_failed(flight, window);
                Err(error)
            }
            Err(panic) => {
                self.settle_failed(flight, window);
                resume_unwind(panic)
            }
        }
    }

    /// Admits an approval when the form is not disposed, is valid, and has
    /// none in flight. Admission sets the in-flight mark before it captures
    /// the model, then raises the approve command's eligibility change once.
    ///
    /// Admission first waits until no other thread holds a publication scope
    /// (spec/20 §5.5). When that wait would close a wait-for cycle, the call
    /// is admitted without it, and its settlement waits instead.
    ///
    /// A nested call (spec/20 §5.4, ADR-0180) queues the admission
    /// notification and the persister start for the outermost update, and
    /// returns `None`.
    fn admit_approval(&self) -> Option<(ApprovalFlight, M)> {
        // Check validity, mark the flight and capture the model under the
        // update lock, so a `set_model` on another thread cannot commit an
        // invalid model between the check and the capture (#719). No callback
        // runs under it, and it is released before the admission observers
        // run.
        let (flight, model, delivery) = {
            let Serialized {
                guard: _serialized, ..
            } = self.serialize();
            if *lock(&self.disposed) || !self.is_valid() {
                return None;
            }
            let flight = ApprovalFlight::admit(&self.approval_in_flight)?;
            let (flight, model) = self.queue_nested_approval(flight, self.model())?;
            let delivery = Delivery::begin(&self.publication, &self.disposed)?;
            (flight, model, delivery)
        };
        // The admission notification opens no publication scope, so another
        // thread's `dispose()` defers its teardown until it returns.
        self.raise_approve_can_execute_changed();
        if let Some(teardown) = delivery.end() {
            teardown();
        }
        // An admission observer that disposes the form prevents the persister
        // call (spec/20 §5.3). Dropping the flight clears the in-flight mark.
        if *lock(&self.disposed) {
            return None;
        }
        Some((flight, model))
    }

    /// Persists `model` and commits the post-persist state: the advanced
    /// snapshot, or the prepared reset transaction. Returns whether the commit
    /// changed the effective errors, or `None` when disposal suppressed it.
    ///
    /// Once the persister succeeds, it opens the approval's pre-publication
    /// window in `window`, so an update made by the reset callback, the
    /// snapshotter, or a validator is queued (spec/20 §5.3, ADR-0174). A
    /// commit opens the settlement scope in `window`.
    fn persist_and_commit(
        &self,
        model: &M,
        window: &mut Option<Publication<M>>,
    ) -> VmxResult<Option<bool>> {
        (self.persister)(model)?;
        if *lock(&self.disposed) {
            return Ok(None);
        }
        let window = window.insert(Publication::enter(&self.publication, Some(true)));
        let committed = if let Some(reset_on_approved) = &self.reset_on_approved {
            // Prepare the complete transition before mutating local state. The
            // callback or either snapshot operation may fail/panic without a
            // partial assignment. The commit validates the reset model.
            let reset = reset_on_approved(model)?;
            let next_model = (self.snapshotter)(&reset);
            let next_snapshot = (self.snapshotter)(&reset);
            self.commit_approval(next_snapshot, Some(next_model), window)
        } else {
            self.commit_approval((self.snapshotter)(model), None, window)
        };
        Ok(committed)
    }

    /// Commits the post-persist state: the advanced snapshot, or a prepared
    /// reset model, which it validates first.
    ///
    /// The commit is authoritative over edits made during the approval
    /// (spec/20 §5.1) and yields only to disposal. The reset model's
    /// validators run with no lock held, so another thread's `set_model` or
    /// `revert` meanwhile commits at once, and the reset then overwrites it
    /// (§5.3, ADR-0215). Before settlement step 1, this step waits until no
    /// other thread holds a publication scope (§5.5). When that wait would
    /// close a wait-for cycle, it commits at once, and two threads then hold
    /// scopes. It installs every field in one step before the approval
    /// outcome is published, so synchronous observers cannot see a reset
    /// model paired with the previous snapshot or errors. A commit opens the
    /// settlement scope in `window` before it releases the update lock.
    /// Returns whether the effective errors changed, or `None` when disposal
    /// suppressed the commit.
    fn commit_approval(
        &self,
        snapshot: M,
        reset: Option<M>,
        window: &mut Publication<M>,
    ) -> Option<bool> {
        // The reset model is validated before any field changes (#1046). A
        // validator registration on any thread during that run makes the
        // validation run again. An update needs no rerun: the reset is
        // authoritative.
        let mut validated: Option<(u64, BTreeMap<String, String>)> = None;
        let serialized = loop {
            if let (Some(model), None) = (&reset, &validated) {
                let revalidations = self.revalidations.load(Ordering::SeqCst);
                validated = Some((revalidations, self.validation_errors_for(model)));
            }
            let Serialized {
                guard: serialized, ..
            } = self.serialize();
            if *lock(&self.disposed) {
                drop(serialized);
                return None;
            }
            let registered = validated.as_ref().is_some_and(|(revalidations, _)| {
                self.revalidations.load(Ordering::SeqCst) != *revalidations
            });
            if !registered {
                break serialized;
            }
            drop(serialized);
            validated = None;
        };
        let reset = reset.zip(validated.map(|(_, errors)| errors));
        self.note_commit();
        // The odd pair version marks the snapshot write, and a reset's model
        // install, for `is_dirty` (#1073); no user code runs inside it.
        self.pair_version.fetch_add(1, Ordering::SeqCst);
        let replaced_snapshot = std::mem::replace(&mut *lock(&self.snapshot), snapshot);
        let (errors_changed, replaced_model) = match reset {
            Some((model, errors)) => {
                let (errors_changed, replaced) = self.install(model, errors);
                (errors_changed, Some(replaced))
            }
            None => (false, None),
        };
        self.pair_version.fetch_add(1, Ordering::SeqCst);
        // The generation moves after the install, so a preparation that reads
        // the new generation also reads the new state (spec/20 §5.4).
        self.commit_generation.fetch_add(1, Ordering::SeqCst);
        window.open_scope();
        drop(serialized);
        // Replaced values are dropped after the update lock is released.
        drop((replaced_snapshot, replaced_model));
        Some(errors_changed)
    }

    /// Settlement steps 2 to 4 of a committed approval. The in-flight mark is
    /// already clear, and `window` holds the settlement scope and is still in
    /// its pre-publication window.
    ///
    /// The updates queued in the window replay after the approval subscribers
    /// have run and the scope has closed (spec/20 §5.3, ADR-0174). A
    /// subscriber panic wins over a replay panic; otherwise the first replay
    /// panic resumes after the last replay (#740, #1050).
    fn settle_approved(&self, model: M, errors_changed: bool, window: Publication<M>) {
        // Updates made by these observers are queued until the approval
        // subscribers have seen the committed state. Hub delivery isolates
        // observer panics; the guard covers any other unwind.
        let notified = catch_unwind(AssertUnwindSafe(|| {
            if errors_changed {
                self.publish_validation_changed();
            }
            // The one settlement notification also covers any strict or
            // validity change made by the commit.
            self.raise_approve_can_execute_changed();
        }));
        // The subscribers run outside this approval's window, so their edits
        // commit at once, also when the approval is nested (spec/20 §5.5).
        window.end_pre_publication();
        // Snapshot only the identities: each callback is looked up when its
        // turn comes, so a callback detached (or a form disposed) earlier in
        // this emission neither runs nor stays alive until it ends (ADR-0139).
        // A disposal whose teardown waits for this publication stops the
        // emission in the same way. A panicking subscriber still lets the
        // queued updates replay, as the other flavors replay them in
        // `finally`; the panic then continues to the approve caller (#740).
        let published = notified.and_then(|()| {
            catch_unwind(AssertUnwindSafe(|| {
                let ids: Vec<u64> = lock(&self.approved_callbacks)
                    .entries
                    .iter()
                    .map(|(id, _)| *id)
                    .collect();
                for id in ids {
                    if *lock(&self.disposed) {
                        break;
                    }
                    let callback = lock(&self.approved_callbacks)
                        .entries
                        .iter()
                        .find(|(entry_id, _)| *entry_id == id)
                        .map(|(_, callback)| Arc::clone(callback));
                    if let Some(callback) = callback {
                        callback(model.clone());
                    }
                }
            }))
        });
        // An enclosing publication on this thread keeps the queue until its
        // own scope has ended.
        let replay_panic = self.finish_publication(window);
        if let Err(payload) = published {
            drop(replay_panic);
            resume_unwind(payload);
        }
        if let Some(payload) = replay_panic {
            resume_unwind(payload);
        }
    }

    /// Settlement of a failed post-persist commit, or of a failed persister
    /// when `window` is `None`.
    ///
    /// Before step 1 it waits until no other thread holds a publication
    /// scope, then holds its own scope over its eligibility change (spec/20
    /// §5.5). The window ends with the failure, so the settlement's
    /// eligibility-change observers update at once. The updates queued on
    /// this thread then replay before the caller routes the failure, which
    /// wins over any replay panic (spec/20 §5.3, ADR-0174).
    fn settle_failed(&self, flight: ApprovalFlight, window: Option<Publication<M>>) {
        let ended_window = window.is_some();
        let mut publication = window.unwrap_or_else(|| Publication::enter(&self.publication, None));
        {
            let Serialized {
                guard: _serialized, ..
            } = self.serialize();
            publication.open_scope();
        }
        // Settlement step 1.
        drop(flight);
        if ended_window {
            publication.end_pre_publication();
        }
        let notified = catch_unwind(AssertUnwindSafe(|| {
            self.raise_approve_can_execute_changed();
        }));
        drop(self.finish_publication(publication));
        if let Err(payload) = notified {
            resume_unwind(payload);
        }
    }

    /// Ends one publication. When it was this thread's outermost, it closes
    /// the scope first, then replays the thread's queue in the order the
    /// updates joined, and then runs a teardown that a `dispose()` left for
    /// it. Each update replays as a new call, under its own unwind
    /// guard, so a panicking replay does not stop the later ones (spec/20
    /// §5.3 and §5.5, ADR-0174, ADR-0176). The teardown runs under the same
    /// guard, after the last replay. Returns the first panic of a replay or
    /// the teardown; later ones are dropped.
    fn finish_publication(&self, publication: Publication<M>) -> Option<PanicPayload> {
        let Finished { queued, teardown } = publication.finish();
        let mut first_panic = None;
        for update in queued {
            let replayed = catch_unwind(AssertUnwindSafe(|| match update {
                QueuedUpdate::Assign(model) => self.set_model(model),
                QueuedUpdate::Revert => self.revert(),
                QueuedUpdate::Revalidate => self.revalidate(),
            }));
            if let Err(payload) = replayed {
                if first_panic.is_none() {
                    first_panic = Some(payload);
                }
            }
        }
        if let Some(teardown) = teardown {
            if let Err(payload) = catch_unwind(AssertUnwindSafe(teardown)) {
                if first_panic.is_none() {
                    first_panic = Some(payload);
                }
            }
        }
        first_panic
    }

    /// Restores the last snapshot and publishes the revert outcome.
    ///
    /// Like [`set_model`](Self::set_model), a revert prepares before it
    /// commits (spec/20 §5.4, ADR-0144): the snapshotter copies the snapshot
    /// and the validators run on that copy before the form changes. A panic in
    /// either unwinds with the form unchanged and nothing published, including
    /// no [`FormRevertedMessage`]. No lock is held while those callbacks run,
    /// and the revert checks the same three cases as
    /// [`set_model`](Self::set_model) when its preparation completes
    /// (spec/20 §5.4, ADR-0215).
    ///
    /// A revert made while an approval commits or publishes the notifications
    /// that precede its approval subscribers is queued like
    /// [`set_model`](Self::set_model), after the same preparation, and
    /// replays after those subscribers have run (spec/20 §5.3, ADR-0174).
    /// It waits for another thread's publication scope, or is queued for that
    /// thread, as [`set_model`](Self::set_model) is (spec/20 §5.5).
    pub fn revert(&self) {
        if *lock(&self.disposed) {
            return;
        }
        let Some(refused_by) = self.begin_update(true) else {
            return;
        };
        self.run_update(|| self.restore(refused_by));
    }

    /// Prepares a revert with no lock held, then places or commits it under
    /// the update lock, and returns its notifications.
    fn restore(&self, refused_by: Option<ThreadId>) -> Step<M> {
        let base = self.preparation_base();
        let snapshot = self.snapshot();
        let restored = (self.snapshotter)(&snapshot);
        let update = self.prepare_update(None, Some(snapshot), restored);
        let guard = self.update_lock.acquire();
        match self.place_prepared(base, QueuedUpdate::Revert, refused_by, true) {
            Placement::Commit(_) => {}
            Placement::Retry(retry) => {
                return Step {
                    retry: Some(retry),
                    discarded: Some(update),
                    ..Step::default()
                };
            }
            Placement::Done => {
                return Step {
                    discarded: Some(update),
                    ..Step::default()
                };
            }
        }
        let (was_eligible, eligible) = (update.was_eligible, update.eligible);
        let errors_changed = self.commit_update(update.model, update.errors);
        let step = self.committed(
            errors_changed,
            vec![
                Notice::Reverted { nested: false },
                Notice::Model,
                Notice::Eligibility(was_eligible, eligible),
            ],
        );
        drop(guard);
        step
    }

    /// Returns the lazily created approval command.
    ///
    /// Executing it runs [`approve`](Self::approve) and routes a failure to
    /// [`approve_errors`](Self::approve_errors). Its eligibility is
    /// [`can_approve`](Self::can_approve), so it is disabled while an approval
    /// is in flight, and its eligibility change fires when an approval is
    /// admitted and once when it settles. A settlement observer, such as an
    /// approval or `approve_errors` subscriber, may execute it again: that
    /// approval is admitted and runs before the observer's `execute` returns.
    /// Executed from a preparation callback or an update's `errors_changed`
    /// subscriber, it is nested, and the approval persists after the
    /// outermost update's notifications, as [`approve`](Self::approve)
    /// states.
    pub fn approve_command(&self) -> RelayCommand {
        self.approve_command
            .get_or_init(|| {
                let form = self.command_target();
                RelayCommandBuilder::default()
                    .shared_action(move || {
                        if let Err(error) = form.approve() {
                            form.publish_approve_error(&error);
                        }
                    })
                    .can_execute({
                        let form = self.command_target();
                        move || form.can_approve()
                    })
                    .trigger(self.approve_can_execute_changed.clone())
                    .build()
            })
            .clone()
    }

    /// Returns the lazily created revert command.
    pub fn deny_command(&self) -> RelayCommand {
        self.deny_command
            .get_or_init(|| {
                let form = self.command_target();
                RelayCommand::new_shared(move || form.revert()).with_can_execute({
                    let form = self.command_target();
                    move || !*lock(&form.disposed)
                })
            })
            .clone()
    }

    /// Returns the form's external message hub.
    pub fn hub(&self) -> MessageHub {
        self.hub.clone()
    }

    /// Returns the stream-like hub that publishes validation-map changes.
    pub fn errors_changed(&self) -> MessageHub {
        self.errors_changed.clone()
    }

    /// Returns the hub that receives failures from fire-and-forget approval.
    pub fn approve_errors(&self) -> MessageHub {
        self.approve_errors.clone()
    }

    /// Registers a callback invoked with each successfully persisted model.
    ///
    /// The registration lasts until the form is disposed and cannot be
    /// detached; a registration made after disposal is dropped at once.
    /// Prefer [`subscribe_approved`](Self::subscribe_approved), which returns
    /// a handle that detaches the callback.
    ///
    /// Existing call sites keep compiling and keep their registration:
    ///
    /// ```
    /// # #![allow(deprecated)]
    /// use std::sync::atomic::{AtomicUsize, Ordering};
    /// use std::sync::Arc;
    /// use vmx::FormVm;
    ///
    /// let form = FormVm::new("profile", 1);
    /// let approvals = Arc::new(AtomicUsize::new(0));
    /// let counted = approvals.clone();
    /// form.on_approved(move |_| {
    ///     counted.fetch_add(1, Ordering::SeqCst);
    /// });
    ///
    /// form.set_model(2);
    /// form.approve().unwrap();
    ///
    /// assert_eq!(approvals.load(Ordering::SeqCst), 1);
    /// ```
    #[deprecated(
        since = "0.31.0",
        note = "cannot be detached before the form is disposed; use `subscribe_approved()`"
    )]
    pub fn on_approved<F>(&self, callback: F)
    where
        F: Fn(M) + Send + Sync + 'static,
    {
        let rejected = lock(&self.approved_callbacks).register(Arc::new(callback));
        drop(rejected);
    }

    /// Subscribes to each successfully persisted model and returns a handle
    /// that detaches the callback.
    ///
    /// Callbacks run in registration order, after the approval state is
    /// published. A callback registered during an approval starts with the
    /// next one, and a callback detached during an approval before its turn
    /// does not receive it. Later subscribers do not receive earlier
    /// approvals. After [`dispose`](Self::dispose) the form keeps no
    /// callback, and a subscription made then is inactive and releases its
    /// captures at once.
    ///
    /// Keep the returned handle for as long as the callback should run:
    /// dropping it detaches the callback.
    ///
    /// ```
    /// use std::sync::{Arc, Mutex};
    /// use vmx::FormVm;
    ///
    /// let form = FormVm::new("profile", 1);
    /// let saved = Arc::new(Mutex::new(Vec::new()));
    /// let subscription = {
    ///     let saved = saved.clone();
    ///     form.subscribe_approved(move |model| saved.lock().unwrap().push(model))
    /// };
    ///
    /// form.set_model(2);
    /// form.approve().unwrap();
    /// subscription.dispose(); // or drop it when the view closes
    /// form.set_model(3);
    /// form.approve().unwrap();
    ///
    /// assert_eq!(*saved.lock().unwrap(), vec![2]);
    ///
    /// // A handle that is not kept detaches at once.
    /// drop(form.subscribe_approved(|_| unreachable!("detached")));
    /// form.set_model(4);
    /// form.approve().unwrap();
    /// ```
    pub fn subscribe_approved<F>(&self, callback: F) -> ApprovalSubscription
    where
        F: Fn(M) + Send + Sync + 'static,
    {
        let registered = lock(&self.approved_callbacks).register(Arc::new(callback));
        match registered {
            Ok(id) => ApprovalSubscription::new(id, Arc::downgrade(&self.approved_callbacks)),
            Err(rejected) => {
                drop(rejected);
                ApprovalSubscription::inactive()
            }
        }
    }

    /// Disposes commands and notification hubs and makes later mutations inert.
    ///
    /// Disposal waits until no other thread holds a publication scope on the
    /// form (spec/20 §5.5). When that wait would close a wait-for cycle, the
    /// call marks the form disposed and returns at once, and later calls are
    /// inert. Either way, calls on other threads that wait for a publication
    /// scope stop waiting and find the form disposed.
    ///
    /// Work outside a publication scope does not make disposal wait: an
    /// approval's admission notification, an update or a validator
    /// registration from its preparation until it returns, or an
    /// `approve_errors` send. When such work is in progress on any thread,
    /// disposal marks the form disposed and returns at once. An update that
    /// is preparing then commits nothing (spec/20 §5.4, ADR-0215). This also
    /// applies to a disposal from an observer of that work. A disposal from
    /// a preparation callback on the preparing thread, with no other such
    /// work in progress, tears down at once.
    ///
    /// After a refused wait, or while a delivery outside a scope is in
    /// progress, the teardown is deferred: no hub completes and no command is
    /// disposed yet. The teardown runs when no publication and no delivery
    /// remains on any thread, on the thread that ends the last one (spec/20
    /// §5.5). That thread can be another thread than the publishing or
    /// delivering thread that the disposal found. For example, when threads A
    /// and C each deliver outside a scope and A returns first, the teardown
    /// runs on C when C returns.
    pub fn dispose(&self) {
        loop {
            let Serialized { guard, refused_by } = self.serialize();
            if let Some(owner) = refused_by {
                if self.defer_teardown(owner) {
                    return;
                }
                // The publisher ended its scope meanwhile: wait again.
                drop(guard);
                continue;
            }
            let tear_down_now = {
                let mut state = lock(&self.publication.state);
                let mut disposed = lock(&self.disposed);
                if std::mem::replace(&mut *disposed, true) {
                    return;
                }
                drop(disposed);
                // Only this thread's own preparations are in progress: a
                // disposal from a preparation callback tears down at once.
                let current = thread::current().id();
                let own = state
                    .preparing
                    .iter()
                    .filter(|entry| **entry == current)
                    .count();
                if state.deliveries == own {
                    true
                } else {
                    let form = self.clone();
                    state.teardown = Some(Box::new(move || form.tear_down()));
                    false
                }
            };
            drop(guard);
            self.wake_scope_waiters();
            if tear_down_now {
                self.tear_down();
            }
            return;
        }
    }

    /// Marks the form disposed and leaves its teardown to the publishers, when
    /// `owner` still holds a scope. Returns `false` when it no longer does.
    fn defer_teardown(&self, owner: ThreadId) -> bool {
        let mut state = lock(&self.publication.state);
        if !state.holds_scope(owner) {
            return false;
        }
        let mut disposed = lock(&self.disposed);
        if !std::mem::replace(&mut *disposed, true) {
            drop(disposed);
            let form = self.clone();
            state.teardown = Some(Box::new(move || form.tear_down()));
            drop(state);
            self.publication.closed.notify_all();
        }
        true
    }

    /// Wakes the calls that wait for a publication scope after this thread
    /// marked the form disposed, so they stop waiting (spec/20 §5.5). Taking
    /// the state lock first orders the mark before any waiter's next check.
    fn wake_scope_waiters(&self) {
        drop(lock(&self.publication.state));
        self.publication.closed.notify_all();
    }

    /// The §10 teardown of a disposed form.
    fn tear_down(&self) {
        if let Some(command) = self.approve_command.get() {
            command.dispose();
        }
        if let Some(command) = self.deny_command.get() {
            command.dispose();
        }
        self.approve_can_execute_changed.dispose();
        self.errors_changed.dispose();
        self.approve_errors.dispose();
        let released = {
            let mut registry = lock(&self.approved_callbacks);
            registry.closed = true;
            std::mem::take(&mut registry.entries)
        };
        drop(released);
        let field_validators = std::mem::take(&mut *lock(&self.field_validators));
        let model_validators = std::mem::take(&mut *lock(&self.model_validators));
        drop(field_validators);
        drop(model_validators);
        // The form's hub carries only the spec/20 §8 messages (model and
        // FormReverted). The wrapped component's ConstructionStatusChanged
        // (Disposed) is not one, and no other flavor publishes it.
        self.component.detach_hub();
        let _ = self.component.dispose();
    }

    fn command_target(&self) -> Self {
        let mut target = self.clone();
        target.approve_command = Arc::new(OnceLock::new());
        target.deny_command = Arc::new(OnceLock::new());
        target
    }

    /// Installs the initial model's errors. Construction runs the same
    /// preparation as an update, so a panicking validator fails construction
    /// and produces no form (spec/20 §5.4).
    fn with_initial_validation(self) -> Self {
        let errors = self.validation_errors_for(&self.model());
        lock(&self.errors).committed = errors;
        self
    }

    /// Revalidates the live model after a validator registration, then
    /// publishes an effective error change and the approve command's
    /// eligibility change.
    ///
    /// The run is an update frame (spec/20 §5.4 and §5.5, #1231, ADR-0216).
    /// It waits like [`set_model`](Self::set_model) while another thread holds
    /// a publication scope, runs the validators with no lock held, and sends
    /// `errors_changed` in its own update scope. When its wait would close a
    /// wait-for cycle, it joins the publisher's queue and replays there as a
    /// new revalidation. In this thread's own pre-publication window it
    /// commits at once. A registration from a preparation callback or an
    /// `errors_changed` subscriber is nested: it commits at once, makes the
    /// interrupted update stale, and returns before its notifications. An
    /// update or registration that one of its validators commits supersedes
    /// it, and a commit of another thread makes it run again.
    fn revalidate(&self) {
        if *lock(&self.disposed) {
            return;
        }
        self.revalidations.fetch_add(1, Ordering::SeqCst);
        let Some(refused_by) = self.begin_update(false) else {
            return;
        };
        self.run_update(|| self.recheck(refused_by));
    }

    /// Prepares a revalidation with no lock held, then places or commits it
    /// under the update lock, and returns its notifications. A refused one
    /// joins the publisher's queue without preparing.
    fn recheck(&self, refused_by: Option<ThreadId>) -> Step<M> {
        let base = self.preparation_base();
        let prepared = refused_by.is_none().then(|| {
            (
                self.can_approve(),
                self.validation_errors_for(&self.model()),
            )
        });
        let guard = self.update_lock.acquire();
        match self.place_prepared(base, QueuedUpdate::Revalidate, refused_by, false) {
            Placement::Commit(_) => {}
            Placement::Retry(retry) => {
                return Step {
                    retry: Some(retry),
                    ..Step::default()
                };
            }
            Placement::Done => return Step::default(),
        }
        let Some((could_approve, errors)) = prepared else {
            return Step::default();
        };
        self.note_commit();
        let errors_changed = self.replace_validation_errors(errors);
        // The generation moves after the install (see `commit_update`).
        self.commit_generation.fetch_add(1, Ordering::SeqCst);
        let step = self.committed(errors_changed, vec![Notice::Revalidated(could_approve)]);
        drop(guard);
        step
    }

    /// Routes a command-path approval failure to `approve_errors`. The send
    /// opens no publication scope, so a `dispose()` meanwhile defers its
    /// teardown until the send returns (spec/20 §5.5).
    fn publish_approve_error(&self, error: &VmxError) {
        let Some(delivery) = Delivery::begin(&self.publication, &self.disposed) else {
            return;
        };
        self.approve_errors.send(Message::Custom {
            sender_id: self.component.id(),
            sender_name: self.component.name(),
            name: error.to_string(),
        });
        if let Some(teardown) = delivery.end() {
            teardown();
        }
    }

    /// Takes the update lock for a form call, after the call's wait for other
    /// threads' publication scopes (spec/20 §5.5, ADR-0176).
    ///
    /// While another thread holds a scope, the call waits until no other
    /// thread holds one, and each wait records an edge to one publisher in the
    /// wait-for graph. When that wait would close a live wait-for cycle, the
    /// call takes the lock without waiting and reports the publisher in
    /// [`Serialized::refused_by`]. Disposal ends the wait.
    ///
    /// No callback runs under the update lock, so a call made while this
    /// thread holds it comes from code such as a model `Clone`. It does not
    /// wait.
    ///
    /// A nested call (spec/20 §5.4, ADR-0180) never waits for another
    /// thread's scope. It takes the refused-wait result at once and reports a
    /// publisher in [`Serialized::refused_by`].
    fn serialize(&self) -> Serialized<'_> {
        let current = thread::current().id();
        if self.update_lock.is_held_by_current() {
            let guard = self.update_lock.acquire();
            let refused_by = if self.nested_here() && !*lock(&self.disposed) {
                lock(&self.publication.state).foreign_publisher(current)
            } else {
                None
            };
            return Serialized { guard, refused_by };
        }
        loop {
            let guard = self.update_lock.acquire();
            let publisher = if *lock(&self.disposed) {
                None
            } else {
                lock(&self.publication.state).foreign_publisher(current)
            };
            let Some(owner) = publisher else {
                return Serialized {
                    guard,
                    refused_by: None,
                };
            };
            if self.nested_here() {
                return Serialized {
                    guard,
                    refused_by: Some(owner),
                };
            }
            // Never wait for a scope while holding the update lock: the
            // publisher may need it.
            drop(guard);
            if self.publication.wait_for_scope(owner, &self.disposed) {
                continue;
            }
            let guard = self.update_lock.acquire();
            if lock(&self.publication.state).holds_scope(owner) {
                return Serialized {
                    guard,
                    refused_by: Some(owner),
                };
            }
        }
    }

    /// Admits an update: its wait for other threads' publication scopes,
    /// which leaves no lock held. Returns the publisher that refused the
    /// wait, or `None` (outer) when the form is disposed.
    ///
    /// A `set_model` or `revert` passes `queues_in_own_window`. Made in this
    /// thread's own pre-publication window, it does not wait: it joins this
    /// thread's queue (spec/20 §5.5, ADR-0215). A revalidation there waits
    /// and commits at once.
    fn begin_update(&self, queues_in_own_window: bool) -> Option<Option<ThreadId>> {
        let refused_by = if queues_in_own_window && self.pre_publishing_here() {
            None
        } else {
            self.serialize().refused_by
        };
        let disposed = *lock(&self.disposed);
        (!disposed).then_some(refused_by)
    }

    /// Reports whether this thread's innermost settlement is in its
    /// pre-publication window.
    fn pre_publishing_here(&self) -> bool {
        lock(&self.publication.state).pre_publishing(thread::current().id())
    }

    /// Reads the commit generation and this thread's own commit and queue
    /// counts before a preparation's first callback. The caller runs a
    /// frame.
    fn preparation_base(&self) -> Base {
        let generation = self.commit_generation.load(Ordering::SeqCst);
        let (commits, queued) = lock(&self.nested)
            .frames(thread::current().id())
            .map_or((0, 0), |entry| (entry.commits, entry.queued));
        Base {
            generation,
            commits,
            queued,
        }
    }

    /// Counts a commit of this thread, so its preparations in progress are
    /// stale. The caller holds the update lock.
    fn note_commit(&self) {
        if let Some(entry) = lock(&self.nested).frames(thread::current().id()) {
            entry.commits += 1;
        }
    }

    /// Places a prepared call (spec/20 §5.3, §5.4 and §5.5, ADR-0174,
    /// ADR-0176, ADR-0215). The caller holds the update lock.
    ///
    /// It checks, in order:
    ///
    /// 1. The form was disposed: the call is dropped.
    /// 2. A callback on this thread committed or queued another update: the
    ///    preparation is stale and is dropped, so that newer state stands.
    /// 3. A call made in this thread's pre-publication window joins this
    ///    thread's queue, when `own_window_queues` is set. A call whose wait
    ///    was refused joins the queue of the publisher that refused it, or
    ///    runs again when that publisher has ended its publications
    ///    meanwhile. Another thread's commit does not affect a queued call.
    /// 4. Another thread committed since the preparation started, or now
    ///    holds a publication scope: the call runs again as a new call.
    /// 5. Otherwise the call is returned for the caller to commit.
    fn place_prepared(
        &self,
        base: Base,
        update: QueuedUpdate<M>,
        refused_by: Option<ThreadId>,
        own_window_queues: bool,
    ) -> Placement<M> {
        let current = thread::current().id();
        let stale = *lock(&self.disposed)
            || lock(&self.nested)
                .frames(current)
                .is_some_and(|entry| entry.commits != base.commits || entry.queued != base.queued);
        if stale {
            drop(update);
            return Placement::Done;
        }
        let mut state = lock(&self.publication.state);
        let target = if own_window_queues && state.pre_publishing(current) {
            Some(current)
        } else {
            refused_by
        };
        let Some(target) = target else {
            let overtaken = self.commit_generation.load(Ordering::SeqCst) != base.generation
                || state.foreign_publisher(current).is_some();
            return if overtaken {
                Placement::Retry(update)
            } else {
                Placement::Commit(update)
            };
        };
        let Some(entry) = state.entry(target) else {
            return Placement::Retry(update);
        };
        entry.queued.push(update);
        drop(state);
        if let Some(entry) = lock(&self.nested).frames(current) {
            entry.queued += 1;
        }
        Placement::Done
    }

    /// Opens a committed update's scope when its errors changed, so its
    /// `errors_changed` delivery reaches observers in commit order (spec/20
    /// §5.5). The caller holds the update lock.
    fn open_update_scope(&self, errors_changed: bool) -> Option<Publication<M>> {
        errors_changed.then(|| {
            let mut publication = Publication::enter(&self.publication, None);
            publication.open_scope();
            publication
        })
    }

    /// Computes the rest of an update to `model` without changing the form:
    /// the approval gates before and after it, and the model's validation
    /// result. Every callback runs on copies, with no lock held (spec/20 §5.4,
    /// ADR-0215).
    ///
    /// Only strict mode reads dirty state, so only a strict form runs the
    /// dirty comparisons, also while the form is invalid (spec/20 §5.2,
    /// ADR-0216). A missing `live` or `snapshot` is copied from the form when
    /// needed.
    fn prepare_update(&self, live: Option<M>, snapshot: Option<M>, model: M) -> PreparedUpdate<M> {
        let strict = *lock(&self.strict);
        let dirty_inputs = strict.then(|| {
            (
                live.unwrap_or_else(|| self.model()),
                snapshot.unwrap_or_else(|| self.snapshot()),
            )
        });
        let was_dirty = dirty_inputs
            .as_ref()
            .is_none_or(|(live, snapshot)| live != snapshot);
        let was_eligible = self.is_valid() && was_dirty;
        let errors = self.validation_errors_for(&model);
        let dirty = dirty_inputs
            .as_ref()
            .is_none_or(|(_, snapshot)| model != *snapshot);
        let eligible = errors.is_empty() && dirty;
        PreparedUpdate {
            model,
            errors,
            was_eligible,
            eligible,
        }
    }

    /// Commits a placed preparation in one step: the model and its errors.
    /// The caller holds the update lock and placed the update.
    ///
    /// Returns whether the effective errors changed.
    fn commit_update(&self, model: M, errors: BTreeMap<String, String>) -> bool {
        self.note_commit();
        // The replaced model is dropped after the model mutex is released.
        let (errors_changed, replaced) = self.install(model, errors);
        drop(replaced);
        // The generation moves after the install, so a preparation that reads
        // the new generation also reads the new model and errors. A
        // preparation that reads the old generation runs again (spec/20 §5.4).
        self.commit_generation.fetch_add(1, Ordering::SeqCst);
        errors_changed
    }

    /// Installs `model` and its `errors` (see [`ErrorState`]). The caller
    /// holds the update lock, so no other commit stages errors or installs a
    /// model meanwhile. No user code runs between the three steps, and the
    /// replaced model is returned for the caller to drop.
    ///
    /// Returns whether the effective errors changed, and the replaced model.
    fn install(&self, model: M, errors: BTreeMap<String, String>) -> (bool, M) {
        let generation = self.component.model_generation();
        lock(&self.errors).staged = Some((generation, errors));
        let replaced = self.component.store_model(model);
        let mut state = lock(&self.errors);
        let errors_changed = state.staged.take().is_some_and(|(_, next)| {
            let changed = state.committed != next;
            state.committed = next;
            changed
        });
        (errors_changed, replaced)
    }

    /// Runs `read` on the errors of the model a reader can see now: the
    /// staged errors once their model is installed, else the committed ones.
    /// Only the error mutex is held, and `read` runs no user code.
    fn read_errors<R>(&self, read: impl FnOnce(&BTreeMap<String, String>) -> R) -> R {
        let state = lock(&self.errors);
        match &state.staged {
            Some((generation, staged)) if self.component.model_generation() != *generation => {
                read(staged)
            }
            _ => read(&state.committed),
        }
    }

    fn validation_errors_for(&self, model: &M) -> BTreeMap<String, String> {
        let mut next = BTreeMap::new();
        let field_validators = lock(&self.field_validators)
            .iter()
            .map(|(field, validator)| (field.clone(), Arc::clone(validator)))
            .collect::<Vec<_>>();
        for (field, validator) in field_validators {
            if let Some(error) = validator(model) {
                next.insert(field, error);
            }
        }
        let model_validators = lock(&self.model_validators).clone();
        for validator in model_validators {
            for (field, update) in validator(model) {
                match update {
                    Some(error) => {
                        next.insert(field, error);
                    }
                    None => {
                        next.remove(&field);
                    }
                }
            }
        }
        next
    }

    /// Replaces the errors of the live model. The caller holds the update
    /// lock, so no errors are staged.
    fn replace_validation_errors(&self, next: BTreeMap<String, String>) -> bool {
        let mut state = lock(&self.errors);
        if state.committed == next {
            false
        } else {
            state.committed = next;
            true
        }
    }

    fn publish_validation_changed(&self) {
        // A disposal whose teardown waits for this thread's publication makes
        // the rest of it inert, as an observer's own disposal does.
        if *lock(&self.disposed) {
            return;
        }
        // Validation surfaces only on the dedicated errors-changed channel, never
        // on the main message hub. spec/20-form-vm.md §8 enumerates a closed set
        // of hub messages (model + FormReverted); C#/Python/TS/Swift never put
        // validation on the hub. An extra PropertyChanged("is_valid") here would
        // break the FORM-008 reverted-then-model pair.
        self.errors_changed.send(Message::Custom {
            sender_id: self.component.id(),
            sender_name: self.component.name(),
            name: "errors_changed".to_string(),
        });
    }

    /// Publishes the `"model"` hub message of a committed update, unless the
    /// form was disposed meanwhile.
    fn publish_model_changed(&self) {
        if !*lock(&self.disposed) {
            self.component.notify_property_changed("model");
        }
    }

    /// Raises the approve command's eligibility change when an update moved
    /// its validity or strict-mode gate. While the form is disposed or an
    /// approval is in flight, the command stays disabled whatever the update
    /// changed.
    fn publish_eligibility_change(&self, was_eligible: bool, eligible: bool) {
        if was_eligible != eligible && !self.approval_in_flight.load(Ordering::SeqCst) {
            self.raise_approve_can_execute_changed();
        }
    }

    fn publish_approve_state_change(&self, previous: bool) {
        if self.can_approve() != previous {
            self.raise_approve_can_execute_changed();
        }
    }

    fn raise_approve_can_execute_changed(&self) {
        if *lock(&self.disposed) {
            return;
        }
        self.approve_can_execute_changed.send(Message::Custom {
            sender_id: self.component.id(),
            sender_name: self.component.name(),
            name: "can_execute_changed".to_string(),
        });
    }
}

#[derive(Clone)]
/// Immutable builder for [`FormVm`].
pub struct FormVmBuilder<M: Clone + PartialEq + Send + 'static> {
    initial: Option<M>,
    persister: Option<FormPersister<M>>,
    strict: bool,
    hub: MessageHub,
    snapshotter: FormSnapshotter<M>,
    reset_on_approved: Option<FormResetOnApproved<M>>,
    field_validators: BTreeMap<String, FieldValidator<M>>,
    model_validators: Vec<ModelValidator<M>>,
}

impl<M: Clone + PartialEq + Send + 'static> Default for FormVmBuilder<M> {
    fn default() -> Self {
        Self {
            initial: None,
            persister: None,
            strict: false,
            hub: NullMessageHub::hub(),
            snapshotter: Arc::new(|model| model.clone()),
            reset_on_approved: None,
            field_validators: BTreeMap::new(),
            model_validators: Vec::new(),
        }
    }
}

impl<M: Clone + PartialEq + Send + 'static> FormVmBuilder<M> {
    /// Creates an empty builder with clone-based snapshots.
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets the required initial model.
    pub fn initial(mut self, model: M) -> Self {
        self.initial = Some(model);
        self
    }

    /// Sets the required persistence callback.
    pub fn persister<F>(mut self, persister: F) -> Self
    where
        F: Fn(&M) -> VmxResult<()> + Send + Sync + 'static,
    {
        self.persister = Some(Arc::new(persister));
        self
    }

    /// Requires a dirty model in addition to validity before approval.
    pub fn strict(mut self, strict: bool) -> Self {
        self.strict = strict;
        self
    }

    /// Sets the message hub used by the built form.
    pub fn hub(mut self, hub: MessageHub) -> Self {
        self.hub = hub;
        self
    }

    /// Sets the function used to create independent model snapshots.
    pub fn snapshotter<F>(mut self, snapshotter: F) -> Self
    where
        F: Fn(&M) -> M + Send + Sync + 'static,
    {
        self.snapshotter = Arc::new(snapshotter);
        self
    }

    /// Derives the next pristine model from the captured value after a
    /// successful persist.
    pub fn reset_on_approved<F>(mut self, reset_on_approved: F) -> Self
    where
        F: Fn(&M) -> VmxResult<M> + Send + Sync + 'static,
    {
        self.reset_on_approved = Some(Arc::new(reset_on_approved));
        self
    }

    /// Adds or replaces a named field validator.
    pub fn validator<F>(mut self, field: impl Into<String>, validator: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        self.field_validators
            .insert(field.into(), Arc::new(validator));
        self
    }

    /// Adds a whole-model validator returning field-keyed errors.
    ///
    /// This string-map form can only add or replace errors. It is the
    /// compatibility path for [`FormVmBuilder::clearing_model_validator`]:
    /// every returned entry becomes `Some(error)`.
    pub fn model_validator<F>(self, validator: F) -> Self
    where
        F: Fn(&M) -> BTreeMap<String, String> + Send + Sync + 'static,
    {
        self.clearing_model_validator(move |model| error_updates(validator(model)))
    }

    /// Adds a whole-model validator that can add, replace, or clear field
    /// errors, with the same semantics as
    /// [`FormVm::with_clearing_model_validator`].
    pub fn clearing_model_validator<F>(mut self, validator: F) -> Self
    where
        F: Fn(&M) -> BTreeMap<String, Option<String>> + Send + Sync + 'static,
    {
        self.model_validators.push(Arc::new(validator));
        self
    }

    /// Validates required inputs and builds the form.
    pub fn build(self) -> VmxResult<FormVm<M>> {
        let initial = self
            .initial
            .ok_or_else(|| VmxError::BuilderValidation("initial is required".to_string()))?;
        let persister = self
            .persister
            .ok_or_else(|| VmxError::BuilderValidation("persister is required".to_string()))?;
        let snapshot = (self.snapshotter)(&initial);
        let form = FormVm {
            component: ComponentVm::with_model(
                "FormVm",
                initial,
                self.hub.clone(),
                NullDispatcher::new(),
            ),
            snapshot: Arc::new(Mutex::new(snapshot)),
            persister,
            snapshotter: self.snapshotter,
            reset_on_approved: self.reset_on_approved,
            strict: Arc::new(Mutex::new(self.strict)),
            errors: Arc::new(Mutex::new(ErrorState::new())),
            field_validators: Arc::new(Mutex::new(self.field_validators)),
            model_validators: Arc::new(Mutex::new(self.model_validators)),
            errors_changed: MessageHub::new(),
            approve_errors: MessageHub::new(),
            approve_can_execute_changed: MessageHub::new(),
            approve_command: Arc::new(OnceLock::new()),
            deny_command: Arc::new(OnceLock::new()),
            approved_callbacks: Arc::new(Mutex::new(ApprovedRegistry::new())),
            publication: Arc::new(PublicationControl::new()),
            approval_in_flight: Arc::new(AtomicBool::new(false)),
            update_lock: Arc::new(UpdateLock::new()),
            nested: Arc::new(Mutex::new(NestedUpdates::new())),
            commit_generation: Arc::new(AtomicU64::new(0)),
            revalidations: Arc::new(AtomicU64::new(0)),
            pair_version: Arc::new(AtomicU64::new(0)),
            disposed: Arc::new(Mutex::new(false)),
            hub: self.hub,
        };
        Ok(form.with_initial_validation())
    }
}
