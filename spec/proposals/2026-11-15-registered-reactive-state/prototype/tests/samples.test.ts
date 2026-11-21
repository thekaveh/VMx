/**
 * The two sample view-models (CollapsibleSectionVM, FavoriteToggleVM) behave as their hand-written equivalents would.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { activate } from "../src/index.js";
import { CollapsibleSectionVM } from "./samples/collapsibleSectionVM.js";
import { type FavoriteRef, type FavoriteStore, FavoriteToggleVM } from "./samples/favoriteToggleVM.js";
import { captureReports, Recorder, services, tick } from "./support.js";

describe("sample CollapsibleSectionVM", () => {
  it("collapses while it has no results, toggles, and announces each change once", async () => {
    const s = services();
    let collapsedChanges = 0;
    const vm = new CollapsibleSectionVM({
      ...s,
      key: "p",
      noResults: true,
      placeholder: "No results",
      onCollapsedChange: () => {
        collapsedChanges += 1;
      },
    });
    const reports = captureReports();
    vm.construct();
    // The unpublished-getter probe runs on a later task (fix round 1, R19.2).
    await tick();
    assert.deepEqual(reports, [], "every public getter that reads reactive state is registered");
    assert.equal(vm.isCollapsed, true);
    assert.equal(vm.toggleLabel, "Show");
    assert.equal(vm.showsToggle, true);
    let raises = 0;
    vm.toggleCommand.canExecuteChanged.subscribe(() => {
      raises += 1;
    });
    assert.equal(vm.toggleCommand.canExecute(), true);
    const rec = new Recorder(s.hub);
    vm.toggleCommand.execute();
    assert.deepEqual(rec.take(), ["hub:section:p.isCollapsed", "hub:section:p.toggleLabel"]);
    assert.equal(collapsedChanges, 1);
    vm.update(false, "No results");
    assert.deepEqual(rec.hubNames(), [
      "section:p.placeholder",
      "section:p.noResults",
      "section:p.showsToggle",
    ]);
    assert.equal(raises, 1, "the predicate's input changed once");
    assert.equal(vm.toggleCommand.canExecute(), false);
    assert.equal(vm.isCollapsed, false);
  });

  it("onCollapsedChange keeps its timing in every status but Disposed (an alive reaction)", () => {
    const s = services();
    let collapsedChanges = 0;
    const vm = new CollapsibleSectionVM({
      ...s,
      key: "q",
      noResults: false,
      placeholder: "",
      onCollapsedChange: () => {
        collapsedChanges += 1;
      },
    });
    activate(vm);
    vm.update(true, "Nothing found");
    assert.equal(collapsedChanges, 1);
    assert.equal(vm.isCollapsed, true);
    vm.reveal();
    assert.equal(collapsedChanges, 2);
    vm.dispose();
    vm.update(false, "");
    assert.equal(collapsedChanges, 2);
  });
});

class Favorites implements FavoriteStore {
  readonly added = new Set<string>();
  readonly removed = new Set<string>();
  has(ref: FavoriteRef, favoriteByDefault: boolean): boolean {
    const key = `${ref.list}/${ref.item}`;
    return this.added.has(key) || (favoriteByDefault && !this.removed.has(key));
  }
  add(ref: FavoriteRef): void {
    const key = `${ref.list}/${ref.item}`;
    this.added.add(key);
    this.removed.delete(key);
  }
  remove(ref: FavoriteRef): void {
    const key = `${ref.list}/${ref.item}`;
    this.added.delete(key);
    this.removed.add(key);
  }
}

describe("sample FavoriteToggleVM", () => {
  it("toggles the favorite, invalidates over the outside store, and follows the default", () => {
    const s = services();
    const store = new Favorites();
    let favoriteChanges = 0;
    const vm = new FavoriteToggleVM({
      ...s,
      key: "doc",
      store,
      ref: { list: "starred", item: "doc-1" },
      disabled: false,
      onFavoriteChange: () => {
        favoriteChanges += 1;
      },
    });
    vm.construct();
    const rec = new Recorder(s.hub);
    assert.equal(vm.isFavorite, false);
    assert.equal(vm.toggleCommand.canExecute(), true);
    vm.toggleCommand.execute();
    assert.equal(vm.isFavorite, true);
    assert.equal(vm.favoriteTitle, "Unfavorite");
    assert.deepEqual(rec.take(), ["hub:favorite:doc.isFavorite", "hub:favorite:doc.favoriteTitle"]);
    assert.equal(favoriteChanges, 1);
    // Another view changed the store; refresh() reads it again.
    store.remove({ list: "starred", item: "doc-1" });
    vm.refresh();
    assert.equal(vm.isFavorite, false);
    vm.setFavoriteByDefault(true);
    assert.equal(vm.isFavorite, false, "a default favorite that the user removed stays removed");
    store.removed.clear();
    vm.refresh();
    assert.equal(vm.isFavorite, true);
    assert.equal(favoriteChanges, 3);
  });

  it("has no toggle without a store", () => {
    const vm = new FavoriteToggleVM({ ...services(), key: "x", store: null, ref: null, disabled: false });
    vm.construct();
    assert.equal(vm.canToggle, false);
    assert.equal(vm.toggleCommand.canExecute(), false);
    assert.equal(vm.isFavorite, false);
  });
});
