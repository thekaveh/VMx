<script lang="ts">
  import { filter } from "rxjs";
  import {
    PropertyChangedMessage,
    type ComponentVMOf,
    type ICommand,
    type IMessageHub,
  } from "@thekaveh/vmx";
  import type { Note } from "./note";

  interface Props {
    vm: ComponentVMOf<Note>;
    hub: IMessageHub;
    saveCommand: ICommand;
  }

  const { vm, hub, saveCommand }: Props = $props();

  // A fresh box per update: a republished model keeps its reference.
  let note = $derived({ model: vm.model });

  $effect(() => {
    // Reading `vm` and `hub` here re-runs the effect, after its cleanup,
    // whenever either input changes.
    const source = vm;
    const subscription = hub.messages
      .pipe(
        filter(
          (m) =>
            m instanceof PropertyChangedMessage &&
            m.sender === source &&
            m.propertyName === "model",
        ),
      )
      .subscribe(() => {
        note = { model: source.model };
      });
    // Catch up with changes made between the render and the subscription.
    note = { model: source.model };
    return () => subscription.unsubscribe();
  });
</script>

<h1>{note.model.title}</h1>
<button onclick={() => saveCommand.execute()}>Save</button>
