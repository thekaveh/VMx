# VMx Documentation Diagrams

`generate_diagrams.py` is the source of truth for the diagrams in this
directory. It derives repository facts from the specification and emits assets
used by the `.io` site and GitHub wiki. Each diagram is stored as:

- `.html` — standalone generated page
- `.svg` — vector embed
- `.png` — high-resolution landscape image for GitHub/wiki rendering

`diagram-registry.json` is the generated inventory used by validation; the
HTML, SVG, PNG, and registry files are all generated outputs.

Regenerate the triplets with `python3 generate_diagrams.py`; the renderer
requires `rsvg-convert` and `pngquant` on `PATH`.
