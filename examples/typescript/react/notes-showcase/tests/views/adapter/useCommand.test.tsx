/**
 * useCommand — RelayCommand → React handler bridge tests (Phase 4.c).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { act } from "react";
import { Subject } from "rxjs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RelayCommand } from "vmx";

import { useCommand } from "../../../src/views/adapter/useCommand.js";

function Probe(props: { cmd: RelayCommand; onClick: () => void }): JSX.Element {
  const { canExecute, execute } = useCommand(props.cmd);
  return (
    <button
      type="button"
      data-testid="btn"
      disabled={!canExecute}
      onClick={() => {
        props.onClick();
        execute();
      }}
    >
      go
    </button>
  );
}

afterEach(() => {
  cleanup();
});

describe("useCommand", () => {
  it("reflects the initial canExecute value", () => {
    const cmd = RelayCommand.builder()
      .task(() => {})
      .predicate(() => true)
      .build();
    render(<Probe cmd={cmd} onClick={() => {}} />);
    expect(screen.getByTestId<HTMLButtonElement>("btn").disabled).toBe(false);
  });

  it("reflects canExecute=false when predicate is false", () => {
    const cmd = RelayCommand.builder()
      .task(() => {})
      .predicate(() => false)
      .build();
    render(<Probe cmd={cmd} onClick={() => {}} />);
    expect(screen.getByTestId<HTMLButtonElement>("btn").disabled).toBe(true);
  });

  it("re-renders when canExecuteChanged fires (predicate flips)", () => {
    let enabled = false;
    const trigger = new Subject<void>();
    const cmd = RelayCommand.builder()
      .task(() => {})
      .predicate(() => enabled)
      .triggers(trigger.asObservable())
      .build();

    render(<Probe cmd={cmd} onClick={() => {}} />);
    expect(screen.getByTestId<HTMLButtonElement>("btn").disabled).toBe(true);

    enabled = true;
    act(() => {
      trigger.next();
    });
    expect(screen.getByTestId<HTMLButtonElement>("btn").disabled).toBe(false);

    enabled = false;
    act(() => {
      trigger.next();
    });
    expect(screen.getByTestId<HTMLButtonElement>("btn").disabled).toBe(true);
  });

  it("execute() forwards to the underlying command", () => {
    const task = vi.fn();
    const cmd = RelayCommand.builder()
      .task(task)
      .predicate(() => true)
      .build();
    render(<Probe cmd={cmd} onClick={() => {}} />);

    act(() => {
      screen.getByTestId<HTMLButtonElement>("btn").click();
    });
    expect(task).toHaveBeenCalledTimes(1);
  });

  it("unsubscribes on unmount (no callback after teardown)", () => {
    const trigger = new Subject<void>();
    const cmd = RelayCommand.builder()
      .task(() => {})
      .predicate(() => true)
      .triggers(trigger.asObservable())
      .build();
    const { unmount } = render(<Probe cmd={cmd} onClick={() => {}} />);
    unmount();
    // Should be quiet — if the subscription leaked, this would attempt a
    // setState on an unmounted component (logged as a React warning).
    act(() => {
      trigger.next();
    });
  });
});
