import { ConstructionStatus } from "../lifecycle/status.js";
import {
  CollectionChangedMessage,
  type CollectionMutationAction,
} from "./collectionChanged.js";
import { ConstructionStatusChangedMessage } from "./constructionStatusChanged.js";
import { PropertyChangedMessage } from "./propertyChanged.js";
import type { IMessage } from "./types.js";

function hasOwn(value: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

export function isPropertyChanged(
  message: IMessage,
): message is PropertyChangedMessage<unknown>;
export function isPropertyChanged<TSender>(
  message: IMessage,
  constraints: {
    readonly sender: TSender;
    readonly propertyName?: string | undefined;
  },
): message is PropertyChangedMessage<TSender>;
/* eslint-disable @typescript-eslint/unified-signatures -- the unary overload prevents filter indices from becoming constraints */
export function isPropertyChanged(
  message: IMessage,
  constraints: {
    readonly propertyName?: string | undefined;
  },
): message is PropertyChangedMessage<unknown>;
/* eslint-enable @typescript-eslint/unified-signatures */
export function isPropertyChanged(
  message: IMessage,
  constraints?: {
    readonly sender?: unknown;
    readonly propertyName?: string | undefined;
  } | number | null,
): message is PropertyChangedMessage<unknown> {
  const match =
    typeof constraints === "object" && constraints !== null
      ? constraints
      : undefined;
  return (
    message instanceof PropertyChangedMessage &&
    (match === undefined ||
      !hasOwn(match, "sender") ||
      message.sender === match.sender) &&
    (match === undefined ||
      !hasOwn(match, "propertyName") ||
      message.propertyName === match.propertyName)
  );
}

export function isCollectionChanged(
  message: IMessage,
): message is CollectionChangedMessage<unknown>;
/* eslint-disable @typescript-eslint/unified-signatures -- the unary overload prevents filter indices from becoming constraints */
export function isCollectionChanged(
  message: IMessage,
  constraints: {
    readonly source?: object | undefined;
    readonly action?: CollectionMutationAction | undefined;
  },
): message is CollectionChangedMessage<unknown>;
/* eslint-enable @typescript-eslint/unified-signatures */
export function isCollectionChanged(
  message: IMessage,
  constraints?: {
    readonly source?: object | undefined;
    readonly action?: CollectionMutationAction | undefined;
  } | number | null,
): message is CollectionChangedMessage<unknown> {
  const match =
    typeof constraints === "object" && constraints !== null
      ? constraints
      : undefined;
  return (
    message instanceof CollectionChangedMessage &&
    (match === undefined ||
      !hasOwn(match, "source") ||
      message.sender === match.source) &&
    (match === undefined ||
      !hasOwn(match, "action") ||
      message.action === match.action)
  );
}

export function isConstructionStatusChanged(
  message: IMessage,
): message is ConstructionStatusChangedMessage;
/* eslint-disable @typescript-eslint/unified-signatures -- the unary overload prevents filter indices from becoming constraints */
export function isConstructionStatusChanged(
  message: IMessage,
  constraints: {
    readonly sender?: object | undefined;
    readonly status?: ConstructionStatus | undefined;
  },
): message is ConstructionStatusChangedMessage;
/* eslint-enable @typescript-eslint/unified-signatures */
export function isConstructionStatusChanged(
  message: IMessage,
  constraints?: {
    readonly sender?: object | undefined;
    readonly status?: ConstructionStatus | undefined;
  } | number | null,
): message is ConstructionStatusChangedMessage {
  const match =
    typeof constraints === "object" && constraints !== null
      ? constraints
      : undefined;
  return (
    message instanceof ConstructionStatusChangedMessage &&
    (match === undefined ||
      !hasOwn(match, "sender") ||
      message.sender === match.sender) &&
    (match === undefined ||
      !hasOwn(match, "status") ||
      message.status === match.status)
  );
}
