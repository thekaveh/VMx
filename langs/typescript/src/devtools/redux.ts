import type { IMessageHub } from "../services/messageHub.js";
import {
  captureDevtoolsState,
  observeHub,
  reportDevtoolsError,
} from "./observer.js";
import type {
  DevtoolsConnection,
  ObserveHubOptions,
} from "./types.js";

export interface ReduxDevtoolsTransport {
  init(state: unknown): void;
  send(action: unknown, state: unknown): void;
  subscribe?(
    listener: (message: unknown) => void,
  ): (() => void) | { unsubscribe(): void } | void;
  unsubscribe?(): void;
}

export interface ReduxDevtoolsExtension {
  connect(options: { readonly name: string }): ReduxDevtoolsTransport;
}

export interface ConnectReduxDevtoolsOptions extends ObserveHubOptions {
  /** Explicit extension. `null` disables guarded global discovery. */
  readonly extension?: ReduxDevtoolsExtension | null;
}

const NOOP_CONNECTION: DevtoolsConnection = Object.freeze({ dispose: () => undefined });

/** Connect a VMx hub to Redux DevTools when an extension is available. */
export function connectReduxDevtools(
  hub: IMessageHub,
  options: ConnectReduxDevtoolsOptions = {},
): DevtoolsConnection {
  const extension = options.extension === null
    ? undefined
    : options.extension ?? discoverReduxDevtools();
  if (extension === undefined) return NOOP_CONNECTION;

  let transport: ReduxDevtoolsTransport;
  try {
    transport = extension.connect({ name: options.name ?? "VMx" });
    if (!isReduxDevtoolsTransport(transport)) {
      throw new TypeError("Redux DevTools connect() returned an invalid transport");
    }
  } catch (error) {
    reportDevtoolsError(options, error, { phase: "transport-connect", sequence: 0 });
    return NOOP_CONNECTION;
  }

  const initial = captureDevtoolsState(0, options);
  if (initial !== undefined) {
    try {
      transport.init(initial);
    } catch (error) {
      reportDevtoolsError(options, error, { phase: "transport-init", sequence: 0 });
    }
  }

  let listenerCleanup: (() => void) | undefined;
  try {
    const subscribe = transport.subscribe?.bind(transport);
    if (subscribe !== undefined) {
      const cleanup = subscribe(() => {
        // Incoming dispatch/time-travel messages are deliberately ignored.
      });
      listenerCleanup = typeof cleanup === "function"
        ? cleanup
        : cleanup === undefined
          ? undefined
          : () => cleanup.unsubscribe();
    }
  } catch (error) {
    reportDevtoolsError(options, error, { phase: "transport-subscribe", sequence: 0 });
  }

  const observer = observeHub(hub, (event) => {
    try {
      transport.send(event.action, event.state);
    } catch (error) {
      reportDevtoolsError(options, error, {
        phase: "transport-send",
        sequence: event.action.sequence,
      });
    }
  }, options);
  let disposed = false;
  return {
    dispose: () => {
      if (disposed) return;
      disposed = true;
      observer.dispose();
      if (listenerCleanup !== undefined) {
        try {
          listenerCleanup();
        } catch (error) {
          reportDevtoolsError(options, error, { phase: "transport-dispose", sequence: 0 });
        }
      }
      try {
        const unsubscribe = transport.unsubscribe?.bind(transport);
        unsubscribe?.();
      } catch (error) {
        reportDevtoolsError(options, error, { phase: "transport-dispose", sequence: 0 });
      }
    },
  };
}

function isReduxDevtoolsTransport(value: unknown): value is ReduxDevtoolsTransport {
  if (typeof value !== "object" || value === null) return false;
  try {
    const candidate = value as { readonly init?: unknown; readonly send?: unknown };
    return typeof candidate.init === "function" && typeof candidate.send === "function";
  } catch {
    return false;
  }
}

function discoverReduxDevtools(): ReduxDevtoolsExtension | undefined {
  try {
    const candidate = (globalThis as unknown as Record<string, unknown>)[
      "__REDUX_DEVTOOLS_EXTENSION__"
    ];
    if (typeof candidate !== "object" || candidate === null) return undefined;
    return typeof (candidate as { readonly connect?: unknown }).connect === "function"
      ? candidate as ReduxDevtoolsExtension
      : undefined;
  } catch {
    return undefined;
  }
}
