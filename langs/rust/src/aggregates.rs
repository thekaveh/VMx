//! Homogeneous and fixed-arity aggregate view-model families.
//!
//! Spec: `spec/07-aggregate-vm.md`; ADR-0013 and ADR-0094.

use super::{
    finish_with_first_error, lock, retain_first_error, Arc, ComponentCore, ConstructionStatus,
    Dispatcher, HashSet, LifecycleOperation, MessageHub, Mutex, NullDispatcher, ParentHandle,
    ParentRegistration, PropertyChangedStream, RelayCommand, VmNode, VmxError, VmxResult,
};

#[derive(Clone)]
/// A homogeneous collection of components with coordinated lifecycle operations.
pub struct AggregateVm<T: VmNode> {
    members: Vec<T>,
}

impl<T: VmNode> AggregateVm<T> {
    /// Creates a new aggregate from the supplied components.
    pub fn new(members: impl IntoIterator<Item = T>) -> Self {
        Self {
            members: members.into_iter().collect(),
        }
    }

    /// Returns a snapshot of the aggregate members.
    pub fn members(&self) -> Vec<T> {
        self.members.clone()
    }

    /// Constructs every aggregate component in order.
    pub fn construct(&self) -> VmxResult<()> {
        for member in &self.members {
            member.construct()?;
        }
        Ok(())
    }

    /// Destructs every aggregate component in order.
    pub fn destruct(&self) -> VmxResult<()> {
        for member in &self.members {
            member.destruct()?;
        }
        Ok(())
    }

    /// Disposes every aggregate component while preserving the first failure.
    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        for member in &self.members {
            retain_first_error(&mut first_error, member.dispose());
        }
        finish_with_first_error(first_error)
    }
}

fn validate_fixed_aggregate_child<T: VmNode>(
    child: &T,
    seen: &mut HashSet<usize>,
) -> VmxResult<()> {
    if !seen.insert(child.id()) {
        return Err(VmxError::DuplicateChild);
    }
    if child.parent_handle().is_some() || child.parent_id().is_some() {
        return Err(VmxError::InconsistentParent);
    }
    Ok(())
}

fn validate_fixed_aggregate_candidate<T: VmNode>(
    child: &T,
    seen: &mut HashSet<usize>,
    owner: &ParentHandle,
) -> VmxResult<()> {
    if !seen.insert(child.id()) {
        return Err(VmxError::DuplicateChild);
    }
    match child.parent_handle() {
        Some(parent) if parent.same_owner(owner) => Ok(()),
        Some(_) => Err(VmxError::InconsistentParent),
        None if child.parent_id().is_some() => Err(VmxError::InconsistentParent),
        None => Ok(()),
    }
}

type AggregateFactory<T> = Arc<dyn Fn() -> T + Send + Sync>;

#[derive(Clone)]
struct AggregateSlot<T: VmNode> {
    factory: Option<AggregateFactory<T>>,
    value: Arc<Mutex<Option<T>>>,
}

impl<T: VmNode> AggregateSlot<T> {
    fn eager(value: T) -> Self {
        Self {
            factory: None,
            value: Arc::new(Mutex::new(Some(value))),
        }
    }

    fn lazy(factory: AggregateFactory<T>) -> Self {
        Self {
            factory: Some(factory),
            value: Arc::new(Mutex::new(None)),
        }
    }

    fn value(&self) -> Option<T> {
        lock(&self.value).clone()
    }

    fn is_lazy(&self) -> bool {
        self.factory.is_some()
    }

    fn next(&self) -> VmxResult<T> {
        self.factory
            .as_ref()
            .map(|factory| factory())
            .or_else(|| self.value())
            .ok_or_else(|| VmxError::InvalidArgument("aggregate slot is empty".to_string()))
    }

    fn replace(&self, value: T) -> Option<T> {
        lock(&self.value).replace(value)
    }
}

#[derive(Clone)]
struct FixedAggregateOwnership {
    registration: ParentRegistration,
    child_ids: Arc<Mutex<HashSet<usize>>>,
}

impl FixedAggregateOwnership {
    fn handle(&self) -> ParentHandle {
        self.registration.handle()
    }

    fn replace_ids(&self, ids: HashSet<usize>) {
        *lock(&self.child_ids) = ids;
    }
}

fn fixed_aggregate_parent<D: Dispatcher>(
    core: &ComponentCore<D>,
    child_ids: HashSet<usize>,
) -> FixedAggregateOwnership {
    let child_ids = Arc::new(Mutex::new(child_ids));
    let registration = ParentRegistration::new(
        core.id(),
        {
            let core = core.clone();
            move || core.parent_handle()
        },
        {
            let child_ids = Arc::clone(&child_ids);
            move |child_id| lock(&child_ids).contains(&child_id)
        },
        move |_child_id, _owner_handle| Err(VmxError::InconsistentParent),
    );
    FixedAggregateOwnership {
        registration,
        child_ids,
    }
}

fn attach_fixed_aggregate_child<T: VmNode>(child: &T, parent: &ParentHandle) {
    child.set_parent_handle(Some(parent.clone()));
}

fn replace_fixed_aggregate_child<T: VmNode>(
    slot: &AggregateSlot<T>,
    next: T,
    parent: &ParentHandle,
) -> VmxResult<()> {
    let mut result = Ok(());
    if let Some(previous) = slot.replace(next.clone()) {
        previous.set_parent_handle(None);
        result = previous.dispose();
    }
    attach_fixed_aggregate_child(&next, parent);
    result
}

#[derive(Clone)]
/// A fixed-arity aggregate with typed component slots and coordinated lifecycle.
pub struct AggregateVm1<T1: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
}

impl<T1: VmNode> AggregateVm1<T1, NullDispatcher> {
    /// Creates an immutable builder for this aggregate arity.
    pub fn builder() -> AggregateVm1Builder<T1, NullDispatcher> {
        AggregateVm1Builder::default()
    }

    /// Creates a new aggregate from the supplied components.
    pub fn new(name: impl Into<String>, component1: T1) -> Self {
        Self::try_new(name, component1)
            .expect("aggregate component must be unowned and identity-unique")
    }

    /// Tries to create an aggregate and returns ownership-validation failures.
    pub fn try_new(name: impl Into<String>, component1: T1) -> VmxResult<Self> {
        Self::try_with_services(name, MessageHub::new(), NullDispatcher::new(), component1)
    }
}

impl<T1: VmNode, D: Dispatcher> AggregateVm1<T1, D> {
    /// Creates an aggregate with explicit hub and dispatcher services.
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
    ) -> Self {
        Self::try_with_services(name, hub, dispatcher, component1)
            .expect("aggregate component must be unowned and identity-unique")
    }

    /// Tries to create an aggregate with explicit services and ownership validation.
    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        attach_fixed_aggregate_child(&component1, &ownership.handle());
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
        })
    }

    fn from_factory(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
        }
    }

    /// Returns aggregate component 1.
    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }

    /// Returns aggregate component 1.
    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }

    /// Returns the aggregate's stable identity.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Returns the aggregate's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the aggregate message hub.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Publishes one named aggregate property change.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Constructs every aggregate component in order.
    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let mut ids = HashSet::new();
                let parent = self.ownership.handle();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()
            })
    }

    /// Destructs every aggregate component in order.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            Ok(())
        })
    }

    /// Disposes every aggregate component while preserving the first failure.
    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
    }

    /// Returns the aggregate lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }
}

impl<T1: VmNode, D: Dispatcher> VmNode for AggregateVm1<T1, D> {
    fn id(&self) -> usize {
        AggregateVm1::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        AggregateVm1::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        AggregateVm1::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        AggregateVm1::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        AggregateVm1::status(self)
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

impl<T1: VmNode, D: Dispatcher> PartialEq for AggregateVm1<T1, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T1: VmNode, D: Dispatcher> Eq for AggregateVm1<T1, D> {}

#[derive(Clone)]
/// A fixed-arity aggregate with typed component slots and coordinated lifecycle.
pub struct AggregateVm1Builder<T1: VmNode, D: Dispatcher = NullDispatcher> {
    name: Option<String>,
    hint: Option<String>,
    hub: Option<MessageHub>,
    dispatcher: Option<D>,
    factory1: Option<AggregateFactory<T1>>,
}

impl<T1: VmNode> Default for AggregateVm1Builder<T1, NullDispatcher> {
    fn default() -> Self {
        Self {
            name: None,
            hint: Some(String::new()),
            hub: None,
            dispatcher: None,
            factory1: None,
        }
    }
}

impl<T1: VmNode, D: Dispatcher> AggregateVm1Builder<T1, D> {
    /// Sets the aggregate name.
    pub fn name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    /// Sets the aggregate hint.
    pub fn hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }

    /// Sets the message hub and dispatcher services.
    pub fn services(mut self, hub: MessageHub, dispatcher: D) -> Self {
        self.hub = Some(hub);
        self.dispatcher = Some(dispatcher);
        self
    }

    /// Sets the construction factory for aggregate component 1.
    pub fn component_1<F>(mut self, factory: F) -> Self
    where
        F: Fn() -> T1 + Send + Sync + 'static,
    {
        self.factory1 = Some(Arc::new(factory));
        self
    }

    /// Validates required fields and builds the aggregate.
    pub fn build(self) -> VmxResult<AggregateVm1<T1, D>> {
        let name = self
            .name
            .ok_or_else(|| VmxError::BuilderValidation("name is required".to_string()))?;
        let hub = self
            .hub
            .ok_or_else(|| VmxError::BuilderValidation("hub is required".to_string()))?;
        let dispatcher = self
            .dispatcher
            .ok_or_else(|| VmxError::BuilderValidation("dispatcher is required".to_string()))?;
        let factory1 = self
            .factory1
            .ok_or_else(|| VmxError::BuilderValidation("component_1 is required".to_string()))?;
        Ok(AggregateVm1::from_factory(
            name, self.hint, hub, dispatcher, factory1,
        ))
    }
}

#[derive(Clone)]
/// A fixed-arity aggregate with typed component slots and coordinated lifecycle.
pub struct AggregateVm2<T1: VmNode, T2: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
}

impl<T1: VmNode, T2: VmNode> AggregateVm2<T1, T2, NullDispatcher> {
    /// Creates an immutable builder for this aggregate arity.
    pub fn builder() -> AggregateVm2Builder<T1, T2, NullDispatcher> {
        AggregateVm2Builder::default()
    }

    /// Creates a new aggregate from the supplied components.
    pub fn new(name: impl Into<String>, component1: T1, component2: T2) -> Self {
        Self::try_new(name, component1, component2)
            .expect("aggregate components must be unowned and identity-unique")
    }

    /// Tries to create an aggregate and returns ownership-validation failures.
    pub fn try_new(name: impl Into<String>, component1: T1, component2: T2) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
        )
    }
}

impl<T1: VmNode, T2: VmNode, D: Dispatcher> AggregateVm2<T1, T2, D> {
    /// Creates an aggregate with explicit hub and dispatcher services.
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
    ) -> Self {
        Self::try_with_services(name, hub, dispatcher, component1, component2)
            .expect("aggregate components must be unowned and identity-unique")
    }

    /// Tries to create an aggregate with explicit services and ownership validation.
    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
        })
    }

    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
        }
    }

    /// Returns aggregate component 1.
    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }

    /// Returns aggregate component 2.
    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }

    /// Returns aggregate component 1.
    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }

    /// Returns aggregate component 2.
    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }

    /// Returns the aggregate's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the aggregate message hub.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Publishes one named aggregate property change.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Returns the aggregate's stable identity.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Constructs every aggregate component in order.
    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                }
                if self.component2.is_lazy() {
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()
            })
    }

    /// Destructs every aggregate component in order.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            Ok(())
        })
    }

    /// Disposes every aggregate component while preserving the first failure.
    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
    }

    /// Returns the aggregate lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }
}

impl<T1: VmNode, T2: VmNode, D: Dispatcher> VmNode for AggregateVm2<T1, T2, D> {
    fn id(&self) -> usize {
        AggregateVm2::id(self)
    }

    fn construct(&self) -> VmxResult<()> {
        AggregateVm2::construct(self)
    }

    fn destruct(&self) -> VmxResult<()> {
        AggregateVm2::destruct(self)
    }

    fn dispose(&self) -> VmxResult<()> {
        AggregateVm2::dispose(self)
    }

    fn status(&self) -> ConstructionStatus {
        AggregateVm2::status(self)
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

impl<T1: VmNode, T2: VmNode, D: Dispatcher> PartialEq for AggregateVm2<T1, T2, D> {
    fn eq(&self, other: &Self) -> bool {
        self.id() == other.id()
    }
}

impl<T1: VmNode, T2: VmNode, D: Dispatcher> Eq for AggregateVm2<T1, T2, D> {}

#[derive(Clone)]
/// A fixed-arity aggregate with typed component slots and coordinated lifecycle.
pub struct AggregateVm3<T1: VmNode, T2: VmNode, T3: VmNode, D: Dispatcher = NullDispatcher> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
    component3: AggregateSlot<T3>,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode> AggregateVm3<T1, T2, T3, NullDispatcher> {
    /// Creates an immutable builder for this aggregate arity.
    pub fn builder() -> AggregateVm3Builder<T1, T2, T3, NullDispatcher> {
        AggregateVm3Builder::default()
    }

    /// Creates a new aggregate from the supplied components.
    pub fn new(name: impl Into<String>, component1: T1, component2: T2, component3: T3) -> Self {
        Self::try_new(name, component1, component2, component3)
            .expect("aggregate components must be unowned and identity-unique")
    }

    /// Tries to create an aggregate and returns ownership-validation failures.
    pub fn try_new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
    ) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
            component3,
        )
    }
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, D: Dispatcher> AggregateVm3<T1, T2, T3, D> {
    /// Creates an aggregate with explicit hub and dispatcher services.
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
    ) -> Self {
        Self::try_with_services(name, hub, dispatcher, component1, component2, component3)
            .expect("aggregate components must be unowned and identity-unique")
    }

    /// Tries to create an aggregate with explicit services and ownership validation.
    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        validate_fixed_aggregate_child(&component3, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        attach_fixed_aggregate_child(&component3, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
            component3: AggregateSlot::eager(component3),
        })
    }

    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
        factory3: AggregateFactory<T3>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
            component3: AggregateSlot::lazy(factory3),
        }
    }

    /// Returns aggregate component 1.
    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }

    /// Returns aggregate component 2.
    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }

    /// Returns aggregate component 3.
    pub fn component_3(&self) -> Option<T3> {
        self.component3.value()
    }

    /// Returns aggregate component 1.
    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }

    /// Returns aggregate component 2.
    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }

    /// Returns aggregate component 3.
    pub fn component3(&self) -> Option<T3> {
        self.component_3()
    }

    /// Returns the aggregate's stable identity.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Returns the aggregate's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the aggregate message hub.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Registers an owned cleanup action with the aggregate.
    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.core.own(cleanup);
    }

    /// Publishes one named aggregate property change.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Constructs every aggregate component in order.
    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let next3 = self.component3.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next3, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component3, next3.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()?;
                self.core.notify_property_changed("component_3");
                next3.construct()
            })
    }

    /// Destructs every aggregate component in order.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            if let Some(component3) = self.component_3() {
                component3.destruct()?;
            }
            Ok(())
        })
    }

    /// Disposes every aggregate component while preserving the first failure.
    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        if let Some(component3) = self.component_3() {
            retain_first_error(&mut first_error, component3.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
    }

    /// Returns the aggregate lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }
}

#[derive(Clone)]
/// A fixed-arity aggregate with typed component slots and coordinated lifecycle.
pub struct AggregateVm4<
    T1: VmNode,
    T2: VmNode,
    T3: VmNode,
    T4: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
    component3: AggregateSlot<T3>,
    component4: AggregateSlot<T4>,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode> AggregateVm4<T1, T2, T3, T4, NullDispatcher> {
    /// Creates an immutable builder for this aggregate arity.
    pub fn builder() -> AggregateVm4Builder<T1, T2, T3, T4, NullDispatcher> {
        AggregateVm4Builder::default()
    }

    /// Creates a new aggregate from the supplied components.
    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> Self {
        Self::try_new(name, component1, component2, component3, component4)
            .expect("aggregate components must be unowned and identity-unique")
    }

    /// Tries to create an aggregate and returns ownership-validation failures.
    pub fn try_new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
            component3,
            component4,
        )
    }
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, D: Dispatcher>
    AggregateVm4<T1, T2, T3, T4, D>
{
    /// Creates an aggregate with explicit hub and dispatcher services.
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> Self {
        Self::try_with_services(
            name, hub, dispatcher, component1, component2, component3, component4,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    /// Tries to create an aggregate with explicit services and ownership validation.
    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        validate_fixed_aggregate_child(&component3, &mut ids)?;
        validate_fixed_aggregate_child(&component4, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        attach_fixed_aggregate_child(&component3, &parent);
        attach_fixed_aggregate_child(&component4, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
            component3: AggregateSlot::eager(component3),
            component4: AggregateSlot::eager(component4),
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
        factory3: AggregateFactory<T3>,
        factory4: AggregateFactory<T4>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
            component3: AggregateSlot::lazy(factory3),
            component4: AggregateSlot::lazy(factory4),
        }
    }

    /// Returns aggregate component 1.
    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }

    /// Returns aggregate component 2.
    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }

    /// Returns aggregate component 3.
    pub fn component_3(&self) -> Option<T3> {
        self.component3.value()
    }

    /// Returns aggregate component 4.
    pub fn component_4(&self) -> Option<T4> {
        self.component4.value()
    }

    /// Returns aggregate component 1.
    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }
    /// Returns aggregate component 2.
    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }
    /// Returns aggregate component 3.
    pub fn component3(&self) -> Option<T3> {
        self.component_3()
    }
    /// Returns aggregate component 4.
    pub fn component4(&self) -> Option<T4> {
        self.component_4()
    }

    /// Returns the aggregate's stable identity.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Returns the aggregate's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the aggregate message hub.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Registers an owned cleanup action with the aggregate.
    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.core.own(cleanup);
    }

    /// Publishes one named aggregate property change.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Constructs every aggregate component in order.
    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let next3 = self.component3.next()?;
                let next4 = self.component4.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next3, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next4, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component3, next3.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component4, next4.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()?;
                self.core.notify_property_changed("component_3");
                next3.construct()?;
                self.core.notify_property_changed("component_4");
                next4.construct()
            })
    }

    /// Destructs every aggregate component in order.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            if let Some(component3) = self.component_3() {
                component3.destruct()?;
            }
            if let Some(component4) = self.component_4() {
                component4.destruct()?;
            }
            Ok(())
        })
    }

    /// Disposes every aggregate component while preserving the first failure.
    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        if let Some(component3) = self.component_3() {
            retain_first_error(&mut first_error, component3.dispose());
        }
        if let Some(component4) = self.component_4() {
            retain_first_error(&mut first_error, component4.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
    }

    /// Returns the aggregate lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }
}

#[derive(Clone)]
/// A fixed-arity aggregate with typed component slots and coordinated lifecycle.
pub struct AggregateVm5<
    T1: VmNode,
    T2: VmNode,
    T3: VmNode,
    T4: VmNode,
    T5: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
    component3: AggregateSlot<T3>,
    component4: AggregateSlot<T4>,
    component5: AggregateSlot<T5>,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode>
    AggregateVm5<T1, T2, T3, T4, T5, NullDispatcher>
{
    /// Creates an immutable builder for this aggregate arity.
    pub fn builder() -> AggregateVm5Builder<T1, T2, T3, T4, T5, NullDispatcher> {
        AggregateVm5Builder::default()
    }

    /// Creates a new aggregate from the supplied components.
    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> Self {
        Self::try_new(
            name, component1, component2, component3, component4, component5,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    /// Tries to create an aggregate and returns ownership-validation failures.
    pub fn try_new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
            component3,
            component4,
            component5,
        )
    }
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode, D: Dispatcher>
    AggregateVm5<T1, T2, T3, T4, T5, D>
{
    #[allow(clippy::too_many_arguments)]
    /// Creates an aggregate with explicit hub and dispatcher services.
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> Self {
        Self::try_with_services(
            name, hub, dispatcher, component1, component2, component3, component4, component5,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    #[allow(clippy::too_many_arguments)]
    /// Tries to create an aggregate with explicit services and ownership validation.
    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        validate_fixed_aggregate_child(&component3, &mut ids)?;
        validate_fixed_aggregate_child(&component4, &mut ids)?;
        validate_fixed_aggregate_child(&component5, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        attach_fixed_aggregate_child(&component3, &parent);
        attach_fixed_aggregate_child(&component4, &parent);
        attach_fixed_aggregate_child(&component5, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
            component3: AggregateSlot::eager(component3),
            component4: AggregateSlot::eager(component4),
            component5: AggregateSlot::eager(component5),
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
        factory3: AggregateFactory<T3>,
        factory4: AggregateFactory<T4>,
        factory5: AggregateFactory<T5>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
            component3: AggregateSlot::lazy(factory3),
            component4: AggregateSlot::lazy(factory4),
            component5: AggregateSlot::lazy(factory5),
        }
    }

    /// Returns aggregate component 1.
    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }
    /// Returns aggregate component 2.
    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }
    /// Returns aggregate component 3.
    pub fn component_3(&self) -> Option<T3> {
        self.component3.value()
    }
    /// Returns aggregate component 4.
    pub fn component_4(&self) -> Option<T4> {
        self.component4.value()
    }
    /// Returns aggregate component 5.
    pub fn component_5(&self) -> Option<T5> {
        self.component5.value()
    }
    /// Returns aggregate component 1.
    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }
    /// Returns aggregate component 2.
    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }
    /// Returns aggregate component 3.
    pub fn component3(&self) -> Option<T3> {
        self.component_3()
    }
    /// Returns aggregate component 4.
    pub fn component4(&self) -> Option<T4> {
        self.component_4()
    }
    /// Returns aggregate component 5.
    pub fn component5(&self) -> Option<T5> {
        self.component_5()
    }

    /// Returns the aggregate's stable identity.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Returns the aggregate's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the aggregate message hub.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Registers an owned cleanup action with the aggregate.
    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.core.own(cleanup);
    }

    /// Publishes one named aggregate property change.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Constructs every aggregate component in order.
    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let next3 = self.component3.next()?;
                let next4 = self.component4.next()?;
                let next5 = self.component5.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next3, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next4, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next5, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component3, next3.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component4, next4.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component5, next5.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()?;
                self.core.notify_property_changed("component_3");
                next3.construct()?;
                self.core.notify_property_changed("component_4");
                next4.construct()?;
                self.core.notify_property_changed("component_5");
                next5.construct()
            })
    }

    /// Destructs every aggregate component in order.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            if let Some(component3) = self.component_3() {
                component3.destruct()?;
            }
            if let Some(component4) = self.component_4() {
                component4.destruct()?;
            }
            if let Some(component5) = self.component_5() {
                component5.destruct()?;
            }
            Ok(())
        })
    }

    /// Disposes every aggregate component while preserving the first failure.
    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        if let Some(component3) = self.component_3() {
            retain_first_error(&mut first_error, component3.dispose());
        }
        if let Some(component4) = self.component_4() {
            retain_first_error(&mut first_error, component4.dispose());
        }
        if let Some(component5) = self.component_5() {
            retain_first_error(&mut first_error, component5.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
    }

    /// Returns the aggregate lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }
}

#[derive(Clone)]
/// A fixed-arity aggregate with typed component slots and coordinated lifecycle.
pub struct AggregateVm6<
    T1: VmNode,
    T2: VmNode,
    T3: VmNode,
    T4: VmNode,
    T5: VmNode,
    T6: VmNode,
    D: Dispatcher = NullDispatcher,
> {
    core: ComponentCore<D>,
    ownership: FixedAggregateOwnership,
    component1: AggregateSlot<T1>,
    component2: AggregateSlot<T2>,
    component3: AggregateSlot<T3>,
    component4: AggregateSlot<T4>,
    component5: AggregateSlot<T5>,
    component6: AggregateSlot<T6>,
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode, T6: VmNode>
    AggregateVm6<T1, T2, T3, T4, T5, T6, NullDispatcher>
{
    /// Creates an immutable builder for this aggregate arity.
    pub fn builder() -> AggregateVm6Builder<T1, T2, T3, T4, T5, T6, NullDispatcher> {
        AggregateVm6Builder::default()
    }

    /// Creates a new aggregate from the supplied components.
    pub fn new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> Self {
        Self::try_new(
            name, component1, component2, component3, component4, component5, component6,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    /// Tries to create an aggregate and returns ownership-validation failures.
    pub fn try_new(
        name: impl Into<String>,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> VmxResult<Self> {
        Self::try_with_services(
            name,
            MessageHub::new(),
            NullDispatcher::new(),
            component1,
            component2,
            component3,
            component4,
            component5,
            component6,
        )
    }
}

impl<T1: VmNode, T2: VmNode, T3: VmNode, T4: VmNode, T5: VmNode, T6: VmNode, D: Dispatcher>
    AggregateVm6<T1, T2, T3, T4, T5, T6, D>
{
    #[allow(clippy::too_many_arguments)]
    /// Creates an aggregate with explicit hub and dispatcher services.
    pub fn with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> Self {
        Self::try_with_services(
            name, hub, dispatcher, component1, component2, component3, component4, component5,
            component6,
        )
        .expect("aggregate components must be unowned and identity-unique")
    }

    #[allow(clippy::too_many_arguments)]
    /// Tries to create an aggregate with explicit services and ownership validation.
    pub fn try_with_services(
        name: impl Into<String>,
        hub: MessageHub,
        dispatcher: D,
        component1: T1,
        component2: T2,
        component3: T3,
        component4: T4,
        component5: T5,
        component6: T6,
    ) -> VmxResult<Self> {
        let mut ids = HashSet::new();
        validate_fixed_aggregate_child(&component1, &mut ids)?;
        validate_fixed_aggregate_child(&component2, &mut ids)?;
        validate_fixed_aggregate_child(&component3, &mut ids)?;
        validate_fixed_aggregate_child(&component4, &mut ids)?;
        validate_fixed_aggregate_child(&component5, &mut ids)?;
        validate_fixed_aggregate_child(&component6, &mut ids)?;
        let core = ComponentCore::new(name, hub, dispatcher);
        let ownership = fixed_aggregate_parent(&core, ids);
        let parent = ownership.handle();
        attach_fixed_aggregate_child(&component1, &parent);
        attach_fixed_aggregate_child(&component2, &parent);
        attach_fixed_aggregate_child(&component3, &parent);
        attach_fixed_aggregate_child(&component4, &parent);
        attach_fixed_aggregate_child(&component5, &parent);
        attach_fixed_aggregate_child(&component6, &parent);
        Ok(Self {
            core,
            ownership,
            component1: AggregateSlot::eager(component1),
            component2: AggregateSlot::eager(component2),
            component3: AggregateSlot::eager(component3),
            component4: AggregateSlot::eager(component4),
            component5: AggregateSlot::eager(component5),
            component6: AggregateSlot::eager(component6),
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn from_factories(
        name: impl Into<String>,
        hint: Option<String>,
        hub: MessageHub,
        dispatcher: D,
        factory1: AggregateFactory<T1>,
        factory2: AggregateFactory<T2>,
        factory3: AggregateFactory<T3>,
        factory4: AggregateFactory<T4>,
        factory5: AggregateFactory<T5>,
        factory6: AggregateFactory<T6>,
    ) -> Self {
        let core = ComponentCore::new(name, hub, dispatcher);
        if let Some(hint) = hint {
            core.set_hint(Some(hint));
        }
        Self {
            ownership: fixed_aggregate_parent(&core, HashSet::new()),
            core,
            component1: AggregateSlot::lazy(factory1),
            component2: AggregateSlot::lazy(factory2),
            component3: AggregateSlot::lazy(factory3),
            component4: AggregateSlot::lazy(factory4),
            component5: AggregateSlot::lazy(factory5),
            component6: AggregateSlot::lazy(factory6),
        }
    }

    /// Returns aggregate component 1.
    pub fn component_1(&self) -> Option<T1> {
        self.component1.value()
    }
    /// Returns aggregate component 2.
    pub fn component_2(&self) -> Option<T2> {
        self.component2.value()
    }
    /// Returns aggregate component 3.
    pub fn component_3(&self) -> Option<T3> {
        self.component3.value()
    }
    /// Returns aggregate component 4.
    pub fn component_4(&self) -> Option<T4> {
        self.component4.value()
    }
    /// Returns aggregate component 5.
    pub fn component_5(&self) -> Option<T5> {
        self.component5.value()
    }
    /// Returns aggregate component 6.
    pub fn component_6(&self) -> Option<T6> {
        self.component6.value()
    }
    /// Returns aggregate component 1.
    pub fn component1(&self) -> Option<T1> {
        self.component_1()
    }
    /// Returns aggregate component 2.
    pub fn component2(&self) -> Option<T2> {
        self.component_2()
    }
    /// Returns aggregate component 3.
    pub fn component3(&self) -> Option<T3> {
        self.component_3()
    }
    /// Returns aggregate component 4.
    pub fn component4(&self) -> Option<T4> {
        self.component_4()
    }
    /// Returns aggregate component 5.
    pub fn component5(&self) -> Option<T5> {
        self.component_5()
    }
    /// Returns aggregate component 6.
    pub fn component6(&self) -> Option<T6> {
        self.component_6()
    }

    /// Returns the aggregate's local property-change stream.
    pub fn property_changed(&self) -> PropertyChangedStream {
        self.core.property_changed_stream()
    }

    /// Returns the aggregate message hub.
    pub fn hub(&self) -> MessageHub {
        self.core.hub()
    }

    /// Registers an owned cleanup action with the aggregate.
    pub fn own<F: FnOnce() + Send + 'static>(&self, cleanup: F) {
        self.core.own(cleanup);
    }

    /// Publishes one named aggregate property change.
    pub fn notify_property_changed(&self, property_name: impl Into<String>) {
        self.core.notify_property_changed(property_name);
    }

    /// Returns the aggregate's stable identity.
    pub fn id(&self) -> usize {
        self.core.id()
    }

    /// Constructs every aggregate component in order.
    pub fn construct(&self) -> VmxResult<()> {
        self.core
            .transition_with(LifecycleOperation::Construct, || {
                let next1 = self.component1.next()?;
                let next2 = self.component2.next()?;
                let next3 = self.component3.next()?;
                let next4 = self.component4.next()?;
                let next5 = self.component5.next()?;
                let next6 = self.component6.next()?;
                let parent = self.ownership.handle();
                let mut ids = HashSet::new();
                validate_fixed_aggregate_candidate(&next1, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next2, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next3, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next4, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next5, &mut ids, &parent)?;
                validate_fixed_aggregate_candidate(&next6, &mut ids, &parent)?;
                if self.component1.is_lazy() {
                    replace_fixed_aggregate_child(&self.component1, next1.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component2, next2.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component3, next3.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component4, next4.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component5, next5.clone(), &parent)?;
                    replace_fixed_aggregate_child(&self.component6, next6.clone(), &parent)?;
                }
                self.ownership.replace_ids(ids);
                self.core.notify_property_changed("component_1");
                next1.construct()?;
                self.core.notify_property_changed("component_2");
                next2.construct()?;
                self.core.notify_property_changed("component_3");
                next3.construct()?;
                self.core.notify_property_changed("component_4");
                next4.construct()?;
                self.core.notify_property_changed("component_5");
                next5.construct()?;
                self.core.notify_property_changed("component_6");
                next6.construct()
            })
    }

    /// Destructs every aggregate component in order.
    pub fn destruct(&self) -> VmxResult<()> {
        self.core.transition_with(LifecycleOperation::Destruct, || {
            if let Some(component1) = self.component_1() {
                component1.destruct()?;
            }
            if let Some(component2) = self.component_2() {
                component2.destruct()?;
            }
            if let Some(component3) = self.component_3() {
                component3.destruct()?;
            }
            if let Some(component4) = self.component_4() {
                component4.destruct()?;
            }
            if let Some(component5) = self.component_5() {
                component5.destruct()?;
            }
            if let Some(component6) = self.component_6() {
                component6.destruct()?;
            }
            Ok(())
        })
    }

    /// Disposes every aggregate component while preserving the first failure.
    pub fn dispose(&self) -> VmxResult<()> {
        let mut first_error = None;
        if let Some(component1) = self.component_1() {
            retain_first_error(&mut first_error, component1.dispose());
        }
        if let Some(component2) = self.component_2() {
            retain_first_error(&mut first_error, component2.dispose());
        }
        if let Some(component3) = self.component_3() {
            retain_first_error(&mut first_error, component3.dispose());
        }
        if let Some(component4) = self.component_4() {
            retain_first_error(&mut first_error, component4.dispose());
        }
        if let Some(component5) = self.component_5() {
            retain_first_error(&mut first_error, component5.dispose());
        }
        if let Some(component6) = self.component_6() {
            retain_first_error(&mut first_error, component6.dispose());
        }
        retain_first_error(
            &mut first_error,
            self.core.transition(LifecycleOperation::Dispose),
        );
        finish_with_first_error(first_error)
    }

    /// Returns the aggregate lifecycle status.
    pub fn status(&self) -> ConstructionStatus {
        self.core.status()
    }
}

macro_rules! impl_fixed_aggregate_vm_node {
    ($name:ident, $($component:ident),+) => {
        impl<$($component: VmNode,)+ D: Dispatcher> VmNode
            for $name<$($component,)+ D>
        {
            fn id(&self) -> usize { self.core.id() }
            fn construct(&self) -> VmxResult<()> { $name::construct(self) }
            fn destruct(&self) -> VmxResult<()> { $name::destruct(self) }
            fn dispose(&self) -> VmxResult<()> { $name::dispose(self) }
            fn status(&self) -> ConstructionStatus { $name::status(self) }
            fn set_parent_id(&self, parent_id: Option<usize>) {
                self.core.set_parent_id(parent_id);
            }
            fn parent_id(&self) -> Option<usize> { self.core.parent_id() }
            fn set_parent_handle(&self, parent: Option<ParentHandle>) {
                self.core.set_parent_handle(parent);
            }
            fn parent_handle(&self) -> Option<ParentHandle> { self.core.parent_handle() }
            fn set_current_flag(&self, is_current: bool) {
                self.core.set_current_flag(is_current);
            }
            fn is_current(&self) -> bool { self.core.is_selected() }
        }

        impl<$($component: VmNode,)+ D: Dispatcher> PartialEq
            for $name<$($component,)+ D>
        {
            fn eq(&self, other: &Self) -> bool { self.core.id() == other.core.id() }
        }

        impl<$($component: VmNode,)+ D: Dispatcher> Eq for $name<$($component,)+ D> {}
    };
}

impl_fixed_aggregate_vm_node!(AggregateVm3, T1, T2, T3);
impl_fixed_aggregate_vm_node!(AggregateVm4, T1, T2, T3, T4);
impl_fixed_aggregate_vm_node!(AggregateVm5, T1, T2, T3, T4, T5);
impl_fixed_aggregate_vm_node!(AggregateVm6, T1, T2, T3, T4, T5, T6);

macro_rules! define_aggregate_builder {
    ($builder:ident, $aggregate:ident, $(($component:ident, $factory:ident, $setter:ident)),+) => {
        #[derive(Clone)]
        /// An immutable builder for a fixed-arity aggregate.
        pub struct $builder<$($component: VmNode,)+ D: Dispatcher = NullDispatcher> {
            name: Option<String>,
            hint: Option<String>,
            hub: Option<MessageHub>,
            dispatcher: Option<D>,
            $($factory: Option<AggregateFactory<$component>>,)+
        }

        impl<$($component: VmNode,)+> Default
            for $builder<$($component,)+ NullDispatcher>
        {
            fn default() -> Self {
                Self {
                    name: None,
                    hint: Some(String::new()),
                    hub: None,
                    dispatcher: None,
                    $($factory: None,)+
                }
            }
        }

        impl<$($component: VmNode,)+ D: Dispatcher> $builder<$($component,)+ D> {
            /// Sets the aggregate name.
            pub fn name(mut self, name: impl Into<String>) -> Self {
                self.name = Some(name.into());
                self
            }

            /// Sets the aggregate hint.
            pub fn hint(mut self, hint: impl Into<String>) -> Self {
                self.hint = Some(hint.into());
                self
            }

            /// Sets the message hub and dispatcher services.
            pub fn services(mut self, hub: MessageHub, dispatcher: D) -> Self {
                self.hub = Some(hub);
                self.dispatcher = Some(dispatcher);
                self
            }

            $(
                /// Sets one required aggregate component factory.
                pub fn $setter<F>(mut self, factory: F) -> Self
                where
                    F: Fn() -> $component + Send + Sync + 'static,
                {
                    self.$factory = Some(Arc::new(factory));
                    self
                }
            )+

            /// Validates required fields and builds the aggregate.
            pub fn build(self) -> VmxResult<$aggregate<$($component,)+ D>> {
                let name = self.name.ok_or_else(|| {
                    VmxError::BuilderValidation("name is required".to_string())
                })?;
                let hub = self.hub.ok_or_else(|| {
                    VmxError::BuilderValidation("hub is required".to_string())
                })?;
                let dispatcher = self.dispatcher.ok_or_else(|| {
                    VmxError::BuilderValidation("dispatcher is required".to_string())
                })?;
                $(
                    let $factory = self.$factory.ok_or_else(|| {
                        VmxError::BuilderValidation(
                            concat!(stringify!($setter), " is required").to_string(),
                        )
                    })?;
                )+
                Ok($aggregate::from_factories(
                    name,
                    self.hint,
                    hub,
                    dispatcher,
                    $($factory,)+
                ))
            }
        }
    };
}

define_aggregate_builder!(
    AggregateVm2Builder,
    AggregateVm2,
    (T1, factory1, component_1),
    (T2, factory2, component_2)
);
define_aggregate_builder!(
    AggregateVm3Builder,
    AggregateVm3,
    (T1, factory1, component_1),
    (T2, factory2, component_2),
    (T3, factory3, component_3)
);
define_aggregate_builder!(
    AggregateVm4Builder,
    AggregateVm4,
    (T1, factory1, component_1),
    (T2, factory2, component_2),
    (T3, factory3, component_3),
    (T4, factory4, component_4)
);
define_aggregate_builder!(
    AggregateVm5Builder,
    AggregateVm5,
    (T1, factory1, component_1),
    (T2, factory2, component_2),
    (T3, factory3, component_3),
    (T4, factory4, component_4),
    (T5, factory5, component_5)
);
define_aggregate_builder!(
    AggregateVm6Builder,
    AggregateVm6,
    (T1, factory1, component_1),
    (T2, factory2, component_2),
    (T3, factory3, component_3),
    (T4, factory4, component_4),
    (T5, factory5, component_5),
    (T6, factory6, component_6)
);

macro_rules! impl_fixed_aggregate_baseline {
    ($name:ident, $($component:ident),+) => {
        impl<$($component: VmNode,)+ D: Dispatcher> $name<$($component,)+ D> {
            /// Returns the aggregate name.
            pub fn name(&self) -> String {
                self.core.name()
            }

            /// Returns the aggregate hint.
            pub fn hint(&self) -> Option<String> {
                self.core.hint()
            }

            /// Destructs and then constructs the aggregate.
            pub fn reconstruct(&self) -> VmxResult<()> {
                self.destruct()?;
                self.construct()
            }

            /// Reports whether the aggregate is constructed.
            pub fn is_constructed(&self) -> bool {
                self.status() == ConstructionStatus::Constructed
            }

            /// Returns the aggregate parent identity, when attached.
            pub fn parent_id(&self) -> Option<usize> {
                self.core.parent_id()
            }

            /// Marks the aggregate as selected.
            pub fn select(&self) {
                self.core.select();
            }

            /// Marks the aggregate as not selected.
            pub fn deselect(&self) {
                self.core.deselect();
            }

            /// Reports whether the aggregate is selected.
            pub fn is_selected(&self) -> bool {
                self.core.is_selected()
            }

            /// Creates a command that selects the aggregate.
            pub fn select_command(&self) -> RelayCommand {
                let vm = self.clone();
                RelayCommand::new({
                    let vm = vm.clone();
                    move || vm.select()
                })
                .with_can_execute(move || !vm.is_selected())
            }

            /// Creates a command that deselects the aggregate.
            pub fn deselect_command(&self) -> RelayCommand {
                let vm = self.clone();
                RelayCommand::new({
                    let vm = vm.clone();
                    move || vm.deselect()
                })
                .with_can_execute(move || vm.is_selected())
            }
        }
    };
}

impl_fixed_aggregate_baseline!(AggregateVm1, T1);
impl_fixed_aggregate_baseline!(AggregateVm2, T1, T2);
impl_fixed_aggregate_baseline!(AggregateVm3, T1, T2, T3);
impl_fixed_aggregate_baseline!(AggregateVm4, T1, T2, T3, T4);
impl_fixed_aggregate_baseline!(AggregateVm5, T1, T2, T3, T4, T5);
impl_fixed_aggregate_baseline!(AggregateVm6, T1, T2, T3, T4, T5, T6);
