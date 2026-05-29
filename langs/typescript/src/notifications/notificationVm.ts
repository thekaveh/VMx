/**
 * NotificationVM — render-side ViewModel for a Notification.
 *
 * See spec/16-notifications.md §NotificationVM and ADR-0031.
 */
import {
  filter,
  skip,
  skipWhile,
  Subscription,
  take,
  type SchedulerLike,
} from "rxjs";
import { RelayCommand, RelayCommandBuilder } from "../commands/relayCommand.js";
import type { Notification } from "./notification.js";
import { NotificationReaction } from "./notification.js";
import type { INotificationHub } from "./notificationHub.js";

/** Default lifespan for NotificationVM: 60 seconds (in milliseconds). */
const DEFAULT_LIFESPAN_MS = 60_000;

/**
 * Render-side ViewModel for a {@link Notification}.
 *
 * Exposes UI-bindable state:
 * - `notification` — the consumed datum
 * - `lifespanMs` — configured lifespan in milliseconds (default 60 000)
 * - `remainingMs` — decays toward 0 via the injected scheduler
 * - `opacity` — derived `remainingMs / lifespanMs`, range [0.0, 1.0]
 * - `isResolved` — `true` once resolved
 * - `dismissCommand` — resolves with Approve and cancels the timer
 *
 * Auto-dismiss: when `remainingMs` reaches 0, the VM resolves the notification
 * with {@link NotificationReaction.Approve}.
 * Use {@link ConfirmationVM} for explicit user action instead.
 */
export class NotificationVM {
  readonly #notification: Notification;
  readonly #hub: INotificationHub;
  readonly #scheduler: SchedulerLike;
  readonly #lifespanMs: number;
  readonly #startTime: number;

  #isResolved = false;
  #timerHandle: ReturnType<SchedulerLike["schedule"]> | null = null;
  #pendingSub: Subscription | null = null;

  readonly dismissCommand: RelayCommand;

  constructor(
    notification: Notification,
    hub: INotificationHub,
    scheduler: SchedulerLike,
    lifespanMs?: number,
  ) {
    this.#notification = notification;
    this.#hub = hub;
    this.#scheduler = scheduler;
    this.#lifespanMs = lifespanMs ?? DEFAULT_LIFESPAN_MS;
    this.#startTime = scheduler.now();

    this.dismissCommand = new RelayCommandBuilder(null, null, [])
      .task(() => this.dismiss())
      .build();

    // Schedule auto-dismiss at lifespan expiry.
    this.#timerHandle = scheduler.schedule(
      () => this.#onExpire(),
      this.#lifespanMs,
    );

    // Subscribe to hub Pending: detect external resolution.
    // skipWhile: skip while notification is NOT yet seen.
    // skip(1): drop the first "present" emission.
    // filter/take(1): fire on the first "gone" emission.
    this.#pendingSub = hub.pending
      .pipe(
        skipWhile((list) => !list.includes(notification)),
        skip(1),
        filter((list) => !list.includes(notification)),
        take(1),
      )
      .subscribe(() => this.#notifyExternalResolve());
  }

  // ── Public properties ───────────────────────────────────────────────────────

  /** The notification datum consumed by this VM. */
  get notification(): Notification {
    return this.#notification;
  }

  /** Configured lifespan in milliseconds (default 60 000 ms). */
  get lifespanMs(): number {
    return this.#lifespanMs;
  }

  /** Remaining time in milliseconds. Decays toward 0. */
  get remainingMs(): number {
    const elapsed = this.#scheduler.now() - this.#startTime;
    const remaining = this.#lifespanMs - elapsed;
    return remaining > 0 ? remaining : 0;
  }

  /**
   * Opacity derived as `remainingMs / lifespanMs`. Range [0.0, 1.0].
   * Linear decay from 1.0 to 0.0 over `lifespanMs`.
   */
  get opacity(): number {
    if (this.#lifespanMs <= 0) return 0.0;
    return this.remainingMs / this.#lifespanMs;
  }

  /** `true` once the notification has been resolved (manually or by timer). */
  get isResolved(): boolean {
    return this.#isResolved;
  }

  // ── Public methods ──────────────────────────────────────────────────────────

  /** Disposes resources: cancels the timer, pending subscription, and command. */
  dispose(): void {
    this.#timerHandle?.unsubscribe();
    this.#timerHandle = null;
    this.#pendingSub?.unsubscribe();
    this.#pendingSub = null;
    this.dismissCommand.dispose();
  }

  // ── Internal ────────────────────────────────────────────────────────────────

  /**
   * Called when the lifespan timer fires.
   * Default: auto-dismiss with Approve.
   * `ConfirmationVM` overrides to suppress auto-dismiss.
   */
  protected onExpire(): void {
    this.#dismiss();
  }

  /** Resolves with Approve and cancels the timer. Idempotent. */
  protected dismiss(): void {
    this.#dismiss();
  }

  /** Resolves with the given reaction and cancels the timer. Idempotent. */
  protected resolveWith(reaction: NotificationReaction): void {
    this.#resolveWith(reaction);
  }

  // ── Private ─────────────────────────────────────────────────────────────────

  #onExpire(): void {
    this.onExpire();
  }

  #dismiss(): void {
    if (this.#isResolved) return;
    this.#isResolved = true;
    this.#timerHandle?.unsubscribe();
    this.#timerHandle = null;
    this.#hub.resolve(this.#notification, NotificationReaction.Approve);
  }

  #resolveWith(reaction: NotificationReaction): void {
    if (this.#isResolved) return;
    this.#isResolved = true;
    this.#timerHandle?.unsubscribe();
    this.#timerHandle = null;
    this.#hub.resolve(this.#notification, reaction);
  }

  #notifyExternalResolve(): void {
    if (this.#isResolved) return;
    this.#isResolved = true;
    this.#timerHandle?.unsubscribe();
    this.#timerHandle = null;
  }
}
