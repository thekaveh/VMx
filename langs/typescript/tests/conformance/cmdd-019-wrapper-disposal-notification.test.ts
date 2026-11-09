// Conformance tests: CMDD-019 — disposing a live wrapper command notifies its
// own canExecuteChanged subscribers once; a second dispose and the inner
// command's subscribers get nothing. See spec/04-commands.md §8.4 and ADR-0222.
import { describe, expect, it } from "vitest";

import {
  CompositeCommand,
  ConfirmationDecoratorCommand,
  DecoratorCommand,
  RelayCommand,
  type ICommand,
} from "../../src/index.js";

describe("CMDD-019", () => {
  const wrappers: [string, (inner: ICommand) => ICommand & { dispose(): void }][] = [
    ["composite", (inner) => new CompositeCommand(inner)],
    ["decorator", (inner) => new DecoratorCommand(inner)],
    ["confirmation", (inner) => new ConfirmationDecoratorCommand(inner, () => Promise.resolve(true))],
  ];

  for (const [kind, wrap] of wrappers) {
    it(`${kind}: disposal notifies wrapper subscribers once and inner subscribers never`, () => {
      const inner = RelayCommand.builder().task(() => {}).build();
      const wrapper = wrap(inner);
      let wrapperSeen = 0;
      let innerSeen = 0;
      wrapper.canExecuteChanged.subscribe(() => {
        wrapperSeen++;
        expect(wrapper.canExecute()).toBe(false);
      });
      inner.canExecuteChanged.subscribe(() => innerSeen++);

      wrapper.dispose();
      wrapper.dispose();

      expect(wrapperSeen).toBe(1);
      expect(innerSeen).toBe(0);
    });
  }
});
