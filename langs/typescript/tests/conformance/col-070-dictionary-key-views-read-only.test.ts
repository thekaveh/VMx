// Conformance tests: COL-070 — dictionary key views give callers no mutator.
// keys1 and keys2 are ReadOnlyObservableList facades over the backing lists.
// The @ts-expect-error lines are checked by `npm run typecheck:tests`.
// See spec/21-collections.md §4.1-§4.2 and ADR-0193 (#1316).

import { describe, expect, it } from "vitest";
import {
  ObservableDictionary,
  ObservableList,
  ReadOnlyObservableList,
} from "../../src/index.js";

const mutators = [
  "push",
  "insert",
  "pop",
  "removeAt",
  "remove",
  "replace",
  "replaceAll",
  "clear",
  "withBatch",
] as const;

// Never called: the compiler checks that each mutator is absent from the type.
function mutatorsDoNotCompile(
  dictionary: ObservableDictionary<string, number, string>,
): void {
  /* eslint-disable @typescript-eslint/no-unsafe-call -- each call names a member the view must not have */
  // @ts-expect-error keys1 has no push
  dictionary.keys1.push("x");
  // @ts-expect-error keys1 has no insert
  dictionary.keys1.insert(0, "x");
  // @ts-expect-error keys1 has no removeAt
  dictionary.keys1.removeAt(0);
  // @ts-expect-error keys1 has no replace
  dictionary.keys1.replace(0, "x");
  // @ts-expect-error keys1 has no clear
  dictionary.keys1.clear();
  // @ts-expect-error keys2 has no withBatch
  dictionary.keys2.withBatch(() => {});
  // @ts-expect-error keys2 has no remove
  dictionary.keys2.remove(1);
  // @ts-expect-error a key view is not an ObservableList
  const list: ObservableList<string> = dictionary.keys1;
  void list;
  /* eslint-enable @typescript-eslint/no-unsafe-call */
}
void mutatorsDoNotCompile;

describe("COL-070", () => {
  it("keys1 and keys2 are read-only views in first-appearance order", () => {
    const sut = new ObservableDictionary<string, number, string>();
    sut.add("a", 1, "one");
    sut.add("b", 2, "two");

    for (const view of [sut.keys1, sut.keys2]) {
      expect(view).toBeInstanceOf(ReadOnlyObservableList);
      expect(view).not.toBeInstanceOf(ObservableList);
      for (const name of mutators) expect(name in view).toBe(false);
    }
    expect(sut.keys1.toArray()).toEqual(["a", "b"]);
    expect(sut.keys2.toArray()).toEqual([1, 2]);
    expect(sut.keys1).toBe(sut.keys1);
  });
});

describe("ReadOnlyObservableList key view", () => {
  it("reads and notifies as the backing list does", () => {
    const sut = new ObservableDictionary<string, number, string>();
    const log: string[] = [];
    sut.keys1.itemAdded.subscribe(({ item, index }) => log.push(`add:${item}:${index}`));
    sut.keys1.itemRemoved.subscribe(({ item, index }) => log.push(`remove:${item}:${index}`));
    sut.keys1.reset.subscribe(() => log.push("reset"));
    sut.keys1.propertyChanged.subscribe((name) => log.push(`property:${name}`));

    sut.add("a", 1, "one");
    sut.add("b", 2, "two");
    expect(sut.keys1.length).toBe(2);
    expect(sut.keys1.at(1)).toBe("b");
    expect([...sut.keys1]).toEqual(["a", "b"]);
    sut.delete("a", 1);
    sut.clear();

    expect(log).toEqual([
      "add:a:0", "property:Count",
      "add:b:1", "property:Count",
      "remove:a:0", "property:Count",
      "reset", "property:Count",
    ]);
  });
});
