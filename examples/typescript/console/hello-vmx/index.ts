/**
 * hello-vmx — minimal console example for the VMx TypeScript library.
 *
 * Demonstrates:
 *   1. Building a ComponentVMOf<UserModel> with the fluent builder.
 *   2. Subscribing to hub messages (ConstructionStatusChangedMessage + PropertyChangedMessage).
 *   3. The full lifecycle: Destruct → Construct → model mutations → Destruct → Dispose.
 *   4. The equality guard: setting the same model value emits no hub message.
 *
 * Run with:
 *   npx tsx index.ts      (from this directory, with vmx installed)
 */

import {
  ComponentVMOf,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "vmx";

// ---------------------------------------------------------------------------
// Domain model
// ---------------------------------------------------------------------------

interface UserModel {
  readonly name: string;
  readonly age: number;
}

// ---------------------------------------------------------------------------
// Demo
// ---------------------------------------------------------------------------

function run(): void {
  console.log("=== hello-vmx ===\n");

  // Infrastructure: shared hub + immediate dispatcher.
  const hub = new MessageHub();
  const dispatcher = RxDispatcher.immediate();

  // Subscribe to hub messages before building the VM.
  const hubSub = hub.messages.subscribe((msg) => {
    if (msg instanceof ConstructionStatusChangedMessage) {
      console.log(`  [hub] ${msg.senderName}  status → ${ConstructionStatus[msg.status]}`);
    } else if (msg instanceof PropertyChangedMessage) {
      console.log(`  [hub] ${msg.senderName}  property '${msg.propertyName}' changed`);
    }
  });

  // Build the VM.
  console.log("Building ComponentVMOf<UserModel> ...");
  const vm = ComponentVMOf.builder<UserModel>()
    .name("user-vm")
    .hint("Displays the current user")
    .services(hub, dispatcher)
    .model({ name: "Alice", age: 30 })
    .modeledHinter((u) => `${u.name} (${u.age})`)
    .onConstruct(() => console.log("  [lifecycle] onConstruct callback fired"))
    .onDestruct(() => console.log("  [lifecycle] onDestruct callback fired"))
    .build();

  console.log(`  vm.name   = ${vm.name}`);
  console.log(`  vm.status = ${ConstructionStatus[vm.status]}`);
  console.log(`  vm.model  = ${JSON.stringify(vm.model)}`);
  console.log();

  // Construct.
  console.log("Calling construct() ...");
  vm.construct();
  console.log(`  vm.status         = ${ConstructionStatus[vm.status]}`);
  console.log(`  vm.isConstructed  = ${vm.isConstructed}`);
  console.log(`  vm.modeledHint    = ${JSON.stringify(vm.modeledHint)}`);
  console.log();

  // Mutate the model.
  console.log("Mutating model → { name: 'Bob', age: 25 } ...");
  vm.model = { name: "Bob", age: 25 };
  console.log(`  vm.model       = ${JSON.stringify(vm.model)}`);
  console.log(`  vm.modeledHint = ${JSON.stringify(vm.modeledHint)}`);
  console.log();

  console.log("Mutating model → { name: 'Carol', age: 40 } ...");
  vm.model = { name: "Carol", age: 40 };
  console.log(`  vm.model       = ${JSON.stringify(vm.model)}`);
  console.log(`  vm.modeledHint = ${JSON.stringify(vm.modeledHint)}`);
  console.log();

  // Equality guard — same reference, no hub message expected.
  console.log("Setting SAME model value (equality guard — no hub message expected) ...");
  const current = vm.model;
  vm.model = current;
  console.log();

  // Destruct.
  console.log("Calling destruct() ...");
  vm.destruct();
  console.log(`  vm.status         = ${ConstructionStatus[vm.status]}`);
  console.log(`  vm.isConstructed  = ${vm.isConstructed}`);
  console.log();

  // Cleanup.
  hubSub.unsubscribe();
  vm.dispose();
  hub.dispose();

  console.log("=== Done ===");
}

run();
