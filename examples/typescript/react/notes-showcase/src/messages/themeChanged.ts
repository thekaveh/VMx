/**
 * ThemeChangedMessage — emitted by ThemeVM after every effective theme
 * transition (preset swap, high-contrast toggle, accent change, font
 * scale, follow-system switch).
 *
 * Conforms to `spec/proposals/2026-06-02-theme-vm-scenario.md` §4
 * ("events (via hub)").
 *
 * Template follows the upstream `PropertyChangedMessage` shape
 * (see `langs/typescript/src/messages/propertyChanged.ts`): a
 * sealed-by-construction class with a static `create` factory and
 * an `ITypedMessage<TSender>` contract.
 */
import type { ITypedMessage } from "@thekaveh/vmx";

import type { ThemeModel } from "../models/themeModel.js";

export class ThemeChangedMessage<TSender>
  implements ITypedMessage<TSender>
{
  readonly sender: TSender;
  readonly senderName: string;
  readonly prev: ThemeModel;
  readonly curr: ThemeModel;

  private constructor(
    sender: TSender,
    senderName: string,
    prev: ThemeModel,
    curr: ThemeModel,
  ) {
    this.sender = sender;
    this.senderName = senderName;
    this.prev = prev;
    this.curr = curr;
  }

  get senderObject(): object {
    return this.sender as object;
  }

  static create<TSender>(
    sender: TSender,
    senderName: string,
    prev: ThemeModel,
    curr: ThemeModel,
  ): ThemeChangedMessage<TSender> {
    return new ThemeChangedMessage(sender, senderName, prev, curr);
  }
}
