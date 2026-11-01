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

/// Model edits deferred while a successful approval publishes the
/// notifications that precede `OnApproved`, so its observers see the
/// committed state.
struct ApprovalPublication<M> {
    /// Number of settlements publishing those notifications. It is a depth,
    /// not a flag: an approval admitted by one of their observers settles
    /// inside the outer publication and must not end it (ADR-0143).
    pre_publishing: usize,
    /// Per thread, the number of settlements still publishing, `OnApproved`
    /// included. Only a thread's outermost settlement replays the deferred
    /// edits (#1061). A nested approval started by an approval subscriber
    /// leaves them until the outer subscribers have run. The depth is per
    /// thread: another thread's settlement still replays when it ends.
    publishing: Vec<(ThreadId, usize)>,
    deferred_models: Vec<M>,
}

impl<M> ApprovalPublication<M> {
    fn new() -> Self {
        Self {
            pre_publishing: 0,
            publishing: Vec::new(),
            deferred_models: Vec::new(),
        }
    }

    fn enter(&mut self, thread: ThreadId) {
        match self
            .publishing
            .iter_mut()
            .find(|(owner, _)| *owner == thread)
        {
            Some((_, depth)) => *depth += 1,
            None => self.publishing.push((thread, 1)),
        }
    }

    /// Ends one settlement on `thread`. Returns whether it was the thread's
    /// outermost one.
    fn leave(&mut self, thread: ThreadId) -> bool {
        let Some(index) = self
            .publishing
            .iter()
            .position(|(owner, _)| *owner == thread)
        else {
            return true;
        };
        self.publishing[index].1 -= 1;
        if self.publishing[index].1 > 0 {
            return false;
        }
        self.publishing.swap_remove(index);
        true
    }
}

/// Counts one settlement in [`ApprovalPublication::publishing`] until it
/// finishes, even when a notification observer panics.
struct ApprovalPublishingGuard<M> {
    publication: Arc<Mutex<ApprovalPublication<M>>>,
    thread: ThreadId,
    finished: bool,
}

impl<M> ApprovalPublishingGuard<M> {
    fn new(publication: Arc<Mutex<ApprovalPublication<M>>>) -> Self {
        let thread = thread::current().id();
        lock(&publication).enter(thread);
        Self {
            publication,
            thread,
            finished: false,
        }
    }

    /// Ends this settlement's publication. Returns the deferred edits when it
    /// is this thread's outermost settlement and no settlement is publishing
    /// its notifications; returns none otherwise.
    fn finish(mut self) -> Vec<M> {
        self.finished = true;
        let mut publication = lock(&self.publication);
        if publication.leave(self.thread) && publication.pre_publishing == 0 {
            std::mem::take(&mut publication.deferred_models)
        } else {
            Vec::new()
        }
    }
}

impl<M> Drop for ApprovalPublishingGuard<M> {
    fn drop(&mut self) {
        if !self.finished {
            lock(&self.publication).leave(self.thread);
        }
    }
}

struct ApprovalPrePublicationGuard<M> {
    publication: Arc<Mutex<ApprovalPublication<M>>>,
}

impl<M> ApprovalPrePublicationGuard<M> {
    fn new(publication: Arc<Mutex<ApprovalPublication<M>>>) -> Self {
        lock(&publication).pre_publishing += 1;
        Self { publication }
    }
}

impl<M> Drop for ApprovalPrePublicationGuard<M> {
    fn drop(&mut self) {
        lock(&self.publication).pre_publishing -= 1;
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

/// Serializes a form's model updates (spec/20 §5.4, ADR-0144).
///
/// The lock is re-entrant: a callback may update or dispose the form again
/// from the thread that holds it, and another thread waits until that thread
/// releases it. Its state mutex is held only to change the owner and depth,
/// never while a callback runs, and [`UpdateGuard`] releases the lock on every
/// exit path, a panic included.
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
    /// The commit generation read before the preparation's first callback.
    generation: u64,
    model: M,
    errors: BTreeMap<String, String>,
    /// Whether the validity and strict-mode gates admitted approval before
    /// the update.
    was_eligible: bool,
    /// Whether they admit approval after it.
    eligible: bool,
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
    approval_publication: Arc<Mutex<ApprovalPublication<M>>>,
    approval_in_flight: Arc<AtomicBool>,
    /// Serializes model updates, approval admission, approval commits, and
    /// disposal across threads (spec/20 §5.4, ADR-0144).
    update_lock: Arc<UpdateLock>,
    /// Counts the commits of model, snapshot, and error state, each made
    /// under the update lock. Only a callback re-entering from the preparing
    /// thread can advance it during a preparation, which is then stale.
    commit_generation: Arc<AtomicU64>,
    /// Counts the revalidations that validator registrations start, each under
    /// the update lock. While an approval validates its reset model, only a
    /// registration re-entering from that thread can advance it (#1046).
    revalidations: Arc<AtomicU64>,
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
            approval_publication: Arc::new(Mutex::new(ApprovalPublication::new())),
            approval_in_flight: Arc::new(AtomicBool::new(false)),
            update_lock: Arc::new(UpdateLock::new()),
            commit_generation: Arc::new(AtomicU64::new(0)),
            revalidations: Arc::new(AtomicU64::new(0)),
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
        let could_approve = self.can_approve();
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
        self.publish_approve_state_change(could_approve);
        self
    }

    /// Adds or replaces validation for one named field and revalidates immediately.
    pub fn with_field_validator<F>(&self, field: impl Into<String>, validator: F)
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        // A registration after dispose is inactive (see the type docs).
        if *lock(&self.disposed) {
            return;
        }
        let could_approve = self.can_approve();
        let replaced = lock(&self.field_validators).insert(field.into(), Arc::new(validator));
        // A replaced validator is dropped after the lock is released.
        drop(replaced);
        self.revalidate();
        self.publish_approve_state_change(could_approve);
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
        let could_approve = self.can_approve();
        lock(&self.model_validators).push(Arc::new(validator));
        self.revalidate();
        self.publish_approve_state_change(could_approve);
    }

    /// Returns a clone of the current editable model.
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
    /// Updates are serialized: another thread's update, approval admission,
    /// approval commit, or disposal waits until this preparation and commit
    /// finish. A callback
    /// may re-enter the form from this thread; when it disposes the form or
    /// commits another update, this call commits and publishes nothing, and
    /// the newer state stands.
    ///
    /// A panic in a validator or in `PartialEq` unwinds with the form
    /// unchanged, nothing published, and no lock poisoned or held, so the form
    /// stays usable.
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
        {
            let mut publication = lock(&self.approval_publication);
            if publication.pre_publishing > 0 {
                publication.deferred_models.push(model);
                return;
            }
        }
        let Some(serialized) = self.begin_update() else {
            return;
        };
        let Some(update) = self.prepare_assignment(model) else {
            return;
        };
        let (was_eligible, eligible) = (update.was_eligible, update.eligible);
        let committed = self.commit_update(update);
        drop(serialized);
        let Some(errors_changed) = committed else {
            return;
        };
        if errors_changed {
            self.publish_validation_changed();
        }
        self.publish_eligibility_change(was_eligible, eligible);
        self.component.notify_property_changed("model");
    }

    /// Returns a clone of the last approved or initial snapshot.
    pub fn snapshot(&self) -> M {
        clone_locked(&self.snapshot)
    }

    /// Reports whether the current model differs from the snapshot.
    pub fn is_dirty(&self) -> bool {
        // Compare copies, so no lock is held while `PartialEq` runs.
        let model = self.model();
        model != self.snapshot()
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
        // No lock is held while the persister runs. A panic is caught only to
        // settle the approval before it resumes.
        let outcome = catch_unwind(AssertUnwindSafe(|| self.persist_and_commit(&model)));
        // Settlement step 1: every settlement observer sees an idle form.
        drop(flight);
        match outcome {
            Ok(Ok(Some(errors_changed))) => {
                self.settle_approved(model, errors_changed);
                Ok(())
            }
            // Disposal during the approval suppressed the commit and settlement.
            Ok(Ok(None)) => Ok(()),
            Ok(Err(error)) => {
                self.raise_approve_can_execute_changed();
                Err(error)
            }
            Err(panic) => {
                self.raise_approve_can_execute_changed();
                resume_unwind(panic)
            }
        }
    }

    /// Admits an approval when the form is not disposed, is valid, and has
    /// none in flight. Admission sets the in-flight mark before it captures
    /// the model, then raises the approve command's eligibility change once.
    fn admit_approval(&self) -> Option<(ApprovalFlight, M)> {
        // Check validity, mark the flight and capture the model under the
        // update lock, so a `set_model` on another thread cannot commit an
        // invalid model between the check and the capture (#719). The lock is
        // re-entrant, and it is released before the admission observers run.
        let (flight, model) = {
            let _serialized = self.update_lock.acquire();
            if *lock(&self.disposed) || !self.is_valid() {
                return None;
            }
            let flight = ApprovalFlight::admit(&self.approval_in_flight)?;
            if *lock(&self.disposed) {
                return None;
            }
            (flight, self.model())
        };
        self.raise_approve_can_execute_changed();
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
    fn persist_and_commit(&self, model: &M) -> VmxResult<Option<bool>> {
        (self.persister)(model)?;
        if *lock(&self.disposed) {
            return Ok(None);
        }
        let committed = if let Some(reset_on_approved) = &self.reset_on_approved {
            // Prepare the complete transition before mutating local state. The
            // callback or either snapshot operation may fail/panic without a
            // partial assignment. The commit validates the reset model.
            let reset = reset_on_approved(model)?;
            let next_model = (self.snapshotter)(&reset);
            let next_snapshot = (self.snapshotter)(&reset);
            self.commit_approval(next_snapshot, Some(next_model))
        } else {
            self.commit_approval((self.snapshotter)(model), None)
        };
        Ok(committed)
    }

    /// Commits the post-persist state: the advanced snapshot, or a prepared
    /// reset model, which it validates first.
    ///
    /// The commit is authoritative over edits made during the approval
    /// (spec/20 §5.1) and yields only to disposal. Admission and this step
    /// take the update lock, so each waits for an update another thread is
    /// preparing, while the persister runs with edits unblocked (§5.3). It installs every
    /// field in one step before the approval outcome is published, so
    /// synchronous observers cannot see a reset model paired with the previous
    /// snapshot or errors. Returns whether the effective errors changed, or
    /// `None` when disposal suppressed the commit.
    fn commit_approval(&self, snapshot: M, reset: Option<M>) -> Option<bool> {
        let serialized = self.update_lock.acquire();
        if *lock(&self.disposed) {
            drop(serialized);
            return None;
        }
        // The reset model is validated under the update lock, before any field
        // changes (#1046). A validator registered on another thread meanwhile
        // revalidates after this commit. A validator registered re-entrantly
        // during a run makes the validation run again, until a run registers
        // none. A re-entrant update needs no rerun: the reset is authoritative.
        let reset = reset.map(|model| loop {
            let revalidations = self.revalidations.load(Ordering::SeqCst);
            let errors = self.validation_errors_for(&model);
            if self.revalidations.load(Ordering::SeqCst) == revalidations {
                break (model, errors);
            }
        });
        if *lock(&self.disposed) {
            drop(serialized);
            return None;
        }
        self.commit_generation.fetch_add(1, Ordering::SeqCst);
        let replaced_snapshot = std::mem::replace(&mut *lock(&self.snapshot), snapshot);
        let (errors_changed, replaced_model) = match reset {
            Some((model, errors)) => {
                let (errors_changed, replaced) = self.install(model, errors);
                (errors_changed, Some(replaced))
            }
            None => (false, None),
        };
        drop(serialized);
        // Replaced values are dropped after the update lock is released.
        drop((replaced_snapshot, replaced_model));
        Some(errors_changed)
    }

    /// Settlement steps 2 to 4 of a committed approval. The in-flight mark is
    /// already clear.
    fn settle_approved(&self, model: M, errors_changed: bool) {
        let publishing = ApprovalPublishingGuard::new(Arc::clone(&self.approval_publication));
        {
            // Model edits made by these observers wait until the approval
            // subscribers have seen the committed state.
            let _publication =
                ApprovalPrePublicationGuard::new(Arc::clone(&self.approval_publication));
            if errors_changed {
                self.publish_validation_changed();
            }
            // The one settlement notification also covers any strict or
            // validity change made by the commit.
            self.raise_approve_can_execute_changed();
        }
        // Snapshot only the identities: each callback is looked up when its
        // turn comes, so a callback detached (or a form disposed) earlier in
        // this emission neither runs nor stays alive until it ends (ADR-0139).
        let ids: Vec<u64> = lock(&self.approved_callbacks)
            .entries
            .iter()
            .map(|(id, _)| *id)
            .collect();
        // A panicking subscriber still lets the deferred edits replay, as the
        // other flavors replay them in `finally`; the panic then continues
        // to the approve caller (#740).
        let published = catch_unwind(AssertUnwindSafe(|| {
            for id in ids {
                let callback = lock(&self.approved_callbacks)
                    .entries
                    .iter()
                    .find(|(entry_id, _)| *entry_id == id)
                    .map(|(_, callback)| Arc::clone(callback));
                if let Some(callback) = callback {
                    callback(model.clone());
                }
            }
        }));
        // An enclosing settlement on this thread, in its notifications or its
        // subscribers, keeps the edits until its own subscribers have run.
        let deferred_models = publishing.finish();
        for deferred_model in deferred_models {
            self.set_model(deferred_model);
        }
        if let Err(payload) = published {
            resume_unwind(payload);
        }
    }

    /// Restores the last snapshot and publishes the revert outcome.
    ///
    /// Like [`set_model`](Self::set_model), a revert prepares before it
    /// commits (spec/20 §5.4, ADR-0144): the snapshotter copies the snapshot
    /// and the validators run on that copy before the form changes. A panic in
    /// either unwinds with the form unchanged and nothing published, including
    /// no [`FormRevertedMessage`]. A revert is serialized with other updates,
    /// and when a callback on this thread disposes the form or commits another
    /// update during preparation, the revert commits and publishes nothing.
    pub fn revert(&self) {
        if *lock(&self.disposed) {
            return;
        }
        let Some(serialized) = self.begin_update() else {
            return;
        };
        let generation = self.commit_generation.load(Ordering::SeqCst);
        let snapshot = self.snapshot();
        let restored = (self.snapshotter)(&snapshot);
        let update = self.prepare_update(generation, None, Some(snapshot), restored);
        let (was_eligible, eligible) = (update.was_eligible, update.eligible);
        let committed = self.commit_update(update);
        drop(serialized);
        let Some(errors_changed) = committed else {
            return;
        };
        if errors_changed {
            self.publish_validation_changed();
        }
        self.hub.send(Message::FormReverted(FormRevertedMessage {
            sender_id: self.component.id(),
            sender_name: "FormVm".to_string(),
        }));
        self.component.notify_property_changed("model");
        self.publish_eligibility_change(was_eligible, eligible);
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
    pub fn approve_command(&self) -> RelayCommand {
        self.approve_command
            .get_or_init(|| {
                let form = self.command_target();
                RelayCommandBuilder::default()
                    .shared_action(move || {
                        if let Err(error) = form.approve() {
                            form.approve_errors.send(Message::Custom {
                                sender_id: form.component.id(),
                                sender_name: form.component.name(),
                                name: error.to_string(),
                            });
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
    pub fn dispose(&self) {
        let should_dispose = {
            // Disposal waits for an update in progress on another thread, so
            // an admitted update completes (spec/20 §5.4).
            let _serialized = self.update_lock.acquire();
            let mut disposed = lock(&self.disposed);
            if *disposed {
                false
            } else {
                *disposed = true;
                true
            }
        };
        if !should_dispose {
            return;
        }

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

    /// Revalidates the live model after a validator registration and
    /// publishes an effective error change. The run is serialized with model
    /// updates, and an update or registration that one of its validators
    /// commits supersedes it.
    fn revalidate(&self) {
        let serialized = self.update_lock.acquire();
        self.revalidations.fetch_add(1, Ordering::SeqCst);
        let generation = self.commit_generation.load(Ordering::SeqCst);
        let errors = self.validation_errors_for(&self.model());
        if self.commit_generation.load(Ordering::SeqCst) != generation {
            return;
        }
        self.commit_generation.fetch_add(1, Ordering::SeqCst);
        let errors_changed = self.replace_validation_errors(errors);
        drop(serialized);
        if errors_changed {
            self.publish_validation_changed();
        }
    }

    /// Takes the update lock for an update admitted before disposal. Returns
    /// `None`, with the lock released, when a disposal that held the lock
    /// first has ended the form.
    fn begin_update(&self) -> Option<UpdateGuard<'_>> {
        let serialized = self.update_lock.acquire();
        let disposed = *lock(&self.disposed);
        (!disposed).then_some(serialized)
    }

    /// Prepares assigning `model` (spec/20 §5.2 steps 3 to 6). Returns `None`
    /// when `model` equals the live model.
    fn prepare_assignment(&self, model: M) -> Option<PreparedUpdate<M>> {
        let generation = self.commit_generation.load(Ordering::SeqCst);
        let live = self.model();
        if live == model {
            return None;
        }
        Some(self.prepare_update(generation, Some(live), None, model))
    }

    /// Computes the rest of an update to `model` without changing the form:
    /// the approval gates before and after it, and the model's validation
    /// result. Every callback runs on copies, with no state mutex held; only
    /// the re-entrant update lock is.
    ///
    /// Only strict mode reads dirty state, so only a strict form runs the
    /// dirty comparisons, and only while its validity gate is open. A missing
    /// `live` or `snapshot` is copied from the form when needed.
    fn prepare_update(
        &self,
        generation: u64,
        live: Option<M>,
        snapshot: Option<M>,
        model: M,
    ) -> PreparedUpdate<M> {
        let strict = *lock(&self.strict);
        let dirty_inputs = strict.then(|| {
            (
                live.unwrap_or_else(|| self.model()),
                snapshot.unwrap_or_else(|| self.snapshot()),
            )
        });
        let was_eligible = self.is_valid()
            && dirty_inputs
                .as_ref()
                .is_none_or(|(live, snapshot)| live != snapshot);
        let errors = self.validation_errors_for(&model);
        let eligible = errors.is_empty()
            && dirty_inputs
                .as_ref()
                .is_none_or(|(_, snapshot)| model != *snapshot);
        PreparedUpdate {
            generation,
            model,
            errors,
            was_eligible,
            eligible,
        }
    }

    /// Commits a completed preparation in one step: the model and its errors.
    /// The caller holds the update lock.
    ///
    /// Returns whether the effective errors changed, or `None` for a stale
    /// preparation: a callback re-entering from this thread disposed the form
    /// or committed another update after the preparation began.
    fn commit_update(&self, update: PreparedUpdate<M>) -> Option<bool> {
        if self.commit_generation.load(Ordering::SeqCst) != update.generation
            || *lock(&self.disposed)
        {
            return None;
        }
        self.commit_generation.fetch_add(1, Ordering::SeqCst);
        // The replaced model is dropped after the model mutex is released.
        let (errors_changed, replaced) = self.install(update.model, update.errors);
        drop(replaced);
        Some(errors_changed)
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
            approval_publication: Arc::new(Mutex::new(ApprovalPublication::new())),
            approval_in_flight: Arc::new(AtomicBool::new(false)),
            update_lock: Arc::new(UpdateLock::new()),
            commit_generation: Arc::new(AtomicU64::new(0)),
            revalidations: Arc::new(AtomicU64::new(0)),
            disposed: Arc::new(Mutex::new(false)),
            hub: self.hub,
        };
        Ok(form.with_initial_validation())
    }
}
