//! Modeled leaf view models, read-only wrappers, and builders.
//!
//! Spec: `spec/05-component-vm.md`.

use super::{
    fmt, lock, Arc, ComponentCore, ConstructionStatus, Dispatcher, LifecycleOperation, Message,
    MessageHub, ModelHint, Mutex, NullDispatcher, ParentHandle, PropertyChangedStream,
    RelayCommand, Subscription, TreeNode, VmNode, VmxError, VmxResult,
};

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
    model_hint: ModelHint<M>,
    select_command: RelayCommand,
    deselect_command: RelayCommand,
    select_next_command: RelayCommand,
    select_previous_command: RelayCommand,
    reconstruct_command: RelayCommand,
    _command_status_subscription: Arc<Subscription>,
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
        let select_command = {
            let action_core = core.clone();
            let predicate_core = core.clone();
            RelayCommand::new(move || action_core.select_via_parent())
                .with_can_execute(move || predicate_core.can_select())
        };
        let deselect_command = {
            let action_core = core.clone();
            let predicate_core = core.clone();
            RelayCommand::new(move || action_core.deselect_via_parent())
                .with_can_execute(move || predicate_core.can_deselect())
        };
        let reconstruct_command = {
            let action_core = core.clone();
            let predicate_core = core.clone();
            RelayCommand::new(move || {
                if action_core.transition(LifecycleOperation::Destruct).is_ok() {
                    let _ = action_core.transition(LifecycleOperation::Construct);
                }
            })
            .with_can_execute(move || predicate_core.status() == ConstructionStatus::Constructed)
        };
        let select_next_command = RelayCommand::noop().with_can_execute(|| false);
        let select_previous_command = RelayCommand::noop().with_can_execute(|| false);
        let command_status_subscription = {
            let sender_id = core.id();
            let select = select_command.clone();
            let deselect = deselect_command.clone();
            let next = select_next_command.clone();
            let previous = select_previous_command.clone();
            let reconstruct = reconstruct_command.clone();
            Arc::new(core.hub().subscribe(move |message| {
                if matches!(
                    message,
                    Message::ConstructionStatusChanged(change) if change.sender_id == sender_id
                ) {
                    select.raise_can_execute_changed();
                    deselect.raise_can_execute_changed();
                    next.raise_can_execute_changed();
                    previous.raise_can_execute_changed();
                    reconstruct.raise_can_execute_changed();
                }
            }))
        };
        Self {
            core,
            model: Arc::new(Mutex::new(model)),
            model_hint: Arc::new(|_| None),
            select_command,
            deselect_command,
            select_next_command,
            select_previous_command,
            reconstruct_command,
            _command_status_subscription: command_status_subscription,
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
        lock(&self.model).clone()
    }

    /// Returns the local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
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

    pub(crate) fn replace_model(&self, model: M) -> bool {
        let mut current = lock(&self.model);
        if *current == model {
            false
        } else {
            *current = model;
            true
        }
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

    /// Transitions the component to destructed state.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition(LifecycleOperation::Destruct)
    }

    /// Destructs and then constructs the component.
    pub fn reconstruct(&self) -> VmxResult<()> {
        self.destruct()?;
        self.construct()
    }

    /// Transitions the component to its terminal disposed state.
    pub fn dispose(&self) -> VmxResult<()> {
        self.core.transition(LifecycleOperation::Dispose)
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
        self.select_command.clone()
    }

    /// Returns the stable command that deselects this component through its parent.
    pub fn deselect_command(&self) -> RelayCommand {
        self.deselect_command.clone()
    }

    /// Returns the inert baseline next-sibling command.
    pub fn select_next_command(&self) -> RelayCommand {
        self.select_next_command.clone()
    }

    /// Returns the inert baseline previous-sibling command.
    pub fn select_previous_command(&self) -> RelayCommand {
        self.select_previous_command.clone()
    }

    /// Returns the stable command that destructs and reconstructs this component.
    pub fn reconstruct_command(&self) -> RelayCommand {
        self.reconstruct_command.clone()
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
/// A fluent builder for modeled [`ComponentVm`] instances.
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

    /// Supplies the required message hub and dispatcher.
    pub fn services(mut self, hub: MessageHub, dispatcher: D) -> Self {
        self.hub = Some(hub);
        self.dispatcher = Some(dispatcher);
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
        builder.services(options.hub, options.dispatcher).build()
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
    /// Message hub injected into the component.
    pub hub: MessageHub,
    /// Dispatcher used for foreground scheduling.
    pub dispatcher: NullDispatcher,
}
