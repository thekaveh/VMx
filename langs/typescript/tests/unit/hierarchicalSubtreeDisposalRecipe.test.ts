/**
 * Executable form of the subtree-disposal recipe in
 * docs/content/primitives/viewmodel-families/hierarchical-family.md. The
 * docs-snippet region is shown there verbatim, dedented, and `make docs-check`
 * keeps them equal. No conformance ID (recipe; spec/18 §3, spec/02 §7).
 */
import { describe, expect, it } from "vitest";
import {
  ConstructionStatus,
  HierarchicalVM,
  MessageHub,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";

interface Folder {
  name: string;
  folders?: Folder[];
  failOnDispose?: boolean;
}

class FolderVM extends HierarchicalVM<Folder, FolderVM> {
  constructor(
    model: Folder,
    private readonly disposed: string[],
    private readonly factoryCalls: string[] = [],
  ) {
    super({
      model,
      name: model.name,
      hub: new MessageHub(),
      dispatcher: RxDispatcher.immediate(),
      eagerChildren: true,
      childrenFactory: (parent) => {
        factoryCalls.push(parent.model.name);
        return (parent.model.folders ?? []).map(
          (folder) => new FolderVM(folder, disposed, factoryCalls),
        );
      },
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }

  protected override _onDispose(): void {
    super._onDispose();
    this.disposed.push(this.model.name);
    if (this.model.failOnDispose) throw new Error(`${this.model.name} failed`);
  }
}

// docs-snippet:start dispose-subtree
interface DisposableTreeNode {
  readonly children: readonly DisposableTreeNode[];
  dispose(): void;
}

/** Disposes a node's materialized subtree, children first. */
function disposeSubtree(node: DisposableTreeNode): void {
  let failed = false;
  let firstError: unknown;
  const attempt = (action: () => void): void => {
    try {
      action();
    } catch (error) {
      if (!failed) {
        failed = true;
        firstError = error;
      }
    }
  };
  for (const child of [...node.children]) attempt(() => disposeSubtree(child));
  attempt(() => node.dispose());
  if (failed) throw firstError;
}
// docs-snippet:end dispose-subtree

function tree(disposed: string[], failing: string[] = []): FolderVM {
  const folder = (name: string, folders?: Folder[]): Folder => ({
    name,
    ...(folders ? { folders } : {}),
    failOnDispose: failing.includes(name),
  });
  const root = new FolderVM(
    folder("root", [folder("docs", [folder("drafts")]), folder("photos")]),
    disposed,
  );
  root.construct();
  return root;
}

describe("hierarchical subtree disposal recipe", () => {
  it("leaves children constructed when only the node is disposed (spec/18 §3)", () => {
    const root = tree([]);
    const [docs] = root.children;

    root.dispose();

    expect(root.status).toBe(ConstructionStatus.Disposed);
    expect(docs?.status).toBe(ConstructionStatus.Constructed);
  });

  it("disposes the materialized subtree depth-first, children before parents", () => {
    const disposed: string[] = [];
    const root = tree(disposed);
    const nodes = [root, ...root.children, ...root.children.flatMap((child) => child.children)];

    disposeSubtree(root);

    expect(disposed).toEqual(["drafts", "docs", "photos", "root"]);
    expect(nodes.every((node) => node.status === ConstructionStatus.Disposed)).toBe(true);
  });

  it("keeps going after a failed node and rethrows the first failure", () => {
    const disposed: string[] = [];
    const root = tree(disposed, ["drafts", "photos"]);

    expect(() => disposeSubtree(root)).toThrowError("drafts failed");
    expect(disposed).toEqual(["drafts", "docs", "photos", "root"]);
  });

  it("does not reach children dropped by invalidation", () => {
    const disposed: string[] = [];
    const root = tree(disposed);
    const [docs] = root.children;

    root.invalidateChildren();
    disposeSubtree(root);

    // The next read built fresh children; the dropped node stays live.
    expect(docs?.parent).toBeNull();
    expect(docs?.status).toBe(ConstructionStatus.Constructed);
    expect(root.children).not.toContain(docs);
  });

  it("materializes a lazy level when it reads children", () => {
    const factoryCalls: string[] = [];
    const lazy = new (class extends HierarchicalVM<Folder, FolderVM> {
      override get type(): ViewModelType {
        return ViewModelType.Component;
      }
    })({
      model: { name: "lazy", folders: [{ name: "child" }] },
      hub: new MessageHub(),
      dispatcher: RxDispatcher.immediate(),
      childrenFactory: (parent) => {
        factoryCalls.push(parent.model.name);
        return (parent.model.folders ?? []).map((folder) => new FolderVM(folder, []));
      },
    });
    lazy.construct();
    expect(factoryCalls).toEqual([]);

    disposeSubtree(lazy);

    expect(factoryCalls).toEqual(["lazy"]);
  });
});
