# REED QR

QR encoding and decoding for AI platforms, assistants, and Python and Rust
applications. REED QR lets developers offer QR features through their
application's tool interface, with all QR processing running locally.

- Encode text as QR images and export PNG files.
- Decode QR codes from PNG/JPEG images and packed video frames.
- Scan video asynchronously with bounded queues and duplicate suppression.
- Read selected LiveKit video tracks through an optional adapter.

The package provides a Rust core and a typed Python API. Applications connect the
API to their assistant or agent framework; no model provider or API key is needed
for QR processing.

## Installation

The package is unreleased. Install from a source checkout with Python 3.11–3.15,
the Rust toolchain in `rust-toolchain.toml`, and a native C/C++ build toolchain.
On Windows, use Visual Studio C++ Build Tools with the Windows SDK.

From the checkout, using uv:

```sh
uv venv
uv pip install .
```

Or, inside an activated Python virtual environment:

```sh
python -m pip install .
```

For the optional LiveKit adapter, install `".[livekit]"` instead of `.` with
either installer. The base package has no required Python runtime dependencies;
its compiled extension includes the Rust dependencies.

Windows x86_64 with CPython 3.11–3.15 has been validated locally. On Apple Silicon,
Python tests and typing checks pass with CPython 3.14.3. The complete macOS matrix
and Linux validation remain pending. See [compatibility](docs/compatibility.md).

Runnable examples: [images](examples/static_image.py) and
[asynchronous video frames](examples/frame_stream.py).

## Images and text

```python
from pathlib import Path
from reed_qr import decode_image, encode_text

image = encode_text("order:12345")
Path("qr.png").write_bytes(image.to_png())

for result in decode_image(image.to_png()):
    print(result.text, result.payload_status)
```

`encode_text()` accepts nonempty UTF-8 text and returns a grayscale image with
PNG output. `decode_image()` accepts PNG or JPEG bytes. A valid image with no
readable QR code returns an empty tuple; malformed input raises a typed exception.

## Video frames

`decode_frame()` accepts a `Frame` with explicit dimensions, row stride, and
pixel format: Gray8, RGB24, RGBA8, or BGRA8. Use `Scanner` when decoding must run
alongside an application event loop:

```python
import asyncio
from reed_qr import Scanner, SourceRef, encode_text

async def read_frame():
    image = encode_text("order:12345")
    async with Scanner() as scanner:
        scanner.submit(image.as_frame(), source=SourceRef("camera"))
        events = scanner.events()
        try:
            event = await asyncio.wait_for(anext(events), timeout=5)
            return event.detections
        finally:
            await events.aclose()
```

The scanner samples frames, keeps one pending frame per source, bounds worker
and result queues, and suppresses repeated detections per source. Applications
own frame capture and actions taken on results. See the [streaming contract](docs/streaming.md).

## LiveKit and agent tools

Attach `LiveKitScanner` to a connected room and select a participant or track.
It reads already-subscribed video tracks and returns detections with participant
and track identity. The application owns room connections and subscription policy.

```python
from reed_qr.integrations.livekit import LiveKitScanner, TrackSelector

async def read_camera(room, participant_identity):
    async with LiveKitScanner(
        room,
        select=TrackSelector(participant_identity=participant_identity),
    ) as scanner:
        async for event in scanner.events():
            if event.error is not None:
                raise event.error
            for result in event.detections:
                print(event.source.track_sid, result.text)
```

Register a bounded scan function as a tool in your agent framework. Installing
REED QR does not automatically register tools or grant camera access. The codec
does not require a model provider, API key, or agent SDK. See [integration guidance](docs/integrations.md).

## Result fidelity and limits

- `payload_bytes` is populated only when the original byte payload is verified.
  Numeric/alphanumeric symbols return text; mixed modes and structured append
  have limited support. Check `payload_status` before using a result.
- Geometry contains detector landmarks. Four outer corners are not provided.
- Default decode limits are 4096 pixels per dimension, 2,190,400 total pixels,
  8 MiB per packed frame, and 16 MiB per compressed image. The image loader also
  has a 128 MiB allocation ceiling. Larger custom render settings may require
  explicit decode options.
- Synchronous calls release the GIL but block their calling thread. `Scanner`
  schedules decoding off the event loop. Cancellation waits for admitted native
  work to finish.

QR contents are untrusted input. Validate decoded values before opening links,
executing commands, or changing application state. Camera accuracy and latency
depend on image quality and hardware; no performance guarantee is established.

## Rust

The reusable [`reed-qr-core`](crates/reed-qr-core/README.md) crate provides the
same image, frame, encoding, and decoding operations without Python or LiveKit.
The PyO3 binding crate is private and is not published independently.

## Development and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md) for builds and checks, and
[ARCHITECTURE.md](ARCHITECTURE.md) for component boundaries.

REED QR uses the [MIT License](LICENSE). Dependencies retain their own
licenses and attribution. See [third-party notices](THIRD_PARTY_NOTICES.md) and
the [license inventory](LICENSE_AUDIT.md).
