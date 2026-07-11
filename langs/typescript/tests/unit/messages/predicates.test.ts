import { filter, from, type Observable } from "rxjs";
import { describe, expect, it } from "vitest";
import {
  CollectionChangedMessage,
  type CollectionMutationAction,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  type IMessage,
  isCollectionChanged,
  isConstructionStatusChanged,
  isPropertyChanged,
  PropertyChangedMessage,
} from "../../../src/index.js";
import { isPropertyChanged as isPropertyChangedFromMessages } from "../../../src/messages/index.js";

function expectType<T>(_value: T): void {}

const sender = { name: "sender" };
const other = { name: "other" };
const property = PropertyChangedMessage.create(sender, "sender", "model");
const collection = CollectionChangedMessage.forAdd<string>(sender, "item", 0);
const status = ConstructionStatusChangedMessage.create(
  sender,
  "sender",
  ConstructionStatus.Constructed,
);
const messages: IMessage[] = [property, collection, status];

describe("raw message predicates", () => {
  it("classifies property changes and narrows their sender type", () => {
    expect(isPropertyChanged(property)).toBe(true);
    expect(isPropertyChangedFromMessages(property)).toBe(true);
    expect(isPropertyChanged(collection)).toBe(false);
    expect(isPropertyChanged(property, other)).toBe(false);
    expect(isPropertyChanged(property, sender, "other")).toBe(false);

    const allProperties = messages.filter(isPropertyChanged);
    expectType<PropertyChangedMessage<unknown>[]>(allProperties);

    const senderProperties = messages.filter((message) =>
      isPropertyChanged(message, sender, "model"),
    );
    expectType<PropertyChangedMessage<typeof sender>[]>(senderProperties);

    const propertyStream = from(messages).pipe(
      filter((message) => isPropertyChanged(message, sender, "model")),
    );
    expectType<Observable<PropertyChangedMessage<typeof sender>>>(
      propertyStream,
    );
  });

  it("classifies collection changes and narrows their item type", () => {
    const wrongAction: CollectionMutationAction = "remove";

    expect(isCollectionChanged<string>(collection)).toBe(true);
    expect(isCollectionChanged<string>(property)).toBe(false);
    expect(isCollectionChanged<string>(collection, other)).toBe(false);
    expect(isCollectionChanged<string>(collection, sender, wrongAction)).toBe(
      false,
    );

    const additions = messages.filter((message) =>
      isCollectionChanged<string>(message, sender, "add"),
    );
    expectType<CollectionChangedMessage<string>[]>(additions);
  });

  it("classifies construction status changes and narrows the stream", () => {
    expect(isConstructionStatusChanged(status)).toBe(true);
    expect(isConstructionStatusChanged(property)).toBe(false);
    expect(isConstructionStatusChanged(status, other)).toBe(false);
    expect(
      isConstructionStatusChanged(
        status,
        sender,
        ConstructionStatus.Destructed,
      ),
    ).toBe(false);

    const constructed = from(messages).pipe(
      filter((message) =>
        isConstructionStatusChanged(
          message,
          sender,
          ConstructionStatus.Constructed,
        ),
      ),
    );
    expectType<Observable<ConstructionStatusChangedMessage>>(constructed);
  });
});
