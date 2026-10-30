"""Run with: uv run python examples/static_image.py"""

from pathlib import Path

from reed_qr import decode_image, encode_text

image = encode_text("Hello from REED QR — 世界")
Path("qr.png").write_bytes(image.to_png())
for detection in decode_image(image.to_png()):
    print(ascii(detection.text), detection.payload_status.value)
