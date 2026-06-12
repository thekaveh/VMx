/**
 * AggregateVM1<VM1> — arity-1 aggregate viewmodel.
 *
 * See spec/08-aggregate-vm.md and ADR-0007.
 */
import { ComponentVMBase } from "../components/componentVMBase.js";
import { ViewModelType } from "../components/types.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";

const SENTINEL = Symbol("not-set");

export class AggregateVM1<VM1 extends ComponentVMBase> extends ComponentVMBase {
  readonly #factory1: () => VM1;
  #component1: VM1 | null = null;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    factory1: () => VM1;
  }) {
    super(opts);
    this.#factory1 = opts.factory1;
  }

  get type(): ViewModelType {
    return ViewModelType.Aggregate;
  }

  get component1(): VM1 | null {
    return this.#component1;
  }

  protected override _onConstruct(): void {
    // On Reconstruct, the previous slot instance is in Destructed state but
    // still holds hub subscriptions and command Subjects. Dispose it before
    // overwriting so subscribers don't leak across the Reconstruct boundary.
    this.#component1?.dispose();
    this.#component1 = this.#factory1();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "component1"));
    this._raisePropertyChanged("component1");
    this.#component1.construct();
  }

  protected override _onDestruct(): void {
    this.#component1?.destruct();
  }

  override dispose(): void {
    // Depth-first dispose (LIFE-013): each component slot first, then self.
    // Matches the override pattern used by CompositeVMBase/GroupVM so that
    // subscribers observe child Disposed transitions before the aggregate's
    // own Disposed transition — a single dispose-ordering rule across all
    // container VM kinds.
    this.#component1?.dispose();
    super.dispose();
  }

  static builder<VM1 extends ComponentVMBase>(): AggregateVM1Builder<VM1> {
    return new AggregateVM1Builder<VM1>();
  }
}

export class AggregateVM1Builder<VM1 extends ComponentVMBase> {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #factory1: (() => VM1) | typeof SENTINEL = SENTINEL;

  constructor(from?: AggregateVM1Builder<VM1>) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#factory1 = from.#factory1;
    }
  }

  name(v: string): AggregateVM1Builder<VM1> { const b = new AggregateVM1Builder<VM1>(this); b.#name = v; return b; }
  hint(v: string): AggregateVM1Builder<VM1> { const b = new AggregateVM1Builder<VM1>(this); b.#hint = v; return b; }
  services(hub: IMessageHub, disp: IDispatcher): AggregateVM1Builder<VM1> { const b = new AggregateVM1Builder<VM1>(this); b.#hub = hub; b.#dispatcher = disp; return b; }
  component1(f: () => VM1): AggregateVM1Builder<VM1> { const b = new AggregateVM1Builder<VM1>(this); b.#factory1 = f; return b; }

  build(): AggregateVM1<VM1> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#hub === null || this.#dispatcher === null) throw new BuilderValidationError("services");
    if (this.#factory1 === SENTINEL) throw new BuilderValidationError("component1");
    const factory1 = this.#factory1;
    return new AggregateVM1<VM1>({ name: this.#name, hint: this.#hint, hub: this.#hub, dispatcher: this.#dispatcher, factory1 });
  }
}
