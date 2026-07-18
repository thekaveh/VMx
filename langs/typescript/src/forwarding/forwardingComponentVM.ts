/**
 * ForwardingComponentVM<M> — forwarding decorator for IComponentVMOf<M>.
 *
 * Every member delegates to the wrapped VM by default.
 * Subclasses override individual members to customize behavior.
 *
 * See spec/09-forwarding.md §ForwardingComponentVM.
 */
import type { Observable } from "rxjs";
import type { ConstructionStatus } from "../lifecycle/status.js";
import type { IComponentVMOf, ViewModelType } from "../components/types.js";
import { RelayCommand } from "../commands/relayCommand.js";
import type { IMessageHub } from "../services/messageHub.js";
import {
  ComponentVMBase,
  type IOwningParentVM,
  ParentTransfer,
} from "../components/componentVMBase.js";
import { NullDispatcher } from "../services/nullDispatcher.js";

class ForwardingParent<M> implements IOwningParentVM {
  constructor(
    private readonly parent: IOwningParentVM,
    private readonly wrapper: ForwardingComponentVM<M>,
  ) {}

  get owner(): ComponentVMBase { return this.parent.owner; }
  get ownerParent(): IOwningParentVM | null { return this.parent.ownerParent; }
  get supportsChildSelection(): boolean { return this.parent.supportsChildSelection; }
  get currentChild(): ComponentVMBase | null {
    return this.parent.currentChild === this.wrapper
      ? this.wrapper.wrappedBase
      : this.parent.currentChild;
  }
  selectChild(_vm: ComponentVMBase): void { this.parent.selectChild(this.wrapper); }
  deselectChild(_vm: ComponentVMBase): void { this.parent.deselectChild(this.wrapper); }
  containsChild(_vm: ComponentVMBase): boolean { return this.parent.containsChild(this.wrapper); }
  detachForTransfer(_vm: ComponentVMBase): ParentTransfer {
    return this.parent.detachForTransfer(this.wrapper);
  }
}

export class ForwardingComponentVM<M> extends ComponentVMBase implements IComponentVMOf<M> {
  protected readonly _wrapped: IComponentVMOf<M>;

  constructor(wrapped: IComponentVMOf<M>) {
    super({
      name: wrapped.name,
      hint: wrapped.hint,
      hub: wrapped.hub,
      dispatcher: NullDispatcher.INSTANCE,
    });
    this._wrapped = wrapped;
  }

  get wrappedBase(): ComponentVMBase {
    if (!(this._wrapped instanceof ComponentVMBase)) {
      throw new TypeError("A forwarding container child must wrap a VMx ComponentVMBase");
    }
    return this._wrapped;
  }

  override get _parent(): IOwningParentVM | null { return super._parent; }
  override set _parent(parent: IOwningParentVM | null) {
    super._parent = parent;
    if (this._wrapped instanceof ComponentVMBase) {
      this._wrapped._parent = parent === null ? null : new ForwardingParent(parent, this);
    }
  }

  get name(): string { return this._wrapped.name; }
  get hint(): string { return this._wrapped.hint; }
  get type(): ViewModelType { return this._wrapped.type; }
  get isCurrent(): boolean { return this._wrapped.isCurrent; }
  get isConstructed(): boolean { return this._wrapped.isConstructed; }
  get status(): ConstructionStatus { return this._wrapped.status; }
  get hub(): IMessageHub { return this._wrapped.hub; }
  get model(): M { return this._wrapped.model; }
  // Delegate the model setter too (spec/09-forwarding.md §1 — the decorator
  // forwards every member; the modeled component's `model` is settable). Matches
  // C#/Python/Swift ForwardingComponentVM and TS ForwardingCompositeVM.set current.
  set model(value: M) { this._wrapped.model = value; }
  get modeledHint(): string { return this._wrapped.modeledHint; }
  republishModel(): void { this._wrapped.republishModel(); }
  get propertyChanged(): Observable<string> { return this._wrapped.propertyChanged; }
  get selectCommand(): RelayCommand { return this._wrapped.selectCommand as RelayCommand; }
  get deselectCommand(): RelayCommand { return this._wrapped.deselectCommand as RelayCommand; }
  get selectNextCommand(): RelayCommand { return this._wrapped.selectNextCommand as RelayCommand; }
  get selectPreviousCommand(): RelayCommand {
    return this._wrapped.selectPreviousCommand as RelayCommand;
  }
  get reconstructCommand(): RelayCommand { return this._wrapped.reconstructCommand as RelayCommand; }

  override _setIsCurrent(value: boolean): void {
    if (this._wrapped instanceof ComponentVMBase) this._wrapped._setIsCurrent(value);
  }

  canConstruct(): boolean { return this._wrapped.canConstruct(); }
  construct(): void { this._wrapped.construct(); }
  canDestruct(): boolean { return this._wrapped.canDestruct(); }
  destruct(): void { this._wrapped.destruct(); }
  canReconstruct(): boolean { return this._wrapped.canReconstruct(); }
  reconstruct(): void { this._wrapped.reconstruct(); }
  dispose(): void { this._wrapped.dispose(); }
  canSelect(): boolean { return this._wrapped.canSelect(); }
  select(): void { this._wrapped.select(); }
  canDeselect(): boolean { return this._wrapped.canDeselect(); }
  deselect(): void { this._wrapped.deselect(); }
}
