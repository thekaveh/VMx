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

type IsAny<T> = 0 extends 1 & T ? true : false;

type IsExact<TActual, TExpected> = IsAny<TActual> extends true
  ? false
  : IsAny<TExpected> extends true
    ? false
    : (<T>() => T extends TActual ? 1 : 2) extends <T>() =>
          T extends TExpected ? 1 : 2
      ? (<T>() => T extends TExpected ? 1 : 2) extends <T>() =>
          T extends TActual ? 1 : 2
        ? true
        : false
      : false;

function expectExactType<_T extends true>(_value: unknown): void {}

const sender = { name: "sender" };
const other = { name: "sender" };
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
    expect(isPropertyChanged(property, sender, "model")).toBe(true);
    expect(isPropertyChanged(collection)).toBe(false);
    expect(isPropertyChanged(property, other)).toBe(false);
    expect(isPropertyChanged(property, sender, "Model")).toBe(false);

    const allProperties = messages.filter(isPropertyChanged);
    expectExactType<
      IsExact<typeof allProperties, PropertyChangedMessage<unknown>[]>
    >(allProperties);

    const senderProperties = messages.filter((message) =>
      isPropertyChanged(message, sender, "model"),
    );
    expect(senderProperties).toEqual([property]);
    expectExactType<
      IsExact<
        typeof senderProperties,
        PropertyChangedMessage<typeof sender>[]
      >
    >(senderProperties);

    const propertyStream = from(messages).pipe(
      filter((message) => isPropertyChanged(message, sender, "model")),
    );
    expectExactType<
      IsExact<
        typeof propertyStream,
        Observable<PropertyChangedMessage<typeof sender>>
      >
    >(propertyStream);
  });

  it("classifies collection changes and narrows their item type", () => {
    const wrongAction: CollectionMutationAction = "remove";

    expect(isCollectionChanged<string>(collection)).toBe(true);
    expect(isCollectionChanged<string>(collection, sender, "add")).toBe(true);
    expect(isCollectionChanged<string>(property)).toBe(false);
    expect(isCollectionChanged<string>(collection, other)).toBe(false);
    expect(isCollectionChanged<string>(collection, sender, wrongAction)).toBe(
      false,
    );

    const additions = messages.filter((message) =>
      isCollectionChanged<string>(message, sender, "add"),
    );
    expect(additions).toEqual([collection]);
    expectExactType<
      IsExact<typeof additions, CollectionChangedMessage<string>[]>
    >(additions);
  });

  it("classifies construction status changes and narrows the stream", () => {
    expect(isConstructionStatusChanged(status)).toBe(true);
    expect(
      isConstructionStatusChanged(
        status,
        sender,
        ConstructionStatus.Constructed,
      ),
    ).toBe(true);
    expect(isConstructionStatusChanged(property)).toBe(false);
    expect(isConstructionStatusChanged(status, other)).toBe(false);
    expect(
      isConstructionStatusChanged(
        status,
        sender,
        ConstructionStatus.Destructed,
      ),
    ).toBe(false);

    const isConstructed = (message: IMessage) =>
      isConstructionStatusChanged(
        message,
        sender,
        ConstructionStatus.Constructed,
      );
    const constructedMessages = messages.filter(isConstructed);
    expect(constructedMessages).toEqual([status]);

    const constructed = from(messages).pipe(
      filter(isConstructed),
    );
    expectExactType<
      IsExact<typeof constructed, Observable<ConstructionStatusChangedMessage>>
    >(constructed);
  });
});
