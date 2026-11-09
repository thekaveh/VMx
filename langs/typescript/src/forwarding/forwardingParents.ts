/**
 * @internal Parent links shared by the forwarding decorators.
 *
 * A forwarding decorator in a container shares one ownership identity with the
 * wrapped component (spec/09-forwarding.md §1 and §2). The container records
 * the decorator as its child, and the wrapped component records a
 * `ForwardingParent` that routes selection and transfer through the decorator.
 * A decorator over a component that another container owns reads that parent
 * through a `WrappedParent`, so a later transfer detaches the wrapped
 * component from its old container.
 */
import {
  ComponentVMBase,
  type IOwningParentVM,
  ParentTransfer,
} from "../components/componentVMBase.js";

/** @internal A forwarding decorator that joins containers for a wrapped VM. */
export type ForwardingWrapper = ComponentVMBase & { readonly wrappedBase: ComponentVMBase };

const directForwardingParents = new WeakMap<object, IOwningParentVM | null>();

class ForwardingParent implements IOwningParentVM {
  constructor(
    readonly parent: IOwningParentVM,
    private readonly wrapper: ForwardingWrapper,
  ) {}

  get retainedWrapper(): ForwardingWrapper { return this.wrapper; }

  get owner(): ComponentVMBase { return this.parent.owner; }
  get ownerParent(): IOwningParentVM | null { return this.parent.ownerParent; }
  get supportsChildSelection(): boolean { return this.parent.supportsChildSelection; }
  get currentChild(): ComponentVMBase | null {
    return this.parent.currentChild === this.wrapper
      ? this.wrapper.wrappedBase
      : this.parent.currentChild;
  }
  selectChild(_vm: ComponentVMBase): void { this.parent.selectChild(this.wrapper); }
  deselectChild(_vm: ComponentVMBase): void { this.parent.deselectChild(this.wrapper); }
  containsChild(_vm: ComponentVMBase): boolean { return this.parent.containsChild(this.wrapper); }
  detachForTransfer(_vm: ComponentVMBase): ParentTransfer {
    const staged = this.parent.detachForTransfer(this.wrapper);
    return new ParentTransfer(
      () => {
        try { staged.commit(); }
        finally { directForwardingParents.set(this.wrapper, null); }
      },
      () => staged.rollback(),
    );
  }
}

class WrappedParent implements IOwningParentVM {
  constructor(
    private readonly parent: IOwningParentVM,
    private readonly wrapper: ForwardingWrapper,
    private readonly wrapped: ComponentVMBase,
  ) {}

  get owner(): ComponentVMBase { return this.parent.owner; }
  get ownerParent(): IOwningParentVM | null { return this.parent.ownerParent; }
  get supportsChildSelection(): boolean { return this.parent.supportsChildSelection; }
  get currentChild(): ComponentVMBase | null {
    return this.parent.currentChild === this.wrapped ? this.wrapper : this.parent.currentChild;
  }
  selectChild(_vm: ComponentVMBase): void { this.parent.selectChild(this.wrapped); }
  deselectChild(_vm: ComponentVMBase): void { this.parent.deselectChild(this.wrapped); }
  containsChild(_vm: ComponentVMBase): boolean { return this.parent.containsChild(this.wrapped); }
  detachForTransfer(_vm: ComponentVMBase): ParentTransfer {
    const retainedWrappers: ForwardingWrapper[] = [];
    let cursor: IOwningParentVM | null = this.parent;
    while (cursor instanceof ForwardingParent) {
      retainedWrappers.push(cursor.retainedWrapper);
      cursor = cursor.parent;
    }
    const staged = this.parent.detachForTransfer(this.wrapped);
    return new ParentTransfer(
      () => {
        try {
          staged.commit();
        } finally {
          for (const retainedWrapper of retainedWrappers) {
            if (retainedWrapper !== this.wrapper) {
              directForwardingParents.set(retainedWrapper, null);
            }
          }
        }
      },
      () => staged.rollback(),
    );
  }
}

/** @internal The parent link a forwarding decorator reports to containers. */
export function forwardingParentOf(
  wrapper: ForwardingWrapper,
  wrapped: unknown,
): IOwningParentVM | null {
  const direct = directForwardingParents.get(wrapper) ?? null;
  if (direct !== null) return direct;
  if (!(wrapped instanceof ComponentVMBase)) return null;
  const wrappedParent = wrapped._parent;
  return wrappedParent === null ? null : new WrappedParent(wrappedParent, wrapper, wrapped);
}

/** @internal Record the container that owns a forwarding decorator. */
export function setForwardingParent(
  wrapper: ForwardingWrapper,
  wrapped: unknown,
  parent: IOwningParentVM | null,
): void {
  directForwardingParents.set(wrapper, parent);
  if (wrapped instanceof ComponentVMBase) {
    wrapped._parent = parent === null ? null : new ForwardingParent(parent, wrapper);
  }
}
