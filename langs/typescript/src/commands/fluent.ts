/**
 * Fluent command composition helpers for VMx.
 *
 * Standalone named exports that are ergonomic shortcuts over the explicit
 * decorator constructors. They add no new behaviour.
 *
 * See spec/04-commands.md §9 and ADR-0027.
 */

import { CompositeCommand } from "./compositeCommand.js";
import {
  ConfirmationDecoratorCommand,
  type ConfirmDelegate,
} from "./confirmationDecoratorCommand.js";
import { DecoratorCommand } from "./decoratorCommand.js";
import type { ICommand } from "./types.js";
import type { IDialogService } from "../dialogs/dialogService.js";

/**
 * Returns a {@link ConfirmationDecoratorCommand} that gates execution of
 * `command` on the supplied async `confirmDelegate`.
 *
 * Equivalent to `new ConfirmationDecoratorCommand(command, confirmDelegate)`.
 */
export function confirm(
  command: ICommand,
  confirmDelegate: ConfirmDelegate,
): ConfirmationDecoratorCommand {
  return new ConfirmationDecoratorCommand(command, confirmDelegate);
}

/**
 * Returns a {@link ConfirmationDecoratorCommand} that gates execution of
 * `command` on {@link IDialogService.confirm} called with `prompt`.
 *
 * Equivalent to `confirm(command, () => dialogService.confirm(prompt))`.
 */
export function confirmWithDialogService(
  command: ICommand,
  dialogService: IDialogService,
  prompt: string,
): ConfirmationDecoratorCommand {
  return new ConfirmationDecoratorCommand(command, () => dialogService.confirm(prompt));
}

/**
 * Returns a {@link CompositeCommand} where `other` executes *before* `command`.
 *
 * Equivalent to `new CompositeCommand(other, command)`.
 */
export function precedeWith(command: ICommand, other: ICommand): CompositeCommand {
  return new CompositeCommand(other, command);
}

/**
 * Returns a {@link CompositeCommand} where `other` executes *after* `command`.
 *
 * Equivalent to `new CompositeCommand(command, other)`.
 */
export function succeedWith(command: ICommand, other: ICommand): CompositeCommand {
  return new CompositeCommand(command, other);
}

/**
 * Returns a {@link DecoratorCommand} wrapping `command` with optional extra
 * `predicate`, `pre`, and `post` hooks.
 *
 * Equivalent to
 * `new DecoratorCommand(command, { extraPredicate: predicate, preExecute: pre, postExecute: post })`.
 *
 * Passing all `undefined`/`null` yields a semantically transparent decorator.
 */
export function wrapWith(
  command: ICommand,
  predicate?: (() => boolean) | null,
  pre?: (() => void) | null,
  post?: (() => void) | null,
): DecoratorCommand {
  return new DecoratorCommand(command, {
    ...(predicate != null ? { extraPredicate: predicate } : {}),
    ...(pre != null ? { preExecute: pre } : {}),
    ...(post != null ? { postExecute: post } : {}),
  });
}
