# Application and agent integration

REED QR processes image bytes or packed frames supplied by an application.
Any agent framework can expose those operations through its tool interface.
The model does not need to interpret QR pixels itself.

## Images and custom video sources

Call `decode_image()` with PNG/JPEG bytes or `decode_frame()` with a `Frame`.
For repeated frames, submit them to `Scanner` and consume its events. Capture
devices, WebRTC stacks and model providers can vary without changing the codec.
See [streaming](streaming.md) for ownership and backpressure.

## LiveKit

Install the optional `livekit` extra. Connect the room through the application's
normal authentication and subscription flow, then attach `LiveKitScanner` to
the selected participant or track. Already-subscribed camera tracks are used;
room-wide subscription policy stays with the application.
The adapter's `active_tracks` count includes closing readers until their stream
cleanup finishes.

This function can be wrapped as a tool using the chosen agent SDK:

```python
import asyncio
from reed_qr.integrations.livekit import LiveKitScanner, TrackSelector

async def scan_qr(room, participant_identity):
    try:
        async with asyncio.timeout(5):
            async with LiveKitScanner(
                room,
                select=TrackSelector(participant_identity=participant_identity),
            ) as scanner:
                async for event in scanner.events():
                    if event.error is not None:
                        return {"status": "scanner_error"}
                    if event.detections:
                        return {
                            "status": "decoded",
                            "detections": [
                                {
                                    "text": item.text,
                                    "payload_status": item.payload_status.value,
                                }
                                for item in event.detections
                            ],
                        }
    except TimeoutError:
        return {"status": "not_found"}
    return {"status": "source_ended"}
```

Bind the room and authorized participant in application code, and register a
zero-argument wrapper as the model's `scan_qr` tool. Each call creates a fresh
scanner and closes it before returning. The timeout bounds waiting for frames;
cleanup still waits for admitted native work. In a persistent scanner, register
`aclose()` with the application's shutdown lifecycle.

Handle missing or disconnected tracks and adapter exceptions in the application's
tool wrapper. Preserve multiple detections and fidelity status rather than
silently choosing a result. Unsupported or binary data may have no text.

Decoded content is untrusted data. A scan does not authorize navigation, command
execution or a business transaction. Keep credentials and room authorization in
the application, and validate results before acting on them.
