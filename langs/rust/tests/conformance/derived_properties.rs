use std::sync::{mpsc, Arc, Barrier, Mutex};

use serde::Deserialize;
use serde_json::Value;
use vmx::{DerivedProperty, ExpandableState, ValueStream};

#[derive(Deserialize)]
struct DerivedPropertyFixture {
    scenarios: Vec<DerivedPropertyScenario>,
}

#[derive(Deserialize)]
struct DerivedPropertyScenario {
    name: String,
    sources_initial: Vec<Value>,
    transform: String,
    mutations: Vec<(usize, Value)>,
    expected_values: Vec<Value>,
}

fn apply_transform(transform: &str, sources: &[Value]) -> Value {
    match transform {
        "sum" => sources
            .iter()
            .map(|value| value.as_i64().expect("sum source must be an integer"))
            .sum::<i64>()
            .into(),
        "concat" => sources
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| value.to_string())
            })
            .collect::<String>()
            .into(),
        unknown => panic!("unknown derived-property fixture transform: {unknown}"),
    }
}

/// DPROP-001 — Single-source derived value computes on construction
#[test]
fn single_source_value_is_available_on_construction() {
    let source = ValueStream::new(2);
    let property = DerivedProperty::from_one(source, |value| value * 2);

    assert_eq!(property.value(), 4);
}

/// DPROP-002 — Source change triggers recompute
#[test]
fn source_change_recomputes_value() {
    let source = ValueStream::new(2);
    let property = DerivedProperty::from_one(source.clone(), |value| value * 2);

    source.send(3);

    assert_eq!(property.value(), 6);
}

/// DPROP-003 — Two-source derived value
#[test]
fn two_source_value_can_be_modeled_by_transform() {
    let left = ValueStream::new(3);
    let right = ValueStream::new(4);
    let property =
        DerivedProperty::from_two(left.clone(), right.clone(), |left, right| left + right);

    assert_eq!(property.value(), 7);

    right.send(6);

    assert_eq!(property.value(), 9);
}

/// DPROP-004 — Five-source derived value (spec minimum)
#[test]
fn five_source_value_can_be_modeled_by_transform() {
    let property = DerivedProperty::from_five(
        ValueStream::new(1),
        ValueStream::new(2),
        ValueStream::new(3),
        ValueStream::new(4),
        ValueStream::new(5),
        |first, second, third, fourth, fifth| first + second + third + fourth + fifth,
    );

    assert_eq!(property.value(), 15);
}

/// DPROP-005 — Mutation of any source recomputes
#[test]
fn any_source_mutation_recomputes() {
    let sources = (1..=5).map(ValueStream::new).collect::<Vec<_>>();
    let property =
        DerivedProperty::from_sources(sources.clone(), |values| values.into_iter().sum::<i32>());

    sources[2].send(30);

    assert_eq!(property.value(), 42);
}

#[test]
fn older_multi_source_transform_cannot_overwrite_a_newer_snapshot() {
    let left = ValueStream::new(0);
    let right = ValueStream::new(0);
    let older_transform_release = Arc::new(Barrier::new(2));
    let (older_transform_entered_tx, older_transform_entered_rx) = mpsc::channel();
    let release = older_transform_release.clone();
    let property = DerivedProperty::from_two(
        left.clone(),
        right.clone(),
        move |left_value, right_value| {
            if (left_value, right_value) == (1, 0) {
                older_transform_entered_tx.send(()).unwrap();
                release.wait();
            }
            left_value + right_value
        },
    );

    let older_sender = std::thread::spawn(move || left.send(1));
    older_transform_entered_rx.recv().unwrap();

    right.send(1);
    assert_eq!(property.value(), 2);

    older_transform_release.wait();
    older_sender.join().unwrap();

    assert_eq!(property.value(), 2);
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
    let source = ValueStream::new(1);
    let written = Arc::new(Mutex::new(Vec::new()));
    let seen = written.clone();
    let property = DerivedProperty::from_sources_with_write_back(
        vec![source],
        |values| values[0],
        |value| *value > 0,
        move |value| {
            seen.lock().unwrap().push(value);
        },
    );

    property.set_value(5).unwrap();
    assert_eq!(*written.lock().unwrap(), vec![5]);

    assert!(!property.can_set(&-1));
    assert!(property.set_value(-1).is_err());
    assert_eq!(
        *written.lock().unwrap(),
        vec![5],
        "a rejected value is not written back"
    );
}

/// DPROP-008 — Write-back action receives the value
#[test]
fn write_back_receives_value() {
    let source = ValueStream::new(1);
    let written = Arc::new(Mutex::new(Vec::new()));
    let seen = written.clone();
    let property = DerivedProperty::from_sources_with_write_back(
        vec![source],
        |values| values[0],
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
    let source = ValueStream::new(1);
    let property = DerivedProperty::from_one(source.clone(), |value| value);
    let values = Arc::new(Mutex::new(Vec::new()));
    let seen = values.clone();
    let _subscription = property
        .value_changes()
        .subscribe(move |value| seen.lock().unwrap().push(value));

    source.send(2);

    assert_eq!(*values.lock().unwrap(), vec![2]);
}

/// DPROP-010 — ValueChanged does not emit when transform output is unchanged
#[test]
fn value_changed_does_not_emit_when_value_is_unchanged() {
    let s1 = ValueStream::new(5);
    let s2 = ValueStream::new(5);
    let property = DerivedProperty::from_two(s1.clone(), s2.clone(), |a, b| a + b);
    assert_eq!(property.value(), 10);
    let values = Arc::new(Mutex::new(Vec::new()));
    let seen = values.clone();
    let _subscription = property
        .value_changes()
        .subscribe(move |value| seen.lock().unwrap().push(value));

    s1.send(3);
    s2.send(7);

    assert_eq!(*values.lock().unwrap(), vec![8, 10]);

    s1.send(3);

    assert_eq!(property.value(), 10);
    assert_eq!(
        *values.lock().unwrap(),
        vec![8, 10],
        "an unchanged transform output must not emit"
    );
}

/// DPROP-011 — Dispose ends subscriptions and ValueChanged completes
#[test]
fn dispose_stops_recompute_emissions() {
    let source = ValueStream::new(1);
    let property = DerivedProperty::from_one(source.clone(), |value| value);
    let completed = Arc::new(Mutex::new(0));
    let observed = completed.clone();
    let _subscription = property
        .value_changes()
        .subscribe_with_completion(|_| {}, move || *observed.lock().unwrap() += 1);
    property.dispose();
    source.send(2);

    assert_eq!(property.value(), 1);
    assert_eq!(*completed.lock().unwrap(), 1);
}

/// DISP-005 — reactive helper disposal completes once and retains the last value
#[test]
fn repeated_derived_property_dispose_is_inert_and_retains_value() {
    let source = ValueStream::new(7);
    let property = DerivedProperty::from_one(source.clone(), |value| value);
    let values = Arc::new(Mutex::new(Vec::new()));
    let completions = Arc::new(Mutex::new(0));
    let seen_values = values.clone();
    let seen_completions = completions.clone();
    let _subscription = property.value_changes().subscribe_with_completion(
        move |value| seen_values.lock().unwrap().push(value),
        move || *seen_completions.lock().unwrap() += 1,
    );
    property.dispose();
    property.dispose();
    source.send(8);

    assert_eq!(*completions.lock().unwrap(), 1, "completes at most once");
    assert!(
        values.lock().unwrap().is_empty(),
        "no post-dispose value is emitted"
    );
    assert_eq!(property.value(), 7);

    let expansion = ExpandableState::new();
    expansion.dispose();
    expansion.expand();
    assert!(!expansion.is_expanded());
    expansion.toggle_expansion();
    assert!(!expansion.is_expanded());

    let expanded = ExpandableState::new_expanded();
    expanded.dispose();
    expanded.collapse();
    assert!(expanded.is_expanded());
    expanded.toggle_expansion();
    assert!(expanded.is_expanded());
}

/// DPROP-012 — Derived-property scenarios match fixture
#[test]
fn all_fixture_scenarios_match_expected_values() {
    let fixture: DerivedPropertyFixture =
        serde_json::from_str(include_str!("../../src/fixtures/derived-properties.json"))
            .expect("derived-property fixture must be valid JSON");
    assert!(
        !fixture.scenarios.is_empty(),
        "derived-property fixture must contain at least one scenario"
    );

    for scenario in fixture.scenarios {
        assert_eq!(
            scenario.expected_values.len(),
            scenario.mutations.len() + 1,
            "scenario {} must cover its initial value and every mutation",
            scenario.name
        );
        let sources = scenario
            .sources_initial
            .into_iter()
            .map(ValueStream::new)
            .collect::<Vec<_>>();
        let transform_name = scenario.transform.clone();
        let property = DerivedProperty::from_sources(sources.clone(), move |values| {
            apply_transform(&transform_name, &values)
        });
        assert_eq!(
            property.value(),
            scenario.expected_values[0],
            "scenario {} initial value",
            scenario.name
        );

        for ((index, value), expected) in scenario
            .mutations
            .into_iter()
            .zip(scenario.expected_values.into_iter().skip(1))
        {
            sources[index].send(value);
            assert_eq!(
                property.value(),
                expected,
                "scenario {} mutation",
                scenario.name
            );
        }
    }
}

#[test]
fn a_recompute_transform_may_read_the_property() {
    let property = Arc::new(vmx::DerivedProperty::new(2));
    let reader = property.clone();
    let (done, finished) = std::sync::mpsc::channel();

    std::thread::spawn(move || {
        property.recompute(move |value| reader.value() + *value);
        let _ = done.send(property.value());
    });

    assert_eq!(
        finished.recv_timeout(std::time::Duration::from_secs(3)),
        Ok(4),
        "recompute must not hold the value lock while the transform runs"
    );
}
