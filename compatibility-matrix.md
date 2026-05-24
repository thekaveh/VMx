# Spec ↔ language compatibility matrix

Maintained by hand alongside spec releases.

| spec  | csharp         | python         | typescript     |
| ----- | -------------- | -------------- | -------------- |
| 1.1.x | 1.1.0 – 1.2.0  | 1.1.0 – 1.2.0  | 1.1.0 – 1.2.0  |
| 1.0.x | 1.0.0          | 1.0.0          | —              |

A `—` cell indicates no flavor has released against that spec version. Once a
flavor ships, its cell shows the version range that implements this spec major
(e.g. `1.0.0` or `1.0.0–1.2.x` once minor/patch releases follow).
