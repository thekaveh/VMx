/**
 * FormRevertedMessage — emitted when a FormVM reverts its Model to Snapshot.
 *
 * See spec/20-form-vm.md §7 — Hub messages.
 */
import type { IMessage } from "./types.js";

export class FormRevertedMessage implements IMessage {
  readonly sender: object;
  readonly senderName: string;

  constructor(sender: object, senderName: string) {
    this.sender = sender;
    this.senderName = senderName;
  }

  get senderObject(): object {
    return this.sender;
  }
}
