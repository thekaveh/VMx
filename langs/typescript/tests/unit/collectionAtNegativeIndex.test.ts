// The `at` helpers of the TypeScript collections resolve an index the way
// `Array.prototype.at` does (#1322, ADR-0009 §2.23).

import { describe, expect, it } from "vitest";
import { ObservableList } from "../../src/collections/observableList.js";
import { ServicedObservableCollection } from "../../src/collections/servicedObservableCollection.js";
import { KeyedServicedObservableCollection } from "../../src/collections/keyedServicedObservableCollection.js";

interface Keyed {
  key: string;
}

const cases: [string, () => { push(item: string): unknown; at(index: number): string | undefined }][] = [
  ["ObservableList", () => new ObservableList<string>()],
  ["ServicedObservableCollection", () => new ServicedObservableCollection<string>()],
];

describe("collection at() negative indexes", () => {
  it.each(cases)("%s resolves negative indexes from the end", (_name, create) => {
    const sut = create();
    sut.push("a");
    sut.push("b");
    sut.push("c");

    expect(sut.at(-1)).toBe("c");
    expect(sut.at(-3)).toBe("a");
    expect(sut.at(-4)).toBeUndefined();
    expect(sut.at(3)).toBeUndefined();
    expect(sut.at(0)).toBe("a");
    expect(sut.at(1.7)).toBe("b");
    expect(sut.at(-1.2)).toBe("c");
  });

  it("KeyedServicedObservableCollection resolves negative indexes from the end", () => {
    const sut = new KeyedServicedObservableCollection<string, Keyed>({
      keyOf: (item) => item.key,
      hub: null,
    });
    const a = { key: "a" };
    const b = { key: "b" };
    const c = { key: "c" };
    sut.push(a);
    sut.push(b);
    sut.push(c);

    expect(sut.at(-1)).toBe(c);
    expect(sut.at(-3)).toBe(a);
    expect(sut.at(-4)).toBeUndefined();
    expect(sut.at(3)).toBeUndefined();
  });
});
