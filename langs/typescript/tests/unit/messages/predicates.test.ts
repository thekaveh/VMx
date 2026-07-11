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
  ServicedObservableCollection,
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
const collectionSource = new ServicedObservableCollection<string>();
const otherCollectionSource = new ServicedObservableCollection<string>();
const opaqueCollectionSource: object = collectionSource;
const collection = CollectionChangedMessage.forAdd(
  collectionSource,
  "item",
  0,
);
const status = ConstructionStatusChangedMessage.create(
  sender,
  "sender",
  ConstructionStatus.Constructed,
);
const messages: IMessage[] = [property, collection, status];

// @ts-expect-error A property generic requires a checked sender constraint.
isPropertyChanged<typeof sender>(property, { propertyName: "model" });
// @ts-expect-error Collection predicates never accept an item generic.
isCollectionChanged<string>(collection, { action: "add" });

function _assertForgedCollectionPayloadRemainsUnknown(): void {
  const typedSource = new ServicedObservableCollection<string>();
  const forgedMessage: IMessage = CollectionChangedMessage.forAdd(
    typedSource,
    42,
    0,
  );

  if (
    isCollectionChanged(forgedMessage, { source: typedSource }) &&
    forgedMessage.newItems[0] !== undefined
  ) {
    /* eslint-disable @typescript-eslint/no-unsafe-call -- the intentionally unknown payload must reject this string method */
    // @ts-expect-error Source identity cannot prove the public message payload type.
    forgedMessage.newItems[0].toUpperCase();
    /* eslint-enable @typescript-eslint/no-unsafe-call */
  }
}

describe("raw message predicates", () => {
  it("classifies property changes and narrows their sender type", () => {
    expect(isPropertyChanged(property)).toBe(true);
    expect(isPropertyChangedFromMessages(property)).toBe(true);
    expect(
      isPropertyChanged(property, { sender, propertyName: "model" }),
    ).toBe(true);
    expect(isPropertyChanged(collection)).toBe(false);
    expect(isPropertyChanged(property, { sender: other })).toBe(false);
    expect(
      isPropertyChanged(property, { sender, propertyName: "Model" }),
    ).toBe(false);
    expect(isPropertyChanged(property, { sender: undefined })).toBe(false);
    expect(
      isPropertyChanged(property, { propertyName: undefined }),
    ).toBe(false);

    const allProperties = messages.filter(isPropertyChanged);
    expect(allProperties).toEqual([property]);
    expectExactType<
      IsExact<typeof allProperties, PropertyChangedMessage<unknown>[]>
    >(allProperties);

    const allPropertyStream = from(messages).pipe(filter(isPropertyChanged));
    const streamedProperties: PropertyChangedMessage<unknown>[] = [];
    allPropertyStream.subscribe((message) => {
      streamedProperties.push(message);
    });
    expect(streamedProperties).toEqual([property]);
    expectExactType<
      IsExact<
        typeof allPropertyStream,
        Observable<PropertyChangedMessage<unknown>>
      >
    >(allPropertyStream);

    const namedProperties = messages.filter((message) =>
      isPropertyChanged(message, { propertyName: "model" }),
    );
    expect(namedProperties).toEqual([property]);
    expectExactType<
      IsExact<typeof namedProperties, PropertyChangedMessage<unknown>[]>
    >(namedProperties);

    const emptyConstraintProperties = messages.filter((message) =>
      isPropertyChanged(message, {}),
    );
    expect(emptyConstraintProperties).toEqual([property]);
    expectExactType<
      IsExact<
        typeof emptyConstraintProperties,
        PropertyChangedMessage<unknown>[]
      >
    >(emptyConstraintProperties);

    const senderProperties = messages.filter((message) =>
      isPropertyChanged(message, { sender, propertyName: "model" }),
    );
    expect(senderProperties).toEqual([property]);
    expectExactType<
      IsExact<
        typeof senderProperties,
        PropertyChangedMessage<typeof sender>[]
      >
    >(senderProperties);

    const senderPropertyStream = from(messages).pipe(
      filter((message) =>
        isPropertyChanged(message, { sender, propertyName: "model" }),
      ),
    );
    expectExactType<
      IsExact<
        typeof senderPropertyStream,
        Observable<PropertyChangedMessage<typeof sender>>
      >
    >(senderPropertyStream);
  });

  it("classifies collection changes without inferring their item type", () => {
    const wrongAction: CollectionMutationAction = "remove";

    expect(isCollectionChanged(collection)).toBe(true);
    expect(
      isCollectionChanged(collection, {
        source: collectionSource,
        action: "add",
      }),
    ).toBe(true);
    expect(isCollectionChanged(property)).toBe(false);
    expect(
      isCollectionChanged(collection, { source: otherCollectionSource }),
    ).toBe(false);
    expect(
      isCollectionChanged(collection, {
        source: collectionSource,
        action: wrongAction,
      }),
    ).toBe(false);
    expect(isCollectionChanged(collection, { source: undefined })).toBe(false);
    expect(isCollectionChanged(collection, { action: undefined })).toBe(false);

    const allCollections = messages.filter(isCollectionChanged);
    expect(allCollections).toEqual([collection]);
    expectExactType<
      IsExact<typeof allCollections, CollectionChangedMessage<unknown>[]>
    >(allCollections);

    const allCollectionStream = from(messages).pipe(
      filter(isCollectionChanged),
    );
    const streamedCollections: CollectionChangedMessage<unknown>[] = [];
    allCollectionStream.subscribe((message) => {
      streamedCollections.push(message);
    });
    expect(streamedCollections).toEqual([collection]);
    expectExactType<
      IsExact<
        typeof allCollectionStream,
        Observable<CollectionChangedMessage<unknown>>
      >
    >(allCollectionStream);

    const additions = messages.filter((message) =>
      isCollectionChanged(message, {
        source: collectionSource,
        action: "add",
      }),
    );
    expect(additions).toEqual([collection]);
    expectExactType<
      IsExact<typeof additions, CollectionChangedMessage<unknown>[]>
    >(additions);

    const additionsByAction = messages.filter((message) =>
      isCollectionChanged(message, { action: "add" }),
    );
    expect(additionsByAction).toEqual([collection]);
    expectExactType<
      IsExact<
        typeof additionsByAction,
        CollectionChangedMessage<unknown>[]
      >
    >(additionsByAction);

    const additionsByOpaqueSource = messages.filter((message) =>
      isCollectionChanged(message, { source: opaqueCollectionSource }),
    );
    expect(additionsByOpaqueSource).toEqual([collection]);
    expectExactType<
      IsExact<
        typeof additionsByOpaqueSource,
        CollectionChangedMessage<unknown>[]
      >
    >(additionsByOpaqueSource);
  });

  it("classifies construction status changes and narrows the stream", () => {
    expect(isConstructionStatusChanged(status)).toBe(true);
    expect(
      isConstructionStatusChanged(status, {
        sender,
        status: ConstructionStatus.Constructed,
      }),
    ).toBe(true);
    expect(isConstructionStatusChanged(property)).toBe(false);
    expect(
      isConstructionStatusChanged(status, { sender: other }),
    ).toBe(false);
    expect(
      isConstructionStatusChanged(status, {
        sender,
        status: ConstructionStatus.Destructed,
      }),
    ).toBe(false);
    expect(
      isConstructionStatusChanged(status, { sender: undefined }),
    ).toBe(false);
    expect(
      isConstructionStatusChanged(status, { status: undefined }),
    ).toBe(false);

    const allStatuses = messages.filter(isConstructionStatusChanged);
    expect(allStatuses).toEqual([status]);
    expectExactType<
      IsExact<typeof allStatuses, ConstructionStatusChangedMessage[]>
    >(allStatuses);

    const allStatusStream = from(messages).pipe(
      filter(isConstructionStatusChanged),
    );
    const streamedStatuses: ConstructionStatusChangedMessage[] = [];
    allStatusStream.subscribe((message) => {
      streamedStatuses.push(message);
    });
    expect(streamedStatuses).toEqual([status]);
    expectExactType<
      IsExact<
        typeof allStatusStream,
        Observable<ConstructionStatusChangedMessage>
      >
    >(allStatusStream);

    const isConstructed = (message: IMessage) =>
      isConstructionStatusChanged(message, {
        sender,
        status: ConstructionStatus.Constructed,
      });
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
