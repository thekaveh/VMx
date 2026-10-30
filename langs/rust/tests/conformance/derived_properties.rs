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
    source.send(3);

    assert_eq!(*values.lock().unwrap(), vec![2, 3]);
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

/// Records every value that `value_changes` publishes.
fn record_value_changes(
    property: &DerivedProperty<i32>,
) -> (Arc<Mutex<Vec<i32>>>, vmx::ValueSubscription) {
    let values = Arc::new(Mutex::new(Vec::new()));
    let seen = values.clone();
    let subscription = property
        .value_changes()
        .subscribe(move |value| seen.lock().unwrap().push(value));
    (values, subscription)
}

/// Starts `recompute(transform)` on a worker whose transform pauses after it
/// receives its snapshot. Returns the snapshot, the release and the worker.
fn paused_recompute(
    property: &DerivedProperty<i32>,
    transform: fn(i32) -> i32,
) -> (i32, mpsc::Sender<()>, std::thread::JoinHandle<()>) {
    let (snapshot_tx, snapshot_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel::<()>();
    let worker = {
        let property = property.clone();
        std::thread::spawn(move || {
            property.recompute(move |value| {
                snapshot_tx.send(*value).unwrap();
                release_rx.recv().unwrap();
                transform(*value)
            });
        })
    };
    let snapshot = snapshot_rx
        .recv_timeout(std::time::Duration::from_secs(3))
        .unwrap();
    (snapshot, release_tx, worker)
}

/// #751 — a `recompute` that starts while another one's transform runs waits
/// for it, so neither update is lost.
#[test]
fn concurrent_recomputes_do_not_lose_an_update() {
    let property = DerivedProperty::new(0i32);
    let (values, _subscription) = record_value_changes(&property);
    let (snapshot, release_first, first) = paused_recompute(&property, |value| value + 1);
    assert_eq!(snapshot, 0);

    let (second_done_tx, second_done_rx) = mpsc::channel();
    let second = {
        let property = property.clone();
        std::thread::spawn(move || {
            property.recompute(|value| value + 10);
            second_done_tx.send(()).unwrap();
        })
    };
    // Before the fix, the second recompute committed here, on the stale 0.
    let _ = second_done_rx.recv_timeout(std::time::Duration::from_millis(200));
    release_first.send(()).unwrap();
    first.join().unwrap();
    second.join().unwrap();

    assert_eq!(property.value(), 11);
    assert_eq!(values.lock().unwrap().last(), Some(&11));
}

/// #751 — a source update that commits while a `recompute` transform runs is
/// not overwritten by the transform's stale result.
#[test]
fn source_update_during_a_recompute_transform_is_not_lost() {
    let source = ValueStream::new(0);
    let property = DerivedProperty::from_one(source.clone(), |value| value);
    let (values, _subscription) = record_value_changes(&property);
    let (snapshot, release, worker) = paused_recompute(&property, |value| value + 1);
    assert_eq!(snapshot, 0);

    let sender = std::thread::spawn(move || source.send(5));
    sender.join().unwrap();
    release.send(()).unwrap();
    worker.join().unwrap();

    let value = property.value();
    assert!(
        value == 5 || value == 6,
        "value {value} matches no serial order"
    );
    assert_eq!(values.lock().unwrap().last(), Some(&value));
}

/// #751 — a transform may call `recompute` on its own thread. The nested
/// call commits first, and the outer result, from a stale snapshot, is
/// discarded.
#[test]
fn nested_recompute_from_a_transform_returns_and_wins() {
    let property = DerivedProperty::new(1i32);
    let (values, _subscription) = record_value_changes(&property);
    let (finished_tx, finished_rx) = mpsc::channel();
    let worker = {
        let property = property.clone();
        std::thread::spawn(move || {
            let nested = property.clone();
            property.recompute(move |value| {
                nested.recompute(|value| value * 100);
                value + 1
            });
            finished_tx.send(property.value()).unwrap();
        })
    };

    assert_eq!(
        finished_rx.recv_timeout(std::time::Duration::from_secs(3)),
        Ok(100)
    );
    worker.join().unwrap();
    assert_eq!(*values.lock().unwrap(), vec![100]);
}

/// #751 — a `value_changes` subscriber may call `recompute` on the
/// publishing thread, and the last published value is the stored one.
#[test]
fn value_changes_subscriber_may_recompute() {
    let property = DerivedProperty::new(0i32);
    let (values, _recorder) = record_value_changes(&property);
    let _bump = {
        let target = property.clone();
        property.value_changes().subscribe(move |value| {
            if value < 3 {
                target.recompute(|value| value + 1);
            }
        })
    };
    let (finished_tx, finished_rx) = mpsc::channel();
    let worker = {
        let property = property.clone();
        std::thread::spawn(move || {
            property.recompute(|value| value + 1);
            finished_tx.send(property.value()).unwrap();
        })
    };

    assert_eq!(
        finished_rx.recv_timeout(std::time::Duration::from_secs(3)),
        Ok(3)
    );
    worker.join().unwrap();
    assert_eq!(values.lock().unwrap().last(), Some(&3));
}

/// Runs `body` on a worker and fails if it does not finish within 5 s.
fn finishes<R: Send + 'static>(what: &str, body: impl FnOnce() -> R + Send + 'static) -> R {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(body());
    });
    rx.recv_timeout(std::time::Duration::from_secs(5))
        .unwrap_or_else(|_| panic!("{what} deadlocked"))
}

/// #751 — a `value_changes` subscriber that recomputes, while another
/// thread's `recompute` transform runs, does not deadlock either thread.
#[test]
fn subscriber_recompute_during_another_threads_transform_does_not_deadlock() {
    let source = ValueStream::new(0);
    let property = DerivedProperty::from_one(source.clone(), |value| value);
    let (in_subscriber_tx, in_subscriber_rx) = mpsc::channel();
    let in_subscriber_tx = Mutex::new(Some(in_subscriber_tx));
    let _subscriber = {
        let target = property.clone();
        property.value_changes().subscribe(move |value| {
            if value == 5 {
                if let Some(tx) = in_subscriber_tx.lock().unwrap().take() {
                    tx.send(()).unwrap();
                }
                target.recompute(|value| value + 100);
            }
        })
    };
    let (snapshot, release, worker) = paused_recompute(&property, |value| value + 1);
    assert_eq!(snapshot, 0);
    let sender = std::thread::spawn(move || source.send(5));
    in_subscriber_rx
        .recv_timeout(std::time::Duration::from_secs(3))
        .unwrap();
    release.send(()).unwrap();

    finishes("recompute and source delivery", move || {
        worker.join().unwrap();
        sender.join().unwrap();
    });
    assert_eq!(property.value(), 105);
    assert_eq!(property.value_changes().value(), 105);
}

/// #751 — a `value_changes` subscriber may wait for another thread's source
/// update; no lock is held while it runs.
#[test]
fn subscriber_may_wait_for_another_threads_source_update() {
    let source = ValueStream::new(0);
    let property = DerivedProperty::from_one(source.clone(), |value| value);
    let _subscriber = {
        let source = source.clone();
        property.value_changes().subscribe(move |value| {
            if value == 1 {
                let source = source.clone();
                std::thread::spawn(move || source.send(7)).join().unwrap();
            }
        })
    };

    finishes("recompute", {
        let property = property.clone();
        move || property.recompute(|value| value + 1)
    });
    assert_eq!(property.value(), 7);
    assert_eq!(property.value_changes().value(), 7);
}

/// #751 — a `recompute` waiting behind another one runs no commit once
/// `dispose()` has returned.
#[test]
fn recompute_waiting_behind_another_commits_nothing_after_dispose() {
    let property = DerivedProperty::new(0i32);
    let (snapshot, release, worker) = paused_recompute(&property, |value| value + 1);
    assert_eq!(snapshot, 0);
    let (waiting_tx, waiting_rx) = mpsc::channel();
    let waiting = {
        let property = property.clone();
        std::thread::spawn(move || {
            waiting_tx.send(()).unwrap();
            property.recompute(|value| value + 10);
        })
    };
    waiting_rx.recv().unwrap();

    property.dispose();
    let at_dispose = property.value();
    release.send(()).unwrap();
    worker.join().unwrap();
    waiting.join().unwrap();

    assert_eq!(property.value(), at_dispose);
}
