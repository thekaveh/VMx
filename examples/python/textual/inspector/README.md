# VMx Inspector

A terminal UI showcase app for the **VMx** hierarchical MVVM framework, built with
[Textual](https://github.com/Textualize/textual).
Architecture diagram:
[`python-textual-inspector.svg`](../../../../docs/assets/diagrams/python-textual-inspector.svg)
([HTML](../../../../docs/assets/diagrams/python-textual-inspector.html),
[PNG](../../../../docs/assets/diagrams/python-textual-inspector.png)).

## 1. What it does

The inspector renders a live VMx hierarchy and lets you drive lifecycle operations
from the keyboard:

```
┌─────────────────────┬──────────────────────────────┐
│  VM Tree            │  Node Details                │
│                     │  ─────────────               │
│  ▼ app              │  name:           app         │
│    header           │  type:           Composite   │
│  ▼ workspace        │  status:         Constructed │
│      editor         │  is_constructed: True        │
│      terminal       │  is_current:     False       │
│      inspector      │  parent:         —           │
│  ▼ sidebar          ├──────────────────────────────┤
│      files          │  Hub messages                │
│      git            │  ts         sender  type     │
│      search         │  12:34:05   app     Construct│
│                     │  …                           │
└─────────────────────┴──────────────────────────────┘
 q quit  c construct  d destruct  r reconstruct  x dispose  s select  ? help
```

The left pane shows the VM tree (built with `walk(root)` from `vmx.tree`).  
The top-right pane shows property details for the selected node.  
The bottom-right pane is a scrolling log of messages received on the shared
`MessageHub`.

## 2. Running

```
uv run --project examples/python/textual/inspector python -m vmx_inspector
```

(Run from the repository root.)
