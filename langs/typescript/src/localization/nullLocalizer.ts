/**
 * NullLocalizer — null-object variant per ADR-0017.
 */
import type { ILocalizer } from "./localizer.js";

export class NullLocalizer implements ILocalizer {
  static readonly INSTANCE: NullLocalizer = new NullLocalizer();

  private constructor() {}

  localize(key: string, _args?: readonly unknown[]): string {
    return key;
  }
}
