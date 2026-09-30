import { createSignal, onCleanup, type Accessor } from "solid-js";
import { filter } from "rxjs";
import {
  type ComponentVMOf,
  type ICommand,
  type IMessageHub,
  PropertyChangedMessage,
} from "@thekaveh/vmx";
import type { Note } from "./note";

/**
 * Binds one VM property for the owning component's lifetime. `vm` and `hub`
 * are read once, so they are fixed inputs: remount (for example with a keyed
 * `<Show>`) to rebind to another VM.
 */
export function useVm<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K,
): Accessor<ComponentVMOf<M>[K]> {
  // `equals: false`: a republished model keeps its reference but must render.
  const [value, setValue] = createSignal(vm[property], { equals: false });
  const sub = hub.messages
    .pipe(
      filter(
        (m): m is PropertyChangedMessage<unknown> =>
          m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === property,
      ),
    )
    .subscribe(() => setValue(() => vm[property]));
  onCleanup(() => sub.unsubscribe());
  return value;
}

export function NoteView(props: {
  vm: ComponentVMOf<Note>;
  hub: IMessageHub;
  saveCommand: ICommand;
}) {
  const model = useVm(props.vm, props.hub, "model");
  return (
    <>
      <h1>{model().title}</h1>
      <button onClick={() => props.saveCommand.execute()}>Save</button>
    </>
  );
}
