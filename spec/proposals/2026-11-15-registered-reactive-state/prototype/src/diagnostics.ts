/**
 * Development diagnostics and the stream-fed error route (R16, R19.*).
 *
 * VMx turns the diagnostics on when the VM's hub has development diagnostics on. The 3.30.0 `MessageHub` keeps that
 * flag private, so the prototype applies the hub's own default (Node `NODE_ENV` is `development` or `test`) and
 * offers `configureReactiveDiagnostics` as a stand-in for the hub flag and the diagnostic sink.
 *
 * Fix round 1 (R19.1, R19.2): a diagnostic that evaluates user code (the staleness check, the unpublished-getter
 * probe) runs on a later task through `later()`, never inside a read or a library operation, so diagnostics change
 * no synchronous behavior.
 */
import { throwError } from "rxjs";

interface ProcessLike {
  readonly env?: Readonly<Record<string, string | undefined>>;
}

const NODE_ENV = (globalThis as { readonly process?: ProcessLike }).process?.env?.["NODE_ENV"];
const NODE_DEVELOPMENT = NODE_ENV === "development" || NODE_ENV === "test";

let developmentOverride: boolean | undefined;
let reporter: (message: string) => void = (message) => {
  console.warn(message);
};
const reported = new Set<string>();

/** Options of {@link configureReactiveDiagnostics} (prototype only). */
export interface ReactiveDiagnosticsOptions {
  /** Forces development diagnostics on or off; `undefined` restores the Node default. */
  readonly development?: boolean | undefined;
  /** Receives each development report. Default: `console.warn`. */
  readonly report?: (message: string) => void;
  /** Forgets which class and name pairs were already reported. */
  readonly resetReports?: boolean;
}

/** Prototype-only switch for the development diagnostics of R19.* and the drain bound of R9.6. */
export function configureReactiveDiagnostics(options: ReactiveDiagnosticsOptions): void {
  if ("development" in options) developmentOverride = options.development;
  if (options.report !== undefined) reporter = options.report;
  if (options.resetReports === true) reported.clear();
}

/** True while development diagnostics are on. */
export function developmentDiagnostics(): boolean {
  return developmentOverride ?? NODE_DEVELOPMENT;
}

/** Reports `message` once per `key` (class and name) while development diagnostics are on. */
export function reportOnce(key: string, message: string): void {
  if (!developmentDiagnostics()) return;
  if (reported.has(key)) return;
  reported.add(key);
  try {
    reporter(message);
  } catch {
    // A failing diagnostic sink must not change behavior (R19.*).
  }
}

/** The TypeScript stream-fed route (spec 03 §3.6): rxjs `config.onUnhandledError`, asynchronously. */
export function reportStreamFed(error: unknown): void {
  throwError(() => error).subscribe();
}

/** Runs `fn` on a later task (a zero timer that does not keep a Node process alive). */
export function later(fn: () => void): void {
  const handle: unknown = setTimeout(() => {
    try {
      fn();
    } catch {
      // A diagnostic must not fail the host.
    }
  }, 0);
  (handle as { unref?: () => void }).unref?.();
}
