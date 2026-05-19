# VMx

[![csharp](https://github.com/kavehr/VMx/actions/workflows/csharp.yml/badge.svg)](https://github.com/kavehr/VMx/actions/workflows/csharp.yml)
[![python](https://github.com/kavehr/VMx/actions/workflows/python.yml/badge.svg)](https://github.com/kavehr/VMx/actions/workflows/python.yml)
[![docs](https://github.com/kavehr/VMx/actions/workflows/docs.yml/badge.svg)](https://github.com/kavehr/VMx/actions/workflows/docs.yml)
[![conformance](https://github.com/kavehr/VMx/actions/workflows/conformance.yml/badge.svg)](https://github.com/kavehr/VMx/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A hierarchical, lifecycle-aware MVVM viewmodel framework, available in multiple language flavors.

| Flavor | Package | Status |
| --- | --- | --- |
| C# | [`VMx`](https://www.nuget.org/packages/VMx/) on NuGet | scaffolding — not yet released |
| Python | [`vmx`](https://pypi.org/project/vmx/) on PyPI | scaffolding — not yet released |
| TypeScript | `vmx` on npm | planned (post-1.0) |

## Repository layout

- `spec/` — the language-neutral specification (source of truth for every flavor).
- `docs/` — user-facing documentation site sources.
- `examples/` — runnable example projects per language.
- `langs/<lang>/` — one self-contained project per language flavor.
- `tools/` — cross-cutting scripts (conformance coverage, compatibility-matrix generator).
- `.github/` — issue/PR templates and CI workflows.

## Getting started

See the language-specific quickstart pages:
- `docs/getting-started/csharp.md` (arrives in Phase 2 of the roadmap)
- `docs/getting-started/python.md` (arrives in Phase 3 of the roadmap)

## Versioning

Each language flavor versions independently in SemVer; the spec versions independently in SemVer too.
Every published package declares the spec version it implements. See [`compatibility-matrix.md`](compatibility-matrix.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the design spec at
[`docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`](docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md).

## License

MIT — see [`LICENSE`](LICENSE).
