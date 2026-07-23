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

Regenerate the triplets with `python3 generate_diagrams.py`; the renderer
requires `rsvg-convert` and `pngquant` on `PATH`.
