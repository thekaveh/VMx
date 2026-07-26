//! Opt-in capability traits and reusable expansion state.
//!
//! Spec: `spec/14-capabilities.md`; ADR-0010, ADR-0057.

use super::{
    lock, Arc, AtomicBool, ConstructionStatus, Message, MessageHub, Mutex, Ordering, VmNode,
};

/// Opt-in selection capability.
pub trait Selectable {
    /// Reports whether selection is currently admitted.
    fn can_select(&self) -> bool;
    /// Selects the receiver.
    fn select(&self);
}

/// Opt-in deselection capability.
pub trait Deselectable {
    /// Reports whether deselection is currently admitted.
    fn can_deselect(&self) -> bool;
    /// Deselects the receiver.
    fn deselect(&self);
}

/// Opt-in selection-toggle capability.
pub trait SelectionTogglable {
    /// Reports whether selection may be toggled.
    fn can_toggle_selection(&self) -> bool;
    /// Toggles the receiver's selection state.
    fn toggle_selection(&self);
}

/// Opt-in expansion capability.
pub trait Expandable {
    /// Reports whether expansion is currently admitted.
    fn can_expand(&self) -> bool;
    /// Reports whether the receiver is expanded.
    fn is_expanded(&self) -> bool;
    /// Expands the receiver.
    fn expand(&self);
}

/// Opt-in collapse capability.
pub trait Collapsible {
    /// Reports whether collapse is currently admitted.
    fn can_collapse(&self) -> bool;
    /// Collapses the receiver.
    fn collapse(&self);
}

/// Opt-in expansion-toggle capability.
pub trait ExpansionTogglable {
    /// Reports whether expansion may be toggled.
    fn can_toggle_expansion(&self) -> bool;
    /// Toggles the receiver's expansion state.
    fn toggle_expansion(&self);
}

/// Opt-in close capability.
pub trait Closable {
    /// Reports whether close is currently admitted.
    fn can_close(&self) -> bool;
    /// Closes the receiver.
    fn close(&self);
}

/// Opt-in search capability.
pub trait Searchable {
    /// Reports whether search is currently admitted.
    fn can_search(&self) -> bool;
    /// Returns the current search term.
    fn search_term(&self) -> String;
    /// Replaces the current search term.
    fn set_search_term(&self, term: String);
    /// Executes the current search.
    fn search(&self);
}

/// Opt-in approval capability.
pub trait Approvable {
    /// Reports whether approval is currently admitted.
    fn can_approve(&self) -> bool;
    /// Approves the receiver's current state.
    fn approve(&self);
}

/// Opt-in cancellation capability.
pub trait Cancelable {
    /// Reports whether cancellation is currently admitted.
    fn can_cancel(&self) -> bool;
    /// Cancels the receiver's current operation.
    fn cancel(&self);
}

/// Opt-in capability for saving typed items.
pub trait Savable<T> {
    /// Reports whether `item` may be saved.
    fn can_save(&self, item: &T) -> bool;
    /// Saves `item`.
    fn save(&self, item: T);
}

/// Opt-in capability for managing typed items.
pub trait Managable<T> {
    /// Reports whether `item` may be managed.
    fn can_manage(&self, item: &T) -> bool;
    /// Manages `item`.
    fn manage(&self, item: T);
}

/// Opt-in capability for creating a new item.
pub trait NewCreatable {
    /// Reports whether creation is currently admitted.
    fn can_create_new(&self) -> bool;
    /// Creates a new item.
    fn create_new(&self);
}

/// Opt-in capability for deleting typed items.
pub trait Deletable<T> {
    /// Reports whether `item` may be deleted.
    fn can_delete(&self, item: &T) -> bool;
    /// Deletes `item`.
    fn delete(&self, item: T);
}

/// Opt-in capability for updating typed items.
pub trait Updatable<T> {
    /// Reports whether `item` may be updated.
    fn can_update(&self, item: &T) -> bool;
    /// Updates `item`.
    fn update(&self, item: T);
}

/// Opt-in capability for deleting the current item.
pub trait CurrentDeletable {
    /// Reports whether the current item may be deleted.
    fn can_delete_current(&self) -> bool;
    /// Deletes the current item.
    fn delete_current(&self);
}

/// Opt-in capability for updating the current item.
pub trait CurrentUpdatable {
    /// Reports whether the current item may be updated.
    fn can_update_current(&self) -> bool;
    /// Updates the current item.
    fn update_current(&self);
}

/// Opt-in construction capability.
pub trait Constructable {
    /// Reports whether construction is currently admitted.
    fn can_construct(&self) -> bool;
    /// Constructs the receiver.
    fn construct(&self);
}

/// Opt-in destruction capability.
pub trait Destructable {
    /// Reports whether destruction is currently admitted.
    fn can_destruct(&self) -> bool;
    /// Destructs the receiver.
    fn destruct(&self);
}

/// Opt-in reconstruction capability.
pub trait Reconstructable {
    /// Reports whether reconstruction is currently admitted.
    fn can_reconstruct(&self) -> bool;
    /// Reconstructs the receiver.
    fn reconstruct(&self);
}

/// A shared, thread-safe predicate stored by [`Filterable`].
pub type FilterPredicate<T> = Arc<dyn Fn(&T) -> bool + Send + Sync>;

/// Opt-in filtering capability over typed items.
///
/// Core VM types do not implement filtering unless a wrapper opts in:
///
/// ```compile_fail
/// use vmx::{ComponentVm, Filterable};
///
/// fn requires_filterable<T: Filterable<&'static str>>(_: &T) {}
/// requires_filterable(&ComponentVm::new("component"));
/// ```
pub trait Filterable<T> {
    /// Returns the current predicate, or `None` when filtering is cleared.
    fn filter(&self) -> Option<FilterPredicate<T>>;
    /// Replaces or clears the current predicate.
    fn set_filter(&mut self, filter: Option<FilterPredicate<T>>);
    /// Reports whether filtering is currently admitted.
    fn can_filter(&self) -> bool;
}

/// Opt-in finite-page navigation capability.
pub trait Pageable {
    /// Returns the maximum number of items exposed by one page.
    fn page_size(&self) -> usize;
    /// Changes the maximum number of items exposed by one page.
    fn set_page_size(&self, page_size: usize);
    /// Returns the current zero-based page index.
    fn current_page_index(&self) -> usize;
    /// Selects a zero-based page index, clamped to the available range.
    fn set_current_page_index(&self, index: usize);
    /// Returns the number of available pages.
    fn page_count(&self) -> usize;
    /// Reports whether finite paging is enabled.
    fn is_paging_enabled(&self) -> bool;
    /// Moves to the first page.
    fn move_to_first_page(&self);
    /// Moves to the previous page.
    fn move_to_previous_page(&self);
    /// Moves to the next page.
    fn move_to_next_page(&self);
    /// Moves to the last page.
    fn move_to_last_page(&self);
}

#[derive(Clone, Default)]
/// Reusable expansion state with a hot change-notification hub.
pub struct ExpandableState {
    expanded: Arc<Mutex<bool>>,
    expanded_changed: MessageHub,
    disposed: Arc<AtomicBool>,
}

impl ExpandableState {
    /// Creates collapsed expansion state.
    pub fn new() -> Self {
        Self::default()
    }

    /// Creates expansion state with the requested initial value.
    pub fn with_initial(initially_expanded: bool) -> Self {
        Self {
            expanded: Arc::new(Mutex::new(initially_expanded)),
            ..Self::default()
        }
    }

    /// Creates expanded expansion state.
    pub fn new_expanded() -> Self {
        Self::with_initial(true)
    }

    /// Reports whether the state is expanded.
    pub fn is_expanded(&self) -> bool {
        *lock(&self.expanded)
    }

    /// Reports whether expansion would change the state.
    pub fn can_expand(&self) -> bool {
        !self.is_expanded()
    }

    /// Reports whether collapse would change the state.
    pub fn can_collapse(&self) -> bool {
        self.is_expanded()
    }

    /// Expands the state and publishes one effective change.
    pub fn expand(&self) {
        self.set_expanded(true);
    }

    /// Collapses the state and publishes one effective change.
    pub fn collapse(&self) {
        self.set_expanded(false);
    }

    /// Toggles the expansion state.
    pub fn toggle_expansion(&self) {
        self.set_expanded(!self.is_expanded());
    }

    /// Returns the hub that publishes effective expansion changes.
    pub fn expanded_changed(&self) -> MessageHub {
        self.expanded_changed.clone()
    }

    /// Disposes the owned change hub and makes later mutations inert.
    ///
    /// Disposal is idempotent.
    pub fn dispose(&self) {
        if self.disposed.swap(true, Ordering::AcqRel) {
            return;
        }
        self.expanded_changed.dispose();
    }

    fn set_expanded(&self, expanded: bool) {
        if self.disposed.load(Ordering::Acquire) {
            return;
        }
        let changed = {
            let mut current = lock(&self.expanded);
            if *current == expanded {
                false
            } else {
                *current = expanded;
                true
            }
        };
        if changed {
            self.expanded_changed.send(Message::Custom {
                sender_id: 0,
                sender_name: "ExpandableState".to_string(),
                name: expanded.to_string(),
            });
        }
    }
}

impl Expandable for ExpandableState {
    fn can_expand(&self) -> bool {
        ExpandableState::can_expand(self)
    }

    fn is_expanded(&self) -> bool {
        ExpandableState::is_expanded(self)
    }

    fn expand(&self) {
        ExpandableState::expand(self);
    }
}

impl Collapsible for ExpandableState {
    fn can_collapse(&self) -> bool {
        ExpandableState::can_collapse(self)
    }

    fn collapse(&self) {
        ExpandableState::collapse(self);
    }
}

impl ExpansionTogglable for ExpandableState {
    fn can_toggle_expansion(&self) -> bool {
        true
    }

    fn toggle_expansion(&self) {
        ExpandableState::toggle_expansion(self);
    }
}

impl<T: VmNode> Constructable for T {
    fn can_construct(&self) -> bool {
        matches!(
            self.status(),
            ConstructionStatus::Destructed | ConstructionStatus::Constructed
        )
    }

    fn construct(&self) {
        let _ = VmNode::construct(self);
    }
}

impl<T: VmNode> Destructable for T {
    fn can_destruct(&self) -> bool {
        matches!(
            self.status(),
            ConstructionStatus::Constructed | ConstructionStatus::Destructed
        )
    }

    fn destruct(&self) {
        let _ = VmNode::destruct(self);
    }
}

impl<T: VmNode> Reconstructable for T {
    fn can_reconstruct(&self) -> bool {
        self.status() == ConstructionStatus::Constructed
    }

    fn reconstruct(&self) {
        if VmNode::destruct(self).is_ok() {
            let _ = VmNode::construct(self);
        }
    }
}
