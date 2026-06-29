/**
 * Vitest global setup — rxjs unhandled-error policy.
 *
 * rxjs v7 routes synchronous exceptions thrown inside subscriber next-handlers
 * through reportUnhandledError, which surfaces them via setTimeout(0) AFTER any
 * try-catch boundary. The HUB-007 tests intentionally trigger a throwing
 * subscriber, so these reports are expected there.
 *
 * VMX-085: previously this file installed a PERMANENT global no-op on
 * `config.onUnhandledError`, which swallowed every rxjs unhandled error
 * suite-wide — masking a genuine unhandled error in any unrelated test. Instead
 * we now RECORD unhandled errors and, by default, surface them as a test
 * failure in `afterEach`. Tests that legitimately expect them (HUB-007) opt in
 * via {@link allowRxUnhandledErrors}, scoping the suppression to exactly those
 * tests.
 */
import { config } from "rxjs";
import { afterEach } from "vitest";

let _expecting = false;
const _recorded: unknown[] = [];

config.onUnhandledError = (err: unknown) => {
  _recorded.push(err);
};

/**
 * Opt the current test in to tolerating rxjs "unhandled error" reports (e.g.
 * HUB-007's intentionally-throwing subscriber, whose error rxjs routes through
 * reportUnhandledError on a macrotask). Auto-resets after each test.
 */
export function allowRxUnhandledErrors(): void {
  _expecting = true;
}

afterEach(async () => {
  // rxjs surfaces unhandled errors on a macrotask (setTimeout(0)); drain the
  // queue so a throw from the just-finished test is captured here before we
  // decide whether it was expected.
  await new Promise((resolve) => setTimeout(resolve, 0));
  const recorded = _recorded.splice(0);
  const expecting = _expecting;
  _expecting = false;
  if (!expecting && recorded.length > 0) {
    const errors = recorded.map((e) =>
      e instanceof Error ? e : new Error(String(e)),
    );
    throw new AggregateError(
      errors,
      `Unexpected rxjs unhandled error(s) surfaced during this test: ${String(
        recorded.length,
      )}. If intentional (e.g. a HUB-007 throwing subscriber), call allowRxUnhandledErrors().`,
    );
  }
});
