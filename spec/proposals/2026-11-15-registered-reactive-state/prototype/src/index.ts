/**
 * A working prototype of registered reactive state for VMx view-models (V1 to V7 of README.md §1.2), on top of the
 * unchanged VMx 3.30.0. Importing this module installs the helpers on ComponentVMBase.prototype.
 */
import "./augment.js";
import { installReactiveHelpers } from "./helpers.js";
import { installLibraryRules } from "./library.js";

installReactiveHelpers();
installLibraryRules();

export { activate, explain, read, tracked } from "./bridge.js";
export { configureReactiveDiagnostics, type ReactiveDiagnosticsOptions } from "./diagnostics.js";
export { type Equality, shallowEqual } from "./equality.js";
export { ReactiveCycleError, ReactiveOverflowError, ReactiveWriteError } from "./errors.js";
export { untracked } from "./graph.js";
export type {
  AsyncCommandOptions,
  CommandOptions,
  ExplainEntry,
  FollowKeyOptions,
  KeyedResourceOptions,
  Memo,
  ReactionOptions,
  Signal,
  StateWriter,
} from "./types.js";
export { find, walk, walkExpanded } from "./walk.js";
