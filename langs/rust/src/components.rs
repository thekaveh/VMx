//! Modeled leaf view models, read-only wrappers, and builders.
//!
//! Spec: `spec/05-component-vm.md`.

use super::{
    clone_locked, finish_with_first_failure, fmt, lock, retain_first_failure, Arc, ComponentCore,
    ConstructionStatus, Dispatcher, LifecycleOperation, Message, MessageHub, ModelHint, Mutex,
    NullDispatcher, ParentHandle, PropertyChangedStream, RelayCommand, Subscription, TreeNode,
    VmNode, VmxError, VmxResult,
};
use std::cell::RefCell;
use std::marker::PhantomData;
use std::sync::atomic::{AtomicU64, Ordering};

/// Identifies the role a view model plays in the VM hierarchy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ViewModelType {
    /// A modeled or unmodeled leaf component.
    Component,
    /// A modeled leaf component whose model is immutable.
    ReadOnlyComponent,
    /// A heterogeneous fixed-slot aggregate.
    Aggregate,
    /// A homogeneous non-selectable group.
    Group,
    /// A homogeneous selectable composite.
    Composite,
}

#[derive(Clone)]
pub(crate) struct ComponentCommands {
    select: RelayCommand,
    deselect: RelayCommand,
    select_next: RelayCommand,
    select_previous: RelayCommand,
    reconstruct: RelayCommand,
    status_subscription: Arc<Subscription>,
}

impl ComponentCommands {
    pub(crate) fn new<D: Dispatcher, F>(core: &ComponentCore<D>, reconstruct_action: F) -> Self
    where
        F: Fn() + Send + Sync + 'static,
    {
        let select = {
            let action_core = core.clone();
            let predicate_core = core.clone();
            RelayCommand::new_shared(move || action_core.select_via_parent())
                .with_can_execute(move || predicate_core.can_select())
        };
        let deselect = {
            let action_core = core.clone();
            let predicate_core = core.clone();
            RelayCommand::new_shared(move || action_core.deselect_via_parent())
                .with_can_execute(move || predicate_core.can_deselect())
        };
        let reconstruct = {
            let predicate_core = core.clone();
            RelayCommand::new_shared(reconstruct_action)
                .with_can_execute(move || predicate_core.can_reconstruct())
        };
        let select_next = RelayCommand::noop().with_can_execute(|| false);
        let select_previous = RelayCommand::noop().with_can_execute(|| false);
        let status_subscription = {
            let sender_id = core.id();
            let commands = [
                select.clone(),
                deselect.clone(),
                select_next.clone(),
                select_previous.clone(),
                reconstruct.clone(),
            ];
            Arc::new(core.hub().subscribe(move |message| {
                if matches!(
                    message,
                    Message::ConstructionStatusChanged(change) if change.sender_id == sender_id
                ) {
                    for command in &commands {
                        command.raise_can_execute_changed();
                    }
                }
            }))
        };
        Self {
            select,
            deselect,
            select_next,
            select_previous,
            reconstruct,
            status_subscription,
        }
    }

    pub(crate) fn select(&self) -> RelayCommand {
        self.select.clone()
    }

    pub(crate) fn deselect(&self) -> RelayCommand {
        self.deselect.clone()
    }

    pub(crate) fn select_next(&self) -> RelayCommand {
        self.select_next.clone()
    }

    pub(crate) fn select_previous(&self) -> RelayCommand {
        self.select_previous.clone()
    }

    pub(crate) fn reconstruct(&self) -> RelayCommand {
        self.reconstruct.clone()
    }

    pub(crate) fn dispose(&self) {
        self.status_subscription.dispose();
        self.select.dispose();
        self.deselect.dispose();
        self.select_next.dispose();
        self.select_previous.dispose();
        self.reconstruct.dispose();
    }
}

/// One in-flight construct or destruct of a [`ComponentVm`] that walks the
/// component's member view-models (spec/02 §6.1, ADR-0162).
///
/// This is the Rust analogue of the protected child-transition helper that
/// subclasses of the component base use in the other flavors. Rust has no
/// subclassing, so a consumer view-model type composes a `ComponentVm`, keeps
/// its member view-models in fields, and drives them through
/// [`ComponentVm::construct_with_children`],
/// [`ComponentVm::destruct_with_children`], and
/// [`ComponentVm::reconstruct_with_children`]. Those methods run the
/// component's own transition and, after its `on_construct` or `on_destruct`
/// hook succeeds, pass a `ChildTransitions` to the walk closure. The closure
/// adds steps:
///
/// - [`transition`](Self::transition) constructs or destructs one child. Steps
///   run in the order they are added, one child at a time: a child starts only
///   after the previous one settled. A child already at the target status is
///   skipped; a child already `Constructing` or `Destructing` is joined, not
///   started again.
/// - [`then`](Self::then) runs a callback once every earlier step settled,
///   before the component publishes its terminal status.
///
/// A child that is still `Constructing` or `Destructing` when its call returns
/// (a background child) keeps the component in its transient status; the
/// remaining steps run, and the component publishes its terminal status, once
/// that child settles. A child that settles anywhere other than the target, or
/// a failing `then` callback, fails the walk: the component rolls back to its
/// prior settled status (`Destructed` after a failed construct, `Constructed`
/// after a failed destruct), and no later step runs. A failure found while the
/// walk method runs is returned from it; a failure found after a background
/// child settles reaches [`ComponentVm::background_errors`]. Siblings that
/// already reached the target are not undone.
///
/// The steps take no order option: pass the children in the order the walk
/// needs, for example in reverse for a reverse-order destruct.
///
/// Two limits apply. `construct_with_children` and `destruct_with_children`
/// return [`VmxError::InvalidArgument`] for a component built with
/// `background(true)`, because the walk cannot move to the background
/// dispatcher; `reconstruct_with_children` runs synchronously like
/// [`ComponentVm::reconstruct`]. And [`ComponentVm::reconstruct`] and
/// [`ComponentVm::reconstruct_command`] run only the hooks, never a walk.
///
/// The handle borrows the transition, so it exists only inside the walk
/// closure; using it from anywhere else does not compile. That is the Rust
/// form of the other flavors' "callable only from the component's own hook"
/// usage error:
///
/// ```compile_fail,E0521
/// use vmx::{ChildTransitions, ComponentVm};
///
/// let vm = ComponentVm::new("parent");
/// let mut escaped: Option<&ChildTransitions<'_, vmx::NullDispatcher>> = None;
/// vm.construct_with_children(|walk| {
///     escaped = Some(walk);
///     Ok(())
/// })
/// .unwrap();
/// ```
///
/// A consumer type with two members:
///
/// ```
/// use vmx::{ComponentVm, ConstructionStatus, VmxResult};
///
/// struct Dashboard {
///     component: ComponentVm,
///     chart: ComponentVm,
///     table: ComponentVm,
/// }
///
/// impl Dashboard {
///     fn new() -> VmxResult<Self> {
///         let dashboard = Self {
///             component: ComponentVm::new("dashboard"),
///             chart: ComponentVm::new("chart"),
///             table: ComponentVm::new("table"),
///         };
///         dashboard.component.own_member(&dashboard.chart)?;
///         dashboard.component.own_member(&dashboard.table)?;
///         Ok(dashboard)
///     }
///
///     fn construct(&self) -> VmxResult<()> {
///         self.component.construct_with_children(|walk| {
///             walk.transition(&self.chart)?;
///             walk.transition(&self.table)
///         })
///     }
///
///     fn destruct(&self) -> VmxResult<()> {
///         self.component.destruct_with_children(|walk| {
///             walk.transition(&self.table)?;
///             walk.transition(&self.chart)
///         })
///     }
/// }
///
/// let dashboard = Dashboard::new().unwrap();
/// dashboard.construct().unwrap();
/// assert_eq!(dashboard.table.status(), ConstructionStatus::Constructed);
/// dashboard.destruct().unwrap();
/// assert_eq!(dashboard.chart.status(), ConstructionStatus::Destructed);
/// dashboard.component.dispose().unwrap();
/// assert_eq!(dashboard.chart.status(), ConstructionStatus::Disposed);
/// ```
pub struct ChildTransitions<'a, D: Dispatcher = NullDispatcher> {
    core: &'a ComponentCore<D>,
    operation: LifecycleOperation,
    /// The first step that failed while the walk closure ran.
    failure: RefCell<Option<VmxError>>,
    /// Keeps the handle on the thread that runs the walk.
    _walk_thread: PhantomData<*const ()>,
}

impl<'a, D: Dispatcher> ChildTransitions<'a, D> {
    fn new(core: &'a ComponentCore<D>, operation: LifecycleOperation) -> Self {
        Self {
            core,
            operation,
            failure: RefCell::new(None),
            _walk_thread: PhantomData,
        }
    }

    /// Constructs (in a construct walk) or destructs (in a destruct walk)
    /// `child` as the next step, after every earlier step settled.
    ///
    /// The step skips a child already at the target status and joins a child
    /// already in the transient status instead of starting it again, so its
    /// hook does not run twice. A background child keeps the parent transient
    /// until it settles.
    ///
    /// Returns the failure of a step that settled while this call ran.
    /// After a step failed, later calls start no child and return the same
    /// failure, and the walk fails even when the closure drops the error.
    pub fn transition<N: VmNode>(&self, child: &N) -> VmxResult<()> {
        self.step(|| self.core.transition_or_join_child(child, self.operation))
    }

    /// Runs `after` once every earlier step settled at the target, before the
    /// parent publishes its terminal status. An `Err` (or a panic) from
    /// `after` rolls the parent back like a failing child.
    ///
    /// When a background child is still in flight, `after` is queued on the
    /// parent and runs when that child settles. It must therefore not capture
    /// the parent `ComponentVm` or a value that holds it: the parent would then
    /// own itself, and a parent waiting on a child that never settles would
    /// never be freed (#750). Capture the members or a weak handle instead.
    pub fn then<F>(&self, after: F) -> VmxResult<()>
    where
        F: FnOnce() -> VmxResult<()> + Send + 'static,
    {
        self.step(|| self.core.child_step(Box::new(after)))
    }

    fn step(&self, run: impl FnOnce() -> VmxResult<()>) -> VmxResult<()> {
        if let Some(error) = self.failure.borrow().clone() {
            return Err(error);
        }
        let result = run();
        if let Err(error) = &result {
            self.failure
                .borrow_mut()
                .get_or_insert_with(|| error.clone());
        }
        result
    }

    /// The walk's result: the closure's own error first, then the first step
    /// failure the closure did not propagate.
    fn finish(self, result: VmxResult<()>) -> VmxResult<()> {
        result?;
        self.failure.into_inner().map_or(Ok(()), Err)
    }
}

/// Runs `operation` on `core` and, after its hook, the walk closure.
fn walk_children<D, F>(
    core: &ComponentCore<D>,
    operation: LifecycleOperation,
    walk: F,
) -> VmxResult<()>
where
    D: Dispatcher,
    F: FnOnce(&ChildTransitions<'_, D>) -> VmxResult<()>,
{
    core.transition_with(operation, || {
        let transitions = ChildTransitions::new(core, operation);
        let result = walk(&transitions);
        transitions.finish(result)
    })
}

/// A modeled leaf viewmodel whose name and hint are fixed at construction.
///
/// ```compile_fail
/// use vmx::ComponentVm;
///
/// let vm = ComponentVm::new("component");
/// vm.set_hint(Some("changed".to_string()));
/// ```
///
/// Core components expose baseline selection operations but do not opt in to
/// the independent [`crate::Selectable`] capability:
///
/// ```compile_fail
/// use vmx::{ComponentVm, Selectable};
///
/// fn requires_selectable<T: Selectable>(_: &T) {}
/// requires_selectable(&ComponentVm::new("component"));
/// ```
#[derive(Clone)]
pub struct ComponentVm<M = (), D: Dispatcher = NullDispatcher> {
    pub(crate) core: ComponentCore<D>,
    model: Arc<Mutex<M>>,
    /// Counts model replacements; only changed while the model lock is held.
    model_generation: Arc<AtomicU64>,
    model_hint: ModelHint<M>,
    view_model_type: ViewModelType,
    commands: ComponentCommands,
}

impl ComponentVm<(), NullDispatcher> {
    /// Creates an unmodeled component with null services.
    pub fn new(name: impl Into<String>) -> Self {
        Self::with_services(name, MessageHub::new(), NullDispatcher::new())
    }
}

impl<D: Dispatcher> ComponentVm<(), D> {
    /// Creates an unmodeled component with explicit services.
    pub fn with_services(name: impl Into<String>, hub: MessageHub, dispatcher: D) -> Self {
        Self::with_model(name, (), hub, dispatcher)
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ComponentVm<M, D> {
    /// Creates a modeled component with explicit services.
    pub fn with_model(name: impl Into<String>, model: M, hub: MessageHub, dispatcher: D) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        let command_core = core.clone();
        let commands = ComponentCommands::new(&core, move || {
            let _ = command_core.reconstruct();
        });
        Self {
            core,
            model: Arc::new(Mutex::new(model)),
            model_generation: Arc::new(AtomicU64::new(0)),
            model_hint: Arc::new(|_| None),
            view_model_type: ViewModelType::Component,
            commands,
        }
    }

    /// Returns this component with a model-derived presentation hint.
    pub fn with_model_hint<F>(self, hint: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        Self {
            model_hint: Arc::new(hint),
            ..self
        }
    }

    /// Returns the stable component identity.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Returns the immutable component name.
    pub fn name(&self) -> String {
        self.core.name()
    }

    /// Returns the immutable role discriminator for this component.
    pub fn view_model_type(&self) -> ViewModelType {
        self.view_model_type
    }

    /// Returns the immutable static presentation hint.
    pub fn hint(&self) -> Option<String> {
        self.core.hint()
    }

    /// Computes the current model-derived presentation hint.
    pub fn modeled_hint(&self) -> Option<String> {
        let model = lock(&self.model).clone();
        (self.model_hint)(&model)
    }

    /// Returns a snapshot of the current model.
    pub fn model(&self) -> M {
        clone_locked(&self.model)
    }

    /// Returns the local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the hot error stream for fire-and-forget background lifecycle hooks.
    pub fn background_errors(&self) -> crate::LifecycleErrorStream {
        self.core.background_errors()
    }

    /// Returns the component's injected message hub.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Registers cleanup work that runs when the component is disposed.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.core.own(cleanup);
    }

    /// Publishes a change for an application-defined property name.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Publishes a model change without replacing the retained model.
    pub fn republish_model(&self) {
        self.core.notify_property_changed("model");
    }

    /// Replaces the model and publishes effective model and modeled-hint changes.
    ///
    /// Equal assignments and assignments after disposal are inert.
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

    /// Installs `model` unless it equals the live model. `PartialEq` runs on
    /// a copy with no lock held, so an `eq` may read this component; the
    /// install re-checks the model generation under the lock and compares
    /// again when another writer got there first. The replaced model is
    /// dropped after the lock is released.
    pub(crate) fn replace_model(&self, model: M) -> bool {
        loop {
            let (generation, live) = {
                let current = lock(&self.model);
                (
                    self.model_generation.load(Ordering::SeqCst),
                    current.clone(),
                )
            };
            if live == model {
                return false;
            }
            drop(live);
            let replaced = {
                let mut current = lock(&self.model);
                if self.model_generation.load(Ordering::SeqCst) != generation {
                    continue;
                }
                self.model_generation.fetch_add(1, Ordering::SeqCst);
                std::mem::replace(&mut *current, model)
            };
            drop(replaced);
            return true;
        }
    }

    /// Installs `model` without comparing it and returns the value it
    /// replaced, so the caller can drop that value after releasing its own
    /// locks. No model code runs while the model lock is held.
    pub(crate) fn store_model(&self, model: M) -> M {
        let mut current = lock(&self.model);
        self.model_generation.fetch_add(1, Ordering::SeqCst);
        std::mem::replace(&mut *current, model)
    }

    /// Returns the model generation. A reader that saw a model installed by
    /// [`store_model`](Self::store_model) or `replace_model` then sees a
    /// generation past the one read before that install.
    pub(crate) fn model_generation(&self) -> u64 {
        self.model_generation.load(Ordering::SeqCst)
    }

    /// Replaces the hook invoked during construction.
    pub fn on_construct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Construct, Arc::new(Mutex::new(hook)));
    }

    /// Replaces the hook invoked during destruction.
    pub fn on_destruct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Destruct, Arc::new(Mutex::new(hook)));
    }

    /// Replaces the hook invoked during disposal.
    pub fn on_dispose<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.core
            .set_hook(LifecycleOperation::Dispose, Arc::new(Mutex::new(hook)));
    }

    /// Transitions the component to constructed state.
    pub fn construct(&self) -> VmxResult<()> {
        self.core.transition(LifecycleOperation::Construct)
    }

    /// Constructs the component and, after its `on_construct` hook, runs
    /// `walk` to construct its member view-models (spec/02 §6.1, ADR-0162).
    ///
    /// See [`ChildTransitions`] for the walk contract: steps run in order,
    /// a background child keeps the component `Constructing` until it
    /// settles, and a failing step rolls the component back to `Destructed`.
    /// A component that is already `Constructed` returns `Ok(())` without
    /// running `walk`, and a rejected transition runs nothing. The hook and
    /// `walk` run on the calling thread, as a container's own hook does.
    ///
    /// This is how a consumer type built around a `ComponentVm` implements
    /// its own `construct`; [`Self::construct`] runs only the hook.
    ///
    /// # Errors
    ///
    /// [`VmxError::InvalidArgument`], with no transition started, when the
    /// component was built with `background(true)`: the walk borrows the
    /// caller's members, so it cannot move to the background dispatcher
    /// (spec/11 §4). Build the component without background work; members
    /// built with `background(true)` still run their own hooks in the
    /// background, and the walk waits for them. Otherwise the transition's
    /// own errors and the first failing step.
    pub fn construct_with_children<F>(&self, walk: F) -> VmxResult<()>
    where
        F: FnOnce(&ChildTransitions<'_, D>) -> VmxResult<()>,
    {
        self.reject_background_walk("construct_with_children")?;
        walk_children(&self.core, LifecycleOperation::Construct, walk)
    }

    /// Destructs the component and, after its `on_destruct` hook, runs `walk`
    /// to destruct its member view-models (spec/02 §6.1, ADR-0162).
    ///
    /// See [`ChildTransitions`]. A failing step rolls the component back to
    /// `Constructed`. A component that is already `Destructed` returns
    /// `Ok(())` without running `walk`. Pass the members in reverse for a
    /// reverse-order destruct.
    ///
    /// # Errors
    ///
    /// [`VmxError::InvalidArgument`], with no transition started, when the
    /// component was built with `background(true)`, as for
    /// [`Self::construct_with_children`]. Otherwise the transition's own
    /// errors and the first failing step.
    pub fn destruct_with_children<F>(&self, walk: F) -> VmxResult<()>
    where
        F: FnOnce(&ChildTransitions<'_, D>) -> VmxResult<()>,
    {
        self.reject_background_walk("destruct_with_children")?;
        walk_children(&self.core, LifecycleOperation::Destruct, walk)
    }

    /// The standalone walks cannot honor `background(true)` (spec/11 §4).
    fn reject_background_walk(&self, method: &str) -> VmxResult<()> {
        if self.core.is_background() {
            return Err(VmxError::InvalidArgument(format!(
                "{method} does not support a component built with background(true)"
            )));
        }
        Ok(())
    }

    /// Destructs the component through `destruct`, then constructs it through
    /// `construct` (spec/02 §6.1, ADR-0162). Admission matches
    /// [`Self::reconstruct`].
    ///
    /// The construct walk starts once the destruct reaches `Destructed`: now
    /// when the destruct settled synchronously, otherwise when its last
    /// background child settles. A failure of a deferred construct walk
    /// reaches [`Self::background_errors`]. A destruct that rolls back skips
    /// the construct walk. `construct` may be stored on the component until
    /// then, so it must not capture the component or a value that holds it
    /// (#750); capture the members.
    ///
    /// Like [`Self::reconstruct`], this runs the component's own hooks on the
    /// calling thread also for a component built with `background(true)`
    /// (spec/11 §4); background members still settle in the background.
    ///
    /// [`Self::reconstruct`] and [`Self::reconstruct_command`] run only the
    /// component's hooks and never a walk; a consumer type routes its own
    /// reconstruct through this method.
    pub fn reconstruct_with_children<FD, FC>(&self, destruct: FD, construct: FC) -> VmxResult<()>
    where
        FD: FnOnce(&ChildTransitions<'_, D>) -> VmxResult<()>,
        FC: FnOnce(&ChildTransitions<'_, D>) -> VmxResult<()> + Send + 'static,
    {
        crate::runtime::reconstruct_admission(self.status())?;
        walk_children(&self.core, LifecycleOperation::Destruct, destruct)?;
        self.core.construct_after_destruct(move |core| {
            walk_children(core, LifecycleOperation::Construct, construct)
        })
    }

    /// Registers `member` for depth-first disposal (spec/02 §7.1, ADR-0162).
    ///
    /// [`Self::dispose`] disposes the registered members in registration
    /// order, each before the component publishes `Disposed`. A member is not
    /// a container child: registration sets no parent link, adds no selection
    /// state, and does not construct it; transition members through
    /// [`Self::construct_with_children`] and
    /// [`Self::destruct_with_children`]. Clones of the component share the
    /// registrations, and the component keeps a clone of `member` until it is
    /// disposed, so a member must not hold the component (#750).
    ///
    /// A member registered once the component's disposal began is disposed
    /// now, and its disposal result is returned. Registering a member twice
    /// keeps one registration.
    ///
    /// # Errors
    ///
    /// [`VmxError::OwnershipCycle`] when `member` is this component (the same
    /// identity); the error of disposing a late member.
    pub fn own_member<N: VmNode>(&self, member: &N) -> VmxResult<()> {
        let member = member.clone();
        self.core
            .own_member(member.id(), Box::new(move || member.dispose()))
    }

    /// Constructs the component and runs `action` while it is Constructing,
    /// so a container can cascade into its children inside its own legal
    /// transition. A rejected transition runs nothing.
    pub(crate) fn construct_with<F>(&self, action: F) -> VmxResult<()>
    where
        F: FnOnce() -> VmxResult<()>,
    {
        self.core
            .transition_with(LifecycleOperation::Construct, action)
    }

    /// Transitions the component to destructed state.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition(LifecycleOperation::Destruct)
    }

    /// Destructs and then constructs the component.
    ///
    /// This runs only the component's own hooks. It does not run a
    /// [`ChildTransitions`] walk, so a consumer type that walks its members
    /// reconstructs through [`Self::reconstruct_with_children`] instead.
    pub fn reconstruct(&self) -> VmxResult<()> {
        crate::runtime::reconstruct_admission(self.status())?;
        self.core.reconstruct()
    }

    /// Stops publishing on the injected hub. A wrapper whose hub contract
    /// excludes lifecycle messages calls this before disposing.
    pub(crate) fn detach_hub(&self) {
        self.core.detach_hub();
    }

    /// Transitions the component to its terminal disposed state.
    ///
    /// Members registered with [`Self::own_member`] are disposed first, in
    /// registration order, before the component publishes `Disposed`
    /// (spec/02 §7.1). Every member is attempted; the first failure is
    /// returned after the component's own teardown. While the members are
    /// being disposed, any other `dispose` of the component, re-entrant or
    /// from another thread, returns `Ok(())` at once without waiting; the
    /// first call finishes the work. A component with no members disposes
    /// as before.
    pub fn dispose(&self) -> VmxResult<()> {
        self.core.abandon_child_settle();
        let Some(members) = self.core.begin_member_disposal() else {
            return Ok(());
        };
        let mut first_failure = None;
        for member in members {
            retain_first_failure(&mut first_failure, member);
        }
        self.core.finish_member_disposal();
        retain_first_failure(&mut first_failure, || {
            let commands = self.commands.clone();
            self.core.dispose_then(move || commands.dispose())
        });
        finish_with_first_failure(first_failure)
    }

    /// Returns the current lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }

    /// Reports whether the component is constructed.
    pub fn is_constructed(&self) -> bool {
        self.status() == ConstructionStatus::Constructed
    }

    /// Reports whether this constructed component can select itself through its parent.
    pub fn can_select(&self) -> bool {
        self.core.can_select()
    }

    /// Selects this component through its owning selectable parent.
    pub fn select(&self) {
        self.core.select_via_parent();
    }

    /// Reports whether this component is the current child of its parent.
    pub fn can_deselect(&self) -> bool {
        self.core.can_deselect()
    }

    /// Deselects this component through its owning selectable parent.
    pub fn deselect(&self) {
        self.core.deselect_via_parent();
    }

    /// Reports whether the component is current in its owning container.
    pub fn is_current(&self) -> bool {
        self.core.is_selected()
    }

    /// Compatibility alias for [`Self::is_current`].
    pub fn is_selected(&self) -> bool {
        self.is_current()
    }

    /// Marks the component as expanded.
    pub fn expand(&self) {
        self.core.set_expanded(true);
    }

    /// Marks the component as collapsed.
    pub fn collapse(&self) {
        self.core.set_expanded(false);
    }

    /// Toggles between expanded and collapsed states.
    pub fn toggle_expansion(&self) {
        self.core.set_expanded(!self.core.is_expanded());
    }

    /// Reports whether the component is expanded.
    pub fn is_expanded(&self) -> bool {
        self.core.is_expanded()
    }

    /// Returns the identity of the current parent, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.core.parent_id()
    }

    /// Returns the stable command that selects this component through its parent.
    pub fn select_command(&self) -> RelayCommand {
        self.commands.select()
    }

    /// Returns the stable command that deselects this component through its parent.
    pub fn deselect_command(&self) -> RelayCommand {
        self.commands.deselect()
    }

    /// Returns the inert baseline next-sibling command.
    pub fn select_next_command(&self) -> RelayCommand {
        self.commands.select_next()
    }

    /// Returns the inert baseline previous-sibling command.
    pub fn select_previous_command(&self) -> RelayCommand {
        self.commands.select_previous()
    }

    /// Returns the stable command that destructs and reconstructs this component.
    ///
    /// The command calls [`Self::reconstruct`], so it runs only the hooks and
    /// no [`ChildTransitions`] walk. A consumer type that walks its members
    /// exposes its own command that calls
    /// [`Self::reconstruct_with_children`].
    pub fn reconstruct_command(&self) -> RelayCommand {
        self.commands.reconstruct()
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

    fn when_lifecycle_settled(&self, callback: crate::LifecycleSettleCallback) -> bool {
        self.core.when_settled(callback)
    }

    fn is_current(&self) -> bool {
        self.core.is_selected()
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> TreeNode for ComponentVm<M, D> {}

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
    /// Creates a read-only modeled component with explicit services.
    pub fn new(name: impl Into<String>, model: M, hub: MessageHub, dispatcher: D) -> Self {
        Self {
            inner: ComponentVm::with_model(name, model, hub, dispatcher),
        }
    }

    /// Returns this component with a model-derived presentation hint.
    pub fn with_model_hint<F>(mut self, hint: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        self.inner = self.inner.with_model_hint(hint);
        self
    }

    /// Returns the stable component identity.
    pub fn id(&self) -> usize {
        self.inner.id()
    }

    /// Returns the immutable component name.
    pub fn name(&self) -> String {
        self.inner.name()
    }

    /// Returns the read-only component role discriminator.
    pub fn view_model_type(&self) -> ViewModelType {
        ViewModelType::ReadOnlyComponent
    }

    /// Returns the immutable static presentation hint.
    pub fn hint(&self) -> Option<String> {
        self.inner.hint()
    }

    /// Computes the current model-derived presentation hint.
    pub fn modeled_hint(&self) -> Option<String> {
        self.inner.modeled_hint()
    }

    /// Returns a snapshot of the immutable model.
    pub fn model(&self) -> M {
        self.inner.model()
    }

    /// Returns the local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.property_changed()
    }

    /// Returns the hot error stream for fire-and-forget background lifecycle hooks.
    pub fn background_errors(&self) -> crate::LifecycleErrorStream {
        self.inner.background_errors()
    }

    /// Returns the component's injected message hub.
    pub fn hub(&self) -> MessageHub {
        self.inner.hub()
    }

    /// Registers cleanup work that runs when the component is disposed.
    pub fn own<F>(&self, cleanup: F)
    where
        F: FnOnce() + Send + 'static,
    {
        self.inner.own(cleanup);
    }

    /// Publishes a change for an application-defined property name.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.notify_property_changed(property_name);
    }

    /// Publishes a model change without exposing model replacement.
    pub fn republish_model(&self) {
        self.inner.republish_model();
    }

    /// Replaces the hook invoked during construction.
    pub fn on_construct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_construct(hook);
    }

    /// Replaces the hook invoked during destruction.
    pub fn on_destruct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_destruct(hook);
    }

    /// Replaces the hook invoked during disposal.
    pub fn on_dispose<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.inner.on_dispose(hook);
    }

    /// Transitions the component to constructed state.
    pub fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }

    /// Transitions the component to destructed state.
    pub fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    /// Destructs and then constructs the component.
    pub fn reconstruct(&self) -> VmxResult<()> {
        self.inner.reconstruct()
    }

    /// Transitions the component to its terminal disposed state.
    pub fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
    }

    /// Returns the current lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    /// Reports whether the component is constructed.
    pub fn is_constructed(&self) -> bool {
        self.inner.is_constructed()
    }

    /// Reports whether this component can select itself through its parent.
    pub fn can_select(&self) -> bool {
        self.inner.can_select()
    }

    /// Selects this component through its parent.
    pub fn select(&self) {
        self.inner.select();
    }

    /// Reports whether this component can deselect itself through its parent.
    pub fn can_deselect(&self) -> bool {
        self.inner.can_deselect()
    }

    /// Deselects this component through its parent.
    pub fn deselect(&self) {
        self.inner.deselect();
    }

    /// Reports whether the component is current in its parent.
    pub fn is_current(&self) -> bool {
        self.inner.is_current()
    }

    /// Compatibility alias for [`Self::is_current`].
    pub fn is_selected(&self) -> bool {
        self.is_current()
    }

    /// Marks the component as expanded.
    pub fn expand(&self) {
        self.inner.expand();
    }

    /// Marks the component as collapsed.
    pub fn collapse(&self) {
        self.inner.collapse();
    }

    /// Toggles between expanded and collapsed states.
    pub fn toggle_expansion(&self) {
        self.inner.toggle_expansion();
    }

    /// Reports whether the component is expanded.
    pub fn is_expanded(&self) -> bool {
        self.inner.is_expanded()
    }

    /// Returns the identity of the current parent, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }

    /// Returns the stable select command.
    pub fn select_command(&self) -> RelayCommand {
        self.inner.select_command()
    }

    /// Returns the stable deselect command.
    pub fn deselect_command(&self) -> RelayCommand {
        self.inner.deselect_command()
    }

    /// Returns the inert baseline next-sibling command.
    pub fn select_next_command(&self) -> RelayCommand {
        self.inner.select_next_command()
    }

    /// Returns the inert baseline previous-sibling command.
    pub fn select_previous_command(&self) -> RelayCommand {
        self.inner.select_previous_command()
    }

    /// Returns the stable reconstruct command.
    pub fn reconstruct_command(&self) -> RelayCommand {
        self.inner.reconstruct_command()
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

    fn when_lifecycle_settled(&self, callback: crate::LifecycleSettleCallback) -> bool {
        self.inner.core.when_settled(callback)
    }

    fn is_current(&self) -> bool {
        self.inner.is_selected()
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> TreeNode for ReadonlyComponentVm<M, D> {}

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

type BuilderLifecycleHook = Arc<Mutex<dyn FnMut() -> VmxResult<()> + Send + 'static>>;

#[derive(Clone)]
/// A fluent builder for modeled [`ComponentVm`] instances.
pub struct ComponentVmBuilder<M: Clone + PartialEq + Send + 'static, D: Dispatcher = NullDispatcher>
{
    name: Option<String>,
    hint: Option<String>,
    model: Option<M>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    background: bool,
    on_construct: Option<BuilderLifecycleHook>,
    on_destruct: Option<BuilderLifecycleHook>,
    model_hint: Option<ModelHint<M>>,
    view_model_type: ViewModelType,
}

impl<M: Clone + PartialEq + Send + 'static> Default for ComponentVmBuilder<M, NullDispatcher> {
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            model: None,
            hub: None,
            dispatcher: None,
            background: false,
            on_construct: None,
            on_destruct: None,
            model_hint: None,
            view_model_type: ViewModelType::Component,
        }
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ComponentVmBuilder<M, D> {
    /// Sets the required component name.
    pub fn name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    /// Sets the optional static presentation hint.
    pub fn hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }

    /// Sets the required initial model.
    pub fn model(mut self, model: M) -> Self {
        self.model = Some(model);
        self
    }

    /// Sets the immutable role discriminator returned by the built component.
    pub fn view_model_type(mut self, view_model_type: ViewModelType) -> Self {
        self.view_model_type = view_model_type;
        self
    }

    /// Supplies the required message hub and dispatcher.
    pub fn services<D2: Dispatcher>(
        self,
        hub: MessageHub,
        dispatcher: D2,
    ) -> ComponentVmBuilder<M, D2> {
        ComponentVmBuilder {
            name: self.name,
            hint: self.hint,
            model: self.model,
            hub: Some(hub),
            dispatcher: Some(dispatcher),
            background: self.background,
            on_construct: self.on_construct,
            on_destruct: self.on_destruct,
            model_hint: self.model_hint,
            view_model_type: self.view_model_type,
        }
    }

    /// Enables background construct/destruct work (disabled by default).
    pub fn background(mut self, background: bool) -> Self {
        self.background = background;
        self
    }

    /// Sets the construction lifecycle callback.
    pub fn on_construct<F>(mut self, hook: F) -> Self
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.on_construct = Some(Arc::new(Mutex::new(hook)));
        self
    }

    /// Sets the destruction lifecycle callback.
    pub fn on_destruct<F>(mut self, hook: F) -> Self
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        self.on_destruct = Some(Arc::new(Mutex::new(hook)));
        self
    }

    /// Supplies an optional model-derived presentation hint.
    pub fn model_hint<F>(mut self, hint: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        self.model_hint = Some(Arc::new(hint));
        self
    }

    /// Validates required fields and creates a component.
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
        let mut vm = ComponentVm::with_model(name, model, hub, dispatcher);
        vm.core.set_background(self.background);
        if let Some(hook) = self.on_construct {
            vm.core.set_hook(LifecycleOperation::Construct, hook);
        }
        if let Some(hook) = self.on_destruct {
            vm.core.set_hook(LifecycleOperation::Destruct, hook);
        }
        vm.view_model_type = self.view_model_type;
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
    /// Returns a modeled-component builder configured for null dispatch.
    pub fn builder() -> ComponentVmBuilder<M, NullDispatcher> {
        ComponentVmBuilder::default()
    }

    /// Creates a modeled component from an options value.
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
        builder
            .view_model_type(options.view_model_type)
            .background(options.background)
            .services(options.hub, options.dispatcher)
            .build()
    }
}

#[derive(Clone)]
/// A fluent builder for modeled [`ReadonlyComponentVm`] instances.
pub struct ReadonlyComponentVmBuilder<
    M: Clone + PartialEq + Send + 'static,
    D: Dispatcher = NullDispatcher,
> {
    inner: ComponentVmBuilder<M, D>,
}

impl<M: Clone + PartialEq + Send + 'static> Default
    for ReadonlyComponentVmBuilder<M, NullDispatcher>
{
    fn default() -> Self {
        Self {
            inner: ComponentVmBuilder::default().view_model_type(ViewModelType::ReadOnlyComponent),
        }
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ReadonlyComponentVmBuilder<M, D> {
    /// Sets the required component name.
    pub fn name(self, name: impl Into<String>) -> Self {
        Self {
            inner: self.inner.name(name),
        }
    }

    /// Sets the optional static presentation hint.
    pub fn hint(self, hint: impl Into<String>) -> Self {
        Self {
            inner: self.inner.hint(hint),
        }
    }

    /// Sets the required immutable model.
    pub fn model(self, model: M) -> Self {
        Self {
            inner: self.inner.model(model),
        }
    }

    /// Enables background construct/destruct work (disabled by default).
    pub fn background(self, background: bool) -> Self {
        Self {
            inner: self.inner.background(background),
        }
    }

    /// Sets the construction lifecycle callback.
    pub fn on_construct<F>(self, hook: F) -> Self
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        Self {
            inner: self.inner.on_construct(hook),
        }
    }

    /// Sets the destruction lifecycle callback.
    pub fn on_destruct<F>(self, hook: F) -> Self
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        Self {
            inner: self.inner.on_destruct(hook),
        }
    }

    /// Supplies an optional model-derived presentation hint.
    pub fn model_hint<F>(self, hint: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        Self {
            inner: self.inner.model_hint(hint),
        }
    }

    /// Supplies the required message hub and dispatcher.
    pub fn services<D2: Dispatcher>(
        self,
        hub: MessageHub,
        dispatcher: D2,
    ) -> ReadonlyComponentVmBuilder<M, D2> {
        ReadonlyComponentVmBuilder {
            inner: self.inner.services(hub, dispatcher),
        }
    }

    /// Validates required fields and creates a read-only component.
    pub fn build(self) -> VmxResult<ReadonlyComponentVm<M, D>> {
        Ok(ReadonlyComponentVm {
            inner: self.inner.build()?,
        })
    }
}

impl<M: Clone + PartialEq + Send + 'static> ReadonlyComponentVm<M, NullDispatcher> {
    /// Returns a read-only modeled-component builder configured for null dispatch.
    pub fn builder() -> ReadonlyComponentVmBuilder<M, NullDispatcher> {
        ReadonlyComponentVmBuilder::default()
    }
}

/// Options for creating a null-dispatcher modeled [`ComponentVm`].
pub struct ComponentVmOptions<M: Clone + PartialEq + Send + 'static> {
    /// Optional component name; validation fails when omitted.
    pub name: Option<String>,
    /// Optional static presentation hint.
    pub hint: Option<String>,
    /// Optional initial model; validation fails when omitted.
    pub model: Option<M>,
    /// Immutable role discriminator returned by the created component.
    pub view_model_type: ViewModelType,
    /// Whether construct/destruct hooks run through the background dispatcher.
    pub background: bool,
    /// Message hub injected into the component.
    pub hub: MessageHub,
    /// Dispatcher used for foreground scheduling.
    pub dispatcher: NullDispatcher,
}
