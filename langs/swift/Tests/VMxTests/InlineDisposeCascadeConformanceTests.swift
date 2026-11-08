//
// Inline dispose cascade conformance tests (spec/02-lifecycle.md §7.2,
// ADR-0175).
//
// Claimed IDs: LIFE-021.
//
// PLACEHOLDER. A `construct()`, `destruct()`, or `reconstruct()` call that
// starts during the cascade throws `StatusTransitionError` for `.disposed` and
// publishes nothing, and no status other than `.disposed` commits once the
// cascade has started. The implementation PR replaces this skipped placeholder
// with the full LIFE-021 scenarios.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest

final class InlineDisposeCascadeConformanceTests: XCTestCase {
    /// LIFE-021 — a lifecycle call during the inline dispose cascade fails
    /// (placeholder).
    func testLife021Placeholder() throws {
        throw XCTSkip("LIFE-021 placeholder: replaced by the ADR-0175 implementation")
    }
}
