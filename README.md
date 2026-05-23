# VMx

[![csharp](https://github.com/thekaveh/VMx/actions/workflows/csharp.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/csharp.yml)
[![python](https://github.com/thekaveh/VMx/actions/workflows/python.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/python.yml)
[![typescript](https://github.com/thekaveh/VMx/actions/workflows/typescript.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/typescript.yml)
[![conformance](https://github.com/thekaveh/VMx/actions/workflows/conformance.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A hierarchical, lifecycle-aware MVVM viewmodel framework, available in multiple language flavors.

| Flavor | Package | Status |
| --- | --- | --- |
| C# | [`VMx`](https://www.nuget.org/packages/VMx/) on NuGet | v1.1.0 |
| Python | [`vmx`](https://pypi.org/project/vmx/) on PyPI | v1.1.0 |
| TypeScript | [`vmx`](https://www.npmjs.com/package/vmx) on npm | v1.1.0 |

## Repository layout

- `spec/` — the language-neutral specification (source of truth for every flavor).
- `docs/` — user-facing documentation site sources.
- `examples/` — runnable example projects per language.
- `langs/<lang>/` — one self-contained project per language flavor.
- `tools/` — cross-cutting scripts (conformance coverage, compatibility-matrix generator).
- `.github/` — issue/PR templates and CI workflows.

## Getting started

See the language-specific quickstart pages:
- [`docs/getting-started/csharp.md`](docs/getting-started/csharp.md)
- [`docs/getting-started/python.md`](docs/getting-started/python.md)

## Versioning

Each language flavor versions independently in SemVer; the spec versions independently in SemVer too.
Every published package declares the spec version it implements. See [`compatibility-matrix.md`](compatibility-matrix.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

MIT — see [`LICENSE`](LICENSE).
