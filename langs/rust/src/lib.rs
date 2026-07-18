//! VMx Rust flavor.
//!
//! The Rust flavor mirrors the VMx language-neutral specification while using
//! Rust naming and error handling. Rust has no inheritance, so the class-family
//! hierarchy used by other flavors is represented by cloneable handles,
//! trait-based contracts, and shared lifecycle/message cores.
#![deny(missing_docs)]

use serde::{Deserialize, Serialize};
use std::cell::Cell;
use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::fmt;
use std::future::Future;
use std::hash::Hash;
use std::panic::{catch_unwind, resume_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, OnceLock, Weak};
use std::task::{Context, Poll};
use std::thread::{self, ThreadId};

mod aggregate_change_stream;
mod async_resource_vm;
mod async_value;
pub use aggregate_change_stream::{
    AggregateChange, AggregateChangeObservable, AggregateChangeReason, AggregateChangeStream,
    AggregateChangeSubscription, AggregateObserveOptions, ObservableMembershipSource,
    ObservablePropertySource,
};
pub use async_resource_vm::{
    AsyncResourceRetention, AsyncResourceState, AsyncResourceStatus, AsyncResourceVm,
};
pub use async_value::AsyncValue;

/// Version of the compiled Rust package.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
/// Minimum language-neutral VMx specification version implemented by this package.
pub const MIN_SPEC_VERSION: &str = "3.22.0";

mod runtime;
pub use runtime::*;
pub(crate) use runtime::{
    begin_membership_transaction, begin_parent_transfer, evaluate_command_predicate,
    finish_with_first_error, lock, next_id, retain_first_error, wait, ComponentCore,
    MembershipDisposeDisposition, MembershipTransactionControl, MembershipTransactionGuard,
    ModelHint, ParentRegistration, ParentTransfer, HIERARCHY_TOPOLOGY_GATE,
};

mod components;
pub use components::{ComponentVm, ComponentVmBuilder, ComponentVmOptions, ReadonlyComponentVm};

mod commands;
pub use commands::{
    AsyncRelayCommand, AsyncRelayCommandBuilder, CancellationToken, Command, CommandOf,
    CompositeCommand, ConfirmationDecoratorCommand, DecoratorCommand, RelayCommand,
    RelayCommandBuilder, RelayCommandOf,
};

mod collections;
pub use collections::{
    KeyedServicedObservableCollection, ObservableDictionary, ObservableList,
    ObservableMultiDictionary, ServicedObservableCollection,
};

mod composites;
pub use composites::{
    CompositeVm, CompositeVmBuilder, CompositeVmOptions, FilteredCompositeVm, FilteredCursorPolicy,
    ModeledCompositeVm, ModeledCompositeVmBuilder, SelectableVmCollection, VmCollection,
};

mod groups;
pub use groups::{GroupVm, GroupVmBuilder, GroupVmOptions};

mod paged_composition;
pub use paged_composition::PagedComposition;

mod searchable_state;
pub use searchable_state::SearchableState;

mod modeled_crud;
pub use modeled_crud::ModeledCrudCommands;

mod derived_property;
pub use derived_property::DerivedProperty;

mod notifications;
pub use notifications::{
    make_confirm, Notification, NotificationHub, NotificationReaction, NotificationType,
    NotificationWaiter, NullNotificationHub,
};
mod dialogs;
pub use dialogs::{
    DialogService, FileFilter, Localizer, NotificationSeverity, NullDialogService, NullLocalizer,
};
mod forms;
pub use forms::{FormVm, FormVmBuilder};

mod discriminator;
pub use discriminator::DiscriminatorVm;

mod hierarchical;
pub use hierarchical::{
    find, walk, walk_expanded, BatchAttachRejection, BatchAttachRejectionReason, BatchAttachResult,
    HierarchicalVm, HierarchicalVmBuilder, MissingParentPolicy,
};
/// Returns the embedded language-neutral lifecycle transition fixture.
pub fn lifecycle_transition_fixture() -> &'static str {
    include_str!("fixtures/lifecycle-transitions.json")
}

mod capabilities;
pub use capabilities::{
    Approvable, Cancelable, Closable, Collapsible, Constructable, CurrentDeletable,
    CurrentUpdatable, Deletable, Deselectable, Destructable, Expandable, ExpandableState,
    ExpansionTogglable, Filterable, Managable, NewCreatable, Pageable, Reconstructable, Savable,
    Searchable, Selectable, SelectionTogglable, Updatable,
};
mod aggregates;
pub use aggregates::{
    AggregateVm, AggregateVm1, AggregateVm1Builder, AggregateVm2, AggregateVm2Builder,
    AggregateVm3, AggregateVm3Builder, AggregateVm4, AggregateVm4Builder, AggregateVm5,
    AggregateVm5Builder, AggregateVm6, AggregateVm6Builder,
};
mod forwarding;
pub use forwarding::{ForwardingComponentVm, ForwardingCompositeVm};

mod token_paging;
pub use token_paging::TokenPagedComposition;

mod specialized_vms;
pub use specialized_vms::{ConfirmationVm, ModalVm, NotificationVm};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn component_constructs_and_disposes() {
        let vm = ComponentVm::new("test");
        vm.construct().unwrap();
        assert_eq!(vm.status(), ConstructionStatus::Constructed);
        vm.dispose().unwrap();
        assert_eq!(vm.status(), ConstructionStatus::Disposed);
    }

    #[test]
    fn failed_dispose_hook_still_completes_property_changed() {
        let vm = ComponentVm::new("test");
        let completions = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&completions);
        let _subscription = vm.property_changed().subscribe_with_completion(
            |_| {},
            move || {
                observed.fetch_add(1, Ordering::SeqCst);
            },
        );
        vm.on_dispose(|| Err(VmxError::Other("boom".to_string())));

        assert!(vm.dispose().is_err());

        assert_eq!(vm.status(), ConstructionStatus::Disposed);
        assert_eq!(completions.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn form_dispose_completes_component_property_changed() {
        let form = FormVm::new("form", 1);
        let completions = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&completions);
        let _subscription = form.component.property_changed().subscribe_with_completion(
            |_| {},
            move || {
                observed.fetch_add(1, Ordering::SeqCst);
            },
        );

        form.dispose();

        assert_eq!(completions.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn message_hub_is_hot_and_resilient() {
        let hub = MessageHub::new();
        hub.send(Message::Custom {
            sender_id: 1,
            sender_name: "sender".to_string(),
            name: "before".to_string(),
        });
        let seen = Arc::new(Mutex::new(Vec::new()));
        let seen_clone = seen.clone();
        let _sub = hub.subscribe(move |message| lock(&seen_clone).push(message.clone()));
        hub.send(Message::Custom {
            sender_id: 1,
            sender_name: "sender".to_string(),
            name: "after".to_string(),
        });
        assert_eq!(lock(&seen).len(), 1);
    }
}
