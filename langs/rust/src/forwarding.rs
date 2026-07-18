//! Transparent component and composite forwarding wrappers.
//!
//! Spec: `spec/09-forwarding.md`; ADR-0124.

use super::{
    Arc, ComponentVm, CompositeVm, ConstructionStatus, Dispatcher, MessageHub, NullDispatcher,
    ParentHandle, PropertyChangedStream, RelayCommand, VmNode, VmxResult,
};

#[derive(Clone)]
enum ForwardingComponentInner<M: Clone + PartialEq + Send + 'static, D: Dispatcher = NullDispatcher>
{
    Component(Box<ComponentVm<M, D>>),
    Forwarding(Box<ForwardingComponentVm<M, D>>),
}

#[derive(Clone)]
/// A component wrapper that forwards the complete baseline surface to an inner VM.
///
/// Rust uses explicit closure hooks instead of inheritance for selective
/// overrides. Nested wrappers retain every decorator layer while sharing the
/// wrapped component's canonical ownership identity.
///
/// ```
/// use vmx::{ComponentVm, ForwardingComponentVm, MessageHub, NullDispatcher};
///
/// let inner = ComponentVm::with_model(
///     "inner",
///     "model",
///     MessageHub::new(),
///     NullDispatcher::new(),
/// );
/// let first = ForwardingComponentVm::new(inner)
///     .with_hint_override(|| Some("OVERRIDE".to_string()));
/// let forwarding = ForwardingComponentVm::wrap(first);
///
/// assert_eq!(forwarding.hint().as_deref(), Some("OVERRIDE"));
/// ```
pub struct ForwardingComponentVm<
    M: Clone + PartialEq + Send + 'static,
    D: Dispatcher = NullDispatcher,
> {
    inner: ForwardingComponentInner<M, D>,
    hint_override: Option<Arc<dyn Fn() -> Option<String> + Send + Sync>>,
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ForwardingComponentVm<M, D> {
    /// Wraps a component without taking additional lifecycle ownership.
    pub fn new(inner: ComponentVm<M, D>) -> Self {
        Self {
            inner: ForwardingComponentInner::Component(Box::new(inner)),
            hint_override: None,
        }
    }

    /// Adds a real decorator layer around an existing forwarding component.
    pub fn wrap(inner: Self) -> Self {
        Self {
            inner: ForwardingComponentInner::Forwarding(Box::new(inner)),
            hint_override: None,
        }
    }

    /// Configures the wrapped component's model-derived hint while retaining
    /// every forwarding layer.
    pub fn with_model_hint<F>(self, hint: F) -> Self
    where
        F: Fn(&M) -> Option<String> + Send + Sync + 'static,
    {
        let Self {
            inner,
            hint_override,
        } = self;
        let inner = match inner {
            ForwardingComponentInner::Component(inner) => {
                ForwardingComponentInner::Component(Box::new((*inner).with_model_hint(hint)))
            }
            ForwardingComponentInner::Forwarding(inner) => {
                ForwardingComponentInner::Forwarding(Box::new((*inner).with_model_hint(hint)))
            }
        };
        Self {
            inner,
            hint_override,
        }
    }

    /// Overrides only the presentation hint for this decorator layer.
    pub fn with_hint_override<F>(mut self, override_hint: F) -> Self
    where
        F: Fn() -> Option<String> + Send + Sync + 'static,
    {
        self.hint_override = Some(Arc::new(override_hint));
        self
    }

    /// Borrows the wrapped component.
    pub fn inner(&self) -> &ComponentVm<M, D> {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner,
            ForwardingComponentInner::Forwarding(inner) => inner.inner(),
        }
    }

    /// Returns the wrapped component's identity.
    pub fn id(&self) -> usize {
        self.inner().id()
    }

    /// Returns the wrapped component's name.
    pub fn name(&self) -> String {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.name(),
            ForwardingComponentInner::Forwarding(inner) => inner.name(),
        }
    }

    /// Returns the wrapped component's static hint.
    pub fn hint(&self) -> Option<String> {
        self.hint_override.as_ref().map_or_else(
            || match &self.inner {
                ForwardingComponentInner::Component(inner) => inner.hint(),
                ForwardingComponentInner::Forwarding(inner) => inner.hint(),
            },
            |override_hint| override_hint(),
        )
    }

    /// Returns the wrapped component's model-derived hint.
    pub fn modeled_hint(&self) -> Option<String> {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.modeled_hint(),
            ForwardingComponentInner::Forwarding(inner) => inner.modeled_hint(),
        }
    }

    /// Returns the wrapped component's model.
    pub fn model(&self) -> M {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.model(),
            ForwardingComponentInner::Forwarding(inner) => inner.model(),
        }
    }

    /// Replaces the wrapped component's model.
    pub fn set_model(&self, model: M) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.set_model(model),
            ForwardingComponentInner::Forwarding(inner) => inner.set_model(model),
        }
    }

    /// Republishes the wrapped component's retained model notification.
    pub fn republish_model(&self) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.republish_model(),
            ForwardingComponentInner::Forwarding(inner) => inner.republish_model(),
        }
    }

    /// Replaces the wrapped component's construction hook.
    pub fn on_construct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.on_construct(hook),
            ForwardingComponentInner::Forwarding(inner) => inner.on_construct(hook),
        }
    }

    /// Replaces the wrapped component's destruction hook.
    pub fn on_destruct<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.on_destruct(hook),
            ForwardingComponentInner::Forwarding(inner) => inner.on_destruct(hook),
        }
    }

    /// Replaces the wrapped component's disposal hook.
    pub fn on_dispose<F>(&self, hook: F)
    where
        F: FnMut() -> VmxResult<()> + Send + 'static,
    {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.on_dispose(hook),
            ForwardingComponentInner::Forwarding(inner) => inner.on_dispose(hook),
        }
    }

    /// Constructs the wrapped component.
    pub fn construct(&self) -> VmxResult<()> {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.construct(),
            ForwardingComponentInner::Forwarding(inner) => inner.construct(),
        }
    }

    /// Destructs the wrapped component.
    pub fn destruct(&self) -> VmxResult<()> {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.destruct(),
            ForwardingComponentInner::Forwarding(inner) => inner.destruct(),
        }
    }

    /// Disposes the wrapped component.
    pub fn dispose(&self) -> VmxResult<()> {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.dispose(),
            ForwardingComponentInner::Forwarding(inner) => inner.dispose(),
        }
    }

    /// Returns the wrapped component's lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.status(),
            ForwardingComponentInner::Forwarding(inner) => inner.status(),
        }
    }

    /// Reconstructs the wrapped component.
    pub fn reconstruct(&self) -> VmxResult<()> {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.reconstruct(),
            ForwardingComponentInner::Forwarding(inner) => inner.reconstruct(),
        }
    }

    /// Reports whether the wrapped component is constructed.
    pub fn is_constructed(&self) -> bool {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.is_constructed(),
            ForwardingComponentInner::Forwarding(inner) => inner.is_constructed(),
        }
    }

    /// Returns the wrapped component's parent identity, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.inner().parent_id()
    }

    /// Returns the wrapped component's selection command.
    pub fn select_command(&self) -> RelayCommand {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.select_command(),
            ForwardingComponentInner::Forwarding(inner) => inner.select_command(),
        }
    }

    /// Returns the wrapped component's deselection command.
    pub fn deselect_command(&self) -> RelayCommand {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.deselect_command(),
            ForwardingComponentInner::Forwarding(inner) => inner.deselect_command(),
        }
    }

    /// Returns the wrapped component's next-sibling selection command.
    pub fn select_next_command(&self) -> RelayCommand {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.select_next_command(),
            ForwardingComponentInner::Forwarding(inner) => inner.select_next_command(),
        }
    }

    /// Returns the wrapped component's previous-sibling selection command.
    pub fn select_previous_command(&self) -> RelayCommand {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.select_previous_command(),
            ForwardingComponentInner::Forwarding(inner) => inner.select_previous_command(),
        }
    }

    /// Returns the wrapped component's reconstruction command.
    pub fn reconstruct_command(&self) -> RelayCommand {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.reconstruct_command(),
            ForwardingComponentInner::Forwarding(inner) => inner.reconstruct_command(),
        }
    }

    /// Reports whether the wrapped component can select itself.
    pub fn can_select(&self) -> bool {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.can_select(),
            ForwardingComponentInner::Forwarding(inner) => inner.can_select(),
        }
    }

    /// Selects the wrapped component.
    pub fn select(&self) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.select(),
            ForwardingComponentInner::Forwarding(inner) => inner.select(),
        }
    }

    /// Reports whether the wrapped component can deselect itself.
    pub fn can_deselect(&self) -> bool {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.can_deselect(),
            ForwardingComponentInner::Forwarding(inner) => inner.can_deselect(),
        }
    }

    /// Deselects the wrapped component.
    pub fn deselect(&self) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.deselect(),
            ForwardingComponentInner::Forwarding(inner) => inner.deselect(),
        }
    }

    /// Reports whether the wrapped component is selected.
    pub fn is_selected(&self) -> bool {
        self.is_current()
    }

    /// Reports whether the wrapped component is current in its parent.
    pub fn is_current(&self) -> bool {
        self.inner().is_current()
    }

    /// Expands the wrapped component.
    pub fn expand(&self) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.expand(),
            ForwardingComponentInner::Forwarding(inner) => inner.expand(),
        }
    }

    /// Collapses the wrapped component.
    pub fn collapse(&self) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.collapse(),
            ForwardingComponentInner::Forwarding(inner) => inner.collapse(),
        }
    }

    /// Toggles the wrapped component's expansion state.
    pub fn toggle_expansion(&self) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.toggle_expansion(),
            ForwardingComponentInner::Forwarding(inner) => inner.toggle_expansion(),
        }
    }

    /// Reports whether the wrapped component is expanded.
    pub fn is_expanded(&self) -> bool {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.is_expanded(),
            ForwardingComponentInner::Forwarding(inner) => inner.is_expanded(),
        }
    }

    /// Returns the wrapped component's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.property_changed(),
            ForwardingComponentInner::Forwarding(inner) => inner.property_changed(),
        }
    }

    /// Returns the wrapped component's message hub.
    pub fn hub(&self) -> MessageHub {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.hub(),
            ForwardingComponentInner::Forwarding(inner) => inner.hub(),
        }
    }

    /// Registers a resource cleanup with the wrapped component.
    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => inner.own(cleanup),
            ForwardingComponentInner::Forwarding(inner) => inner.own(cleanup),
        }
    }

    /// Publishes a property change through the wrapped component.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        match &self.inner {
            ForwardingComponentInner::Component(inner) => {
                inner.notify_property_changed(property_name)
            }
            ForwardingComponentInner::Forwarding(inner) => {
                inner.notify_property_changed(property_name)
            }
        }
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> VmNode for ForwardingComponentVm<M, D> {
    fn id(&self) -> usize {
        self.id()
    }

    fn construct(&self) -> VmxResult<()> {
        self.construct()
    }

    fn destruct(&self) -> VmxResult<()> {
        self.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        self.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner().set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner().set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.inner().parent_handle()
    }

    fn set_current_flag(&self, is_current: bool) {
        self.inner().set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.is_current()
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> PartialEq
    for ForwardingComponentVm<M, D>
{
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> Eq for ForwardingComponentVm<M, D> {}

#[derive(Clone)]
/// A composite wrapper that forwards collection, selection, and lifecycle behavior.
pub struct ForwardingCompositeVm<T: VmNode, D: Dispatcher = NullDispatcher> {
    inner: CompositeVm<T, D>,
}

impl<T: VmNode, D: Dispatcher> ForwardingCompositeVm<T, D> {
    /// Wraps `inner` without adding a second child collection.
    pub fn new(inner: CompositeVm<T, D>) -> Self {
        Self { inner }
    }

    /// Borrows the wrapped composite.
    pub fn inner(&self) -> &CompositeVm<T, D> {
        &self.inner
    }

    /// Returns the wrapped composite's identity.
    pub fn id(&self) -> usize {
        self.inner.id()
    }

    /// Returns the wrapped composite's name.
    pub fn name(&self) -> String {
        self.inner.name()
    }

    /// Returns the wrapped composite's hint.
    pub fn hint(&self) -> Option<String> {
        self.inner.hint()
    }

    /// Returns a snapshot of the wrapped child collection.
    pub fn items(&self) -> Vec<T> {
        self.inner.items()
    }

    /// Returns the child at `index`, when present.
    pub fn get(&self, index: usize) -> Option<T> {
        self.inner.get(index)
    }

    /// Returns the wrapped collection length.
    pub fn len(&self) -> usize {
        self.inner.len()
    }

    /// Reports whether the wrapped collection is empty.
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Adds a child through the wrapped composite.
    pub fn add(&self, item: T) -> VmxResult<()> {
        self.inner.add(item)
    }

    /// Inserts a child at `index` through the wrapped composite.
    pub fn insert(&self, index: usize, item: T) -> VmxResult<()> {
        self.inner.insert(index, item)
    }

    /// Removes the matching child through the wrapped composite.
    pub fn remove(&self, item: &T) -> VmxResult<()> {
        self.inner.remove(item)
    }

    /// Removes and returns the child at `index`.
    pub fn remove_at(&self, index: usize) -> VmxResult<T> {
        self.inner.remove_at(index)
    }

    /// Replaces and returns the child at `index`.
    pub fn replace(&self, index: usize, item: T) -> VmxResult<T> {
        self.inner.replace(index, item)
    }

    /// Moves a child between strict pre-move positions.
    pub fn move_item(&self, from_index: usize, to_index: usize) -> VmxResult<()> {
        self.inner.move_item(from_index, to_index)
    }

    /// Clears the wrapped child collection.
    pub fn clear(&self) {
        self.inner.clear();
    }

    /// Returns the current child, when selected.
    pub fn current(&self) -> Option<T> {
        self.inner.current()
    }

    /// Sets or clears the current child.
    pub fn set_current(&self, item: Option<T>) -> VmxResult<()> {
        self.inner.set_current(item)
    }

    /// Selects a child through the wrapped composite.
    pub fn select_component(&self, item: &T) -> VmxResult<()> {
        self.inner.select_component(item)
    }

    /// Deselects a child through the wrapped composite.
    pub fn deselect_component(&self, item: &T) -> VmxResult<()> {
        self.inner.deselect_component(item)
    }

    /// Reports whether `item` can become current.
    pub fn can_select_component(&self, item: &T) -> bool {
        self.inner.can_select_component(item)
    }

    /// Coalesces collection messages produced by `action`.
    pub fn batch_update<F>(&self, action: F)
    where
        F: FnOnce(),
    {
        self.inner.batch_update(action);
    }

    /// Constructs the wrapped composite and its children.
    pub fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }

    /// Destructs the wrapped composite and its children.
    pub fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    /// Disposes the wrapped composite and its children.
    pub fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
    }

    /// Returns the wrapped composite's lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    /// Reconstructs the wrapped composite.
    pub fn reconstruct(&self) -> VmxResult<()> {
        self.inner.reconstruct()
    }

    /// Reports whether the wrapped composite is constructed.
    pub fn is_constructed(&self) -> bool {
        self.inner.is_constructed()
    }

    /// Returns the wrapped composite's parent identity, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }

    /// Returns the wrapped composite's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.property_changed()
    }

    /// Returns the wrapped composite's message hub.
    pub fn hub(&self) -> MessageHub {
        self.inner.hub()
    }

    /// Registers a resource cleanup with the wrapped composite.
    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.inner.own(cleanup);
    }

    /// Publishes a property change through the wrapped composite.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.notify_property_changed(property_name);
    }
}

impl<T: VmNode, D: Dispatcher> IntoIterator for ForwardingCompositeVm<T, D> {
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.items().into_iter()
    }
}

impl<T: VmNode, D: Dispatcher> IntoIterator for &ForwardingCompositeVm<T, D> {
    type Item = T;
    type IntoIter = std::vec::IntoIter<T>;

    fn into_iter(self) -> Self::IntoIter {
        self.items().into_iter()
    }
}
