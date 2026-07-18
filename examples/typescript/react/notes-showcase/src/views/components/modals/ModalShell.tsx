import { useEffect, useRef, type JSX, type ReactNode } from "react";

const FOCUSABLE = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

type InertElement = HTMLElement & { inert: boolean };

export interface ModalShellProps {
  readonly activationKey: object;
  readonly ariaLabel: string;
  readonly children: ReactNode;
  readonly onEscape: () => void;
  readonly role?: "dialog" | "alertdialog";
}

/** Shared keyboard, focus, and background-isolation contract for every modal. */
export function ModalShell({
  activationKey,
  ariaLabel,
  children,
  onEscape,
  role = "dialog",
}: ModalShellProps): JSX.Element {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return undefined;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const background = document.querySelector<HTMLElement>("[data-dialog-background]");
    const backgroundWasInert = background !== null
      && Boolean((background as InertElement).inert);
    const priorAriaHidden = background?.getAttribute("aria-hidden") ?? null;
    if (background !== null) {
      (background as InertElement).inert = true;
      background.setAttribute("aria-hidden", "true");
    }

    const focusable = (): HTMLElement[] =>
      Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE))
        .filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
    const preferred = dialog.querySelector<HTMLElement>("[data-autofocus]");
    (preferred ?? focusable()[0] ?? dialog).focus();

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        onEscape();
        return;
      }
      if (event.key !== "Tab") return;

      const items = focusable();
      if (items.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (first === undefined || last === undefined) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);

    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      if (background !== null) {
        (background as InertElement).inert = backgroundWasInert;
        if (priorAriaHidden === null) background.removeAttribute("aria-hidden");
        else background.setAttribute("aria-hidden", priorAriaHidden);
      }
      if (previouslyFocused?.isConnected === true) previouslyFocused.focus();
    };
  }, [activationKey, onEscape]);

  return (
    <div
      ref={dialogRef}
      className="dialog-backdrop"
      role={role}
      aria-modal="true"
      aria-label={ariaLabel}
      tabIndex={-1}
    >
      {children}
    </div>
  );
}
