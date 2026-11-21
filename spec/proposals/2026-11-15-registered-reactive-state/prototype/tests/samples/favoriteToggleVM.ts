/**
 * Sample view-model: a favorite toggle over a store that lives outside the graph, so the view-model re-reads it with
 * `invalidate()` after each change it makes or learns about.
 */
import { ComponentVM, type IDispatcher, type IMessageHub } from "@thekaveh/vmx";

export const FAVORITE_TEXT = { favorite: "Favorite", unfavorite: "Unfavorite" } as const;

export interface FavoriteRef {
  readonly list: string;
  readonly item: string;
}

/** The application's favorites store: outside the graph. */
export interface FavoriteStore {
  has(ref: FavoriteRef, favoriteByDefault: boolean): boolean;
  add(ref: FavoriteRef, favoriteByDefault: boolean): void;
  remove(ref: FavoriteRef, favoriteByDefault: boolean): void;
}

export interface FavoriteToggleVMOptions {
  readonly hub: IMessageHub;
  readonly dispatcher: IDispatcher;
  readonly key: string;
  readonly store: FavoriteStore | null;
  readonly ref: FavoriteRef | null;
  readonly disabled: boolean;
  readonly onFavoriteChange?: () => void;
}

export class FavoriteToggleVM extends ComponentVM {
  readonly toggleCommand = this.relayCommand(
    () => this.#setFavorite(!this.isFavorite),
    () => this.canToggle,
  );
  readonly toggleLabel = FAVORITE_TEXT.favorite;
  declare readonly favoriteByDefault: boolean;
  readonly #o: FavoriteToggleVMOptions;
  readonly #set = this.observable({ favoriteByDefault: false });

  constructor(o: FavoriteToggleVMOptions) {
    super({ name: `favorite:${o.key}`, hint: "", hub: o.hub, dispatcher: o.dispatcher });
    this.#o = o;
    this.computed("isFavorite", "favoriteTitle");
    if (o.onFavoriteChange) this.reaction(() => this.isFavorite, o.onFavoriteChange, { alive: true });
  }

  get canToggle(): boolean {
    return this.#o.store !== null && this.#o.ref !== null && !this.#o.disabled;
  }

  get isFavorite(): boolean {
    const { store, ref } = this.#o;
    return ref !== null && store !== null && store.has(ref, this.favoriteByDefault);
  }

  get favoriteTitle(): string {
    return this.isFavorite ? FAVORITE_TEXT.unfavorite : FAVORITE_TEXT.favorite;
  }

  refresh(): void {
    this.invalidate("isFavorite");
  }

  setFavoriteByDefault(on: boolean): void {
    this.#set({ favoriteByDefault: on });
  }

  #setFavorite(on: boolean): void {
    const { store, ref } = this.#o;
    if (ref === null || store === null) return;
    if (on) store.add(ref, this.favoriteByDefault);
    else store.remove(ref, this.favoriteByDefault);
    this.invalidate("isFavorite");
  }
}
