//! The shared bounded wait for the conformance tests.
//!
//! A test that could deadlock runs its body on a worker thread through
//! [`within_timeout`]. A deadlock then fails the test with a timeout message
//! instead of hanging the suite. A worker panic fails the test with the
//! worker's own panic message, not with a deadlock message.

use std::any::Any;
use std::sync::mpsc::{self, RecvTimeoutError};
use std::thread;
use std::time::Duration;

/// Runs `body` on a worker thread and returns its result.
///
/// The test fails when `body` does not return within `bound`. The failure
/// message names `label` and `bound`. When `body` panics, the test fails with
/// a message that names `label` and contains the worker's panic message.
pub(super) fn within_timeout<R: Send + 'static>(
    label: &str,
    bound: Duration,
    body: impl FnOnce() -> R + Send + 'static,
) -> R {
    let (tx, rx) = mpsc::channel();
    let worker = thread::spawn(move || {
        let _ = tx.send(body());
    });
    match rx.recv_timeout(bound) {
        Ok(value) => value,
        Err(RecvTimeoutError::Timeout) => {
            panic!("{label} did not finish within {bound:?}: it deadlocked or hung")
        }
        Err(RecvTimeoutError::Disconnected) => {
            let message = match worker.join() {
                Ok(()) => "worker exited without a result".to_string(),
                Err(payload) => panic_message(payload.as_ref()),
            };
            panic!("{label} worker panicked: {message}")
        }
    }
}

/// The text of a panic payload, or a placeholder for a non-string payload.
fn panic_message(payload: &(dyn Any + Send)) -> String {
    payload
        .downcast_ref::<&str>()
        .map(|text| (*text).to_string())
        .or_else(|| payload.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "non-string panic payload".to_string())
}

#[cfg(test)]
mod tests {
    use super::{panic_message, within_timeout};
    use std::panic::{catch_unwind, AssertUnwindSafe};
    use std::sync::mpsc;
    use std::time::Duration;

    /// The failure message of a call that is expected to panic.
    fn failure_of(call: impl FnOnce()) -> String {
        let payload = catch_unwind(AssertUnwindSafe(call)).expect_err("the wait did not fail");
        panic_message(payload.as_ref())
    }

    #[test]
    fn returns_the_body_result_within_the_bound() {
        assert_eq!(
            within_timeout("quick body", Duration::from_secs(5), || 7),
            7
        );
    }

    #[test]
    fn a_timeout_names_the_label_and_the_bound() {
        let bound = Duration::from_millis(50);
        // The worker blocks until the test ends, then exits on its own.
        let (release, blocked) = mpsc::channel::<()>();
        let message = failure_of(|| {
            within_timeout("blocked body", bound, move || {
                let _ = blocked.recv();
            });
        });
        drop(release);
        assert!(message.contains("blocked body"), "{message}");
        assert!(message.contains(&format!("{bound:?}")), "{message}");
    }

    #[test]
    fn a_worker_panic_reports_its_message_not_a_deadlock() {
        let message = failure_of(|| {
            within_timeout("panicking body", Duration::from_secs(5), || -> u8 {
                panic!("the body broke an invariant")
            });
        });
        assert!(message.contains("panicking body"), "{message}");
        assert!(message.contains("the body broke an invariant"), "{message}");
        assert!(!message.contains("deadlock"), "{message}");
        assert!(!message.contains("did not finish"), "{message}");
    }

    #[test]
    fn a_formatted_worker_panic_reports_its_message() {
        let message = failure_of(|| {
            within_timeout("formatted panic", Duration::from_secs(5), || -> u8 {
                panic!("value {} out of range", 42)
            });
        });
        assert!(message.contains("value 42 out of range"), "{message}");
    }
}
