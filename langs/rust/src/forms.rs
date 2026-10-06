use super::{
    lock, Arc, AtomicBool, BTreeMap, ComponentVm, FormRevertedMessage, Message, MessageHub, Mutex,
    NullDispatcher, NullMessageHub, OnceLock, Ordering, RelayCommand, RelayCommandBuilder,
    VmxError, VmxResult, Weak,
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

struct ApprovalPublication<M> {
    pre_publishing: bool,
    deferred_models: Vec<M>,
}

struct ApprovalPrePublicationGuard<M> {
    publication: Arc<Mutex<ApprovalPublication<M>>>,
}

impl<M> ApprovalPrePublicationGuard<M> {
    fn new(publication: Arc<Mutex<ApprovalPublication<M>>>) -> Self {
        lock(&publication).pre_publishing = true;
        Self { publication }
    }
}

impl<M> Drop for ApprovalPrePublicationGuard<M> {
    fn drop(&mut self) {
        lock(&self.publication).pre_publishing = false;
    }
}

#[derive(Clone)]
/// Editable model state with validation, persistence, approval, and revert commands.
pub struct FormVm<M: Clone + PartialEq + Send + 'static> {
    pub(crate) component: ComponentVm<M>,
    snapshot: Arc<Mutex<M>>,
    persister: FormPersister<M>,
    snapshotter: FormSnapshotter<M>,
    reset_on_approved: Option<FormResetOnApproved<M>>,
    strict: Arc<Mutex<bool>>,
    errors: Arc<Mutex<BTreeMap<String, String>>>,
    field_validators: Arc<Mutex<BTreeMap<String, FieldValidator<M>>>>,
    model_validators: Arc<Mutex<Vec<ModelValidator<M>>>>,
    errors_changed: MessageHub,
    approve_errors: MessageHub,
    approve_can_execute_changed: MessageHub,
    approve_command: Arc<OnceLock<RelayCommand>>,
    deny_command: Arc<OnceLock<RelayCommand>>,
    approved_callbacks: Arc<Mutex<ApprovedRegistry<M>>>,
    approval_publication: Arc<Mutex<ApprovalPublication<M>>>,
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
            errors: Arc::new(Mutex::new(BTreeMap::new())),
            field_validators: Arc::new(Mutex::new(BTreeMap::new())),
            model_validators: Arc::new(Mutex::new(Vec::new())),
            errors_changed: MessageHub::new(),
            approve_errors: MessageHub::new(),
            approve_can_execute_changed: MessageHub::new(),
            approve_command: Arc::new(OnceLock::new()),
            deny_command: Arc::new(OnceLock::new()),
            approved_callbacks: Arc::new(Mutex::new(ApprovedRegistry::new())),
            approval_publication: Arc::new(Mutex::new(ApprovalPublication {
                pre_publishing: false,
                deferred_models: Vec::new(),
            })),
            disposed: Arc::new(Mutex::new(false)),
            hub,
        };
        form.validate();
        form
    }

    /// Creates an empty immutable builder for a form.
    pub fn builder() -> FormVmBuilder<M> {
        FormVmBuilder::new()
    }

    /// Adds a whole-model validator that returns an ordered error list.
    pub fn with_validator<F>(self, validator: F) -> Self
    where
        F: Fn(&M) -> Vec<String> + Send + Sync + 'static,
    {
        let could_approve = self.can_approve();
        lock(&self.model_validators).push(Arc::new(move |model| {
            validator(model)
                .into_iter()
                .enumerate()
                .map(|(index, error)| (index.to_string(), Some(error)))
                .collect()
        }));
        self.validate();
        self.publish_approve_state_change(could_approve);
        self
    }

    /// Adds or replaces validation for one named field and revalidates immediately.
    pub fn with_field_validator<F>(&self, field: impl Into<String>, validator: F)
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        let could_approve = self.can_approve();
        lock(&self.field_validators).insert(field.into(), Arc::new(validator));
        self.validate();
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
        let could_approve = self.can_approve();
        lock(&self.model_validators).push(Arc::new(validator));
        self.validate();
        self.publish_approve_state_change(could_approve);
    }

    /// Returns a clone of the current editable model.
    pub fn model(&self) -> M {
        self.component.model()
    }

    /// Replaces the editable model and publishes resulting validation changes.
    pub fn set_model(&self, model: M) {
        if *lock(&self.disposed) {
            return;
        }
        {
            let mut publication = lock(&self.approval_publication);
            if publication.pre_publishing {
                publication.deferred_models.push(model);
                return;
            }
        }
        let could_approve = self.can_approve();
        if !self.component.replace_model(model) {
            return;
        }
        self.validate();
        self.publish_approve_state_change(could_approve);
        self.component.notify_property_changed("model");
    }

    /// Returns a clone of the last approved or initial snapshot.
    pub fn snapshot(&self) -> M {
        lock(&self.snapshot).clone()
    }

    /// Reports whether the current model differs from the snapshot.
    pub fn is_dirty(&self) -> bool {
        self.model() != *lock(&self.snapshot)
    }

    /// Returns the current validation messages in field-key order.
    pub fn errors(&self) -> Vec<String> {
        lock(&self.errors).values().cloned().collect()
    }

    /// Returns the current validation errors keyed by field.
    pub fn error_map(&self) -> BTreeMap<String, String> {
        lock(&self.errors).clone()
    }

    /// Returns the current error for `field`, when present.
    pub fn field_error(&self, field: &str) -> Option<String> {
        lock(&self.errors).get(field).cloned()
    }

    /// Reports whether no validation errors are present.
    pub fn is_valid(&self) -> bool {
        lock(&self.errors).is_empty()
    }

    /// Reports whether approval is currently admitted.
    pub fn can_approve(&self) -> bool {
        !*lock(&self.disposed) && self.is_valid() && (!*lock(&self.strict) || self.is_dirty())
    }

    /// Persists the captured model and advances or resets the pristine snapshot.
    pub fn approve(&self) -> VmxResult<()> {
        if *lock(&self.disposed) {
            return Ok(());
        }
        if !self.is_valid() {
            return Ok(());
        }
        let model = self.model();
        (self.persister)(&model)?;
        if *lock(&self.disposed) {
            return Ok(());
        }
        let could_approve = self.can_approve();
        let errors_changed = if let Some(reset_on_approved) = &self.reset_on_approved {
            // Prepare the complete transition before mutating local state. The
            // callback or either snapshot operation may fail/panic without a
            // partial assignment.
            let reset = reset_on_approved(&model)?;
            let next_model = (self.snapshotter)(&reset);
            let next_snapshot = (self.snapshotter)(&reset);
            let next_errors = self.validation_errors_for(&next_model);

            // Install every derived field before the approval outcome is
            // published, so synchronous observers cannot see a reset model
            // paired with the previous snapshot or errors.
            *lock(&self.snapshot) = next_snapshot;
            let errors_changed = self.replace_validation_errors(next_errors);
            self.component.replace_model(next_model);
            errors_changed
        } else {
            *lock(&self.snapshot) = (self.snapshotter)(&model);
            false
        };
        {
            let _publication =
                ApprovalPrePublicationGuard::new(Arc::clone(&self.approval_publication));
            if errors_changed {
                self.publish_validation_changed();
            }
            self.publish_approve_state_change(could_approve);
        }
        let callbacks = lock(&self.approved_callbacks).entries.clone();
        for (id, callback) in callbacks {
            // A callback detached, or a form disposed, during this emission
            // before the callback's turn does not receive it (ADR-0139).
            if !lock(&self.approved_callbacks).is_registered(id) {
                continue;
            }
            callback(model.clone());
        }
        let deferred_models = {
            let mut publication = lock(&self.approval_publication);
            std::mem::take(&mut publication.deferred_models)
        };
        for deferred_model in deferred_models {
            self.set_model(deferred_model);
        }
        Ok(())
    }

    /// Restores the last snapshot and publishes the revert outcome.
    pub fn revert(&self) {
        if *lock(&self.disposed) {
            return;
        }
        let could_approve = self.can_approve();
        let snapshot = lock(&self.snapshot).clone();
        let restored = (self.snapshotter)(&snapshot);
        self.component.replace_model(restored);
        self.validate();
        self.hub.send(Message::FormReverted(FormRevertedMessage {
            sender_id: self.component.id(),
            sender_name: "FormVm".to_string(),
        }));
        self.component.notify_property_changed("model");
        self.publish_approve_state_change(could_approve);
    }

    /// Returns the lazily created approval command.
    pub fn approve_command(&self) -> RelayCommand {
        self.approve_command
            .get_or_init(|| {
                let form = self.command_target();
                RelayCommandBuilder::default()
                    .action(move || {
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
                RelayCommand::new(move || form.revert()).with_can_execute({
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
        lock(&self.field_validators).clear();
        lock(&self.model_validators).clear();
        let _ = self.component.dispose();
    }

    fn command_target(&self) -> Self {
        let mut target = self.clone();
        target.approve_command = Arc::new(OnceLock::new());
        target.deny_command = Arc::new(OnceLock::new());
        target
    }

    fn validate(&self) {
        let next = self.validation_errors_for(&self.model());
        self.commit_validation(next);
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

    fn commit_validation(&self, next: BTreeMap<String, String>) {
        if self.replace_validation_errors(next) {
            self.publish_validation_changed();
        }
    }

    fn replace_validation_errors(&self, next: BTreeMap<String, String>) -> bool {
        {
            let mut errors = lock(&self.errors);
            if *errors == next {
                false
            } else {
                *errors = next;
                true
            }
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

    fn publish_approve_state_change(&self, previous: bool) {
        if self.can_approve() != previous {
            self.approve_can_execute_changed.send(Message::Custom {
                sender_id: self.component.id(),
                sender_name: self.component.name(),
                name: "can_execute_changed".to_string(),
            });
        }
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
            errors: Arc::new(Mutex::new(BTreeMap::new())),
            field_validators: Arc::new(Mutex::new(self.field_validators)),
            model_validators: Arc::new(Mutex::new(self.model_validators)),
            errors_changed: MessageHub::new(),
            approve_errors: MessageHub::new(),
            approve_can_execute_changed: MessageHub::new(),
            approve_command: Arc::new(OnceLock::new()),
            deny_command: Arc::new(OnceLock::new()),
            approved_callbacks: Arc::new(Mutex::new(ApprovedRegistry::new())),
            approval_publication: Arc::new(Mutex::new(ApprovalPublication {
                pre_publishing: false,
                deferred_models: Vec::new(),
            })),
            disposed: Arc::new(Mutex::new(false)),
            hub: self.hub,
        };
        form.validate();
        Ok(form)
    }
}
