from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from io import BytesIO

import pytest
import segno
from reed_qr import (
    DecodeOptions,
    EncodeError,
    EncodeOptions,
    ErrorCorrection,
    Frame,
    ImageDecodeError,
    InvalidFrameError,
    PayloadStatus,
    ReedQRError,
    ResourceLimitError,
    decode_frame,
    decode_image,
    encode_text,
)


def independent_png(content, **kwargs):
    output = BytesIO()
    segno.make_qr(content, error="m", **kwargs).save(output, kind="png", scale=6, border=4)
    return output.getvalue()


@pytest.mark.parametrize("text", ["1234567890", "REED QR", "Hello, 世界 🦀", "A\0B"])
def test_independent_utf8_codes(text):
    results = decode_image(independent_png(text, encoding="utf-8", eci=True, mode="byte"))
    assert len(results) == 1
    result = results[0]
    assert result.text == text
    assert result.payload_bytes == text.encode("utf-8")
    assert result.payload_status is PayloadStatus.EXACT_BYTES
    assert isinstance(result.payload_bytes, bytes)
    assert result.corners is None
    assert result.landmarks


def test_binary_payload_is_bytes_without_corrupted_text():
    payload = b"\x00\xff\x80\xc0\xafREED\x00\xfe"
    result = decode_image(independent_png(payload, mode="byte"))[0]
    assert result.payload_bytes == payload
    assert result.byte_segments == (payload,)
    assert result.text is None


@pytest.mark.parametrize("correction", list(ErrorCorrection))
def test_generation_and_frame_decoding(correction):
    image = encode_text("Hello, 世界", options=EncodeOptions(error_correction=correction))
    assert image.width == image.height
    assert len(image.pixels) == image.width * image.height
    assert image.to_png().startswith(b"\x89PNG")
    assert decode_frame(image.as_frame())[0].text == "Hello, 世界"
    assert decode_image(image.to_png())[0].text == "Hello, 世界"


def test_frame_snapshots_mutable_buffers():
    image = encode_text("OWNED BUFFER")
    buffer = bytearray(image.pixels)
    frame = Frame.from_buffer(
        buffer, width=image.width, height=image.height, row_stride=image.width
    )
    buffer[:] = b"\xff" * len(buffer)
    assert decode_frame(frame)[0].text == "OWNED BUFFER"


def test_results_and_images_are_immutable():
    image = encode_text("IMMUTABLE")
    result = decode_image(image.to_png())[0]
    with pytest.raises(FrozenInstanceError):
        result.text = "changed"
    with pytest.raises(FrozenInstanceError):
        image.width = 1


def test_no_code_is_empty_and_invalid_input_has_distinct_errors():
    assert decode_frame(Frame(bytes([255]) * 128 * 128, 128, 128, 128)) == ()
    with pytest.raises(ImageDecodeError):
        decode_image(b"not an image")
    with pytest.raises(InvalidFrameError):
        decode_frame(Frame(b"short", 16, 16, 16))
    with pytest.raises(InvalidFrameError):
        Frame(b"", -1, 16, 16)
    with pytest.raises(InvalidFrameError):
        decode_frame(Frame(b"\xff" * 16, 4, 4, 3))
    with pytest.raises(ResourceLimitError):
        decode_image(encode_text("LIMIT").to_png(), options=DecodeOptions(max_pixels=4))
    assert issubclass(ImageDecodeError, ReedQRError)


@pytest.mark.parametrize("kwargs", [{"pixels_per_module": 0}, {"quiet_zone": 3}])
def test_invalid_generation_settings(kwargs):
    with pytest.raises(EncodeError):
        EncodeOptions(**kwargs)
    with pytest.raises(EncodeError):
        encode_text("")


def test_hostile_limits_are_rejected_before_native_conversion():
    for kwargs in [{"max_pixels": 0}, {"max_pixels": 2**65}, {"max_frame_bytes": -1}]:
        with pytest.raises(ResourceLimitError):
            DecodeOptions(**kwargs)


def test_independent_calls_are_safe_from_multiple_threads():
    png = independent_png("THREAD-SAFE", mode="byte")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(decode_image, [png] * 24))
    assert all(batch[0].text == "THREAD-SAFE" for batch in results)


def test_large_default_encoding_roundtrips():
    text = "a" * 2300
    image = encode_text(text)

    assert decode_image(image.to_png())[0].text == text
    assert decode_frame(image.as_frame())[0].text == text
