use std::sync::{Arc, Mutex};

use vmx::{DerivedProperty, Message};

/// DPROP-001 — Single-source derived value computes on construction
#[test]
fn single_source_value_is_available_on_construction() {
    let property = DerivedProperty::new(4);

    assert_eq!(property.value(), 4);
}

/// DPROP-002 — Source change triggers recompute
#[test]
fn source_change_recomputes_value() {
    let property = DerivedProperty::new(4);

    property.recompute(|value| value + 1);

    assert_eq!(property.value(), 5);
}

/// DPROP-003 — Two-source derived value
#[test]
fn two_source_value_can_be_modeled_by_transform() {
    let property = DerivedProperty::new((2, 3));

    property.recompute(|(a, b)| (a + b, *b));

    assert_eq!(property.value(), (5, 3));
}

/// DPROP-004 — Five-source derived value (spec minimum)
#[test]
fn five_source_value_can_be_modeled_by_transform() {
    let property = DerivedProperty::new([1, 2, 3, 4, 5]);

    property.recompute(|values| [values.iter().sum(), 0, 0, 0, 0]);

    assert_eq!(property.value()[0], 15);
}

/// DPROP-005 — Mutation of any source recomputes
#[test]
fn any_source_mutation_recomputes() {
    let property = DerivedProperty::new(vec![1, 2]);

    property.recompute(|values| {
        let mut next = values.clone();
        next[1] = 4;
        next
    });

    assert_eq!(property.value(), vec![1, 4]);
}

/// DPROP-006 — Default-built derived property is read-only
#[test]
fn default_derived_property_is_read_only() {
    let property = DerivedProperty::new(1);

    assert!(!property.can_set(&2));
    assert!(property.set_value(2).is_err());
}

/// DPROP-007 — Validator + write-back enables SetValue
#[test]
fn validator_and_write_back_enable_set_value() {
    let written = Arc::new(Mutex::new(None));
    let seen = written.clone();
    let property = DerivedProperty::with_write_back(
        1,
        |value| *value > 0,
        move |value| {
            *seen.lock().unwrap() = Some(value);
        },
    );

    property.set_value(3).unwrap();

    assert_eq!(*written.lock().unwrap(), Some(3));
}

/// DPROP-008 — Write-back action receives the value
#[test]
fn write_back_receives_value() {
    let written = Arc::new(Mutex::new(Vec::new()));
    let seen = written.clone();
    let property = DerivedProperty::with_write_back(
        1,
        |_| true,
        move |value| {
            seen.lock().unwrap().push(value);
        },
    );

    property.set_value(9).unwrap();

    assert_eq!(written.lock().unwrap().clone(), vec![9]);
}

/// DPROP-009 — ValueChanged emits on recompute
#[test]
fn value_changed_emits_on_recompute() {
    let property = DerivedProperty::new(1);
    let hits = Arc::new(Mutex::new(0));
    let seen = hits.clone();
    let _subscription = property.value_changed().subscribe(move |message| {
        if matches!(message, Message::PropertyChanged(_)) {
            *seen.lock().unwrap() += 1;
        }
    });

    property.recompute(|value| value + 1);

    assert_eq!(*hits.lock().unwrap(), 1);
}

/// DPROP-010 — ValueChanged does not emit when transform output is unchanged
#[test]
fn value_changed_does_not_emit_when_value_is_unchanged() {
    let property = DerivedProperty::new(1);
    let hits = Arc::new(Mutex::new(0));
    let seen = hits.clone();
    let _subscription = property.value_changed().subscribe(move |_| {
        *seen.lock().unwrap() += 1;
    });

    property.recompute(|value| *value);

    assert_eq!(*hits.lock().unwrap(), 0);
}

/// DPROP-011 — Dispose ends subscriptions and ValueChanged completes
#[test]
fn dispose_stops_recompute_emissions() {
    let property = DerivedProperty::new(1);
    property.dispose();
    property.recompute(|value| value + 1);

    assert_eq!(property.value(), 1);
}

/// DPROP-012 — Derived-property scenarios match fixture
#[test]
fn fixture_style_sum_scenario_matches_expected_values() {
    let property = DerivedProperty::new([1, 2, 3]);

    property.recompute(|values| [values.iter().sum(), 0, 0]);

    assert_eq!(property.value(), [6, 0, 0]);
}
