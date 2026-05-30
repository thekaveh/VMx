/**
 * NoteVM — leaf VM for a single note.
 *
 * Capabilities (scenario §6.2): ISelectable, IClosable, IDeletable<NoteVM>,
 * ISavable<NoteVM>, IReconstructable.
 *
 * `closeCommand` invokes a host-supplied close callback (the host wires it to
 * `NotesViewVM.current = null` so the form clears). This avoids back-
 * references from the leaf to its container. Same pattern as the C# / Python
 * flavors.
 */
import {
  ComponentVMBase,
  ConfirmationDecoratorCommand,
  ConstructionStatus,
  declareCapabilities,
  PropertyChangedMessage,
  RelayCommand,
  ViewModelType,
  type ICommand,
  type IDispatcher,
  type IMessageHub,
} from "vmx";
import {
  type INotificationHub,
  Notification,
  NotificationType,
} from "vmx/notifications";

import type { NoteModel } from "../models/noteModel.js";

const SENTINEL = Symbol("not-set");

type NoteHandler = (vm: NoteVM) => void;

export class NoteVM extends ComponentVMBase {
  readonly #onClose: NoteHandler | null;
  readonly #onDelete: NoteHandler | null;
  readonly #onSave: NoteHandler | null;
  readonly #confirmDelete: ((vm: NoteVM) => Promise<boolean>) | null;
  readonly #notificationHub: INotificationHub | null;
  readonly #closeCommand: RelayCommand;
  readonly #saveCommand: RelayCommand;
  readonly #innerDeleteCommand: RelayCommand;
  readonly #deleteCommand: ICommand;
  #model: NoteModel;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    model: NoteModel;
    onClose?: NoteHandler | null;
    onDelete?: NoteHandler | null;
    onSave?: NoteHandler | null;
    confirmDelete?: ((vm: NoteVM) => Promise<boolean>) | null;
    notificationHub?: INotificationHub | null;
  }) {
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#model = opts.model;
    this.#onClose = opts.onClose ?? null;
    this.#onDelete = opts.onDelete ?? null;
    this.#onSave = opts.onSave ?? null;
    this.#confirmDelete = opts.confirmDelete ?? null;
    this.#notificationHub = opts.notificationHub ?? null;
    declareCapabilities(
      this,
      "ISelectable",
      "IClosable",
      "IDeletable",
      "ISavable",
      "IReconstructable",
    );

    this.#closeCommand = RelayCommand.builder()
      .predicate(() => this.canClose())
      .task(() => this.close())
      .build();
    this.#saveCommand = RelayCommand.builder()
      .predicate(() => this.canSave(this))
      .task(() => this.save(this))
      .build();
    // Spec §5.2.8 / §6.2: when a confirm-delete delegate is wired, wrap the
    // delete in a ConfirmationDecoratorCommand. The inner command invokes
    // `#performDelete`, which posts a "Note deleted" notification (if a hub
    // is wired) and calls the host delete callback.
    this.#innerDeleteCommand = RelayCommand.builder()
      .predicate(() => this.canDelete(this))
      .task(() => this.#performDelete(this))
      .build();
    this.#deleteCommand =
      this.#confirmDelete !== null
        ? new ConfirmationDecoratorCommand(
            this.#innerDeleteCommand,
            () => this.#confirmDelete!(this),
          )
        : this.#innerDeleteCommand;
  }

  #performDelete(item: NoteVM): void {
    if (!this.canDelete(item)) return;
    if (this.#onDelete !== null) this.#onDelete(item);
    if (this.#notificationHub !== null) {
      void this.#notificationHub.post(
        new Notification(NotificationType.Notification, `Note deleted: “${item.title}”`),
      );
    }
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  get model(): NoteModel {
    return this.#model;
  }

  set model(value: NoteModel) {
    if (this.#model === value) return;
    const oldTitle = this.#model.title;
    const oldStarred = this.#model.starred;
    this.#model = value;
    this._hub.send(PropertyChangedMessage.create(this, this._name, "Model"));
    this._raisePropertyChanged("model");
    if (oldTitle !== value.title) {
      this._hub.send(PropertyChangedMessage.create(this, this._name, "Title"));
      this._raisePropertyChanged("title");
    }
    if (oldStarred !== value.starred) {
      this._hub.send(
        PropertyChangedMessage.create(this, this._name, "Starred"),
      );
      this._raisePropertyChanged("starred");
    }
  }

  /** Note id (proxy on `model`). */
  get noteId(): string {
    return this.#model.id;
  }

  get title(): string {
    return this.#model.title;
  }

  get body(): string {
    return this.#model.body;
  }

  get starred(): boolean {
    return this.#model.starred;
  }

  get tags(): readonly string[] {
    return this.#model.tags;
  }

  // ── IClosable ─────────────────────────────────────────────────────────────

  canClose(): boolean {
    return this.status === ConstructionStatus.Constructed;
  }

  close(): void {
    if (this.#onClose !== null) this.#onClose(this);
  }

  // ── IDeletable<NoteVM> ────────────────────────────────────────────────────

  canDelete(item: NoteVM): boolean {
    return item === this && this.status === ConstructionStatus.Constructed;
  }

  delete(item: NoteVM): void {
    if (!this.canDelete(item)) return;
    if (this.#onDelete !== null) this.#onDelete(item);
  }

  // ── ISavable<NoteVM> ──────────────────────────────────────────────────────

  canSave(item: NoteVM): boolean {
    return item === this && this.status === ConstructionStatus.Constructed;
  }

  save(item: NoteVM): void {
    if (!this.canSave(item)) return;
    if (this.#onSave !== null) this.#onSave(item);
  }

  get closeCommand(): ICommand {
    return this.#closeCommand;
  }

  get saveCommand(): ICommand {
    return this.#saveCommand;
  }

  get deleteCommand(): ICommand {
    return this.#deleteCommand;
  }

  protected override _onDispose(): void {
    this.#closeCommand.dispose();
    this.#saveCommand.dispose();
    // ConfirmationDecoratorCommand is not Disposable in VMx-TS; dispose the
    // raw inner RelayCommand explicitly to avoid leaking its CanExecute
    // subscriptions.
    this.#innerDeleteCommand.dispose();
    super._onDispose();
  }

  static builder(): NoteVMBuilder {
    return new NoteVMBuilder();
  }
}

export class NoteVMBuilder {
  #name: string | null = null;
  #hint = "";
  #model: NoteModel | typeof SENTINEL = SENTINEL;
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #onClose: NoteHandler | null = null;
  #onDelete: NoteHandler | null = null;
  #onSave: NoteHandler | null = null;
  #confirmDelete: ((vm: NoteVM) => Promise<boolean>) | null = null;
  #notificationHub: INotificationHub | null = null;

  constructor(from?: NoteVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#model = from.#model;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#onClose = from.#onClose;
      this.#onDelete = from.#onDelete;
      this.#onSave = from.#onSave;
      this.#confirmDelete = from.#confirmDelete;
      this.#notificationHub = from.#notificationHub;
    }
  }

  name(value: string): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#hint = value;
    return b;
  }

  model(value: NoteModel): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#model = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  onClose(fn: NoteHandler): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#onClose = fn;
    return b;
  }

  onDelete(fn: NoteHandler): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#onDelete = fn;
    return b;
  }

  onSave(fn: NoteHandler): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#onSave = fn;
    return b;
  }

  /** When set, `deleteCommand` is wrapped in a `ConfirmationDecoratorCommand`
   * calling this delegate. Typical host wiring:
   * `(vm) => dialogService.confirm(\`Delete "${vm.title}"?\`)`.
   */
  confirmDelete(fn: (vm: NoteVM) => Promise<boolean>): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#confirmDelete = fn;
    return b;
  }

  /** When set, a successful delete (post-confirm if any) posts a
   * "Note deleted" notification on the hub.
   */
  notificationHub(hub: INotificationHub): NoteVMBuilder {
    const b = new NoteVMBuilder(this);
    b.#notificationHub = hub;
    return b;
  }

  build(): NoteVM {
    if (this.#name === null) throw new Error("name is required");
    if (this.#model === SENTINEL) throw new Error("model is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("services (hub + dispatcher) are required");
    return new NoteVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      model: this.#model,
      onClose: this.#onClose,
      onDelete: this.#onDelete,
      onSave: this.#onSave,
      confirmDelete: this.#confirmDelete,
      notificationHub: this.#notificationHub,
    });
  }
}
