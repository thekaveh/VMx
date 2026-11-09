import { throwError } from "rxjs";

/**
 * Report `error` through rxjs's unhandled-error route (ADR-0200 §2.3).
 *
 * rxjs delivers the error to `config.onUnhandledError` on a timer, after the
 * current synchronous flush returns. With no handler set, rxjs rethrows it on
 * that timer. This never throws to its caller.
 */
export function reportUnhandled(error: unknown): void {
  throwError(() => error).subscribe();
}
