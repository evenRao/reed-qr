"""Synchronous QR operations; use Scanner for bounded async frame scheduling."""

from __future__ import annotations

from . import _native
from .types import DecodeOptions, Detection, EncodeOptions, Frame, Landmark, PayloadStatus, QrImage


def _detections(results: list[_native.RawDetection]) -> tuple[Detection, ...]:
    return tuple(
        Detection(
            format=result["format"],
            payload_bytes=result["payload_bytes"],
            text=result["text"],
            payload_status=PayloadStatus(result["payload_status"]),
            byte_segments=tuple(result["byte_segments"]),
            landmarks=tuple(Landmark(*point) for point in result["landmarks"]),
        )
        for result in results
    )


def decode_image(data: bytes, *, options: DecodeOptions | None = None) -> tuple[Detection, ...]:
    """Decode PNG/JPEG bytes. A valid image with no readable QR returns ()."""
    options = options or DecodeOptions()
    return _detections(_native.decode_image(data, options._native_args()))


def decode_frame(frame: Frame, *, options: DecodeOptions | None = None) -> tuple[Detection, ...]:
    """Decode a packed frame, validating its layout before native processing."""
    options = options or DecodeOptions()
    layout = frame.width, frame.height, frame.row_stride, frame.format.value
    return _detections(_native.decode_frame(frame.data, layout, options._native_args()))


def encode_text(text: str, *, options: EncodeOptions | None = None) -> QrImage:
    """Encode nonempty UTF-8 text with integer scaling and a valid quiet zone."""
    options = options or EncodeOptions()
    width, pixels, png = _native.encode_text(
        text, options.pixels_per_module, options.quiet_zone, options.error_correction.value
    )
    return QrImage(width, width, pixels, png)
