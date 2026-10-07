# VMx benchmarks

Dependency-free benchmark harnesses for the TypeScript, Python, and Rust
flavors, the committed baselines they are compared against, and nothing that
ships in a published package. The method, commands, report format, and review
thresholds are in
[docs/content/performance-methodology.md](../docs/content/performance-methodology.md).

| Path          | Harness                                                        |
| ------------- | -------------------------------------------------------------- |
| `typescript/` | `node --expose-gc benchmarks/typescript/run.mjs`               |
| `python/`     | `uv run --project langs/python python benchmarks/python/run.py` |
| `rust/`       | `cargo run --release --locked --manifest-path benchmarks/rust/Cargo.toml --` |
| `baselines/`  | Reports recorded on a named machine, compared with `tools/compare-benchmarks.py` |
