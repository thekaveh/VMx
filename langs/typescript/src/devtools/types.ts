import type { IMessage } from "../messages/types.js";

export type DevtoolsJsonPrimitive = string | number | boolean | null;
export type DevtoolsJsonValue =
  | DevtoolsJsonPrimitive
  | readonly DevtoolsJsonValue[]
  | { readonly [key: string]: DevtoolsJsonValue };

export interface DevtoolsAction {
  readonly type: string;
  readonly messageType: string;
  readonly senderName: string;
  readonly sequence: number;
  readonly details?: Readonly<Record<string, DevtoolsJsonValue>>;
}

export interface DevtoolsEvent {
  readonly name: string;
  readonly timestamp: number;
  readonly action: DevtoolsAction;
  readonly state: Readonly<Record<string, DevtoolsJsonValue>>;
}

export type DevtoolsSink =
  | ((event: DevtoolsEvent) => void)
  | {
    next(event: DevtoolsEvent): void;
    complete?(): void;
  };

export interface SnapshotSource {
  readonly name: string;
  select(): unknown;
  serialize?(value: unknown): unknown;
}

export interface DevtoolsSerializationLimits {
  readonly maxDepth?: number;
  readonly maxStringLength?: number;
  readonly maxArrayLength?: number;
  readonly maxObjectKeys?: number;
}

export type DevtoolsErrorPhase =
  | "clock"
  | "allow-filter"
  | "deny-filter"
  | "map-action"
  | "select-snapshot"
  | "serialize-snapshot"
  | "redact"
  | "sanitize"
  | "schedule"
  | "sink"
  | "transport-connect"
  | "transport-init"
  | "transport-send"
  | "transport-subscribe"
  | "transport-dispose";

export interface DevtoolsErrorContext {
  readonly phase: DevtoolsErrorPhase;
  readonly sequence: number;
  readonly snapshotName?: string;
}

export interface DevtoolsRedactionContext {
  readonly kind: "action" | "state";
  readonly sequence: number;
  readonly snapshotName?: string;
}

export interface ObserveHubOptions {
  readonly name?: string;
  readonly snapshots?: readonly SnapshotSource[];
  readonly allow?: (message: IMessage) => boolean;
  readonly deny?: (message: IMessage) => boolean;
  readonly mapAction?: (message: IMessage, fallback: DevtoolsAction) => unknown;
  readonly redact?: (value: unknown, context: DevtoolsRedactionContext) => unknown;
  readonly limits?: DevtoolsSerializationLimits;
  readonly sampleEvery?: number;
  readonly throttleMs?: number;
  readonly timerScheduler?: DevtoolsTimerScheduler;
  readonly now?: () => number;
  readonly onError?: (error: unknown, context: DevtoolsErrorContext) => void;
}

export interface DevtoolsTimerScheduler {
  schedule(callback: () => void, delayMs: number): unknown;
  cancel(handle: unknown): void;
}

export interface DevtoolsConnection {
  dispose(): void;
}
