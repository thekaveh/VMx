/**
 * Test-runner-neutral fixtures, recorders, doubles, and harnesses.
 *
 * Import from `@thekaveh/vmx/testing`; this surface is intentionally excluded
 * from the package root entry.
 */
export { RecordingMessageHub } from "./recordingMessageHub.js";
export {
  ManualDispatcher,
  createTestServices,
  type TestServices,
} from "./dispatchers.js";
export {
  PropertyChangeRecorder,
  CollectionChangeRecorder,
  ObservableListRecorder,
  recordPropertyChanges,
  recordCollectionChanges,
  recordObservableList,
  type PropertyChangeFilter,
  type CollectionChangeFilter,
  type ObservableListChange,
  type ObservableListMutationAction,
} from "./recorders.js";
export {
  CommandDouble,
  CommandDoubleOf,
  AsyncCommandDouble,
  type CommandDoubleOptions,
} from "./commandDoubles.js";
export {
  FormHarness,
  createFormHarness,
  type FormHarnessOptions,
} from "./formHarness.js";
