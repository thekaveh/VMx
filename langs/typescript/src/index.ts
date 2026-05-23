/**
 * vmx — public re-exports.
 *
 * Import from "vmx" to access all public types.
 */

// Version
export { __version__, __minSpecVersion__ } from "./version.js";

// Lifecycle
export { ConstructionStatus } from "./lifecycle/status.js";
export { StatusTransitionError } from "./lifecycle/exceptions.js";
export {
  isLegal,
  requireTransition,
  finalState,
} from "./lifecycle/transitionValidator.js";

// Messages
export type { IMessage, ITypedMessage } from "./messages/types.js";
export { PropertyChangedMessage } from "./messages/propertyChanged.js";
export { ConstructionStatusChangedMessage } from "./messages/constructionStatusChanged.js";

// Collections
export type {
  CollectionChangedAction,
  CollectionChangedEvent,
} from "./collections/collectionChangedEvent.js";
export { makeCollectionChangedEvent } from "./collections/collectionChangedEvent.js";
export { BatchUpdateHandle } from "./collections/batchUpdateHandle.js";

// Services
export type { IMessageHub } from "./services/messageHub.js";
export { MessageHub } from "./services/messageHub.js";
export type { IDispatcher } from "./services/dispatcher.js";
export { RxDispatcher } from "./services/dispatcher.js";

// Commands
export type { ICommand, ICommandOf } from "./commands/types.js";
export {
  RelayCommand,
  RelayCommandBuilder,
  RelayCommandOf,
  RelayCommandOfBuilder,
} from "./commands/relayCommand.js";

// Components
export { ViewModelType } from "./components/types.js";
export type { IComponentVM, IComponentVMOf } from "./components/types.js";
export { ComponentVMBase } from "./components/componentVMBase.js";
export { ComponentVM, ComponentVMBuilder } from "./components/componentVM.js";
export {
  ComponentVMOf,
  ComponentVMOfBuilder,
} from "./components/componentVMOf.js";
export {
  ReadonlyComponentVMOf,
  ReadonlyComponentVMOfBuilder,
} from "./components/readonlyComponentVMOf.js";

// Composites
export { CompositeVMBase } from "./composites/compositeVMBase.js";
export { CompositeVM, CompositeVMBuilder } from "./composites/compositeVM.js";
export {
  CompositeVMOf,
  CompositeVMOfBuilder,
} from "./composites/compositeVMOf.js";

// Groups
export { GroupVM, GroupVMBuilder } from "./groups/groupVM.js";

// Aggregates
export {
  AggregateVM1,
  AggregateVM1Builder,
} from "./aggregates/aggregateVM1.js";
export {
  AggregateVM2,
  AggregateVM2Builder,
} from "./aggregates/aggregateVM2.js";
export {
  AggregateVM3,
  AggregateVM3Builder,
} from "./aggregates/aggregateVM3.js";
export {
  AggregateVM4,
  AggregateVM4Builder,
} from "./aggregates/aggregateVM4.js";
export {
  AggregateVM5,
  AggregateVM5Builder,
} from "./aggregates/aggregateVM5.js";

// Forwarding decorators
export { ForwardingComponentVM } from "./forwarding/forwardingComponentVM.js";
export { ForwardingCompositeVM } from "./forwarding/forwardingCompositeVM.js";

// Tree utilities
export { walk, find } from "./tree/walk.js";
