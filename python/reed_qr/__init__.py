"""REED QR: local Rust QR processing with typed Python contracts."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._native import (
        CodecError,
        EncodeError,
        ImageDecodeError,
        InvalidFrameError,
        ReedQRError,
        ResourceLimitError,
        UnsupportedFormatError,
    )
    from .api import decode_frame, decode_image, encode_text
    from .scanner import (
        ScanEvent,
        Scanner,
        ScannerClosedError,
        ScannerConfig,
        ScannerState,
        ScannerStats,
        ShutdownTimeoutError,
        SourceRef,
        SubmitOutcome,
    )
    from .types import (
        DecodeOptions,
        Detection,
        EncodeOptions,
        ErrorCorrection,
        Frame,
        Landmark,
        PayloadStatus,
        PixelFormat,
        QrImage,
    )

__version__ = "0.1.0"
__all__ = [
    "ScanEvent",
    "Scanner",
    "ScannerClosedError",
    "ScannerConfig",
    "ScannerState",
    "ScannerStats",
    "ShutdownTimeoutError",
    "SourceRef",
    "SubmitOutcome",
    "CodecError",
    "DecodeOptions",
    "Detection",
    "EncodeError",
    "EncodeOptions",
    "ErrorCorrection",
    "Frame",
    "ImageDecodeError",
    "InvalidFrameError",
    "Landmark",
    "PayloadStatus",
    "PixelFormat",
    "QrImage",
    "ReedQRError",
    "ResourceLimitError",
    "UnsupportedFormatError",
    "decode_frame",
    "decode_image",
    "encode_text",
]


# Keep guidance available even when the compiled extension cannot be loaded.
_EXPORT_MODULES = {
    **dict.fromkeys(
        (
            "CodecError",
            "EncodeError",
            "ImageDecodeError",
            "InvalidFrameError",
            "ReedQRError",
            "ResourceLimitError",
            "UnsupportedFormatError",
        ),
        "._native",
    ),
    **dict.fromkeys(("decode_frame", "decode_image", "encode_text"), ".api"),
    **dict.fromkeys(
        (
            "ScanEvent",
            "Scanner",
            "ScannerClosedError",
            "ScannerConfig",
            "ScannerState",
            "ScannerStats",
            "ShutdownTimeoutError",
            "SourceRef",
            "SubmitOutcome",
        ),
        ".scanner",
    ),
    **dict.fromkeys(
        (
            "DecodeOptions",
            "Detection",
            "EncodeOptions",
            "ErrorCorrection",
            "Frame",
            "Landmark",
            "PayloadStatus",
            "PixelFormat",
            "QrImage",
        ),
        ".types",
    ),
}


def __getattr__(name: str) -> object:
    module = _EXPORT_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value: object = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
