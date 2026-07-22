use vmx::{
    Approvable, Cancelable, Closable, Collapsible, Constructable, CurrentDeletable,
    CurrentUpdatable, Deletable, Deselectable, Destructable, Expandable, ExpansionTogglable,
    Filterable, Managable, NewCreatable, Pageable, Reconstructable, Savable, Searchable,
    Selectable, SelectionTogglable, Updatable,
};

#[derive(Default)]
struct Fixture {
    calls: usize,
    text: String,
}

impl Selectable for Fixture {
    fn can_select(&self) -> bool {
        true
    }
    fn select(&self) {}
}

impl Deselectable for Fixture {
    fn can_deselect(&self) -> bool {
        true
    }
    fn deselect(&self) {}
}

impl SelectionTogglable for Fixture {
    fn can_toggle_selection(&self) -> bool {
        true
    }
    fn toggle_selection(&self) {}
}

impl Expandable for Fixture {
    fn can_expand(&self) -> bool {
        true
    }
    fn expand(&self) {}
}

impl Collapsible for Fixture {
    fn can_collapse(&self) -> bool {
        true
    }
    fn collapse(&self) {}
}

impl ExpansionTogglable for Fixture {
    fn can_toggle_expansion(&self) -> bool {
        true
    }
    fn toggle_expansion(&self) {}
}

impl Closable for Fixture {
    fn can_close(&self) -> bool {
        true
    }
    fn close(&self) {}
}

impl Searchable for Fixture {
    fn can_search(&self) -> bool {
        true
    }
    fn search_term(&self) -> String {
        self.text.clone()
    }
    fn search(&self) {}
}

impl Approvable for Fixture {
    fn can_approve(&self) -> bool {
        true
    }
    fn approve(&self) {}
}

impl Cancelable for Fixture {
    fn can_cancel(&self) -> bool {
        true
    }
    fn cancel(&self) {}
}

impl Savable<&'static str> for Fixture {
    fn can_save(&self, _item: &&'static str) -> bool {
        true
    }
    fn save(&self, _item: &'static str) {}
}

impl Managable<&'static str> for Fixture {
    fn can_manage(&self, _item: &&'static str) -> bool {
        true
    }
    fn manage(&self, _item: &'static str) {}
}

impl NewCreatable for Fixture {
    fn can_create_new(&self) -> bool {
        true
    }
    fn create_new(&self) {}
}

impl Deletable<&'static str> for Fixture {
    fn can_delete(&self, _item: &&'static str) -> bool {
        true
    }
    fn delete(&self, _item: &'static str) {}
}

impl Updatable<&'static str> for Fixture {
    fn can_update(&self, _item: &&'static str) -> bool {
        true
    }
    fn update(&self, _item: &'static str) {}
}

impl CurrentDeletable for Fixture {
    fn can_delete_current(&self) -> bool {
        true
    }
    fn delete_current(&self) {}
}

impl CurrentUpdatable for Fixture {
    fn can_update_current(&self) -> bool {
        true
    }
    fn update_current(&self) {}
}

impl Constructable for Fixture {
    fn can_construct(&self) -> bool {
        true
    }
    fn construct(&self) {}
}

impl Destructable for Fixture {
    fn can_destruct(&self) -> bool {
        true
    }
    fn destruct(&self) {}
}

impl Reconstructable for Fixture {
    fn can_reconstruct(&self) -> bool {
        true
    }
    fn reconstruct(&self) {}
}

impl Filterable<&'static str> for Fixture {
    fn filter_term(&self) -> String {
        self.text.clone()
    }
    fn set_filter_term(&mut self, term: impl Into<String>) {
        self.text = term.into();
    }
    fn accepts(&self, item: &&'static str) -> bool {
        item.contains(&self.text)
    }
}

impl Pageable for Fixture {
    fn page_index(&self) -> usize {
        self.calls
    }
    fn page_count(&self) -> usize {
        3
    }
    fn set_page_index(&mut self, index: usize) {
        self.calls = index.min(self.page_count().saturating_sub(1));
    }
}

/// CAP-001 — ISelectable contract
#[test]
fn selectable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_select());
    fixture.select();
}

/// CAP-002 — IDeselectable contract
#[test]
fn deselectable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_deselect());
    fixture.deselect();
}

/// CAP-003 — ISelectionTogglable contract
#[test]
fn selection_togglable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_toggle_selection());
    fixture.toggle_selection();
}

/// CAP-004 — IExpandable contract
#[test]
fn expandable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_expand());
    fixture.expand();
}

/// CAP-005 — ICollapsible contract
#[test]
fn collapsible_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_collapse());
    fixture.collapse();
}

/// CAP-006 — IExpansionTogglable contract
#[test]
fn expansion_togglable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_toggle_expansion());
    fixture.toggle_expansion();
}

/// CAP-007 — IClosable contract
#[test]
fn closable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_close());
    fixture.close();
}

/// CAP-008 — ISearchable contract
#[test]
fn searchable_contract() {
    let fixture = Fixture {
        text: "abc".to_string(),
        ..Fixture::default()
    };
    assert!(fixture.can_search());
    assert_eq!(fixture.search_term(), "abc");
    fixture.search();
}

/// CAP-009 — IApprovable contract
#[test]
fn approvable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_approve());
    fixture.approve();
}

/// CAP-010 — ICancelable contract
#[test]
fn cancelable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_cancel());
    fixture.cancel();
}

/// CAP-011 — ISavable<T> contract
#[test]
fn savable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_save(&"a"));
    fixture.save("a");
}

/// CAP-012 — IManagable<T> contract
#[test]
fn managable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_manage(&"x"));
    fixture.manage("x");
}

/// CAP-013 — INewCreatable contract
#[test]
fn new_creatable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_create_new());
    fixture.create_new();
}

/// CAP-014 — IDeletable<T> contract
#[test]
fn deletable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_delete(&"a"));
    fixture.delete("a");
}

/// CAP-015 — IUpdatable<T> contract
#[test]
fn updatable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_update(&"a"));
    fixture.update("a");
}

/// CAP-016 — ICurrentDeletable contract
#[test]
fn current_deletable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_delete_current());
    fixture.delete_current();
}

/// CAP-017 — ICurrentUpdatable contract
#[test]
fn current_updatable_contract() {
    let fixture = Fixture::default();
    assert!(fixture.can_update_current());
    fixture.update_current();
}

/// CAP-018 — Lifecycle capability set
#[test]
fn lifecycle_capability_set() {
    let fixture = Fixture::default();
    assert!(fixture.can_construct());
    assert!(fixture.can_destruct());
    assert!(fixture.can_reconstruct());
}

/// CAP-019 — A single VM may implement multiple capabilities
#[test]
fn single_type_may_implement_multiple_capabilities() {
    let fixture = Fixture::default();
    assert!(fixture.can_select());
    assert!(fixture.can_expand());
    assert!(fixture.can_close());
    assert!(fixture.can_approve());
    assert!(fixture.can_cancel());
}

/// CAP-020 — Core VM types do NOT implement non-baseline capabilities by default
#[test]
fn core_vm_types_do_not_implement_non_baseline_capabilities_by_default() {
    let component = vmx::ComponentVm::new("bare");
    assert!(!component.is_selected());

    fn requires_baseline_lifecycle<T: Constructable + Destructable + Reconstructable>(_: &T) {}
    requires_baseline_lifecycle(&component);
    assert!(Constructable::can_construct(&component));
    assert!(Destructable::can_destruct(&component));
    component.construct().unwrap();
    assert!(Constructable::can_construct(&component));
    assert!(Destructable::can_destruct(&component));
}

/// CAP-021 — `IFilterable<TItem>` capability contract surface and opt-in behavior
#[test]
fn filterable_contract() {
    let mut fixture = Fixture::default();
    fixture.set_filter_term("a");
    assert!(fixture.accepts(&"alpha"));
    assert!(!fixture.accepts(&"rhythm"));
}

/// CAP-022 — `IPageable` capability contract surface and clamping/navigation behavior
#[test]
fn pageable_contract() {
    let mut fixture = Fixture::default();
    fixture.set_page_index(99);
    assert_eq!(fixture.page_index(), 2);
}
