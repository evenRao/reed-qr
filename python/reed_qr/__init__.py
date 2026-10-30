"""REED QR: local Rust QR processing with typed Python contracts."""

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
