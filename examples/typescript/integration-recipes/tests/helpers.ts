import { defer, finalize, type Observable } from "rxjs";
import {
  ComponentVMOf,
  MessageHub,
  RelayCommand,
  RxDispatcher,
  type IMessage,
  type IMessageHub,
} from "@thekaveh/vmx";

/** A hub wrapper that counts binding subscriptions and their teardowns. */
export interface CountingHub extends IMessageHub {
  readonly subscriptions: number;
  readonly teardowns: number;
}

export function countingHub(inner: IMessageHub = new MessageHub()): CountingHub {
  let subscriptions = 0;
  let teardowns = 0;
  const messages: Observable<IMessage> = defer(() => {
    subscriptions += 1;
    return inner.messages.pipe(
      finalize(() => {
        teardowns += 1;
      }),
    );
  });
  return {
    messages,
    send: (message) => inner.send(message),
    get subscriptions() {
      return subscriptions;
    },
    get teardowns() {
      return teardowns;
    },
  };
}

export function constructedVm<M>(hub: IMessageHub, model: M, name = "note"): ComponentVMOf<M> {
  const vm = ComponentVMOf.builder<M>()
    .name(name)
    .model(model)
    .services(hub, RxDispatcher.immediate())
    .build();
  vm.construct();
  return vm;
}

export function countingCommand(): { command: RelayCommand; runs: () => number } {
  let runs = 0;
  const command = RelayCommand.builder()
    .task(() => {
      runs += 1;
    })
    .build();
  return { command, runs: () => runs };
}
