# License inventory

This inventory covers the REED QR plugin and its locked dependencies. Project
metadata, the root license and both Rust crates declare MIT. Dependencies
retain their own license terms and upstream attribution.

## Rust dependencies

All 90 third-party package/version entries in `Cargo.lock` have collected license
evidence. The graph includes normal, build, development and target-specific
dependencies. It declares permissive licenses and exceptions; no GPL, LGPL or
MPL declaration was found in this Rust graph.

- [Package inventory](docs/licenses/rust-dependencies.md)
- [License texts and copyright notices](licenses/RUST-THIRD-PARTY.txt)
- [Package checksums and notice hashes](licenses/manifest.json)

The current graph includes image 0.25.10, zune-core 0.5.3 and zune-jpeg 0.5.15.
All resolved crates supply license evidence in their released packages; no
external license-file workaround is needed for this graph.

The notice collector preserves released text and source copyright lines. It
does not infer that every resolved dependency is linked on every target.

The Rust standard library is supplied by the toolchain rather than Cargo.lock.
Its [upstream copyright inventory](licenses/RUST-STDLIB.html), including full
license texts, is retained from the pinned Rust distribution and included in
Python artifacts. The inventory covers target-specific library files and their
exceptions as well as the common MIT/Apache terms.

## Python dependencies

The base Python package has no required Python runtime dependencies. The
[Python inventory](docs/licenses/python-dependencies.md) covers every entry in
`uv.lock`, distinguishing the optional LiveKit extra, build backend and development
tools. These are separate distributions; their license expressions do not replace
their actual license files or native component notices.

The development graph includes the MIT-licensed ast-serialize dependency used by
mypy 2.4.0. Its supplied license files were reviewed with the new toolchain.

The optional LiveKit RTC 1.2.0 bundle includes WebRTC and mixed-license media components.
Its shipped `livekit/rtc/resources/LICENSE.md` contains Apache, BSD, MIT, Zlib,
custom permissive notices and FFmpeg GPL/LGPL texts. The presence of those texts
alone does not establish which FFmpeg features were compiled. Matching native
build provenance remains necessary before repackaging those binaries.

The installed Windows NumPy wheel also includes OpenBLAS/LAPACK and GCC runtime
notices, including GPL with the GCC runtime exception. Other platforms can select
different native payloads. The development-only pathspec dependency declares MPL-2.0.

## Packaging and maintenance

Python artifacts must include `LICENSE`, `THIRD_PARTY_NOTICES.md`, and the complete
Rust dependency and standard-library notices. Both Rust crates carry a local
`LICENSE`; the core package also carries its scoped dependency notice bundle.
`scripts/check_artifacts.py`
checks the built wheel and source archive contents.

Run `scripts/update_license_inventory.py --check` after fetching locked Rust
sources. Regenerate and review notices whenever `Cargo.lock` changes, and update
the Python inventory whenever `uv.lock` changes.

This is an inventory and packaging review, not certification of source ownership,
patent clearance, or every company's distribution policy. Other platform wheels,
native RTC provenance and external toolchain internals need separate review.
