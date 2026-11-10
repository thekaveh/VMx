# VMx Inspector

A terminal UI showcase app for the **VMx** hierarchical MVVM framework, built with
[Textual](https://github.com/Textualize/textual).
Architecture diagram:
[`python-textual-inspector.svg`](../../../../docs/assets/diagrams/python-textual-inspector.svg)
([HTML](../../../../docs/assets/diagrams/python-textual-inspector.html),
[PNG](../../../../docs/assets/diagrams/python-textual-inspector.png)).

## 1. What it does

The inspector renders a live VMx hierarchy and lets you drive lifecycle operations
from the keyboard. This abbreviated sketch shows the sample tree after a
reconstruct of the root node. The real message log shows more rows and the
full message type names.

```text
┌───────────────────────────────┬──────────────────────────────────────────┐
│ VM Tree                       │ Node Details                             │
│                               │                                          │
│ ▼ app                         │ name:           app                      │
│     header                    │ type:           Composite                │
│   ▼ workspace                 │ status:         CONSTRUCTED              │
│       editor                  │ is_constructed: True                     │
│       terminal                │ is_current:     False                    │
│       inspector               │ parent:         —                        │
│   ▼ state-lab                 ├──────────────────────────────────────────┤
│       form-vm                 │ Hub Messages                             │
│       discriminator-vm        │ Time      Sender  Type       Detail      │
│       token-paged-composition │ 12:34:05  app     Construc…  DESTRUCTING │
│   ▼ sidebar                   │ …                                        │
│       files                   │ 12:34:05  app     Construc…  CONSTRUCTED │
│       git                     │                                          │
│       search                  │                                          │
└───────────────────────────────┴──────────────────────────────────────────┘
 q Quit  c Construct  d Destruct  r Reconstruct  x Dispose  s Select  ? Help
```

The left pane shows the VM tree (built with `walk(root)` from `vmx.tree`).  
The top-right pane shows property details for the selected node.  
The bottom-right pane is a scrolling log of messages received on the shared
`MessageHub`.

## 2. Running

Run from the repository root:

```bash
uv run --project examples/python/textual/inspector python -m vmx_inspector
```
