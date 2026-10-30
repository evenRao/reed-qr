"""Optional selected-track LiveKit RTC integration for REED QR."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from functools import partial
from types import TracebackType
from typing import Literal, cast

try:
    from livekit import rtc
    from livekit.rtc.room import EventTypes
except ImportError as error:
    raise ImportError(
        "Install REED QR with its LiveKit extra: uv add 'reed-qr[livekit]'"
    ) from error

from .. import Frame, PixelFormat, ReedQRError, ResourceLimitError
from ..scanner import ScanEvent, Scanner, ScannerConfig, ScannerStats, SourceRef


class LiveKitAdapterError(ReedQRError):
    """The RTC reader or attachment lifecycle failed."""


@dataclass(frozen=True, slots=True)
class TrackSelector:
    participant_identity: str | None = None
    track_sid: str | None = None
    source: Literal["camera", "screen_share"] = "camera"

    def __post_init__(self) -> None:
        if not self.participant_identity and not self.track_sid:
            raise ValueError("select a participant identity or an explicit track SID")
        if self.source not in ("camera", "screen_share"):
            raise ValueError("source must be camera or screen_share")

    def matches(
        self, participant: rtc.RemoteParticipant, publication: rtc.RemoteTrackPublication
    ) -> bool:
        source = (
            rtc.TrackSource.SOURCE_CAMERA
            if self.source == "camera"
            else rtc.TrackSource.SOURCE_SCREENSHARE
        )
        return (
            publication.kind == rtc.TrackKind.KIND_VIDEO
            and publication.source == source
            and (
                self.participant_identity is None
                or participant.identity == self.participant_identity
            )
            and (self.track_sid is None or publication.sid == self.track_sid)
        )


@dataclass(slots=True)
class _Target:
    track: rtc.Track
    ref: SourceRef


@dataclass(slots=True)
class _Session:
    target: _Target
    stream: rtc.VideoStream
    task: asyncio.Task[None]


class LiveKitScanner:
    """Attach to selected, already-subscribed tracks in a connected Room.

    Owns its frame readers and generic scanner, never the application's room or
    room-wide subscription policy. A single reconciliation task coalesces events.
    """

    def __init__(
        self, room: rtc.Room, *, select: TrackSelector, config: ScannerConfig | None = None
    ):
        self._room = room
        self._selector = select
        self._scanner = Scanner(config or ScannerConfig(max_sources=1))
        self._sessions: dict[str, _Session] = {}
        self._ended: dict[str, rtc.Track] = {}
        self._dirty = asyncio.Event()
        self._control: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._closing = False
        self._reconnecting = False
        self._disconnected = False
        self._failure: Exception | None = None
        self._callbacks: tuple[tuple[EventTypes, Callable[..., None]], ...] = (
            ("track_subscribed", self._changed),
            ("track_unsubscribed", self._changed),
            ("track_unpublished", self._changed),
            ("participant_disconnected", self._changed),
            ("reconnecting", self._on_reconnecting),
            ("reconnected", self._on_reconnected),
            ("disconnected", self._on_disconnected),
        )

    async def __aenter__(self) -> LiveKitScanner:
        if self._control is not None or self._closing:
            raise RuntimeError("a LiveKitScanner can be started only once")
        if not self._room.isconnected():
            raise ValueError("connect the LiveKit room before attaching a scanner")
        await self._scanner.__aenter__()
        for event, callback in self._callbacks:
            self._room.on(event, callback)
        self._dirty.set()  # Callbacks are registered before the initial snapshot.
        self._control = asyncio.create_task(self._reconcile(), name="reed-qr-livekit-control")
        self._control.add_done_callback(self._control_done)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _changed(self, *args: object) -> None:
        if not self._closing:
            self._dirty.set()

    def _on_reconnecting(self, *args: object) -> None:
        self._reconnecting = True
        self._changed()

    def _on_reconnected(self, *args: object) -> None:
        self._reconnecting = False
        self._ended.clear()
        self._changed()

    def _on_disconnected(self, *args: object) -> None:
        self._disconnected = True
        self._changed()

    def _targets(self) -> dict[str, _Target]:
        if self._reconnecting or self._disconnected:
            return {}
        found: dict[str, _Target] = {}
        for participant in self._room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.track is not None and self._selector.matches(
                    participant, publication
                ):
                    found[publication.sid] = _Target(
                        publication.track,
                        SourceRef(
                            publication.sid,
                            participant_identity=participant.identity,
                            track_sid=publication.sid,
                        ),
                    )
                    if len(found) > self._scanner.config.max_sources:
                        found.pop(max(found))
        # Deterministic selection and bounded owned readers, independent of callback rate.
        return {sid: found[sid] for sid in sorted(found)[: self._scanner.config.max_sources]}

    async def _reconcile(self) -> None:
        while not self._closing:
            await self._dirty.wait()
            self._dirty.clear()
            targets = self._targets()
            self._ended = {
                sid: track
                for sid, track in self._ended.items()
                if sid in targets and targets[sid].track is track
            }
            for sid, session in tuple(self._sessions.items()):
                target = targets.get(sid)
                if (
                    target is None
                    or target.track is not session.target.track
                    or self._ended.get(sid) is target.track
                ):
                    await self._stop(sid)
            for sid, target in targets.items():
                if self._closing:
                    break
                if sid not in self._sessions and self._ended.get(sid) is not target.track:
                    stream = rtc.VideoStream.from_track(
                        track=target.track,
                        format=rtc.VideoBufferType.RGB24,
                        capacity=1,
                    )
                    task = asyncio.create_task(
                        self._read(stream, target.ref), name="reed-qr-livekit-reader"
                    )
                    self._sessions[sid] = _Session(target, stream, task)
                    task.add_done_callback(partial(self._reader_done, sid, target.track))
            if self._disconnected:
                return

    async def _read(self, stream: rtc.VideoStream, source: SourceRef) -> None:
        async for event in stream:
            if self._closing:
                return
            video = event.frame
            limits = self._scanner.config.decode_options
            if (
                video.width > limits.max_dimension
                or video.height > limits.max_dimension
                or video.width * video.height > limits.max_pixels
                or video.data.nbytes > limits.max_frame_bytes
            ):
                raise ResourceLimitError("LiveKit frame exceeds configured limits")
            if video.type != rtc.VideoBufferType.RGB24:
                raise LiveKitAdapterError(
                    "LiveKit did not supply the requested packed RGB24 format"
                )
            # SDK normalizes stride for requested packed frames. Snapshot its mutable data.
            frame = Frame(
                bytes(video.data),
                video.width,
                video.height,
                video.width * 3,
                PixelFormat.RGB24,
                source_timestamp_us=event.timestamp_us,
                source_clock="livekit-video-stream",
                rotation={0: 0, 1: 90, 2: 180, 3: 270}.get(cast(int, event.rotation), 0),
            )
            self._scanner.submit(frame, source=source)

    def _reader_done(self, sid: str, track: rtc.Track, task: asyncio.Task[None]) -> None:
        if task.cancelled() or self._closing:
            return
        error = task.exception()
        if error is not None:
            self._failure = (
                error if isinstance(error, Exception) else LiveKitAdapterError(str(error))
            )
            self._request_close()
        else:
            self._ended[sid] = track
            self._dirty.set()

    def _control_done(self, task: asyncio.Task[None]) -> None:
        if self._closing:
            return
        error = (
            LiveKitAdapterError("attachment task was cancelled")
            if task.cancelled()
            else task.exception()
        )
        if error is not None:
            self._failure = (
                error if isinstance(error, Exception) else LiveKitAdapterError(str(error))
            )
        self._request_close()

    async def _stop(self, sid: str) -> None:
        session = self._sessions[sid]
        await self._scanner.remove_source(sid)
        session.task.cancel()
        await asyncio.gather(session.task, return_exceptions=True)
        await session.stream.aclose()
        self._sessions.pop(sid)

    async def events(self) -> AsyncIterator[ScanEvent]:
        async for event in self._scanner.events():
            yield event
        if self._failure is not None:
            await self.aclose()
            raise self._failure

    def stats(self) -> ScannerStats:
        return self._scanner.stats()

    @property
    def active_tracks(self) -> int:
        return len(self._sessions)

    def _request_close(self) -> None:
        if self._close_task is None:
            self._closing = True
            for event, callback in self._callbacks:
                self._room.off(event, callback)
            self._dirty.set()
            self._close_task = asyncio.create_task(self._close(), name="reed-qr-livekit-close")

    async def _close(self) -> None:
        try:
            if self._control is not None:
                await asyncio.gather(self._control, return_exceptions=True)
            results = await asyncio.gather(
                *(self._stop(sid) for sid in tuple(self._sessions)), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    failure = LiveKitAdapterError("An RTC stream failed during cleanup")
                    self._failure = self._failure or failure
                    raise failure from result
        finally:
            self._ended.clear()
            await self._scanner.aclose()

    async def aclose(self) -> None:
        self._request_close()
        assert self._close_task is not None
        await asyncio.shield(self._close_task)
