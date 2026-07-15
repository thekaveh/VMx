//! Transparent component and composite forwarding wrappers.
//!
//! Spec: `spec/13-forwarding-wrappers.md`; ADR-0028.

use super::{
    ComponentVm, CompositeVm, ConstructionStatus, Dispatcher, MessageHub, NullDispatcher,
    PropertyChangedStream, RelayCommand, VmNode, VmxResult,
};

#[derive(Clone)]
/// A component wrapper that forwards the complete baseline surface to an inner VM.
pub struct ForwardingComponentVm<
    M: Clone + PartialEq + Send + 'static,
    D: Dispatcher = NullDispatcher,
> {
    inner: ComponentVm<M, D>,
}

impl<M: Clone + PartialEq + Send + 'static, D: Dispatcher> ForwardingComponentVm<M, D> {
    /// Wraps `inner` without taking additional lifecycle ownership.
    pub fn new(inner: ComponentVm<M, D>) -> Self {
        Self { inner }
    }

    /// Borrows the wrapped component.
    pub fn inner(&self) -> &ComponentVm<M, D> {
        &self.inner
    }

    /// Returns the wrapped component's identity.
    pub fn id(&self) -> usize {
        self.inner.id()
    }

    /// Returns the wrapped component's name.
    pub fn name(&self) -> String {
        self.inner.name()
    }

    /// Returns the wrapped component's static hint.
    pub fn hint(&self) -> Option<String> {
        self.inner.hint()
    }

    /// Returns the wrapped component's model-derived hint.
    pub fn modeled_hint(&self) -> Option<String> {
        self.inner.modeled_hint()
    }

    /// Returns the wrapped component's model.
    pub fn model(&self) -> M {
        self.inner.model()
    }

    /// Replaces the wrapped component's model.
    pub fn set_model(&self, model: M) {
        self.inner.set_model(model);
    }

    /// Republishes the wrapped component's retained model notification.
    pub fn republish_model(&self) {
        self.inner.republish_model();
    }

    /// Constructs the wrapped component.
    pub fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }

    /// Destructs the wrapped component.
    pub fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    /// Disposes the wrapped component.
    pub fn dispose(&self) -> VmxResult<()> {
        self.inner.dispose()
    }

    /// Returns the wrapped component's lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    /// Reconstructs the wrapped component.
    pub fn reconstruct(&self) -> VmxResult<()> {
        self.inner.reconstruct()
    }

    /// Reports whether the wrapped component is constructed.
    pub fn is_constructed(&self) -> bool {
        self.inner.is_constructed()
    }

    /// Returns the wrapped component's parent identity, when attached.
    pub fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }

    /// Returns the wrapped component's selection command.
    pub fn select_command(&self) -> RelayCommand {
        self.inner.select_command()
    }

    /// Selects the wrapped component.
    pub fn select(&self) {
        self.inner.select();
    }

    /// Deselects the wrapped component.
    pub fn deselect(&self) {
        self.inner.deselect();
    }

    /// Reports whether the wrapped component is selected.
    pub fn is_selected(&self) -> bool {
        self.inner.is_selected()
    }

    /// Returns the wrapped component's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.inner.property_changed()
    }

    /// Returns the wrapped component's message hub.
    pub fn hub(&self) -> MessageHub {
        self.inner.hub()
    }

    /// Registers a resource cleanup with the wrapped component.
    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.inner.own(cleanup);
    }

    /// Publishes a property change through the wrapped component.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.inner.notify_property_changed(property_name);
    }
}

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
