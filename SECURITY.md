# Security Policy

## 1. Supported Versions

VMx applies security fixes to the current source line and to the latest stable
release of each published distribution. Older releases and historical commits
are unsupported; upgrade before requesting a backport.

| Distribution | Supported line |
| --- | --- |
| Repository source and unpublished flavors | Current `main` |
| Python (`vmx` on PyPI) | Latest stable PyPI release |
| Swift (`VMx` through SwiftPM) | Latest stable GitHub release |
| C# (`VMx`), TypeScript (`@thekaveh/vmx`), and Rust (`vmx-rs`) | Current `main` until the first public registry release; latest stable release thereafter |

The compatibility matrix describes implementation compatibility, not a promise
to maintain every historical package line.

## 2. Reporting a Vulnerability

Report security issues privately, not in public issues. Email
`kaveh.razavi@gmail.com` with subject `[VMx security]`. GitHub private
vulnerability reporting is not currently enabled for this repository, so the
public issue tracker and Security-tab issue flow are not confidential channels.

You will receive an acknowledgement within 72 hours. Coordinated disclosure
timelines are negotiated case by case.
