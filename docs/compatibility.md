# Compatibility and validation

The Python package supports standard CPython 3.11–3.15. Rust sources use the
toolchain pinned in `rust-toolchain.toml` and declare Rust 1.99 as the minimum.

| Platform | Validation |
| --- | --- |
| Windows x86_64 | 44 core/adapter tests and strict type checks pass on CPython 3.11.18, 3.12.16, 3.13.18, 3.14.10 and 3.15.2 |
| Linux x86_64 | CI configured; build and installation not yet verified |
| macOS Apple Silicon | 44 Python tests and strict type checks pass on CPython 3.14.3 with a non-editable source installation; Rust tests and the complete wheel matrix remain pending |
| macOS Intel | CI configured; build and installation not yet verified |
| Other Python/platform combinations | Require their own native build and test results |

The development environment uses Python 3.15.2 and uv 0.13.6. CI includes all five
supported Python minors on Linux x86_64, Windows x86_64, and both macOS
architectures. Linux CI wheels target manylinux_2_28. Every job builds from the
source distribution and tests the installed wheel. macOS runners cover version 15
on Intel and Apple Silicon, plus version 27 on Apple Silicon through `xcode-27`.
Linux runners cover Ubuntu 24.04 and 26.04 LTS. These configured checks do
not replace successful platform results; Linux, Intel macOS, and the complete
Apple Silicon wheel matrix still require successful runs. Ruff and mypy retain Python 3.11 as their source-language
target so newer development tools do not introduce syntax incompatible with the
oldest supported consumer interpreter.

Windows wheels for all five Python versions passed clean installation checks
using pip, `uv pip install`, and `uv add`. The checks use isolated Python mode
and a restricted Windows PATH so unrelated SDK DLLs cannot mask missing imports.
The source archive and Cargo package also pass license and package-content checks.
A wheel rebuilt from the source archive passed all three clean-install workflows.

The test suite covers independent QR generation, UTF-8 and binary payloads,
rotations, multiple symbols, packed pixel layouts, image loading and resource
limits. Scanner tests cover overload, sampling, duplicate suppression, stale
frames, source replacement, cancellation and shutdown. RTC tests cover selected
tracks, reconnect events, participant departure and reader failures.

Local integration checks with LiveKit RTC 1.1.21 and 1.2.0 exercised generated 720p video
through an actual server, a bounded scan function, and the updated Rust decoder.
Changing QR values returned fresh results; blank video timed out, duplicates were
suppressed, and reader/server shutdown completed. Function invocation was
programmatic; spoken model-driven calls were outside that check.

The full Python suite also passes with RTC 1.1.21 on Windows CPython 3.14.3.
The optional dependency range preserves compatibility with agent SDKs that pin
that RTC release; the development lockfile continues to select RTC 1.2.0.

Perspective, blur, glare, occlusion and device variability need a larger camera
corpus. Long-session memory behavior, SDK buffering and latency budgets still
need measurement. Passing synthetic and contract tests does not establish those
performance or accuracy guarantees.
