//! COL-073 — a failing subscriber of a token-paging notification step skips no
//! later step of the committed load or refresh (spec/21-collections.md §6.2,
//! ADR-0239, extends ADR-0220).
//!
//! Rust `MessageHub` runs each subscriber inside `catch_unwind` and returns
//! normally, so a panicking `Reset` or property subscriber skips no later
//! subscriber and no later step, and the load or refresh returns normally.

use std::sync::{Arc, Mutex};

use vmx::{CollectionChangeAction, Message, Subscription, TokenPagedComposition};

type Page = (Vec<i32>, Option<&'static str>);

/// The first page can change between calls; the page after it is terminal.
#[derive(Clone)]
struct Backend {
    first_page: Arc<Mutex<Page>>,
}

impl Backend {
    fn new(first: Page) -> Self {
        Self {
            first_page: Arc::new(Mutex::new(first)),
        }
    }

    fn set_first_page(&self, page: Page) {
        *self.first_page.lock().unwrap() = page;
    }

    fn pager(&self) -> TokenPagedComposition<i32, &'static str> {
        let backend = self.clone();
        TokenPagedComposition::with_loader(None, move |token| match token {
            None => backend.first_page.lock().unwrap().clone(),
            Some(_) => (vec![3], None),
        })
    }
}

fn is_reset(message: &Message) -> bool {
    matches!(
        message,
        Message::CollectionChanged(change) if change.action == CollectionChangeAction::Reset
    )
}

fn is_property(message: &Message) -> bool {
    matches!(message, Message::PropertyChanged(_))
}

/// Records the Reset, property and command signals in the order they arrive.
struct Trace {
    entries: Arc<Mutex<Vec<String>>>,
    _subscriptions: Vec<Subscription>,
}

impl Trace {
    fn entries(&self) -> Vec<String> {
        self.entries.lock().unwrap().clone()
    }
}

/// Subscribes a recorder to the pager's hub and to one command's eligibility
/// signal. A command raises its own signal when it starts and finishes, so the
/// recorder observes the command that the test does not execute. When `fail_on`
/// names a message kind, a subscriber that panics on that kind comes first, so
/// the recorder proves that the panic skips no later subscriber.
fn record_trace(
    pages: &TokenPagedComposition<i32, &'static str>,
    fail_on: Option<fn(&Message) -> bool>,
    observe_refresh: bool,
) -> Trace {
    let entries = Arc::new(Mutex::new(Vec::new()));
    let hub = pages.hub();
    let mut subscriptions = Vec::new();
    if let Some(fails) = fail_on {
        subscriptions.push(hub.subscribe(move |message| {
            if fails(message) {
                panic!("subscriber failed");
            }
        }));
    }
    let hub_entries = entries.clone();
    subscriptions.push(hub.subscribe(move |message| match message {
        Message::CollectionChanged(change) if change.action == CollectionChangeAction::Reset => {
            hub_entries
                .lock()
                .unwrap()
                .push("collection:Reset".to_string());
        }
        Message::PropertyChanged(change) => {
            hub_entries
                .lock()
                .unwrap()
                .push(format!("property:{}", change.property_name));
        }
        _ => {}
    }));
    let command_entries = entries.clone();
    let observed = if observe_refresh {
        pages.refresh_command().can_execute_changed()
    } else {
        pages.load_more_command().can_execute_changed()
    };
    subscriptions.push(observed.subscribe(move |_| {
        command_entries
            .lock()
            .unwrap()
            .push("command:can_execute_changed".to_string());
    }));
    Trace {
        entries,
        _subscriptions: subscriptions,
    }
}

fn expected_steps() -> Vec<String> {
    [
        "collection:Reset",
        "property:items",
        "property:current_token",
        "property:has_more",
        "command:can_execute_changed",
    ]
    .iter()
    .map(|step| step.to_string())
    .collect()
}

/// COL-073 — a panicking Reset subscriber skips no later step of an appending load
#[test]
fn failing_reset_subscriber_skips_no_later_step_on_load() {
    let pages = Backend::new((vec![1, 2], None)).pager();
    let trace = record_trace(&pages, Some(is_reset), true);

    pages.load_next();

    assert_eq!(pages.items(), vec![1, 2]);
    assert!(!pages.has_more());
    assert_eq!(trace.entries(), expected_steps());
}

/// COL-073 — a panicking Reset subscriber skips no later step of a replacing refresh
#[test]
fn failing_reset_subscriber_skips_no_later_step_on_replacing_refresh() {
    let backend = Backend::new((vec![1, 2], Some("t2")));
    let pages = backend.pager();
    pages.load_next();
    backend.set_first_page((vec![9], None));
    let trace = record_trace(&pages, Some(is_reset), false);

    pages.refresh();

    assert_eq!(pages.items(), vec![9]);
    assert_eq!(pages.current_token(), None);
    assert!(!pages.has_more());
    assert_eq!(trace.entries(), expected_steps());
}

/// COL-073 — a panicking property subscriber skips no later property or command step
#[test]
fn failing_property_subscriber_skips_no_later_step() {
    let pages = Backend::new((vec![1, 2], None)).pager();
    let trace = record_trace(&pages, Some(is_property), true);

    pages.load_next();

    assert_eq!(trace.entries(), expected_steps());
}

/// COL-073 — a Reset subscriber that disposes the composition stops the later property and command steps
#[test]
fn disposing_reset_subscriber_stops_the_later_steps() {
    let pages = Arc::new(Backend::new((vec![1, 2], None)).pager());
    let disposer = Arc::clone(&pages);
    let _dispose = pages.hub().subscribe(move |message| {
        if is_reset(message) {
            disposer.dispose();
        }
    });
    let trace = record_trace(&pages, None, true);

    pages.load_next();

    assert_eq!(trace.entries(), vec!["collection:Reset".to_string()]);
}
