/**
 * Test support: services, an event recorder, the stream-fed error sink and the diagnostics sink.
 */
import {
  type ComponentVMBase,
  ConstructionStatusChangedMessage,
  type IDispatcher,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "@thekaveh/vmx";
import { config } from "rxjs";
import { configureReactiveDiagnostics } from "../src/index.js";

export interface Services {
  readonly hub: MessageHub;
  readonly dispatcher: IDispatcher;
}

export function services(): Services {
  return { hub: new MessageHub(), dispatcher: RxDispatcher.immediate() };
}

export function base(s: Services, name: string): {
  name: string;
  hint: string;
  hub: MessageHub;
  dispatcher: IDispatcher;
} {
  return { name, hint: "", hub: s.hub, dispatcher: s.dispatcher };
}

/** Records hub and local property-change events, and status messages, in delivery order. */
export class Recorder {
  readonly events: string[] = [];

  constructor(hub: MessageHub, options: { readonly status?: boolean } = {}) {
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage) {
        this.events.push(`hub:${message.senderName}.${message.propertyName}`);
      } else if (options.status === true && message instanceof ConstructionStatusChangedMessage) {
        this.events.push(`status:${message.senderName}.${String(message.status)}`);
      }
    });
  }

  /** Also record the VM-local surface of `vm` (this activates it, R4.2 b). */
  local(vm: ComponentVMBase): this {
    vm.propertyChanged.subscribe((name) => this.events.push(`local:${vm.name}.${name}`));
    return this;
  }

  push(event: string): void {
    this.events.push(event);
  }

  take(): string[] {
    const copy = [...this.events];
    this.events.length = 0;
    return copy;
  }

  hubNames(): string[] {
    return this.events.filter((event) => event.startsWith("hub:")).map((event) => event.slice(4));
  }
}

/** Every error routed to rxjs `config.onUnhandledError` (the stream-fed route). */
export const unhandled: unknown[] = [];
config.onUnhandledError = (error: unknown): void => {
  unhandled.push(error);
};

/** Waits for the asynchronous stream-fed route, then returns and clears what arrived. */
export async function streamFed(): Promise<unknown[]> {
  await new Promise((resolve) => setTimeout(resolve, 5));
  const copy = [...unhandled];
  unhandled.length = 0;
  return copy;
}

/** Every development report since the last `captureReports()` (the default sink would print them). */
export const reports: string[] = [];
configureReactiveDiagnostics({ report: (message) => reports.push(message) });

/** Clears the reports and forgets which class and name pairs were reported. */
export function captureReports(): string[] {
  reports.length = 0;
  configureReactiveDiagnostics({ resetReports: true });
  return reports;
}

export function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/** A promise with its resolve and reject functions. */
export function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
