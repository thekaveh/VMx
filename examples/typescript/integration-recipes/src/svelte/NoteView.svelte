<script lang="ts">
  import type { ComponentVMOf, ICommand, IMessageHub } from "@thekaveh/vmx";
  import type { Note } from "./note";
  import { vmStore } from "./vmStore";

  export let vm: ComponentVMOf<Note>;
  export let hub: IMessageHub;
  export let saveCommand: ICommand;

  // A new vm or hub creates a new store; `$model` moves to it and releases
  // the old one.
  $: model = vmStore(vm, hub, "model");
</script>

<h1>{$model.title}</h1>
<button on:click={() => saveCommand.execute()}>Save</button>
