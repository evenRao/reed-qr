"""Synthetic 720p camera: uv run python examples/frame_stream.py"""

import asyncio
from dataclasses import replace

from reed_qr import Frame, Scanner, ScannerConfig, SourceRef, encode_text


def camera_frame(text: str) -> Frame:
    image = encode_text(text)
    width, height = 1280, 720
    pixels = bytearray([255]) * (width * height)
    left, top = (width - image.width) // 2, (height - image.height) // 2
    for y in range(image.height):
        start = (top + y) * width + left
        pixels[start : start + image.width] = image.pixels[y * image.width : (y + 1) * image.width]
    return Frame.from_buffer(pixels, width=width, height=height, row_stride=width)


async def feed(scanner: Scanner) -> None:
    try:
        frames = [camera_frame("ITEM-001"), camera_frame("ITEM-002")]
        for index in range(60):
            value = replace(
                frames[index // 30],
                source_timestamp_us=index * 1_000_000 // 30,
                source_clock="synthetic-camera",
            )
            scanner.submit(value, source=SourceRef("camera"))
            await asyncio.sleep(1 / 30)
        await asyncio.sleep(0.1)
    finally:
        await scanner.aclose()


async def report(scanner: Scanner) -> None:
    async for event in scanner.events():
        if event.error is not None:
            raise event.error
        for result in event.detections:
            print(event.source.source_id, ascii(result.text))


async def main() -> None:
    async with Scanner(ScannerConfig(scan_hz=5, max_sources=1)) as scanner:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(feed(scanner))
            tasks.create_task(report(scanner))
    stats = scanner.stats()
    print(
        f"received={stats.frames_received} decoded={stats.frames_decoded} "
        f"sampled_out={stats.frames_sampled_out} suppressed={stats.detections_suppressed}"
    )


if __name__ == "__main__":
    asyncio.run(main())
