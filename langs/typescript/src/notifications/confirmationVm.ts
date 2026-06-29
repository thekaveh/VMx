/**
 * ConfirmationVM — render-side ViewModel for a confirmation Notification.
 *
 * See spec/16-notifications.md §ConfirmationVM and ADR-0031.
 */
import type { SchedulerLike } from "rxjs";
import { RelayCommand } from "../commands/relayCommand.js";
import type { Notification } from "./notification.js";
import { NotificationReaction } from "./notification.js";
import type { INotificationHub } from "./notificationHub.js";
import { NotificationVM } from "./notificationVm.js";

/** Default lifespan for ConfirmationVM: 300 seconds (in milliseconds). */
const DEFAULT_LIFESPAN_MS = 300_000;

/**
 * Render-side ViewModel for a confirmation {@link Notification}.
 *
 * Extends {@link NotificationVM} with explicit {@link approveCommand} and
 * {@link rejectCommand}. Default lifespan is 300 000 ms (300 seconds).
 *
 * Unlike {@link NotificationVM}, ConfirmationVM does **not** auto-resolve on
 * lifespan expiry — timeout means "user did not decide".
 */
export class ConfirmationVM extends NotificationVM {
  readonly approveCommand: RelayCommand;
  readonly rejectCommand: RelayCommand;

  constructor(
    notification: Notification,
    hub: INotificationHub,
    scheduler: SchedulerLike,
    lifespanMs?: number,
    tickIntervalMs?: number,
  ) {
    super(
      notification,
      hub,
      scheduler,
      lifespanMs ?? DEFAULT_LIFESPAN_MS,
      tickIntervalMs,
    );

    this.approveCommand = RelayCommand.builder()
      .task(() => this.resolveWith(NotificationReaction.Approve))
      .build();

    this.rejectCommand = RelayCommand.builder()
      .task(() => this.resolveWith(NotificationReaction.Reject))
      .build();
  }

  /**
   * VMX-092: ConfirmationVM never auto-resolves, so it declines to arm the
   * lifespan expiry timer at all — there is no work for it to do on fire.
   * (Observable behavior is unchanged: timeout still means "user did not
   * decide" and the notification remains pending.)
   */
  protected override armsExpiryTimer(): boolean {
    return false;
  }

  /**
   * ConfirmationVM does NOT auto-resolve on lifespan expiry.
   * Timeout means "user did not decide"; the notification remains pending.
   * Retained as a defensive no-op in case a subclass re-arms the timer.
   */
  protected override onExpire(): void {
    // Intentional no-op. ConfirmationVM requires an explicit user action.
  }

  /** Disposes commands and delegates to base dispose. */
  override dispose(): void {
    this.approveCommand.dispose();
    this.rejectCommand.dispose();
    super.dispose();
  }
}
