"""Immutable input and output contracts for local QR processing."""

from dataclasses import dataclass, field
from enum import StrEnum
from sys import maxsize

from ._native import EncodeError, InvalidFrameError, ResourceLimitError, UnsupportedFormatError


class PixelFormat(StrEnum):
    GRAY8 = "gray8"
    RGB24 = "rgb24"
    RGBA8 = "rgba8"
    BGRA8 = "bgra8"


class PayloadStatus(StrEnum):
    EXACT_BYTES = "exact_bytes"
    TEXT_ONLY = "text_only"
    UNSUPPORTED = "unsupported"


class ErrorCorrection(StrEnum):
    L = "L"
    M = "M"
    Q = "Q"
    H = "H"


@dataclass(frozen=True, slots=True)
class DecodeOptions:
    max_dimension: int = 4096
    max_pixels: int = 1480 * 1480
    max_frame_bytes: int = 8 * 1024 * 1024
    max_image_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        values = self._native_args()
        ceilings = (2**32 - 1, 2**64 - 1, maxsize, maxsize)
        if any(
            type(value) is not int or not 0 < value <= ceiling
            for value, ceiling in zip(values, ceilings, strict=True)
        ):
            raise ResourceLimitError("decode limits must be positive integers within native ranges")

    def _native_args(self) -> tuple[int, int, int, int]:
        return self.max_dimension, self.max_pixels, self.max_frame_bytes, self.max_image_bytes


@dataclass(frozen=True, slots=True)
class EncodeOptions:
    error_correction: ErrorCorrection = ErrorCorrection.M
    pixels_per_module: int = 8
    quiet_zone: int = 4

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "error_correction", ErrorCorrection(self.error_correction))
        except ValueError as error:
            raise EncodeError("error correction must be L, M, Q, or H") from error
        if type(self.pixels_per_module) is not int or not 0 < self.pixels_per_module < 2**32:
            raise EncodeError("pixels_per_module must be a positive 32-bit integer")
        if type(self.quiet_zone) is not int or not 4 <= self.quiet_zone <= 64:
            raise EncodeError("quiet_zone must be 4 to 64 modules")


@dataclass(frozen=True, slots=True)
class Frame:
    data: bytes
    width: int
    height: int
    row_stride: int
    format: PixelFormat = PixelFormat.GRAY8
    source_timestamp_us: int | None = None
    source_clock: str | None = None
    rotation: int = 0

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (self.width, self.height, self.row_stride)
        ):
            raise InvalidFrameError("dimensions and row stride must be positive integers")
        if self.width >= 2**32 or self.height >= 2**32 or self.row_stride > maxsize:
            raise InvalidFrameError("frame layout exceeds native integer ranges")
        try:
            object.__setattr__(self, "format", PixelFormat(self.format))
        except ValueError as error:
            raise UnsupportedFormatError("unsupported packed pixel format") from error
        if not isinstance(self.data, (bytes, bytearray, memoryview)):
            raise InvalidFrameError("frame data must be bytes, bytearray, or memoryview")
        # Snapshot caller-owned mutable storage; never retain a borrowed buffer.
        if not isinstance(self.data, bytes):
            object.__setattr__(self, "data", bytes(self.data))

    def validate(self, options: DecodeOptions) -> None:
        """Check admission limits without copying or decoding pixel data."""
        if (
            self.width > options.max_dimension
            or self.height > options.max_dimension
            or self.width * self.height > options.max_pixels
            or len(self.data) > options.max_frame_bytes
        ):
            raise ResourceLimitError("frame exceeds configured dimensions or byte limits")
        bpp = {
            PixelFormat.GRAY8: 1,
            PixelFormat.RGB24: 3,
            PixelFormat.RGBA8: 4,
            PixelFormat.BGRA8: 4,
        }[self.format]
        row = self.width * bpp
        if self.row_stride < row or len(self.data) < (self.height - 1) * self.row_stride + row:
            raise InvalidFrameError("invalid row stride or incomplete pixel buffer")

    @classmethod
    def from_buffer(
        cls,
        data: bytes | bytearray | memoryview,
        *,
        width: int,
        height: int,
        row_stride: int,
        format: PixelFormat = PixelFormat.GRAY8,
    ) -> "Frame":
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise InvalidFrameError("frame data must be bytes, bytearray, or memoryview")
        return cls(bytes(data), width, height, row_stride, format)


@dataclass(frozen=True, slots=True)
class Landmark:
    x: float
    y: float
    kind: str


@dataclass(frozen=True, slots=True)
class Detection:
    format: str
    payload_bytes: bytes | None
    text: str | None
    payload_status: PayloadStatus
    byte_segments: tuple[bytes, ...]
    landmarks: tuple[Landmark, ...]
    corners: tuple[tuple[float, float], ...] | None = None


@dataclass(frozen=True, slots=True)
class QrImage:
    width: int
    height: int
    pixels: bytes = field(repr=False)
    _png: bytes = field(repr=False)

    def to_png(self) -> bytes:
        return self._png

    def as_frame(self) -> Frame:
        return Frame(self.pixels, self.width, self.height, self.width)
