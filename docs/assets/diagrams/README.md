# VMx Documentation Diagrams

`diagram-registry.json` is the maintained inventory and metadata source for the
diagram IDs, titles, filenames, and documentation references.
`generate_diagrams.py` defines the visual content and layout, derives repository
facts from the specification, validates that its definitions match the registry,
and emits assets used by the `.io` site and GitHub wiki. Each diagram is stored
as:

- `.html` — standalone generated page
- `.svg` — vector embed
- `.png` — high-resolution landscape image for GitHub/wiki rendering

The HTML, SVG, and PNG files are generated outputs. Update the registry and
generator together when adding, removing, renaming, or retitling a diagram.

Each PNG records the SHA-256 digest of the SVG it was rendered from, in a PNG
`tEXt` chunk named `vmx-svg-sha256`. PNG bytes differ between rasterizer stacks,
for example between macOS and Ubuntu. Thus the generators render a PNG only when
its recorded digest differs from its current SVG. A run on another host keeps
every PNG whose SVG did not change. `--check` compares the HTML and SVG bytes.
For each PNG, it reports a missing PNG or a PNG whose digest differs from the
current SVG. It never renders a PNG.

Run these commands from the repository root. The renderer requires
`rsvg-convert` and `pngquant` on `PATH` when a PNG must be rendered again.

```bash
python3 docs/assets/diagrams/generate_diagrams.py          # regenerate
python3 docs/assets/diagrams/generate_diagrams.py --check  # verify drift (CI)
python3 tools/generate-doc-diagrams.py --check             # root diagrams
python3 -m scripts.docs.validate_diagrams                  # links and assets
```

`make docs-check` runs all of these checks.
