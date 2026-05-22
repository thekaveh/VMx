# 04 — Commands

VMx commands implement an `ICommand`-style interface and use Rx for reactive
re-evaluation of `CanExecute`.

## Command contract

```
ICommand:
    CanExecute() : bool
    Execute() : void
    CanExecuteChanged : event  / IObservable<Unit>
```

A parameterized variant accepts a typed parameter:

```
ICommand<T>:
    CanExecute(parameter: T) : bool
    Execute(parameter: T) : void
    CanExecuteChanged : event  / IObservable<Unit>
```

## Predicate semantics

A command is built with an optional `predicate` (`() -> bool` or `(T) -> bool`):

- If `predicate` is null/absent, `CanExecute` returns `true` unconditionally.
- If `predicate` is present, `CanExecute` returns its result.
- The predicate MUST NOT raise. If it does, the language flavor MAY treat the result
  as `false` (defensive) but MUST NOT propagate the exception to the caller.

## Task semantics

A command is built with an optional `task` (`() -> void` / `Action` or `(T) -> void`):

- If `task` is null/absent, `Execute` is a no-op (returns immediately, does not raise).
- If `task` is present, `Execute` invokes it.
- The task MUST NOT raise; if it does, the exception propagates to the caller of
  `Execute`. The exception is the application's responsibility, not the command's.

## Triggers

A command MAY be built with one or more `triggers` (`IObservable<Unit>`). On each
emission of any trigger, the command:

1. Re-evaluates `CanExecute`.
1. Fires `CanExecuteChanged` (the consumer-facing event/observable).

Triggers do NOT carry data — only the fact that re-evaluation should happen. The
typical pattern: derive a trigger from a property's change stream
(`vm.Status.Where(s => s == Constructed).Select(_ => Unit.Default)`).

## RelayCommand

`RelayCommand` is the concrete `ICommand` implementation, built via a fluent
immutable builder:

```
RelayCommand.Builder()
    .Task(() => ...)         // optional
    .Predicate(() => ...)    // optional
    .Triggers(observable)    // optional, multiple calls allowed
    .Build()
```

`RelayCommand<T>` follows the same pattern with parameterized predicate/task.

## Builder semantics

- Setters return a NEW builder instance (immutability).
- `Triggers` is additive: multiple `.Triggers(obs)` calls combine all observables
  into the trigger set.
- `Build()` succeeds even with no task, no predicate, and no triggers (yielding a
  command whose `CanExecute` returns `true` and whose `Execute` is a no-op).

## Fixture

`fixtures/command-truthtable.json` encodes five canonical command configurations that
`CMD-NNN` conformance tests load. Each row encodes: predicate value, task presence,
trigger behavior, expected `CanExecute` return, whether `Execute` invokes the task,
and whether `CanExecuteChanged` fires.
