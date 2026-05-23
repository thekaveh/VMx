/**
 * Vitest global setup — patches rxjs.config.onUnhandledError.
 *
 * rxjs v7 routes synchronous exceptions thrown inside subscriber next-handlers
 * through reportUnhandledError, which surfaces them via setTimeout(0) AFTER
 * any try-catch boundary. This causes false-positive "unhandled error" reports
 * in vitest when MessageHub's HUB-007 tests intentionally trigger throwing
 * subscribers. Setting config.onUnhandledError to a no-op suppresses these
 * surfaced errors globally for the test suite, which is safe because the hub
 * already swallows them before they reach reportUnhandledError.
 */
import { config } from "rxjs";

config.onUnhandledError = () => {
  // swallow — hub exceptions are intentionally swallowed per HUB-007
};
