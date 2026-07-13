import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Subject } from "rxjs";
import { describe, expect, it } from "vitest";
import {
  adaptCommandTruthTableFixture,
  runConsumerConformance,
  type ConsumerConformanceAdapter,
  type ConsumerConformanceFactory,
  type JsonObject,
} from "../../../src/conformance/index.js";
import { RelayCommand } from "../../../src/index.js";

const here = dirname(fileURLToPath(import.meta.url));

describe("command truth-table consumer adapter", () => {
  it("executes every unchanged fixture row through the generic runner", async () => {
    const raw = JSON.parse(
      readFileSync(
        join(here, "..", "..", "..", "src", "fixtures", "command-truthtable.json"),
        "utf8",
      ),
    ) as unknown;
    const suite = adaptCommandTruthTableFixture(raw);

    const report = await runConsumerConformance(suite, commandFactory);

    expect(suite.cases.map((testCase) => testCase.fixture)).toEqual(
      (raw as { cases: unknown[] }).cases,
    );
    expect(report).toMatchObject({
      suite: "vmx-command-truthtable",
      total: 5,
      passed: 5,
      failed: 0,
    });
    expect(report.cases.map((result) => result.id)).toEqual([
      "no-predicate-no-trigger",
      "predicate-true",
      "predicate-false",
      "trigger-fires-can-execute-event",
      "null-task",
    ]);
  });
});

interface CommandTruthTableRow extends JsonObject {
  readonly predicate: boolean | null;
  readonly task: string | null;
  readonly trigger_emits: boolean;
}

const commandFactory: ConsumerConformanceFactory = ({ caseFixture }) => {
  const row = caseFixture as CommandTruthTableRow;
  const trigger = new Subject<void>();
  let taskInvoked = false;
  let canExecuteChanged = false;
  let canExecute = false;

  let builder = RelayCommand.builder().triggers(trigger);
  if (row.predicate !== null) {
    builder = builder.predicate(() => row.predicate as boolean);
  }
  if (row.task !== null) {
    builder = builder.task(() => {
      taskInvoked = true;
    });
  }
  const command = builder.build();
  const subscription = command.canExecuteChanged.subscribe(() => {
    canExecuteChanged = true;
  });

  return {
    invoke(operation) {
      if (operation !== "evaluate") {
        throw new Error(`unknown operation: ${operation}`);
      }
      if (row.trigger_emits) trigger.next();
      canExecute = command.canExecute();
      command.execute();
    },
    snapshot: () => ({ canExecute, taskInvoked, canExecuteChanged }),
    drainMessages: () => [],
    dispose() {
      subscription.unsubscribe();
      command.dispose();
      trigger.complete();
    },
  } satisfies ConsumerConformanceAdapter;
};
