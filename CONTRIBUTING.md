# Contributing

Use the Rust toolchain in `rust-toolchain.toml`, Python 3.11–3.15, and uv 0.13.6
or newer. The development interpreter is pinned to Python 3.15.2.
On Windows, source builds need Visual Studio C++ Build Tools and the Windows SDK.

## Environment and checks

```sh
uv sync --locked --extra livekit
uv run --locked --extra livekit python -m pytest
uv run --locked --extra livekit ruff check python tests examples scripts
uv run --locked --extra livekit ruff format --check python tests examples scripts
uv run --locked --extra livekit mypy
cargo fmt --all -- --check
uv run --locked --extra livekit cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test -p reed-qr-core --locked
```

`uv sync` builds an editable installation. Rebuild the extension after Rust changes:

```sh
uv run --locked --extra livekit maturin develop
```

The default interpreter is recorded in `.python-version`. Select another with
`uv sync --locked --extra livekit --python 3.11`, or the desired supported version.
For core-only tests, omit `--extra livekit`; adapter tests skip when RTC is absent.
The adapter tests use simulated room/track events and require no credentials or
media devices. Type checking includes the optional adapter and needs the extra.

On macOS or Linux, use a regular installation to test the packaged Python modules:

```sh
uv sync --locked --extra livekit --no-editable --python 3.14
.venv/bin/python -m pytest
.venv/bin/python -m mypy
cargo test -p reed-qr-core --locked
```

Replace `3.14` with the supported interpreter being tested. Running the environment's
Python directly avoids invoking a pytest executable from another installation.
Keep the non-editable installation for these checks; another `uv sync` without
`--no-editable` restores the default editable setup.

## Test data

Rust tests generate independent QR symbols with `qrcode`; Python tests use Segno.
Keep payload bytes, text, mode, error correction, and rendering settings explicit.
Saved fixtures must record their source, generation recipe, expected results, and
license or permission. Do not commit private payloads or captured participant video.

## Dependencies and notices

Commit `Cargo.lock` and `uv.lock` changes with dependency updates. Fetch the resolved
Rust sources and regenerate the license files:

```sh
cargo fetch --locked
uv run --locked --extra livekit python scripts/update_license_inventory.py
uv run --locked --extra livekit python scripts/update_license_inventory.py --python-inventory
uv run --locked --extra livekit python scripts/update_license_inventory.py --check
```

The collector preserves released license texts and copyright notices. Review new
dependency licenses before refreshing the Python inventory from an installed
environment. Exact-version evidence for interpreter-specific alternatives is
retained from prior reviews. The check mode validates the committed package
versions and scopes without depending on which interpreter is running it.

## Packaging

On Windows with multiple Python installations or SDKs, put the selected Python
runtime ahead of unrelated DLL directories before building. CI configures this
automatically. In PowerShell:

```powershell
$pythonBase = (uv run --locked --extra livekit python -c "import sys; print(sys.base_prefix)").Trim()
$env:PATH = "$pythonBase;$pythonBase\DLLs;$env:PATH"
```

```sh
uv run --locked --extra livekit maturin build --release --locked --out dist
uv run --locked --extra livekit maturin sdist --out dist
uv run --locked --extra livekit python scripts/check_artifacts.py
uv run --locked --extra livekit python scripts/verify_wheel.py
cargo package -p reed-qr-core --locked --allow-dirty
```

Select a wheel explicitly with `scripts/verify_wheel.py --wheel PATH` when needed.
The verification script tests pip, `uv pip install`, and `uv add` in clean
environments outside the checkout. It verifies static and asynchronous scanning,
typing files, and operation without LiveKit installed. Windows checks restrict
PATH to the selected Python runtime, uv and operating-system directories.

The internal `reed-qr-python` crate is not published. Python releases belong on
PyPI and the reusable core belongs on crates.io. Uploads require separate release
approval after the platform, artifact, and licensing checks pass.

## Continuous integration

The `CI` workflow runs on pushes, pull requests, merge queues, and manual dispatch.
It checks formatting and dependency notices, then tests Python 3.11–3.15 on Linux
x86_64, Windows x86_64, macOS Intel, and macOS Apple Silicon. Rust uses the pinned
toolchain; the license job also installs `rust-docs` to verify standard-library
notices.

Each platform builds a wheel from the source distribution and runs the full
Python suite against that installed wheel with the LiveKit extra present. Separate
clean environments verify the base package through pip, `uv pip install`, and
`uv add`, without LiveKit. Linux wheels use a manylinux_2_28 container. Python 3.15
jobs also package, compile, and inspect the reusable Rust crate.
An additional adapter run checks the minimum supported LiveKit RTC version on
Linux with Python 3.14, independently of the newer SDK in the development lockfile.

Download verified packages and JUnit test reports from the workflow run's
artifacts; they expire after 14 days. The stable `CI passed` check requires both
the formatting/license job and the entire platform matrix to succeed. Use it as
the required status check in repository branch protection. The workflow does not
publish to PyPI or crates.io and needs no service credentials.
