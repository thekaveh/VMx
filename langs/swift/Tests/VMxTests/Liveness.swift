import Foundation

/// The bound, in seconds, for a wait that is expected to succeed (#1408). It
/// matches C# `Liveness.HangGuard` and Python `HANG_GUARD`.
///
/// A slow or oversubscribed runner, or a Thread Sanitizer build, can delay a
/// thread by seconds, so short deadlines fail without any wrong behavior. A
/// passing wait returns as soon as its condition holds, so the bound costs
/// nothing; it only stops a hang.
///
/// Rules:
///
/// - **Positive waits** use `hangGuard`: `wait(for:timeout:)`,
///   `fulfillment(of:timeout:)`, `DispatchSemaphore` and `DispatchGroup`
///   waits, condition rendezvous, and polling deadlines whose success the
///   test expects.
/// - **Outer waits** that must outlive inner `hangGuard` waits, such as a wait
///   for a thread that itself waits, use a multiple of the bound, so the inner
///   failure is the one reported.
/// - **Blocking holds** that a positive wait on another thread must time out
///   before, such as a hook parked until the test releases it, also use a
///   multiple, so a regression cannot pass because the hold expired first.
/// - **Negative windows** assert that something did *not* happen, such as
///   `XCTAssertEqual(done.wait(timeout: .now() + 0.05), .timedOut)` or an
///   inverted expectation. They keep their short spans, because the full span
///   elapses on every passing run.
let hangGuard: TimeInterval = 30
