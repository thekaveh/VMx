import { Observable } from "rxjs";
import { afterEach, describe, expect, it } from "vitest";
import { PropertyChangedMessage } from "../../../src/messages/propertyChanged.js";
import type { IMessage } from "../../../src/messages/types.js";
import { MessageHub, type IMessageHub } from "../../../src/services/messageHub.js";
import {
  connectReduxDevtools,
  type DevtoolsErrorContext,
  type ReduxDevtoolsExtension,
  type ReduxDevtoolsTransport,
} from "../../../src/devtools/index.js";

class RecordingTransport implements ReduxDevtoolsTransport {
  readonly initial: unknown[] = [];
  readonly sent: Array<{ action: unknown; state: unknown }> = [];
  listener: ((message: unknown) => void) | undefined;
  unsubscribed = 0;

  init(state: unknown): void {
    this.initial.push(state);
  }

  send(action: unknown, state: unknown): void {
    this.sent.push({ action, state });
  }

  subscribe(listener: (message: unknown) => void): () => void {
    this.listener = listener;
    return () => { this.unsubscribed += 1; };
  }

  unsubscribe(): void {
    this.unsubscribed += 1;
  }
}

class RecordingExtension implements ReduxDevtoolsExtension {
  readonly names: string[] = [];
  readonly transports: RecordingTransport[] = [];

  connect(options: { readonly name: string }): ReduxDevtoolsTransport {
    this.names.push(options.name);
    const transport = new RecordingTransport();
    this.transports.push(transport);
    return transport;
  }
}

afterEach(() => {
  Reflect.deleteProperty(globalThis, "__REDUX_DEVTOOLS_EXTENSION__");
});

describe("connectReduxDevtools", () => {
  it("connects by stable name, initializes explicit snapshots, and sends safe events", () => {
    const hub = new MessageHub();
    const extension = new RecordingExtension();
    let route = "gallery";
    const connection = connectReduxDevtools(hub, {
      name: "DayDreams",
      extension,
      snapshots: [{ name: "app", select: () => ({ route }) }],
    });

    route = "world";
    hub.send(PropertyChangedMessage.create({ secret: "no" }, "AppVM", "route"));

    expect(extension.names).toEqual(["DayDreams"]);
    expect(extension.transports[0]?.initial).toEqual([{ app: { route: "gallery" } }]);
    expect(extension.transports[0]?.sent).toHaveLength(1);
    expect(extension.transports[0]?.sent[0]?.action).toEqual(expect.objectContaining({
      type: "PropertyChangedMessage/AppVM/route",
      senderName: "AppVM",
      sequence: 1,
    }));
    expect(extension.transports[0]?.sent[0]?.state).toEqual({ app: { route: "world" } });

    connection.dispose();
    connection.dispose();
    expect(extension.transports[0]?.unsubscribed).toBe(2);
    hub.dispose();
  });

  it("discovers the guarded global extension without importing Redux", () => {
    const hub = new MessageHub();
    const extension = new RecordingExtension();
    Object.defineProperty(globalThis, "__REDUX_DEVTOOLS_EXTENSION__", {
      configurable: true,
      value: extension,
    });

    const connection = connectReduxDevtools(hub, { name: "global" });
    hub.send(PropertyChangedMessage.create({}, "VM", "model"));

    expect(extension.names).toEqual(["global"]);
    expect(extension.transports[0]?.sent).toHaveLength(1);
    connection.dispose();
    hub.dispose();
  });

  it("does zero hub, selector, timer, or transport work when disconnected", () => {
    let subscriptions = 0;
    let selections = 0;
    let schedules = 0;
    const hub: IMessageHub = {
      messages: new Observable<IMessage>(() => {
        subscriptions += 1;
        return () => undefined;
      }),
      send: () => undefined,
    };

    const connection = connectReduxDevtools(hub, {
      extension: null,
      snapshots: [{ name: "state", select: () => ++selections }],
      throttleMs: 1,
      timerScheduler: {
        schedule: () => { schedules += 1; return 1; },
        cancel: () => undefined,
      },
    });

    connection.dispose();
    connection.dispose();
    expect({ subscriptions, selections, schedules }).toEqual({
      subscriptions: 0,
      selections: 0,
      schedules: 0,
    });
  });

  it("isolates connect, init, send, and unsubscribe failures", () => {
    const errors: Array<{ message: string; context: DevtoolsErrorContext }> = [];
    const onError = (error: unknown, context: DevtoolsErrorContext): void => {
      errors.push({ message: (error as Error).message, context });
    };
    const hub = new MessageHub();
    const connectFailure = connectReduxDevtools(hub, {
      extension: { connect: () => { throw new Error("connect failed"); } },
      onError,
    });
    connectFailure.dispose();

    const transport: ReduxDevtoolsTransport = {
      init: () => { throw new Error("init failed"); },
      send: () => { throw new Error("send failed"); },
      subscribe: () => () => { throw new Error("listener unsubscribe failed"); },
      unsubscribe: () => { throw new Error("transport unsubscribe failed"); },
    };
    const connection = connectReduxDevtools(hub, {
      extension: { connect: () => transport },
      onError,
    });
    hub.send(PropertyChangedMessage.create({}, "VM", "model"));
    connection.dispose();

    expect(errors.map(({ message }) => message)).toEqual([
      "connect failed",
      "init failed",
      "send failed",
      "listener unsubscribe failed",
      "transport unsubscribe failed",
    ]);
    expect(errors.map(({ context }) => context.phase)).toEqual([
      "transport-connect",
      "transport-init",
      "transport-send",
      "transport-dispose",
      "transport-dispose",
    ]);
    hub.dispose();
  });

  it("isolates hostile transport method getters and malformed transports", () => {
    const errors: Array<{ message: string; context: DevtoolsErrorContext }> = [];
    const onError = (error: unknown, context: DevtoolsErrorContext): void => {
      errors.push({ message: (error as Error).message, context });
    };
    const hub = new MessageHub();
    const malformed = connectReduxDevtools(hub, {
      extension: { connect: () => null as never },
      onError,
    });
    malformed.dispose();

    const subscribeGetter = connectReduxDevtools(hub, {
      extension: {
        connect: () => ({
          init: () => undefined,
          send: () => undefined,
          get subscribe(): never { throw new Error("subscribe getter failed"); },
        }),
      },
      onError,
    });
    subscribeGetter.dispose();

    const unsubscribeGetter = connectReduxDevtools(hub, {
      extension: {
        connect: () => ({
          init: () => undefined,
          send: () => undefined,
          get unsubscribe(): never { throw new Error("unsubscribe getter failed"); },
        }),
      },
      onError,
    });
    expect(() => unsubscribeGetter.dispose()).not.toThrow();

    expect(errors.map(({ message }) => message)).toEqual([
      "Redux DevTools connect() returned an invalid transport",
      "subscribe getter failed",
      "unsubscribe getter failed",
    ]);
    expect(errors.map(({ context }) => context.phase)).toEqual([
      "transport-connect",
      "transport-subscribe",
      "transport-dispose",
    ]);
    hub.dispose();
  });

  it("ignores inbound dispatch messages and keeps concurrent adapters independent", () => {
    const firstHub = new MessageHub();
    const secondHub = new MessageHub();
    const extension = new RecordingExtension();
    let firstState = 1;
    const first = connectReduxDevtools(firstHub, {
      name: "first",
      extension,
      snapshots: [{ name: "value", select: () => firstState }],
    });
    const second = connectReduxDevtools(secondHub, { name: "second", extension });

    extension.transports[0]?.listener?.({ type: "DISPATCH", state: "{\"value\":99}" });
    firstState = 2;
    firstHub.send(PropertyChangedMessage.create({}, "FirstVM", "value"));
    secondHub.send(PropertyChangedMessage.create({}, "SecondVM", "value"));
    first.dispose();
    const reconnected = connectReduxDevtools(firstHub, { name: "first", extension });
    firstHub.send(PropertyChangedMessage.create({}, "FirstVM", "value"));

    expect(extension.names).toEqual(["first", "second", "first"]);
    expect(extension.transports[0]?.sent[0]?.state).toEqual({ value: 2 });
    expect(extension.transports[0]?.sent[0]?.action).toEqual(expect.objectContaining({ sequence: 1 }));
    expect(extension.transports[1]?.sent[0]?.action).toEqual(expect.objectContaining({ sequence: 1 }));
    expect(extension.transports[2]?.sent[0]?.action).toEqual(expect.objectContaining({ sequence: 1 }));
    second.dispose();
    reconnected.dispose();
    firstHub.dispose();
    secondHub.dispose();
  });
});
