//! `CommandExt`: fluent helpers on every cloneable command (#358).
//!
//! Integration tests compile as an external crate, so these chains use only
//! the public `vmx::` surface. No conformance-ID markers: the helpers
//! themselves are CMD-008..CMD-011, pinned in `command_decorators.rs`.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use vmx::{
    AsyncRelayCommand, AsyncValue, Command, CommandExt, CompositeCommand,
    ConfirmationDecoratorCommand, DecoratorCommand, RelayCommand, NO_HOOK, NO_PREDICATE,
};

type Log = Arc<Mutex<Vec<&'static str>>>;

fn log() -> Log {
    Arc::new(Mutex::new(Vec::new()))
}

fn push(log: &Log, label: &'static str) -> impl Fn() + Send + Sync + 'static {
    let log = log.clone();
    move || log.lock().unwrap().push(label)
}

fn relay(log: &Log, label: &'static str) -> RelayCommand {
    RelayCommand::new(push(log, label))
}

fn entries(log: &Log) -> Vec<&'static str> {
    log.lock().unwrap().clone()
}

#[test]
fn a_chain_starting_with_a_relay_command_continues_past_each_helper() {
    let log = log();
    let command = relay(&log, "save")
        .confirm(|| AsyncValue::ready(true))
        .wrap_with(
            NO_PREDICATE,
            Some(push(&log, "pre")),
            Some(push(&log, "post")),
        )
        .succeed_with(relay(&log, "audit"))
        .precede_with(relay(&log, "validate"));

    command.execute();

    assert_eq!(
        entries(&log),
        vec!["validate", "pre", "save", "post", "audit"]
    );
}

#[test]
fn a_chain_starting_with_a_composite_command_continues() {
    let log = log();
    let composite = CompositeCommand::from_commands(vec![relay(&log, "a"), relay(&log, "b")]);

    composite
        .wrap_with(
            NO_PREDICATE,
            Some(push(&log, "pre")),
            Some(push(&log, "post")),
        )
        .confirm(|| AsyncValue::ready(true))
        .execute();

    assert_eq!(entries(&log), vec!["pre", "a", "b", "post"]);
}

#[test]
fn a_chain_starting_with_a_decorator_command_continues() {
    let log = log();
    let decorator = DecoratorCommand::new(
        relay(&log, "inner"),
        NO_PREDICATE,
        Some(push(&log, "pre")),
        NO_HOOK,
    );

    decorator.precede_with(relay(&log, "first")).execute();

    assert_eq!(entries(&log), vec!["first", "pre", "inner"]);
}

#[test]
fn a_chain_starting_with_a_confirmation_decorator_continues() {
    let log = log();
    let confirming =
        ConfirmationDecoratorCommand::new(relay(&log, "delete"), || AsyncValue::ready(true));
    let declined =
        ConfirmationDecoratorCommand::new(relay(&log, "never"), || AsyncValue::ready(false));

    confirming.succeed_with(relay(&log, "refresh")).execute();
    declined
        .succeed_with(relay(&log, "still refreshes"))
        .execute();

    assert_eq!(entries(&log), vec!["delete", "refresh", "still refreshes"]);
}

#[test]
fn a_chain_starting_with_an_async_relay_command_continues() {
    let log = log();
    let command = AsyncRelayCommand::new(|_token| Ok(()))
        .wrap_with(Some(|| true), Some(push(&log, "pre")), NO_HOOK)
        .succeed_with(relay(&log, "after"));

    assert!(command.can_execute());
    command.execute();

    assert_eq!(entries(&log), vec!["pre", "after"]);
}

struct Counter {
    hits: AtomicUsize,
}

impl Command for Counter {
    fn can_execute(&self) -> bool {
        true
    }

    fn execute(&self) {
        self.hits.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn a_custom_command_opts_in_through_an_arc_without_implementing_clone() {
    let counter = Arc::new(Counter {
        hits: AtomicUsize::new(0),
    });
    let blocked = Arc::new(AtomicUsize::new(0));

    counter
        .clone()
        .wrap_with(Some(|| true), NO_HOOK, NO_HOOK)
        .execute();
    let dynamic: Arc<dyn Command> = counter.clone();
    dynamic.confirm(|| AsyncValue::ready(true)).execute();
    counter
        .clone()
        .wrap_with(
            Some(|| false),
            NO_HOOK,
            Some({
                let blocked = blocked.clone();
                move || {
                    blocked.fetch_add(1, Ordering::SeqCst);
                }
            }),
        )
        .execute();

    assert_eq!(counter.hits.load(Ordering::SeqCst), 2);
    assert_eq!(blocked.load(Ordering::SeqCst), 0);
}

#[derive(Clone)]
struct Named(Log, &'static str);

impl Command for Named {
    fn can_execute(&self) -> bool {
        true
    }

    fn execute(&self) {
        self.0.lock().unwrap().push(self.1);
    }
}

#[test]
fn a_cloneable_custom_command_chains_directly() {
    let log = log();

    Named(log.clone(), "custom")
        .succeed_with(Named(log.clone(), "next"))
        .execute();

    assert_eq!(entries(&log), vec!["custom", "next"]);
}

#[test]
fn a_chained_graph_forwards_eligibility_changes_and_keeps_execution_order() {
    let log = log();
    let enabled = Arc::new(Mutex::new(true));
    let gated = relay(&log, "gated").with_can_execute({
        let enabled = enabled.clone();
        move || *enabled.lock().unwrap()
    });
    let graph = gated
        .clone()
        .wrap_with(
            NO_PREDICATE,
            Some(push(&log, "pre")),
            Some(push(&log, "post")),
        )
        .succeed_with(relay(&log, "tail"));
    let notifications = Arc::new(AtomicUsize::new(0));
    let _subscription = graph.can_execute_changed().subscribe({
        let notifications = notifications.clone();
        move |_| {
            notifications.fetch_add(1, Ordering::SeqCst);
        }
    });

    gated.raise_can_execute_changed();
    assert_eq!(notifications.load(Ordering::SeqCst), 1);

    graph.execute();
    *enabled.lock().unwrap() = false;
    graph.execute();

    assert_eq!(entries(&log), vec!["pre", "gated", "post", "tail", "tail"]);
}

#[test]
fn inherent_and_trait_helpers_build_equivalent_graphs() {
    let inherent_log = log();
    let trait_log = log();

    relay(&inherent_log, "inner")
        .wrap_with(NO_PREDICATE, Some(push(&inherent_log, "pre")), NO_HOOK)
        .execute();
    CommandExt::wrap_with(
        relay(&trait_log, "inner"),
        NO_PREDICATE,
        Some(push(&trait_log, "pre")),
        NO_HOOK,
    )
    .execute();

    assert_eq!(entries(&inherent_log), entries(&trait_log));
}
