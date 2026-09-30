<script setup lang="ts">
import type { ComponentVMOf, ICommand, IMessageHub } from "@thekaveh/vmx";
import { useVm } from "./composables/useVm";
import type { Note } from "./note";

const props = defineProps<{
  vm: ComponentVMOf<Note>;
  hub: IMessageHub;
  saveCommand: ICommand;
}>();
const model = useVm(props.vm, props.hub, "model");
</script>

<template>
  <h1>{{ model.title }}</h1>
  <button @click="props.saveCommand.execute()">Save</button>
</template>
