//! A lifecycle call during the inline dispose cascade (spec/02 §7.2,
//! ADR-0175).
//!
//! PLACEHOLDER. A `construct()`, `destruct()`, or `reconstruct()` call that
//! starts during the cascade returns `VmxError::Disposed` and publishes
//! nothing, and no status other than `Disposed` commits once the cascade has
//! started. The implementation PR replaces this ignored placeholder with the
//! full LIFE-021 scenarios.

/// LIFE-021 — a lifecycle call during the inline dispose cascade fails
/// (placeholder).
#[test]
#[ignore = "LIFE-021 placeholder: replaced by the ADR-0175 implementation"]
fn life_021_placeholder() {}
