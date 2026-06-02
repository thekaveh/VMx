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
  type ICommand,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";

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
  // Edge-case backfill (readonly notebook gating): a dedicated *Add Note*
  // command whose `canExecute` predicate consults the host-supplied
  // `canAddNote` callback. The host (e.g. `WorkspaceVM`) wires this to
  // `!notesView.currentNotebookIsReadonly`. Defaults stay backward-compatible:
  // a no-op action and an always-true predicate.
  readonly #addNoteCommand: RelayCommand;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    focusedGetter: FocusedGetter;
    addNoteAction?: () => void;
    canAddNote?: () => boolean;
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
    const addNoteAction = opts.addNoteAction ?? ((): void => undefined);
    const canAddNote = opts.canAddNote ?? ((): boolean => true);
    this.#addNoteCommand = RelayCommand.builder()
      .predicate(canAddNote)
      .task(addNoteAction)
      .build();
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
   * Host-driven *Add Note* command.
   *
   * Edge-case backfill (readonly notebook gating): `canExecute` delegates
   * to the `canAddNote` callback supplied at construction. `WorkspaceVM`
   * wires the predicate to `!notesView.currentNotebookIsReadonly` so the
   * bar gates adding notes to readonly notebooks.
   */
  get addNoteCommand(): ICommand {
    return this.#addNoteCommand;
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
    // Save / Delete target NoteVM (the only example-defined VM implementing
    // ISavable<T> / IDeletable<T>). Scenario §6.2: each note saves /
    // deletes itself. Reuse `note.saveCommand` / `note.deleteCommand`
    // directly so the action-bar Delete fires the same
    // ConfirmationDecoratorCommand (and "Note deleted" notification) that
    // the in-list delete button uses — keeping the action-bar and the
    // in-list delete button behaviorally identical (parity with C#
    // CapabilityActionsVM.cs:121-131).
    if (focused instanceof NoteVM) {
      const note = focused;
      if (hasCapability(focused, "ISavable")) {
        out.push(makeActionVM("Save", note.saveCommand));
      }
      if (hasCapability(focused, "IDeletable")) {
        out.push(makeActionVM("Delete", note.deleteCommand));
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
    this.#addNoteCommand.dispose();
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
  #addNoteAction: (() => void) | null = null;
  #canAddNote: (() => boolean) | null = null;

  constructor(from?: CapabilityActionsVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#focusedGetter = from.#focusedGetter;
      this.#addNoteAction = from.#addNoteAction;
      this.#canAddNote = from.#canAddNote;
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

  /** Wire the *Add Note* command body (edge-case backfill). */
  addNoteAction(action: () => void): CapabilityActionsVMBuilder {
    const b = new CapabilityActionsVMBuilder(this);
    b.#addNoteAction = action;
    return b;
  }

  /**
   * Wire the *Add Note* command can-execute predicate.
   *
   * Used by `WorkspaceVM` to consult `notesView.currentNotebookIsReadonly`
   * so the bar disables *Add Note* against readonly notebooks.
   */
  canAddNote(predicate: () => boolean): CapabilityActionsVMBuilder {
    const b = new CapabilityActionsVMBuilder(this);
    b.#canAddNote = predicate;
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
      ...(this.#addNoteAction !== null
        ? { addNoteAction: this.#addNoteAction }
        : {}),
      ...(this.#canAddNote !== null ? { canAddNote: this.#canAddNote } : {}),
    });
  }
}
