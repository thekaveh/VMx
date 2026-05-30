/**
 * CapabilityActionsVM — projects a focused VM's capability surface into a
 * flat list of `ActionVM`s for the capability-action bar (spec §14.4).
 *
 * VMx-API adaptation: TypeScript's interfaces are structural, but the
 * capability registry (CAP-020) requires explicit `declareCapabilities`
 * markers — we use `hasCapability` instead of `instanceof` checks for
 * capability discovery. NoteVM (the only example-defined target of
 * `IDeletable<NoteVM>` / `ISavable<NoteVM>`) is detected by `instanceof`
 * so we can wire the right argument.
 */
import { BehaviorSubject, map } from "rxjs";
import {
  ComponentVMBase,
  DerivedProperty,
  hasCapability,
  RelayCommand,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "vmx";

import { type ActionVM, makeActionVM } from "./actionVM.js";
import { NoteVM } from "./noteVM.js";

type FocusedGetter = () => object | null;

interface SelectionShape {
  canSelect(): boolean;
  select(): void;
}
interface DeselectionShape {
  canDeselect(): boolean;
  deselect(): void;
}
interface ToggleSelectionShape {
  canToggleSelection(): boolean;
  toggleSelection(): void;
}
interface ExpandShape {
  canExpand(): boolean;
  expand(): void;
}
interface CollapseShape {
  canCollapse(): boolean;
  collapse(): void;
}
interface ToggleExpansionShape {
  canToggleExpansion(): boolean;
  toggleExpansion(): void;
}
interface ClosableShape {
  canClose(): boolean;
  close(): void;
}
interface ApprovableShape {
  canApprove(): boolean;
  approve(): void;
}
interface CancelableShape {
  canCancel(): boolean;
  cancel(): void;
}
interface NewCreatableShape {
  canCreateNew(): boolean;
  createNew(): void;
}
interface ReconstructShape {
  canReconstruct(): boolean;
  reconstruct(): void;
}

export class CapabilityActionsVM extends ComponentVMBase {
  readonly #focusedGetter: FocusedGetter;
  readonly #focusSubject: BehaviorSubject<object | null>;
  readonly #actionsDerived: DerivedProperty<readonly ActionVM[]>;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    focusedGetter: FocusedGetter;
  }) {
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#focusedGetter = opts.focusedGetter;
    this.#focusSubject = new BehaviorSubject<object | null>(
      opts.focusedGetter(),
    );
    this.#actionsDerived = new DerivedProperty<readonly ActionVM[]>(
      this.#focusSubject.pipe(map((f) => CapabilityActionsVM.project(f))),
      null,
      null,
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  get focusedVM(): object | null {
    return this.#focusedGetter();
  }

  /** Live projection: list of (label, command) for the focused VM. */
  get actions(): DerivedProperty<readonly ActionVM[]> {
    return this.#actionsDerived;
  }

  /**
   * Re-projects the action list from the current focused VM. The host calls
   * this after focus changes (typically via a hub subscription).
   */
  recomputeActions(): void {
    this.#focusSubject.next(this.#focusedGetter());
  }

  static project(focused: object | null): readonly ActionVM[] {
    if (focused === null) return [];
    const out: ActionVM[] = [];

    if (hasCapability(focused, "ISelectable")) {
      const f = focused as SelectionShape;
      out.push(
        makeActionVM(
          "Select",
          RelayCommand.builder()
            .predicate(() => f.canSelect())
            .task(() => f.select())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "IDeselectable")) {
      const f = focused as DeselectionShape;
      out.push(
        makeActionVM(
          "Deselect",
          RelayCommand.builder()
            .predicate(() => f.canDeselect())
            .task(() => f.deselect())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "ISelectionTogglable")) {
      const f = focused as ToggleSelectionShape;
      out.push(
        makeActionVM(
          "Toggle Selection",
          RelayCommand.builder()
            .predicate(() => f.canToggleSelection())
            .task(() => f.toggleSelection())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "IExpandable")) {
      const f = focused as ExpandShape;
      out.push(
        makeActionVM(
          "Expand",
          RelayCommand.builder()
            .predicate(() => f.canExpand())
            .task(() => f.expand())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "ICollapsible")) {
      const f = focused as CollapseShape;
      out.push(
        makeActionVM(
          "Collapse",
          RelayCommand.builder()
            .predicate(() => f.canCollapse())
            .task(() => f.collapse())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "IExpansionTogglable")) {
      const f = focused as ToggleExpansionShape;
      out.push(
        makeActionVM(
          "Toggle Expansion",
          RelayCommand.builder()
            .predicate(() => f.canToggleExpansion())
            .task(() => f.toggleExpansion())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "IClosable")) {
      const f = focused as ClosableShape;
      out.push(
        makeActionVM(
          "Close",
          RelayCommand.builder()
            .predicate(() => f.canClose())
            .task(() => f.close())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "IApprovable")) {
      const f = focused as ApprovableShape;
      out.push(
        makeActionVM(
          "Approve",
          RelayCommand.builder()
            .predicate(() => f.canApprove())
            .task(() => f.approve())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "ICancelable")) {
      const f = focused as CancelableShape;
      out.push(
        makeActionVM(
          "Cancel",
          RelayCommand.builder()
            .predicate(() => f.canCancel())
            .task(() => f.cancel())
            .build(),
        ),
      );
    }
    if (hasCapability(focused, "INewCreatable")) {
      const f = focused as NewCreatableShape;
      out.push(
        makeActionVM(
          "New",
          RelayCommand.builder()
            .predicate(() => f.canCreateNew())
            .task(() => f.createNew())
            .build(),
        ),
      );
    }
    if (focused instanceof NoteVM) {
      const note = focused;
      if (hasCapability(focused, "ISavable")) {
        out.push(
          makeActionVM(
            "Save",
            RelayCommand.builder()
              .predicate(() => note.canSave(note))
              .task(() => note.save(note))
              .build(),
          ),
        );
      }
      if (hasCapability(focused, "IDeletable")) {
        out.push(
          makeActionVM(
            "Delete",
            RelayCommand.builder()
              .predicate(() => note.canDelete(note))
              .task(() => note.delete(note))
              .build(),
          ),
        );
      }
    }
    if (hasCapability(focused, "IReconstructable")) {
      const f = focused as ReconstructShape;
      out.push(
        makeActionVM(
          "Reconstruct",
          RelayCommand.builder()
            .predicate(() => f.canReconstruct())
            .task(() => f.reconstruct())
            .build(),
        ),
      );
    }
    return out;
  }

  protected override _onDispose(): void {
    this.#actionsDerived.dispose();
    this.#focusSubject.complete();
    super._onDispose();
  }

  static builder(): CapabilityActionsVMBuilder {
    return new CapabilityActionsVMBuilder();
  }
}

export class CapabilityActionsVMBuilder {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #focusedGetter: FocusedGetter | null = null;

  constructor(from?: CapabilityActionsVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#focusedGetter = from.#focusedGetter;
    }
  }

  name(value: string): CapabilityActionsVMBuilder {
    const b = new CapabilityActionsVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): CapabilityActionsVMBuilder {
    const b = new CapabilityActionsVMBuilder(this);
    b.#hint = value;
    return b;
  }

  services(
    hub: IMessageHub,
    dispatcher: IDispatcher,
  ): CapabilityActionsVMBuilder {
    const b = new CapabilityActionsVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  focusedGetter(getter: FocusedGetter): CapabilityActionsVMBuilder {
    const b = new CapabilityActionsVMBuilder(this);
    b.#focusedGetter = getter;
    return b;
  }

  build(): CapabilityActionsVM {
    if (this.#name === null) throw new Error("name is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("services are required");
    if (this.#focusedGetter === null)
      throw new Error("focusedGetter is required");
    return new CapabilityActionsVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      focusedGetter: this.#focusedGetter,
    });
  }
}
