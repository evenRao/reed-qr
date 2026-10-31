# REED QR

Local QR encoding and decoding for Python and Rust applications, with a typed
Python API, bounded asynchronous frame scanning, and an optional LiveKit adapter.
Applications can expose these operations as tools in an assistant or agent framework.
All QR processing runs locally; the codec needs no model provider or API key.

**Start here:** [Install](#1-install-reed-qr) · [Verify](#2-check-your-installation) ·
[First QR code](#3-create-and-read-your-first-qr-code) ·
[LiveKit](#8-scan-a-livekit-video-track) · [Rust](#10-use-the-rust-crate)

[Documentation](https://github.com/evenRao/reed-qr#readme) ·
[Source](https://github.com/evenRao/reed-qr) ·
[Issues](https://github.com/evenRao/reed-qr/issues) ·
[Compatibility](https://github.com/evenRao/reed-qr/blob/main/docs/compatibility.md)

## What you can build

- Generate QR images from UTF-8 text and save them as PNG files.
- Read one or more QR codes from PNG/JPEG bytes or packed video frames.
- Scan incoming frames alongside asyncio work, with per-source sampling,
  bounded queues, and duplicate suppression.
- Read selected, already-subscribed LiveKit camera or screen-share tracks.
- Connect a bounded scan operation to an application's assistant tool interface.

| Component | Install or import | Purpose |
| --- | --- | --- |
| Python distribution | `reed-qr` | Package name used by pip and uv |
| Python library | `reed_qr` | Image, frame, and streaming APIs |
| Onboarding command | `reed-qr` or `python -m reed_qr` | Offline guide, diagnostics, and documentation |
| Optional adapter | `reed_qr.integrations.livekit` | Track readers for LiveKit RTC |
| Rust library | `reed-qr-core` / `reed_qr_core` | Synchronous QR processing without Python |

The API is experimental in the `0.1.x` series. Review
[result fidelity](#6-understand-detection-results) and
[limits](#11-limits-and-operational-behavior) before building actions around detections.

## 1. Install REED QR

Release status: the first release is being prepared. Registry commands below
apply once `0.1.0` is published. Until then, use the
[source checkout instructions](#install-from-a-source-checkout).

### Requirements

- Standard CPython **3.11 through 3.15**.
- A supported wheel for your Python version and operating system, or the source
  build tools described below.
- The optional LiveKit extra only if you use the LiveKit adapter.

CI builds and tests Windows x86_64, Linux x86_64, macOS Intel, and macOS Apple
Silicon. Linux wheels target `manylinux_2_28` (glibc 2.28 or newer); Alpine/musl,
Windows ARM, Linux ARM, PyPy, and free-threaded CPython require separate validation.
A compatible wheel includes the compiled Rust extension: installing it requires
neither Rust nor a C/C++ compiler. The base package has no required Python
runtime dependencies.

### Option A: pip and a virtual environment

Check that `python --version` reports a supported version, then create an environment:

```sh
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```sh
source .venv/bin/activate
```

Install the package and display the welcome screen:

```sh
python -m pip install reed-qr
python -m reed_qr
```

On Windows, use `.\.venv\Scripts\python.exe` directly if activation is unavailable.
On macOS/Linux, use `.venv/bin/python`. Using the environment's Python explicitly
ensures installation and execution select the same interpreter.

### Option B: a uv project

From a new project directory:

```sh
uv init my-qr-app
cd my-qr-app
uv add reed-qr
uv run python -m reed_qr
```

In an existing project, start with `uv add reed-qr`. Prefix the Python commands
in this guide with `uv run`, for example `uv run python qr_demo.py`.

### Optional: LiveKit

For pip:

```sh
python -m pip install "reed-qr[livekit]"
```

For a uv project:

```sh
uv add "reed-qr[livekit]"
```

The extra accepts LiveKit RTC `>=1.1.21,<2`. It does not install an agent framework,
connect a room, subscribe to cameras, or register assistant tools. Your application
owns those operations. The development lockfile selects RTC 1.2.0.

### Install from a source checkout

Source builds require the pinned Rust toolchain in
[`rust-toolchain.toml`](https://github.com/evenRao/reed-qr/blob/main/rust-toolchain.toml)
and a native C/C++ build toolchain. On Windows, install Visual Studio C++ Build
Tools and the Windows SDK. On macOS, install Xcode Command Line Tools. On Linux,
install your distribution's native compiler and linker tools.

```sh
git clone https://github.com/evenRao/reed-qr.git
cd reed-qr
uv venv --python 3.15
uv pip install .
uv run --no-sync python -m reed_qr doctor
```

`--no-sync` uses the environment just created without synchronizing the
development dependency group. For LiveKit, replace `.` with `".[livekit]"`.

With pip, create and activate a supported virtual environment, then run these
commands from the checkout:

```sh
python -m pip install .
python -m reed_qr doctor
```

For contributor setup, locked dependencies, and tests, see
[CONTRIBUTING.md](https://github.com/evenRao/reed-qr/blob/main/CONTRIBUTING.md).

## 2. Check your installation

Run the local installation check:

```sh
python -m reed_qr doctor
```

It reports your Python interpreter, platform, distribution version, native
extension loading, and an actual QR encode/decode round trip through PNG and
Gray8 frame inputs. A successful check ends with:

```text
Installation check passed.
```

The check needs no network, camera, credentials, or output files. LiveKit is
optional; its absence does not fail the check. An installed SDK's version is
reported without attempting a room connection.

For support reports or automation:

```sh
python -m reed_qr doctor --json
```

The JSON report has an `ok` boolean, package `version`, and `checks` array.
Exit status is `0` when required checks pass and `1` when any required check fails.
Review interpreter paths and platform details before sharing a report.

### Keep instructions within reach

| Command | Result |
| --- | --- |
| `reed-qr` | Welcome screen and next steps |
| `reed-qr --help` | Command usage |
| `reed-qr --version` | Package version |
| `reed-qr guide` | Bundled step-by-step guide; works offline |
| `reed-qr doctor` | Local installation check |
| `reed-qr docs` | Documentation URL |
| `reed-qr docs --open` | Open documentation in your default browser |

Every command also works as `python -m reed_qr <command>`. In a uv project, use
`uv run reed-qr <command>` or `uv run python -m reed_qr <command>`.
The CLI provides onboarding and diagnostics; image encoding and decoding use
the Python or Rust APIs below.

Installation and ordinary imports do not open windows or print banners. The
welcome screen and guide remain available even if the compiled extension cannot
load. Browser opening is requested explicitly with `docs --open`; if no browser
is available, copy the printed URL.

## 3. Create and read your first QR code

Create a file named `qr_demo.py` containing:

```python
from pathlib import Path

from reed_qr import decode_image, encode_text

image = encode_text("order:12345")
Path("qr.png").write_bytes(image.to_png())

for detection in decode_image(Path("qr.png").read_bytes()):
    print(detection.text, detection.payload_status.value)
```

Run it in your environment:

```sh
python qr_demo.py
```

Expected output:

```text
order:12345 exact_bytes
```

A `qr.png` file is written to the current directory. `encode_text()` accepts
nonempty UTF-8 text. Its immutable `QrImage` exposes `width`, `height`, grayscale
`pixels`, `to_png()`, and `as_frame()`.

To choose rendering settings:

```python
from reed_qr import EncodeOptions, ErrorCorrection, encode_text

image = encode_text(
    "order:12345",
    options=EncodeOptions(
        error_correction=ErrorCorrection.H,
        pixels_per_module=8,
        quiet_zone=4,
    ),
)
```

Error correction accepts `L`, `M`, `Q`, or `H`; the default is `M`. Higher error
correction reduces payload capacity. The default scale is eight pixels per module
and the quiet zone is four modules. Preserve that clear border when embedding the
image in another design. Quiet zones must be 4–64 modules. Text must fit the QR
capacity for the selected settings; the input byte ceiling is an additional guard,
not a promise that every input below it will fit.

## 4. Decode an existing PNG or JPEG

Pass compressed image bytes, rather than a filename, to `decode_image()`:

```python
from pathlib import Path

from reed_qr import ReedQRError, decode_image

try:
    detections = decode_image(Path("qr.png").read_bytes())
except OSError as error:
    print(f"Could not read the file: {error}")
except ReedQRError as error:
    print(f"Could not decode the image: {error}")
else:
    if not detections:
        print("No readable QR code found.")
    for detection in detections:
        print(detection.text, detection.payload_status.value)
```

A valid image with no readable QR returns an empty tuple. Malformed image bytes
raise an exception. Multiple symbols can produce multiple detections; their
ordering is not an application priority. Only PNG and JPEG compressed inputs
are enabled.

## 5. Decode packed pixel frames

Create a `Frame` with explicit layout information. This complete example uses
pixels from a generated image:

```python
from reed_qr import Frame, PixelFormat, decode_frame, encode_text

image = encode_text("frame:001")
frame = Frame.from_buffer(
    image.pixels,
    width=image.width,
    height=image.height,
    row_stride=image.width,
    format=PixelFormat.GRAY8,
)
for detection in decode_frame(frame):
    print(detection.text)
```

Expected output is `frame:001`. Replace the generated buffer and dimensions with
those supplied by your capture system.

| Pixel format | Bytes per pixel | Channel order |
| --- | --- | --- |
| `PixelFormat.GRAY8` | 1 | Grayscale |
| `PixelFormat.RGB24` | 3 | Red, green, blue |
| `PixelFormat.RGBA8` | 4 | Red, green, blue, alpha |
| `PixelFormat.BGRA8` | 4 | Blue, green, red, alpha |

`row_stride` is measured in **bytes**, including row padding. It must be at least
`width * bytes_per_pixel`, and the buffer must contain every active row.
`Frame.from_buffer()` accepts bytes, bytearray, or memoryview and snapshots mutable
storage so later camera-buffer reuse cannot alter an admitted frame.

RGBA/BGRA conversion ignores alpha; composite transparency before submitting when
needed. Planar YUV buffers require conversion to a supported packed format.
Timestamp and rotation fields are metadata: they do not rotate pixels or transform
returned coordinates.

## 6. Understand detection results

| Field | Meaning |
| --- | --- |
| `format` | `"QR_CODE"` |
| `text` | Faithful text when available, otherwise `None` |
| `payload_bytes` | Verified complete original byte payload when available, otherwise `None` |
| `payload_status` | `EXACT_BYTES`, `TEXT_ONLY`, or `UNSUPPORTED` |
| `byte_segments` | Individual decoded byte segments; potentially only part of a mixed-mode payload |
| `landmarks` | Named detector points in input-image pixel coordinates |
| `corners` | Currently `None`; four outer corners are not supplied |

Use `payload_status.value` when serializing the status as a string:

- `exact_bytes`: complete byte payload is verified. Binary data may have no text.
- `text_only`: faithful text is available, but complete original bytes are not
  claimed. Numeric and alphanumeric symbols commonly take this path.
- `unsupported`: complete payload fidelity is unavailable. Mixed modes and
  structured append have limited support; do not treat concatenated byte segments
  as a verified complete payload.

A successful scan does not authorize opening a URL, executing a command, or
completing a transaction. Validate decoded content against the application's
expected format and authorization rules.

## 7. Scan frames asynchronously

Use `Scanner` when decoding must run alongside other asyncio work. Save this
self-contained example as `scan_demo.py`:

```python
import asyncio

from reed_qr import Scanner, ScannerConfig, SourceRef, encode_text


async def main():
    frame = encode_text("camera:001").as_frame()
    async with Scanner(ScannerConfig(scan_hz=5, max_sources=1)) as scanner:
        scanner.submit(frame, source=SourceRef("camera"))
        events = scanner.events()
        try:
            event = await asyncio.wait_for(anext(events), timeout=5)
            if event.error is not None:
                raise event.error
            for detection in event.detections:
                print(event.source.source_id, detection.text)
        finally:
            await events.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

Run `python scan_demo.py`. Expected output:

```text
camera camera:001
```

For continuous video, keep feeding frames in a separate application-owned task
while one consumer iterates `scanner.events()`. Cancel and await the feeder when
scanning ends. The runnable
[frame-stream example](https://github.com/evenRao/reed-qr/blob/main/examples/frame_stream.py)
shows the full lifecycle using synthetic 720p frames without camera hardware.
Download it into your project and run `python frame_stream.py`, or run
`uv run python examples/frame_stream.py` from a development checkout.

`submit()` returns a `SubmitOutcome`: accepted, replaced pending work, sampled
out, or rejected because source capacity is full. Admission does not promise a
detection event. Blank or unreadable frames emit no event.

| Setting | Default | Purpose |
| --- | --- | --- |
| `scan_hz` | `5.0` | Maximum admission rate per source |
| `workers` | `1` | Maximum concurrent native decode jobs |
| `max_sources` | `4` | Maximum admitted sources |
| `result_capacity` | `32` | Maximum queued event batches |
| `max_detections_per_frame` | `16` | Maximum retained detections per frame |
| `max_frame_age_s` | `1.0` | Maximum pending-frame age before decoding |
| `duplicate_cooldown_s` | `2.0` | Per-source repeat suppression; `0` disables it |
| `dedup_capacity_per_source` | `256` | Maximum remembered payload identities per source |
| `dedup_idle_expiry_s` | `60.0` | Idle duplicate-cache expiry, at least the cooldown |

Each source retains one replaceable pending frame. Event queues are lossy: the
oldest queued batch is dropped under load. `scanner.stats()` exposes admission,
miss, failure, suppression, truncation, and queue-drop counters. Events are
notifications, not durable transaction records.

Use one event loop and one event consumer per scanner. Context-manager exit waits
for admitted native work and cleans up the executor. Cancellation or a shutdown
timeout cannot forcibly interrupt an active native decode. See the
[streaming contract](https://github.com/evenRao/reed-qr/blob/main/docs/streaming.md)
for source generations, timing, replacement, failure delivery, and shutdown.

## 8. Scan a LiveKit video track

Install the `livekit` extra from step 1. Your application must then:

1. Authenticate and connect a LiveKit `rtc.Room`.
2. Subscribe to the authorized participant's video track using its normal policy.
3. Pass that connected room and participant identity to a bounded scan function.
4. Handle a detection, timeout, source ending, or adapter failure.

Add this function to an existing LiveKit application:

```python
import asyncio

from livekit import rtc
from reed_qr.integrations.livekit import LiveKitScanner, TrackSelector


async def scan_camera(room: rtc.Room, participant_identity: str) -> dict:
    try:
        async with asyncio.timeout(5):
            async with LiveKitScanner(
                room,
                select=TrackSelector(participant_identity=participant_identity),
            ) as scanner:
                async for event in scanner.events():
                    if event.error is not None:
                        raise event.error
                    if event.detections:
                        return {
                            "status": "decoded",
                            "track_sid": event.source.track_sid,
                            "detections": [
                                {
                                    "text": item.text,
                                    "payload_status": item.payload_status.value,
                                    "payload_hex": (
                                        item.payload_bytes.hex()
                                        if item.payload_bytes is not None
                                        else None
                                    ),
                                }
                                for item in event.detections
                            ],
                        }
    except TimeoutError:
        return {"status": "not_found"}
    return {"status": "source_ended"}
```

Call `await scan_camera(room, participant_identity)` from the application's
existing event loop. This function does not create or connect a room. Adapter
failures propagate to the caller; handle them using the application's error policy.
The timeout bounds waiting for frames; cleanup can take longer while admitted
native work finishes. A timeout means no detection arrived within that interval,
not proof that no QR code was visible.

To select a specific track, use `TrackSelector(track_sid="...")`. For screen
sharing, add `source="screen_share"`; the default is `"camera"`. Supplying both a
participant and track requires both to match. Selection still requires an
existing video subscription.

The application owns credentials, subscriptions, permissions, and room shutdown.
The adapter owns its frame readers and scanner. See
[integration guidance](https://github.com/evenRao/reed-qr/blob/main/docs/integrations.md).

## 9. Connect scanning to an assistant or agent

Any framework with application tools can expose QR operations. Installation does
not automatically register a tool or give a model camera access.

1. Implement a bounded function such as `scan_camera()` above.
2. Bind the connected room and authorized participant in trusted application code.
3. Register a small wrapper with the framework's tool-registration mechanism.
4. Return structured data, including the detection's fidelity status.
5. Validate results before allowing navigation or another application action.

Inside the application that already owns `room` and `authorized_participant_identity`:

```python
async def scan_current_camera() -> dict:
    """Look for a QR code on the authorized participant's subscribed camera."""
    return await scan_camera(room, authorized_participant_identity)
```

Register `scan_current_camera` using the framework's supported tool API. Keep room
credentials and authorization decisions outside model-supplied arguments. No
particular agent SDK is required by the QR codec.

## 10. Use the Rust crate

The reusable `reed-qr-core` library exposes the codec without Python or LiveKit.
It declares Rust **1.99** as its minimum version; contributor builds use pinned
Rust 1.99.1. After publication, add it to an application:

```sh
cargo new qr-demo
cd qr-demo
cargo add reed-qr-core@0.1.0
```

Replace `src/main.rs` with:

```rust
use reed_qr_core::{Decoder, EncodeOptions, encode_text};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let image = encode_text("order:12345", &EncodeOptions::default())?;
    let png = image.to_png()?;
    std::fs::write("qr.png", &png)?;

    for detection in Decoder::default().decode_image(&png)? {
        println!("{:?}: {:?}", detection.payload_status, detection.text);
    }
    Ok(())
}
```

Run `cargo run`. Before publication, use a path dependency pointing to
`crates/reed-qr-core`. The crate is a library dependency; `cargo install reed-qr-core`
does not install the Python onboarding command.

See the [crate guide](https://github.com/evenRao/reed-qr/blob/main/crates/reed-qr-core/README.md)
and [Rust API reference](https://docs.rs/reed-qr-core) (available after publication).
The internal `reed-qr-python` PyO3 binding crate is private and not published
independently.

## 11. Limits and operational behavior

| Decode limit | Default |
| --- | --- |
| Width or height | 4,096 pixels |
| Total pixels | 2,190,400 |
| Packed frame storage | 8 MiB |
| Compressed image input | 16 MiB |
| Image-loader allocation ceiling | 128 MiB |

The default total-pixel limit covers 1280×720 and 1920×1080 inputs, but not
3840×2160. A 1080p RGBA frame also needs its full storage to fit the byte limit.
Default QR rendering fits default decode limits. Larger custom rendering may
require explicit decode options.

Choose application-appropriate input limits:

```python
from reed_qr import DecodeOptions, decode_image

options = DecodeOptions(max_dimension=1920, max_pixels=1920 * 1080)
# png_bytes comes from the application's file or transport reader.
detections = decode_image(png_bytes, options=options)
```

For a scanner, pass options through `ScannerConfig(decode_options=options)`.
Frame layout and arithmetic bounds remain validated. These limits bound toolkit
inputs and retention; they do not establish a hard process-memory cap or control
buffering in upstream SDKs.

Synchronous calls release the GIL during native processing and still block their
calling thread. Use `Scanner` for event-loop applications. Real-camera accuracy,
latency, and long-session memory depend on input quality, hardware, transport,
and application behavior. Perspective, glare, blur, occlusion, and device diversity
need broader validation; there is no established performance or accuracy guarantee.

## 12. Troubleshooting

| Symptom | Next step |
| --- | --- |
| `No matching distribution found` | Check Python 3.11–3.15, platform, publication status, and selected index. Unsupported targets may need a source build. |
| `reed-qr` is not recognized | Use `python -m reed_qr` with the environment's interpreter, or `uv run reed-qr` in a uv project. |
| `No module named reed_qr` | Run `python -m pip show reed-qr` with the interpreter that runs your application. |
| Native import or DLL error | Run `python -m reed_qr doctor`; check interpreter/architecture compatibility and reinstall a matching wheel in a clean environment. |
| Rust/compiler error during installation | A source build was selected. Use a supported wheel or install pinned Rust and native build tools. |
| Missing LiveKit module | Install `"reed-qr[livekit]"` in the application's environment. |
| `ResourceLimitError` | Inspect dimensions, total pixels, stride/storage size, and compressed bytes; resize upstream or choose deliberate limits. |
| `InvalidFrameError` | Check pixel format, dimensions, byte stride, and whether every active row is present. |
| Valid image has no detections | Check focus, contrast, resolution, quiet zone, and supported QR modes. An ordinary miss is an empty tuple. |
| Video scan has no events | Confirm frames arrive, the selected track is subscribed, and the consumer runs. Inspect `scanner.stats()` for sampling, misses, and suppression. |
| `docs --open` cannot open a browser | Use the printed URL on a machine with a browser. `guide` remains available offline. |

Typed codec errors include `EncodeError`, `ImageDecodeError`,
`UnsupportedFormatError`, `InvalidFrameError`, `ResourceLimitError`, and `CodecError`,
all derived from `ReedQRError`. Scanner lifecycle and LiveKit adapter errors have
additional types documented in their modules.

When [reporting an issue](https://github.com/evenRao/reed-qr/issues), include the
package version, a reviewed `doctor --json` report, a minimal reproducer, and
expected versus observed behavior. Share image/frame fixtures only with permission;
remove private QR contents, room tokens, and participant data.

## Further documentation

- [Offline getting-started guide](https://github.com/evenRao/reed-qr/blob/main/python/reed_qr/GETTING_STARTED.md)
- [Streaming contracts and shutdown](https://github.com/evenRao/reed-qr/blob/main/docs/streaming.md)
- [Application, LiveKit, and agent integration](https://github.com/evenRao/reed-qr/blob/main/docs/integrations.md)
- [Compatibility and validation](https://github.com/evenRao/reed-qr/blob/main/docs/compatibility.md)
- [Rust crate guide](https://github.com/evenRao/reed-qr/blob/main/crates/reed-qr-core/README.md)
- [Contributor setup and checks](https://github.com/evenRao/reed-qr/blob/main/CONTRIBUTING.md)
- [Architecture](https://github.com/evenRao/reed-qr/blob/main/ARCHITECTURE.md)
- [CI results and build artifacts](https://github.com/evenRao/reed-qr/actions/workflows/checks.yml)

## License

REED QR uses the [MIT License](https://github.com/evenRao/reed-qr/blob/main/LICENSE).
Dependencies retain their own licenses and attribution. See
[third-party notices](https://github.com/evenRao/reed-qr/blob/main/THIRD_PARTY_NOTICES.md)
and the [license inventory](https://github.com/evenRao/reed-qr/blob/main/LICENSE_AUDIT.md).
