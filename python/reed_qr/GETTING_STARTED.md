# REED QR - Getting started

This guide is bundled with your installation and can be read offline:

    python -m reed_qr guide

In a uv project, prefix commands with `uv run`. Use the same Python environment
for installation and execution. Registry installation requires publication;
source installation uses `python -m pip install .` from the repository checkout.

## 1. Verify your installation

    python -m reed_qr doctor

The check loads the Rust extension and generates and decodes a QR code through
PNG and Gray8 frame inputs. Success ends with "Installation check passed."
No internet connection, camera, credentials, or output file is needed.
LiveKit is optional and its absence does not fail the check.

For a machine-readable report:

    python -m reed_qr doctor --json

Exit status is 0 on success, 1 if a required check fails. Review local interpreter
paths and platform details before sharing the report.

## 2. Create and read a QR code

Save the following as qr_demo.py:

```python
from pathlib import Path
from reed_qr import decode_image, encode_text

image = encode_text("order:12345")
Path("qr.png").write_bytes(image.to_png())
for detection in decode_image(Path("qr.png").read_bytes()):
    print(detection.text, detection.payload_status.value)
```

Run it:

    python qr_demo.py

Expected output:

    order:12345 exact_bytes

The file qr.png is saved in the current directory. Encoding accepts nonempty
UTF-8 text. Decode other images by passing PNG or JPEG bytes to `decode_image()`.
A valid image with no readable QR returns an empty tuple; malformed input raises
a `ReedQRError` subclass. Always handle all detections.

## 3. Decode pixels already in memory

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
print(decode_frame(frame)[0].text)
```

Expected output: frame:001

Replace the generated pixels with your camera's buffer. Supported packed formats
are GRAY8 (1 byte/pixel), RGB24 (3), RGBA8 (4), and BGRA8 (4). Row stride is in
bytes, including padding. Mutable input storage is snapshotted. Convert planar
YUV before submission; alpha is ignored. Rotation metadata does not rotate pixels.

## 4. Run asynchronous scanning

Save this as scan_demo.py:

```python
import asyncio
from reed_qr import Scanner, ScannerConfig, SourceRef, encode_text


async def main():
    frame = encode_text("camera:001").as_frame()
    async with Scanner(ScannerConfig(max_sources=1)) as scanner:
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

Run `python scan_demo.py`. Expected output: camera camera:001

For continuous video, supply frames in a separate task and keep one event consumer.
Cancel and await your feeder when scanning ends. Use one event loop per scanner.
Sampling defaults to 5 Hz per source and duplicate suppression to 2 seconds.
Set `ScannerConfig(duplicate_cooldown_s=0)` to disable suppression.
Check `scanner.stats()` for sampled, missed, failed, or dropped work.
Queues are bounded and event delivery is lossy. Context-manager cleanup waits
for admitted native work; cancellation cannot forcibly interrupt a native decode.

## 5. Add LiveKit if needed

With pip:

    python -m pip install "reed-qr[livekit]"

Or in a uv project:

    uv add "reed-qr[livekit]"

Your application connects an `rtc.Room` and subscribes to authorized video tracks.
Then attach `LiveKitScanner` from `reed_qr.integrations.livekit` using
`TrackSelector(participant_identity="...")` or `TrackSelector(track_sid="...")`.
For a screen-share track, add `source="screen_share"` to the selector.
Use an async context manager and put a bounded wait around event consumption.
Room authentication, subscriptions, and tool registration belong to your app.

Complete example: https://github.com/evenRao/reed-qr#8-scan-a-livekit-video-track

## 6. Check fidelity and limits

- `exact_bytes`: complete verified payload bytes; binary data may have no text.
- `text_only`: faithful text is available; complete original bytes are not claimed.
- `unsupported`: complete payload fidelity is unavailable. Individual byte
  segments may be only part of a mixed-mode symbol. Structured append is limited.
- Geometry supplies detector landmarks, not four outer corners.
- Defaults: 4096 pixels per dimension, 2,190,400 total pixels, 8 MiB packed
  frame storage, 16 MiB compressed input, and a 128 MiB image-loader allocation
  ceiling. Use `DecodeOptions` to choose appropriate input limits.
- Synchronous APIs block their calling thread. Use `Scanner` for asyncio apps.
- Validate decoded content before following a URL or performing another action.

## 7. Rust applications

Use Rust 1.99 or newer. After publication, add the library:

    cargo add reed-qr-core@0.1.0

The `reed_qr_core` API provides `encode_text`, `Decoder`, `FrameView`, and `Limits`.
It runs synchronously and requires neither Python nor LiveKit. Add the library
as a dependency; it does not install the Python onboarding command.
Before publication, use a path dependency to the checkout's crates/reed-qr-core.

Guide: https://github.com/evenRao/reed-qr/blob/main/crates/reed-qr-core/README.md

## 8. Find help

    python -m reed_qr --help
    python -m reed_qr docs
    python -m reed_qr docs --open

The last command explicitly requests your default browser. If none is available,
copy the printed URL. Ordinary imports and installation stay quiet.

If the extension cannot load, `guide`, `docs`, and `doctor` still work. Confirm
that Python and pip use the same environment and that the wheel matches your
Python version, operating system, and architecture. Source builds require Rust
and native C/C++ build tools. Supported Python versions are CPython 3.11-3.15.

Full guide: https://github.com/evenRao/reed-qr#readme
Streaming: https://github.com/evenRao/reed-qr/blob/main/docs/streaming.md
Integrations: https://github.com/evenRao/reed-qr/blob/main/docs/integrations.md
Issues: https://github.com/evenRao/reed-qr/issues
