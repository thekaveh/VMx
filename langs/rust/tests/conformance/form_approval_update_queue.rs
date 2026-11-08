//! `FormVm` queues updates made during approval publication (spec/20 §5.1,
//! §5.3 and §5.4, ADR-0174).
//!
//! PLACEHOLDER: the spec change for ADR-0174 adds FORM-039 and FORM-040
//! before the Rust implementation lands. The implementation PR replaces each
//! ignored test with the behavioral test. The conformance execution check
//! counts an ignored ID as not passing, so CI stays red until then.

/// FORM-039 — updates during approval publication replay after `on_approved`
#[test]
#[ignore = "ADR-0174 placeholder: replaced by the Rust FormVm implementation"]
fn form_039_updates_during_publication_replay_after_on_approved() {}

/// FORM-040 — a queued update prepares at call time and replays in isolation
#[test]
#[ignore = "ADR-0174 placeholder: replaced by the Rust FormVm implementation"]
fn form_040_queued_update_prepares_at_call_time_and_replays_in_isolation() {}
