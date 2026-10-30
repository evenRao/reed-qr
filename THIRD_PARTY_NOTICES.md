# Third-party notices

REED QR is licensed under MIT. Its dependencies retain their own license
terms, copyright notices and attribution.

The compiled Python extension uses the Rust dependencies resolved in `Cargo.lock`.
Their complete available license texts and notices are included in
[licenses/RUST-THIRD-PARTY.txt](licenses/RUST-THIRD-PARTY.txt). This bundle covers
all resolved targets, including build and test dependencies, and is included in
Python wheels and source distributions. The Rust core crate includes its own
`LICENSE` and scoped `THIRD_PARTY_NOTICES.txt`.

The compiled extension also uses the Rust standard library. The pinned Rust
distribution's [standard-library copyright inventory](licenses/RUST-STDLIB.html)
is included with the Python artifacts. It covers the standard-library source
tree and dependencies, including target-specific files, rather than identifying
every object linked into a particular wheel.

| Direct dependency | License | Purpose |
| --- | --- | --- |
| rxing 0.9.3 | Apache-2.0 | QR encoding and decoding; ported from ZXing |
| image 0.25.10 | MIT OR Apache-2.0 | PNG/JPEG image handling |
| thiserror 2.0.21 | MIT OR Apache-2.0 | Rust errors |
| PyO3 0.30.1 | MIT OR Apache-2.0 | Python bindings |
| qrcode 0.14.1 | MIT OR Apache-2.0 | Rust test fixtures |
| Segno 1.6.6 | BSD-3-Clause | Python test fixtures |

The base package has no Python runtime dependencies. The optional LiveKit extra
and development tools are installed as separate distributions with their own
notices. Their locked versions and scopes are listed in the
[Python inventory](docs/licenses/python-dependencies.md).

The LiveKit RTC wheel contains native media components under additional terms.
Its package-level Apache declaration does not describe every bundled component.
Retain its shipped notices and inspect the matching binaries before redistributing
them. These native RTC binaries are not bundled into the REED QR wheel.

See [LICENSE_AUDIT.md](LICENSE_AUDIT.md) for scope and remaining review limits.
