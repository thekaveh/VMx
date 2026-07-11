/**
 * vmx — public re-exports.
 *
 * Import from "@thekaveh/vmx" to access all public types.
 */

// Version
export { __version__, __minSpecVersion__ } from "./version.js";

// Builders
export { BuilderValidationError } from "./builders/exceptions.js";

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
export { propertyValueChangedMessagesFor } from "./messages/propertyValueChanged.js";
export { whenPropertyChanged } from "./messages/whenPropertyChanged.js";
export { ConstructionStatusChangedMessage } from "./messages/constructionStatusChanged.js";
export { TreeStructureChangedMessage } from "./messages/treeStructureChanged.js";
export type { TreeStructureChange } from "./messages/treeStructureChanged.js";

// Collections
export type {
  CollectionChangedAction,
  CollectionChangedEvent,
} from "./collections/collectionChangedEvent.js";
export { makeCollectionChangedEvent } from "./collections/collectionChangedEvent.js";
export { BatchUpdateHandle, type IBatchable } from "./collections/batchUpdateHandle.js";
export type { IVmCollection, ISelectableVmCollection } from "./collections/vmCollection.js";
export { ServicedObservableCollection } from "./collections/servicedObservableCollection.js";
export {
  ObservableList,
  type ItemAddedEvent,
  type ItemRemovedEvent,
  type ItemReplacedEvent,
} from "./collections/observableList.js";
export {
  ObservableDictionary,
  type DictionaryEntry,
  type DictionaryItemAddedEvent,
  type DictionaryItemRemovedEvent,
  type DictionaryItemReplacedEvent,
} from "./collections/observableDictionary.js";
export {
  PagedComposition,
  type PagedCompositionSource,
} from "./collections/pagedComposition.js";
export {
  TokenPagedComposition,
  type TokenPage,
  type TokenPagedCompositionOptions,
} from "./collections/tokenPagedComposition.js";

// Collection messages
export type { CollectionMutationAction, ICollectionChangedMessage } from "./messages/collectionChanged.js";
export { CollectionChangedMessage } from "./messages/collectionChanged.js";

// Services
export type {
  IMessageHub,
  ITransactionalMessageHub,
  MessageHubOptions,
} from "./services/messageHub.js";
export { MessageHub } from "./services/messageHub.js";
export type { IDispatcher } from "./services/dispatcher.js";
export { RxDispatcher } from "./services/dispatcher.js";
export { NullMessageHub } from "./services/nullMessageHub.js";
export { NullDispatcher } from "./services/nullDispatcher.js";

// State helpers
export { DiscriminatorVM } from "./state/discriminatorVM.js";

// Commands
export type { ICommand, ICommandOf, IAsyncCommand } from "./commands/types.js";
export {
  RelayCommand,
  RelayCommandBuilder,
  RelayCommandOf,
  RelayCommandOfBuilder,
} from "./commands/relayCommand.js";
export {
  AsyncRelayCommand,
  AsyncRelayCommandBuilder,
} from "./commands/asyncRelayCommand.js";
export { CompositeCommand } from "./commands/compositeCommand.js";
export {
  DecoratorCommand,
  type DecoratorCommandOptions,
} from "./commands/decoratorCommand.js";
export {
  ConfirmationDecoratorCommand,
  type ConfirmDelegate,
} from "./commands/confirmationDecoratorCommand.js";
export {
  ModeledCrudCommands,
  type ModeledCrudCommandsOptions,
} from "./commands/modeledCrudCommands.js";
export {
  confirm,
  confirmWithDialogService,
  precedeWith,
  succeedWith,
  wrapWith,
} from "./commands/fluent.js";

// Components
export { ViewModelType } from "./components/types.js";
export type { IComponentVM, IComponentVMOf } from "./components/types.js";
export { ComponentVMBase, type IParentVM } from "./components/componentVMBase.js";
export { ComponentVM, ComponentVMBuilder } from "./components/componentVM.js";
export type { ComponentVMOptions } from "./components/componentVM.js";
export {
  ComponentVMOf,
  ComponentVMOfBuilder,
} from "./components/componentVMOf.js";
export type { ComponentVMOfOptions } from "./components/componentVMOf.js";
export {
  ReadonlyComponentVMOf,
  ReadonlyComponentVMOfBuilder,
} from "./components/readonlyComponentVMOf.js";

// Composites
export { CompositeVMBase } from "./composites/compositeVMBase.js";
export { CompositeVM, CompositeVMBuilder } from "./composites/compositeVM.js";
export type { CompositeVMOptions } from "./composites/compositeVM.js";
export {
  CompositeVMOf,
  CompositeVMOfBuilder,
} from "./composites/compositeVMOf.js";
export {
  FilteredCompositeVM,
  FilteredCursorPolicy,
  type FilteredCompositeOptions,
} from "./composites/filteredCompositeVM.js";
export {
  ScoredFilteredCompositeVM,
  type ScoredFilteredCompositeOptions,
} from "./composites/scoredFilteredCompositeVM.js";

// Groups
export { GroupVM, GroupVMBuilder } from "./groups/groupVM.js";
export type { GroupVMOptions } from "./groups/groupVM.js";

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
export {
  AggregateVM6,
  AggregateVM6Builder,
} from "./aggregates/aggregateVM6.js";

// Forwarding decorators
export { ForwardingComponentVM } from "./forwarding/forwardingComponentVM.js";
export { ForwardingCompositeVM } from "./forwarding/forwardingCompositeVM.js";

// Tree utilities
export { walk, find, walkExpanded } from "./tree/walk.js";

// Hierarchical VM (spec v2.1)
export {
  BatchAttachRejectionReason,
  HierarchicalVM,
  HierarchicalVMBuilder,
  MissingParentPolicy,
} from "./hierarchical/hierarchicalVm.js";
export type {
  BatchAttachOptions,
  BatchAttachRejection,
  BatchAttachResult,
  HierarchicalVMOptions,
  HierarchicalVMConstructionContext,
} from "./hierarchical/hierarchicalVm.js";

// Dialogs (spec v2.1)
export type {
  IDialogService,
  IModalDialogService,
  FileFilter,
  NotificationSeverity,
} from "./dialogs/dialogService.js";
export { ModalVM } from "./dialogs/modalVM.js";
export { NullDialogService } from "./dialogs/nullDialogService.js";

// Forms (spec v2.1)
export { FormVM, FormVMBuilder } from "./forms/formVm.js";
export type { FormVMOptions, Persister, ResetOnApproved, Snapshotter } from "./forms/formVm.js";
export { FormRevertedMessage } from "./messages/formReverted.js";

// Expandable state helper (spec v2.0)
export { ExpandableState } from "./capabilities/expandableState.js";

// Searchable state helper (spec v2.0)
export {
  SearchableState,
  type SearchableStateOptions,
} from "./capabilities/searchableState.js";

// Derived properties (spec v2.0)
export {
  DerivedProperty,
  type DerivedFromSourcesOptions,
  fromFive,
  fromFour,
  fromMany,
  fromOne,
  fromSources,
  fromThree,
  fromTwo,
} from "./properties/index.js";

// Localization (spec v2.0)
export type { ILocalizer } from "./localization/localizer.js";
export { NullLocalizer } from "./localization/nullLocalizer.js";

// Capabilities (spec v2.0)
export {
  CAPABILITIES,
  type CapabilityName,
  declareCapabilities,
  hasCapability,
} from "./capabilities/registry.js";
export type {
  IDeselectable,
  ISelectable,
  ISelectionTogglable,
} from "./capabilities/selection.js";
export type {
  ICollapsible,
  IExpandable,
  IExpansionTogglable,
} from "./capabilities/expansion.js";
export type {
  IConstructable,
  IDestructable,
  IReconstructable,
} from "./capabilities/lifecycleCapabilities.js";
export type {
  IApprovable,
  ICancelable,
  IClosable,
} from "./capabilities/dialog.js";
export type { ISearchable } from "./capabilities/search.js";
export type {
  IDeletable,
  INewCreatable,
  ISavable,
  IUpdatable,
} from "./capabilities/crud.js";
export type {
  ICurrentDeletable,
  ICurrentUpdatable,
} from "./capabilities/currentCrud.js";
export type { IManagable } from "./capabilities/management.js";
export type { IFilterable } from "./capabilities/filter.js";
export type { IPageable } from "./capabilities/pageable.js";
