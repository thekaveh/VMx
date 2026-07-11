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
  sender?: TSender,
  propertyName?: string,
): message is PropertyChangedMessage<TSender>;
export function isPropertyChanged<TSender = unknown>(
  message: IMessage,
  sender?: TSender,
  propertyName?: string,
): message is PropertyChangedMessage<TSender> {
  return (
    message instanceof PropertyChangedMessage &&
    (sender === undefined || message.sender === sender) &&
    (propertyName === undefined || message.propertyName === propertyName)
  );
}

export function isCollectionChanged<TItem = unknown>(
  message: IMessage,
  source?: object,
  action?: CollectionMutationAction,
): message is CollectionChangedMessage<TItem> {
  return (
    message instanceof CollectionChangedMessage &&
    (source === undefined || message.sender === source) &&
    (action === undefined || message.action === action)
  );
}

export function isConstructionStatusChanged(
  message: IMessage,
  sender?: object,
  status?: ConstructionStatus,
): message is ConstructionStatusChangedMessage {
  return (
    message instanceof ConstructionStatusChangedMessage &&
    (sender === undefined || message.sender === sender) &&
    (status === undefined || message.status === status)
  );
}
