/**
 * ILocalizer contract. See spec/17-localization.md.
 */
export interface ILocalizer {
  localize(key: string, args?: readonly unknown[]): string;
}
