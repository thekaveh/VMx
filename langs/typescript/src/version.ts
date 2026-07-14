/**
 * Package version, matching package.json.
 *
 * Kept in sync with package.json by scripts/check-version-sync.mjs, which runs
 * as part of `prebuild` and `prepack`. Update both when releasing.
 */
export const __version__ = "3.21.1";

/** Minimum spec version this package implements (see spec/VERSION). */
export const __minSpecVersion__ = "3.20.1";
