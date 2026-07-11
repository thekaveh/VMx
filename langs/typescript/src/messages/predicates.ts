import { ConstructionStatus } from "../lifecycle/status.js";
import {
  CollectionChangedMessage,
  type CollectionMutationAction,
} from "./collectionChanged.js";
import { ConstructionStatusChangedMessage } from "./constructionStatusChanged.js";
import { PropertyChangedMessage } from "./propertyChanged.js";
import type { IMessage } from "./types.js";

export function isPropertyChanged(
  message: IMessage,
): message is PropertyChangedMessage<unknown>;
export function isPropertyChanged<TSender = unknown>(
  message: IMessage,
  constraints?: {
    readonly sender?: TSender;
    readonly propertyName?: string;
  },
): message is PropertyChangedMessage<TSender>;
export function isPropertyChanged<TSender = unknown>(
  message: IMessage,
  constraints?: {
    readonly sender?: TSender;
    readonly propertyName?: string;
  } | number | null,
): message is PropertyChangedMessage<TSender> {
  const match =
    typeof constraints === "object" && constraints !== null
      ? constraints
      : undefined;
  return (
    message instanceof PropertyChangedMessage &&
    (match?.sender === undefined || message.sender === match.sender) &&
    (match?.propertyName === undefined ||
      message.propertyName === match.propertyName)
  );
}

export function isCollectionChanged(
  message: IMessage,
): message is CollectionChangedMessage<unknown>;
export function isCollectionChanged<TItem = unknown>(
  message: IMessage,
  constraints?: {
    readonly source?: object;
    readonly action?: CollectionMutationAction;
  },
): message is CollectionChangedMessage<TItem>;
export function isCollectionChanged<TItem = unknown>(
  message: IMessage,
  constraints?: {
    readonly source?: object;
    readonly action?: CollectionMutationAction;
  } | number | null,
): message is CollectionChangedMessage<TItem> {
  const match =
    typeof constraints === "object" && constraints !== null
      ? constraints
      : undefined;
  return (
    message instanceof CollectionChangedMessage &&
    (match?.source === undefined || message.sender === match.source) &&
    (match?.action === undefined || message.action === match.action)
  );
}

export function isConstructionStatusChanged(
  message: IMessage,
): message is ConstructionStatusChangedMessage;
/* eslint-disable @typescript-eslint/unified-signatures -- the unary overload keeps direct filter callbacks from accepting their index as constraints */
export function isConstructionStatusChanged(
  message: IMessage,
  constraints?: {
    readonly sender?: object;
    readonly status?: ConstructionStatus;
  },
): message is ConstructionStatusChangedMessage;
/* eslint-enable @typescript-eslint/unified-signatures */
export function isConstructionStatusChanged(
  message: IMessage,
  constraints?: {
    readonly sender?: object;
    readonly status?: ConstructionStatus;
  } | number | null,
): message is ConstructionStatusChangedMessage {
  const match =
    typeof constraints === "object" && constraints !== null
      ? constraints
      : undefined;
  return (
    message instanceof ConstructionStatusChangedMessage &&
    (match?.sender === undefined || message.sender === match.sender) &&
    (match?.status === undefined || message.status === match.status)
  );
}
