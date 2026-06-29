/**
 * NotificationVM — render-side ViewModel for a Notification.
 *
 * See spec/16-notifications.md §NotificationVM and ADR-0031.
 */
import {
  filter,
  type Observable,
  skip,
  skipWhile,
  Subject,
  Subscription,
  take,
  type SchedulerLike,
} from "rxjs";
import { RelayCommand } from "../commands/relayCommand.js";
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
 * - `propertyChanged` — INPC-style change-notification stream (VMX-135)
 *
 * Auto-dismiss: when `remainingMs` reaches 0, the VM resolves the notification
 * with {@link NotificationReaction.Approve}.
 * Use {@link ConfirmationVM} for explicit user action instead.
 *
 * Change-notification (VMX-135): `propertyChanged` emits property names so a
 * binding view can repaint. `isResolved` always emits on resolution; when a
 * `tickIntervalMs` is supplied, `remainingMs`/`opacity` emit periodically while
 * the notification fades. Without a tick interval the two time-varying
 * properties stay poll-only (no recurring scheduler work), preserving the prior
 * behaviour.
 */
export class NotificationVM {
  readonly #notification: Notification;
  readonly #hub: INotificationHub;
  readonly #scheduler: SchedulerLike;
  readonly #lifespanMs: number;
  readonly #tickIntervalMs: number;
  readonly #emitsDecayTicks: boolean;
  readonly #startTime: number;
  readonly #propertyChangedSubject = new Subject<string>();

  #isResolved = false;
  #disposed = false;
  #timerHandle: ReturnType<SchedulerLike["schedule"]> | null = null;
  #pendingSub: Subscription | null = null;
  #tickHandle: Subscription | null = null;

  readonly dismissCommand: RelayCommand;

  constructor(
    notification: Notification,
    hub: INotificationHub,
    scheduler: SchedulerLike,
    lifespanMs?: number,
    tickIntervalMs?: number,
  ) {
    this.#notification = notification;
    this.#hub = hub;
    this.#scheduler = scheduler;
    this.#lifespanMs = lifespanMs ?? DEFAULT_LIFESPAN_MS;
    this.#tickIntervalMs = tickIntervalMs ?? 0;
    this.#emitsDecayTicks = this.#tickIntervalMs > 0 && this.#lifespanMs > 0;
    this.#startTime = scheduler.now();

    this.dismissCommand = RelayCommand.builder()
      .task(() => this.#dismiss())
      .build();

    // Schedule auto-dismiss at lifespan expiry — unless a subclass opts out
    // (VMX-092). ConfirmationVM never auto-resolves, so arming a full-lifespan
    // (default 300 s) timer only to no-op on fire pins a scheduler action +
    // closure for no effect; it declines via `armsExpiryTimer()`.
    if (this.armsExpiryTimer()) {
      this.#timerHandle = scheduler.schedule(
        () => this.#onExpire(),
        this.#lifespanMs,
      );
    }

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

    // VMX-135: when a tick cadence is requested, periodically raise
    // propertyChanged for the decaying state so a bound view repaints the fade.
    // The recurring action self-terminates once the notification resolves, is
    // disposed, or the decay completes (remainingMs hits 0).
    if (this.#emitsDecayTicks) this.#scheduleDecayTick();
  }

  // ── Public properties ───────────────────────────────────────────────────────

  /** The notification datum consumed by this VM. */
  get notification(): Notification {
    return this.#notification;
  }

  /**
   * INPC-style change-notification stream (VMX-135): emits the name of each
   * property whose value changed (`isResolved`, and — when a tick interval is
   * configured — `remainingMs`/`opacity` as the notification fades).
   */
  get propertyChanged(): Observable<string> {
    return this.#propertyChangedSubject.asObservable();
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
    if (this.#disposed) return;
    this.#disposed = true;
    this.#timerHandle?.unsubscribe();
    this.#timerHandle = null;
    this.#pendingSub?.unsubscribe();
    this.#pendingSub = null;
    this.#tickHandle?.unsubscribe();
    this.#tickHandle = null;
    this.dismissCommand.dispose();
    this.#propertyChangedSubject.complete();
  }

  // ── Internal ────────────────────────────────────────────────────────────────

  /**
   * Schedules the next periodic decay tick (VMX-135). Each fired tick raises
   * propertyChanged for the time-varying state and reschedules until the
   * notification resolves, is disposed, or the decay completes.
   */
  #scheduleDecayTick(): void {
    this.#tickHandle = this.#scheduler.schedule(() => {
      if (this.#disposed || this.#isResolved) return;
      this.#raisePropertyChanged("remainingMs");
      this.#raisePropertyChanged("opacity");
      if (this.remainingMs > 0) this.#scheduleDecayTick();
    }, this.#tickIntervalMs);
  }

  /** Emits `propertyName` on the change-notification stream (VMX-135). */
  #raisePropertyChanged(propertyName: string): void {
    if (!this.#disposed) this.#propertyChangedSubject.next(propertyName);
  }

  /** Raises propertyChanged for the resolved + decay state (VMX-135). */
  #raiseResolvedChanges(): void {
    this.#raisePropertyChanged("isResolved");
    this.#raisePropertyChanged("remainingMs");
    this.#raisePropertyChanged("opacity");
  }

  /**
   * Whether this VM arms the lifespan expiry timer at construction.
   * Default: `true` (auto-dismiss on expiry). `ConfirmationVM` overrides this
   * to `false` because it never auto-resolves — avoiding a no-op timer
   * (VMX-092). Called from the constructor; overrides must not read
   * subclass-initialized state.
   */
  protected armsExpiryTimer(): boolean {
    return true;
  }

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
    this.#tickHandle?.unsubscribe();
    this.#tickHandle = null;
    this.#hub.resolve(this.#notification, NotificationReaction.Approve);
    this.#raiseResolvedChanges();
  }

  #resolveWith(reaction: NotificationReaction): void {
    if (this.#isResolved) return;
    this.#isResolved = true;
    this.#timerHandle?.unsubscribe();
    this.#timerHandle = null;
    this.#tickHandle?.unsubscribe();
    this.#tickHandle = null;
    this.#hub.resolve(this.#notification, reaction);
    this.#raiseResolvedChanges();
  }

  #notifyExternalResolve(): void {
    if (this.#isResolved) return;
    this.#isResolved = true;
    this.#timerHandle?.unsubscribe();
    this.#timerHandle = null;
    this.#tickHandle?.unsubscribe();
    this.#tickHandle = null;
    this.#raiseResolvedChanges();
  }
}
