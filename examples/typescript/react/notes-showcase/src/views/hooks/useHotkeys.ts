/**
 * useHotkeys — tiny static-keymap hotkey dispatcher.
 *
 * See plan §5.c. Reads a `{ "Mod+S": () => …, … }` map and dispatches
 * matching `keydown` events on `window`. "Mod" matches Cmd or Ctrl on every
 * platform. A final `KeyA`..`KeyZ` token is a `KeyboardEvent.code` name and
 * matches the physical key, so Option on macOS does not change it. Other
 * final tokens match `KeyboardEvent.key`.
 *
 * No external dependency. Re-binds on every keymap change — callers should
 * pass stable command references (the `useCommand` result has a stable
 * `execute` per render, which is fine: the listener captures the *latest*
 * map on each render).
 */
import { useEffect, useRef } from "react";

export type Hotkey = `Mod+${string}` | `Mod+Shift+${string}`;
export type Keymap = Record<string, () => void>;

const CODE_TOKEN = /^Key[A-Z]$/;

function matchesHotkey(e: KeyboardEvent, hotkey: string): boolean {
  const parts = hotkey.split("+").map((p) => p.trim());
  const token = parts[parts.length - 1] ?? "";
  const wantMod = parts.includes("Mod");
  const wantShift = parts.includes("Shift");
  const wantAlt = parts.includes("Alt");
  const hasMod = e.metaKey || e.ctrlKey;
  if (wantMod !== hasMod) return false;
  if (wantShift !== e.shiftKey) return false;
  if (wantAlt !== e.altKey) return false;
  if (CODE_TOKEN.test(token)) return e.code === token;
  return e.key.toLowerCase() === token.toLowerCase();
}

export function useHotkeys(map: Keymap): void {
  // Keep the latest map in a ref so the listener always reads up-to-date
  // handlers without re-binding the listener every render.
  const mapRef = useRef(map);
  mapRef.current = map;

  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      for (const [hotkey, handlerFn] of Object.entries(mapRef.current)) {
        if (matchesHotkey(e, hotkey)) {
          e.preventDefault();
          handlerFn();
          return;
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
}
