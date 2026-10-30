"""Run using a clean interpreter outside the checkout after installing a wheel."""

import asyncio
import importlib.metadata
import importlib.util
from pathlib import Path

import reed_qr
from reed_qr import Scanner, SourceRef, decode_image, encode_text

image = encode_text("REED QR clean wheel — 世界")
assert decode_image(image.to_png())[0].text == "REED QR clean wheel — 世界"
assert importlib.util.find_spec("livekit") is None, "standalone wheel must not require LiveKit"
assert Path(reed_qr.__file__).parent.joinpath("py.typed").exists()
assert Path(reed_qr.__file__).parent.joinpath("_native.pyi").exists()
assert importlib.metadata.version("reed-qr") == reed_qr.__version__


async def stream_smoke() -> None:
    async with Scanner() as scanner:
        scanner.submit(image.as_frame(), source=SourceRef("wheel-smoke"))
        events = scanner.events()
        event = await asyncio.wait_for(anext(events), 5)
        assert event.detections[0].text == "REED QR clean wheel — 世界"
        await events.aclose()


asyncio.run(stream_smoke())
print(f"Wheel smoke test passed: {reed_qr.__file__}")
