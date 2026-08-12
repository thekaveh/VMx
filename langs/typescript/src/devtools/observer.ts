import type { IMessage } from "../messages/types.js";
import { CollectionChangedMessage } from "../messages/collectionChanged.js";
import { ConstructionStatusChangedMessage } from "../messages/constructionStatusChanged.js";
import { FormRevertedMessage } from "../messages/formReverted.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import { TreeStructureChangedMessage } from "../messages/treeStructureChanged.js";
import type { IMessageHub } from "../services/messageHub.js";
import { sanitizeDevtoolsValue } from "./sanitize.js";
import type {
  DevtoolsAction,
  DevtoolsConnection,
  DevtoolsErrorContext,
  DevtoolsEvent,
  DevtoolsJsonValue,
  DevtoolsSink,
  DevtoolsTimerScheduler,
  ObserveHubOptions,
} from "./types.js";

/** Observe delivered hub messages without exposing sender/model graphs by default. */
export function observeHub(
  hub: IMessageHub,
  sink: DevtoolsSink,
  options: ObserveHubOptions = {},
): DevtoolsConnection {
  let disposed = false;
  let sequence = 0;
  let timerHandle: unknown;
  let timerPending = false;
  let pendingCount = 0;
  let pendingLastAction: DevtoolsAction | undefined;
  const pendingActions: DevtoolsAction[] = [];
  const emit = typeof sink === "function" ? sink : (event: DevtoolsEvent) => sink.next(event);
  const complete = typeof sink === "function" ? undefined : sink.complete?.bind(sink);
  const scheduler = options.timerScheduler ?? DEFAULT_TIMER_SCHEDULER;
  const throttleMs = finiteAtLeast(options.throttleMs, 0, 0);
  const sampleEvery = Math.floor(finiteAtLeast(options.sampleEvery, 1, 1));

  const deliver = (action: DevtoolsAction): void => {
    const event = buildEvent(action, options);
    if (event === undefined) return;
    try {
      emit(event);
    } catch (error) {
      reportDevtoolsError(options, error, { phase: "sink", sequence: action.sequence });
    }
  };

  const cancelPending = (): void => {
    if (timerPending) {
      try {
        scheduler.cancel(timerHandle);
      } catch (error) {
        reportDevtoolsError(options, error, { phase: "schedule", sequence });
      }
    }
    timerPending = false;
    timerHandle = undefined;
    pendingActions.length = 0;
    pendingCount = 0;
    pendingLastAction = undefined;
  };

  const flush = (): void => {
    timerPending = false;
    timerHandle = undefined;
    if (disposed || pendingCount === 0) return;
    const actions = pendingActions.splice(0);
    const count = pendingCount;
    const last = pendingLastAction;
    pendingCount = 0;
    pendingLastAction = undefined;
    if (last === undefined) return;
    const batchFallback: DevtoolsAction = {
      type: `VMx batch/${options.name ?? "VMx"}/${String(count)}`,
      messageType: "VMxBatch",
      senderName: options.name ?? "VMx",
      sequence: last.sequence,
      details: {
        count,
        retainedCount: actions.length,
        omittedCount: count - actions.length,
        actions: actions as unknown as DevtoolsJsonValue,
      },
    };
    const batch = redactAndSanitizeAction(
      batchFallback,
      batchFallback,
      last.sequence,
      options,
    );
    if (batch !== undefined) deliver(batch);
  };

  const subscription = hub.messages.subscribe({
    next: (message) => {
      if (disposed || !passesFilters(message, options, sequence + 1)) return;
      sequence += 1;
      if (sequence % sampleEvery !== 0) return;
      const action = buildAction(message, sequence, options);
      if (action === undefined) return;
      if (throttleMs === 0) {
        deliver(action);
        return;
      }
      pendingCount += 1;
      pendingLastAction = action;
      const retainedLimit = resolvedRetainedActionLimit(options);
      if (pendingActions.length < retainedLimit) pendingActions.push(action);
      if (timerPending) return;
      timerPending = true;
      try {
        timerHandle = scheduler.schedule(flush, throttleMs);
      } catch (error) {
        timerPending = false;
        timerHandle = undefined;
        pendingActions.length = 0;
        pendingCount = 0;
        pendingLastAction = undefined;
        reportDevtoolsError(options, error, { phase: "schedule", sequence });
      }
    },
    complete: () => {
      if (disposed) return;
      cancelPending();
      if (complete === undefined) return;
      try {
        complete();
      } catch (error) {
        reportDevtoolsError(options, error, { phase: "sink", sequence });
      }
    },
  });

  return {
    dispose: () => {
      if (disposed) return;
      disposed = true;
      cancelPending();
      subscription.unsubscribe();
    },
  };
}

function finiteAtLeast(value: number | undefined, minimum: number, fallback: number): number {
  return value !== undefined && Number.isFinite(value) && value >= minimum ? value : fallback;
}

function resolvedRetainedActionLimit(options: ObserveHubOptions): number {
  return Math.floor(finiteAtLeast(options.limits?.maxArrayLength, 0, 100));
}

function passesFilters(
  message: IMessage,
  options: ObserveHubOptions,
  sequence: number,
): boolean {
  if (options.allow !== undefined) {
    try {
      if (!options.allow(message)) return false;
    } catch (error) {
      reportDevtoolsError(options, error, { phase: "allow-filter", sequence });
      return false;
    }
  }
  if (options.deny !== undefined) {
    try {
      if (options.deny(message)) return false;
    } catch (error) {
      reportDevtoolsError(options, error, { phase: "deny-filter", sequence });
      return false;
    }
  }
  return true;
}

function buildAction(
  message: IMessage,
  sequence: number,
  options: ObserveHubOptions,
): DevtoolsAction | undefined {
  const fallback = defaultAction(message, sequence);
  let mapped: unknown = fallback;
  if (options.mapAction !== undefined) {
    try {
      mapped = options.mapAction(message, fallback);
    } catch (error) {
      reportDevtoolsError(options, error, { phase: "map-action", sequence });
      return undefined;
    }
  }

  return redactAndSanitizeAction(mapped, fallback, sequence, options);
}

function buildEvent(
  action: DevtoolsAction,
  options: ObserveHubOptions,
): DevtoolsEvent | undefined {
  const state = captureDevtoolsState(action.sequence, options);
  if (state === undefined) return undefined;
  let timestamp: number;
  try {
    timestamp = options.now?.() ?? Date.now();
  } catch (error) {
    reportDevtoolsError(options, error, { phase: "clock", sequence: action.sequence });
    return undefined;
  }

  return deepFreeze({
    name: options.name ?? "VMx",
    timestamp,
    action,
    state,
  });
}

function redactAndSanitizeAction(
  action: unknown,
  fallback: DevtoolsAction,
  sequence: number,
  options: ObserveHubOptions,
): DevtoolsAction | undefined {
  let redacted = action;
  if (options.redact !== undefined) {
    try {
      redacted = options.redact(action, { kind: "action", sequence });
    } catch (error) {
      reportDevtoolsError(options, error, { phase: "redact", sequence });
      return undefined;
    }
  }
  try {
    return normalizeDevtoolsAction(redacted, fallback, sequence, options);
  } catch (error) {
    reportDevtoolsError(options, error, { phase: "sanitize", sequence });
    return undefined;
  }
}

function normalizeDevtoolsAction(
  value: unknown,
  fallback: DevtoolsAction,
  sequence: number,
  options: ObserveHubOptions,
): DevtoolsAction {
  const record = typeof value === "object" && value !== null
    ? value as Record<string, unknown>
    : {};
  const result: DevtoolsAction = {
    type: sanitizedActionString(record, "type", fallback.type, options),
    messageType: sanitizedActionString(record, "messageType", fallback.messageType, options),
    senderName: sanitizedActionString(record, "senderName", fallback.senderName, options),
    sequence,
  };
  let details: DevtoolsJsonValue | undefined;
  if (record["details"] !== undefined) {
    details = sanitizeDevtoolsValue(record["details"], options.limits);
  }
  return typeof details === "object" && details !== null && !Array.isArray(details)
    ? { ...result, details: details as Readonly<Record<string, DevtoolsJsonValue>> }
    : result;
}

function sanitizedActionString(
  record: Record<string, unknown>,
  key: string,
  fallback: string,
  options: ObserveHubOptions,
): string {
  let value: unknown;
  try {
    value = record[key];
  } catch {
    value = fallback;
  }
  const selected = typeof value === "string" && value.length > 0 ? value : fallback;
  const sanitized = sanitizeDevtoolsValue(selected, options.limits);
  return typeof sanitized === "string" ? sanitized : fallback;
}

export function captureDevtoolsState(
  sequence: number,
  options: ObserveHubOptions,
): Readonly<Record<string, DevtoolsJsonValue>> | undefined {
  const state = Object.create(null) as Record<string, DevtoolsJsonValue>;
  for (const source of options.snapshots ?? []) {
    let value: unknown;
    try {
      value = source.select();
    } catch (error) {
      reportDevtoolsError(options, error, {
        phase: "select-snapshot",
        sequence,
        snapshotName: source.name,
      });
      return undefined;
    }
    if (source.serialize !== undefined) {
      try {
        value = source.serialize(value);
      } catch (error) {
        reportDevtoolsError(options, error, {
          phase: "serialize-snapshot",
          sequence,
          snapshotName: source.name,
        });
        return undefined;
      }
    }
    if (options.redact !== undefined) {
      try {
        value = options.redact(value, {
          kind: "state",
          sequence,
          snapshotName: source.name,
        });
      } catch (error) {
        reportDevtoolsError(options, error, {
          phase: "redact",
          sequence,
          snapshotName: source.name,
        });
        return undefined;
      }
    }
    try {
      state[source.name] = sanitizeDevtoolsValue(value, options.limits);
    } catch (error) {
      reportDevtoolsError(options, error, {
        phase: "sanitize",
        sequence,
        snapshotName: source.name,
      });
      return undefined;
    }
  }
  return state;
}

function defaultAction(message: IMessage, sequence: number): DevtoolsAction {
  const messageType = canonicalMessageType(message);
  const senderName = safeMetadataString(message, "senderName") ?? "Unknown";
  const details: Record<string, DevtoolsJsonValue> = {};
  for (const key of ["propertyName", "status", "action", "index", "oldIndex", "newIndex"] as const) {
    const value = safeScalar(message, key);
    if (value !== undefined) details[key] = value;
  }
  const discriminator = typeof details.propertyName === "string"
    ? details.propertyName
    : typeof details.action === "string"
      ? details.action
      : undefined;
  return {
    type: [messageType, senderName, discriminator].filter(Boolean).join("/"),
    messageType,
    senderName,
    sequence,
    ...(Object.keys(details).length === 0 ? {} : { details }),
  };
}

function canonicalMessageType(message: IMessage): string {
  try {
    if (message instanceof PropertyChangedMessage) return "PropertyChangedMessage";
    if (message instanceof CollectionChangedMessage) return "CollectionChangedMessage";
    if (message instanceof ConstructionStatusChangedMessage) return "ConstructionStatusChangedMessage";
    if (message instanceof TreeStructureChangedMessage) return "TreeStructureChangedMessage";
    if (message instanceof FormRevertedMessage) return "FormRevertedMessage";
  } catch {
    // IMessage is structural; hostile proxies must not escape observability.
  }
  return safeMetadataString(message, "constructor", "name") ?? "IMessage";
}

function safeMetadataString(
  value: unknown,
  key: string,
  nestedKey?: string,
): string | undefined {
  try {
    const selected = (value as Record<string, unknown>)[key];
    const nested = nestedKey === undefined
      ? selected
      : (selected as Record<string, unknown> | null | undefined)?.[nestedKey];
    return typeof nested === "string" && nested.length > 0 ? nested : undefined;
  } catch {
    return undefined;
  }
}

function safeScalar(message: IMessage, key: string): DevtoolsJsonValue | undefined {
  try {
    const value = (message as unknown as Record<string, unknown>)[key];
    return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
      || value === null
      ? value
      : undefined;
  } catch {
    return "[unavailable]";
  }
}

export function reportDevtoolsError(
  options: ObserveHubOptions,
  error: unknown,
  context: DevtoolsErrorContext,
): void {
  try {
    options.onError?.(error, context);
  } catch {
    // Diagnostics must never destabilize the observed hub.
  }
}

function deepFreeze<T>(value: T): T {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const child of Object.values(value)) deepFreeze(child);
  return value;
}

const DEFAULT_TIMER_SCHEDULER: DevtoolsTimerScheduler = {
  schedule: (callback, delayMs) => setTimeout(callback, delayMs),
  cancel: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};
