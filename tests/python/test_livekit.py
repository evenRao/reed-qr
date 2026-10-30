import asyncio
from types import SimpleNamespace

import pytest

rtc = pytest.importorskip("livekit.rtc")
from livekit.rtc.event_emitter import EventEmitter  # noqa: E402
from reed_qr import ScannerConfig, encode_text  # noqa: E402
from reed_qr.integrations.livekit import (  # noqa: E402
    LiveKitAdapterError,
    LiveKitScanner,
    TrackSelector,
)


class FakeRoom(EventEmitter):
    def __init__(self):
        super().__init__()
        self.remote_participants = {}
        self.connected = True

    def isconnected(self):
        return self.connected


class FakeStream:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.queue.get()
        if value is None:
            raise StopAsyncIteration
        return value

    async def aclose(self):
        self.closed = True


def publication(sid="track", source=None):
    return SimpleNamespace(
        sid=sid,
        kind=rtc.TrackKind.KIND_VIDEO,
        source=source or rtc.TrackSource.SOURCE_CAMERA,
        track=SimpleNamespace(sid=sid),
    )


def setup_room(monkeypatch, identity="operator", publications=None):
    room = FakeRoom()
    participant = SimpleNamespace(
        identity=identity,
        track_publications={item.sid: item for item in (publications or [publication()])},
    )
    room.remote_participants[identity] = participant
    streams, requests = [], []

    def from_track(**kwargs):
        stream = FakeStream()
        streams.append(stream)
        requests.append(kwargs)
        return stream

    monkeypatch.setattr(rtc.VideoStream, "from_track", from_track)
    return room, participant, streams, requests


async def wait_until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def video_event(text="RTC TEST"):
    image = encode_text(text)
    rgb = b"".join(bytes([pixel]) * 3 for pixel in image.pixels)
    return SimpleNamespace(
        frame=rtc.VideoFrame(image.width, image.height, rtc.VideoBufferType.RGB24, rgb),
        timestamp_us=1234,
        rotation=1,
    )


def test_explicit_selection_and_initial_track_snapshot(monkeypatch):
    async def scenario():
        room, _, streams, requests = setup_room(
            monkeypatch,
            publications=[
                publication("camera"),
                publication("screen", rtc.TrackSource.SOURCE_SCREENSHARE),
            ],
        )
        async with LiveKitScanner(
            room, select=TrackSelector(participant_identity="operator")
        ) as scanner:
            await wait_until(lambda: scanner.active_tracks == 1)
            for _ in range(100):
                room.emit("track_subscribed", None, None, None)
            await asyncio.sleep(0)
            assert len(streams) == 1
            assert requests[0]["capacity"] == 1
            assert requests[0]["format"] == rtc.VideoBufferType.RGB24
            streams[0].queue.put_nowait(video_event())
            events = scanner.events()
            event = await asyncio.wait_for(anext(events), 5)
            assert event.detections[0].text == "RTC TEST"
            assert event.source.participant_identity == "operator"
            assert event.source.track_sid == "camera"
            assert event.rotation == 90
            assert event.source_timestamp_us == 1234
            await events.aclose()
        assert streams[0].closed and room.connected
        assert all(not callbacks for callbacks in room._events.values())

    asyncio.run(scenario())


def test_other_participants_are_ignored(monkeypatch):
    async def scenario():
        room, _, streams, _ = setup_room(monkeypatch, identity="someone-else")
        async with LiveKitScanner(room, select=TrackSelector(participant_identity="operator")):
            await asyncio.sleep(0)
            assert not streams

    asyncio.run(scenario())


def test_replaced_track_gets_a_new_source_generation(monkeypatch):
    async def scenario():
        room, participant, streams, _ = setup_room(monkeypatch)
        async with LiveKitScanner(
            room,
            select=TrackSelector(participant_identity="operator"),
            config=ScannerConfig(scan_hz=1000, max_sources=1),
        ) as scanner:
            await wait_until(lambda: len(streams) == 1)
            events = scanner.events()
            streams[0].queue.put_nowait(video_event("FIRST"))
            first = await asyncio.wait_for(anext(events), 5)
            participant.track_publications["track"].track = SimpleNamespace(sid="track")
            room.emit("track_subscribed", None, None, None)
            await wait_until(lambda: len(streams) == 2)
            assert streams[0].closed
            streams[1].queue.put_nowait(video_event("SECOND"))
            second = await asyncio.wait_for(anext(events), 5)
            assert second.source.generation > first.source.generation
            assert second.detections[0].text == "SECOND"
            await events.aclose()

    asyncio.run(scenario())


def test_reconnect_and_participant_departure_release_streams(monkeypatch):
    async def scenario():
        room, _, streams, _ = setup_room(monkeypatch)
        async with LiveKitScanner(
            room, select=TrackSelector(participant_identity="operator")
        ) as scanner:
            await wait_until(lambda: len(streams) == 1)
            room.emit("reconnecting")
            await wait_until(lambda: scanner.active_tracks == 0)
            assert streams[0].closed
            room.emit("reconnected")
            await wait_until(lambda: len(streams) == 2)
            room.remote_participants.clear()
            room.emit("participant_disconnected", None)
            await wait_until(lambda: scanner.active_tracks == 0)
            assert streams[1].closed

    asyncio.run(scenario())


def test_closing_reader_stays_counted_until_stream_cleanup_finishes(monkeypatch):
    async def scenario():
        room, _, streams, _ = setup_room(monkeypatch)
        async with LiveKitScanner(room, select=TrackSelector(track_sid="track")) as scanner:
            await wait_until(lambda: len(streams) == 1)
            stream = streams[0]
            closing, release = asyncio.Event(), asyncio.Event()

            async def delayed_close():
                closing.set()
                await release.wait()
                stream.closed = True

            monkeypatch.setattr(stream, "aclose", delayed_close)
            room.emit("reconnecting")
            try:
                await asyncio.wait_for(closing.wait(), 5)
                assert scanner.active_tracks == 1
                assert not stream.closed
            finally:
                release.set()
            await wait_until(lambda: scanner.active_tracks == 0)
            assert stream.closed

    asyncio.run(scenario())


def test_disconnected_room_ends_iterator_without_owning_room(monkeypatch):
    async def scenario():
        room, _, streams, _ = setup_room(monkeypatch)
        async with LiveKitScanner(room, select=TrackSelector(track_sid="track")) as scanner:
            await wait_until(lambda: scanner.active_tracks == 1)
            room.connected = False
            room.emit("disconnected", None)
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(scanner.events()), 5)
        assert streams[0].closed

    asyncio.run(scenario())


def test_ended_track_is_not_reattached_in_a_loop(monkeypatch):
    async def scenario():
        room, _, streams, _ = setup_room(monkeypatch)
        async with LiveKitScanner(room, select=TrackSelector(track_sid="track")) as scanner:
            await wait_until(lambda: scanner.active_tracks == 1)
            streams[0].queue.put_nowait(None)
            await wait_until(lambda: scanner.active_tracks == 0)
            for _ in range(10):
                room.emit("track_subscribed", None, None, None)
            await asyncio.sleep(0)
            assert len(streams) == 1 and streams[0].closed

    asyncio.run(scenario())


def test_invalid_pixel_format_propagates_and_cleans_up(monkeypatch):
    async def scenario():
        room, _, streams, _ = setup_room(monkeypatch)
        async with LiveKitScanner(room, select=TrackSelector(track_sid="track")) as scanner:
            await wait_until(lambda: scanner.active_tracks == 1)
            streams[0].queue.put_nowait(
                SimpleNamespace(
                    frame=SimpleNamespace(
                        width=1, height=1, data=memoryview(b"1234"), type=rtc.VideoBufferType.RGBA
                    )
                )
            )
            with pytest.raises(LiveKitAdapterError, match="RGB24"):
                await asyncio.wait_for(anext(scanner.events()), 5)
        assert streams[0].closed

    asyncio.run(scenario())


def test_selection_is_required():
    with pytest.raises(ValueError, match="select a participant"):
        TrackSelector()
