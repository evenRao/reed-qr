"""Bounded, transport-independent frame scanning on one asyncio event loop."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from enum import StrEnum
from itertools import count
from types import TracebackType

from ._native import ReedQRError
from .api import decode_frame
from .types import DecodeOptions, Detection, Frame


class ScannerClosedError(ReedQRError):
    """Submission requires a running scanner."""


class ShutdownTimeoutError(ReedQRError):
    """Close is still running; native work has not been forcibly interrupted."""


class ScannerState(StrEnum):
    NEW = "new"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"


class SubmitOutcome(StrEnum):
    ACCEPTED = "accepted"
    REPLACED = "replaced"
    SAMPLED_OUT = "sampled_out"
    CAPACITY_REJECTED = "capacity_rejected"


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    participant_identity: str | None = None
    track_sid: str | None = None
    generation: int = 0  # Assigned by the scanner on admission, not by the caller.

    def __post_init__(self) -> None:
        if not self.source_id or len(self.source_id) > 256:
            raise ValueError("source_id must contain 1 to 256 characters")
        if any(
            value is not None and len(value) > 256
            for value in (self.participant_identity, self.track_sid)
        ):
            raise ValueError("source metadata identifiers must be at most 256 characters")


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    scan_hz: float = 5.0
    workers: int = 1
    max_sources: int = 4
    result_capacity: int = 32
    max_detections_per_frame: int = 16
    max_frame_age_s: float = 1.0
    duplicate_cooldown_s: float = 2.0  # Zero disables suppression.
    dedup_capacity_per_source: int = 256
    dedup_idle_expiry_s: float = 60.0
    decode_options: DecodeOptions = field(default_factory=DecodeOptions)

    def __post_init__(self) -> None:
        for name in ("scan_hz", "max_frame_age_s", "dedup_idle_expiry_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(self.duplicate_cooldown_s) or self.duplicate_cooldown_s < 0:
            raise ValueError("duplicate_cooldown_s must be finite and nonnegative")
        if not math.isfinite(1_000_000_000 / self.scan_hz):
            raise ValueError("scan_hz is too small to represent a sampling interval")
        for name in (
            "workers",
            "max_sources",
            "result_capacity",
            "max_detections_per_frame",
            "dedup_capacity_per_source",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.workers > 32:
            raise ValueError("workers must not exceed 32")


@dataclass(frozen=True, slots=True)
class ScanEvent:
    scanner_id: str
    source: SourceRef
    sequence: int
    detections: tuple[Detection, ...]
    received_monotonic_ns: int
    decoded_monotonic_ns: int
    source_timestamp_us: int | None
    source_clock: str | None
    rotation: int
    truncated: bool = False
    error: ReedQRError | None = None


@dataclass(frozen=True, slots=True)
class ScannerStats:
    frames_received: int = 0
    frames_sampled_out: int = 0
    frames_replaced: int = 0
    frames_capacity_rejected: int = 0
    frames_stale: int = 0
    frames_decoded: int = 0
    frames_missed: int = 0
    frames_failed: int = 0
    late_results_discarded: int = 0
    detections_found: int = 0
    detections_suppressed: int = 0
    detections_truncated: int = 0
    unsupported_payloads: int = 0
    result_batches_dropped: int = 0
    active_sources: int = 0
    active_workers: int = 0
    pending_frames: int = 0
    queued_results: int = 0
    dedup_entries: int = 0


@dataclass(slots=True)
class _Pending:
    frame: Frame
    received_ns: int


@dataclass(slots=True)
class _Source:
    ref: SourceRef
    pending: _Pending | None = None
    next_sample_ns: int = 0
    busy: bool = False
    cache: OrderedDict[bytes, tuple[int, int]] = field(default_factory=OrderedDict)


class Scanner:
    """Use as an async context manager; all methods are event-loop-affine.

    At most `workers` executor submissions exist, with at most one job per source.
    Each source retains one replaceable pending frame. Event delivery is lossy.
    """

    def __init__(self, config: ScannerConfig | None = None):
        self._config = config or ScannerConfig()
        self.scanner_id = uuid.uuid4().hex
        self._state = ScannerState.NEW
        self._loop: asyncio.AbstractEventLoop | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._scheduler: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._jobs: set[asyncio.Task[None]] = set()
        self._sources: dict[str, _Source] = {}
        self._order: deque[str] = deque()
        self._generations = count(1)
        self._sequences = count(1)
        self._results: deque[ScanEvent] = deque()
        self._wake = asyncio.Event()
        self._result_wake = asyncio.Event()
        self._consumer_active = False
        self._failure: Exception | None = None
        self._counts: dict[str, int] = {}
        # Older Windows interpreters use a coarse clock for monotonic_ns().
        self._clock_ns = time.perf_counter_ns

    @property
    def config(self) -> ScannerConfig:
        return self._config

    @property
    def state(self) -> ScannerState:
        return self._state

    def _check_loop(self) -> None:
        if self._loop is not asyncio.get_running_loop():
            raise RuntimeError("scanner must be used on its owning asyncio event loop")

    def _increment(self, name: str, amount: int = 1) -> None:
        self._counts[name] = self._counts.get(name, 0) + amount

    async def __aenter__(self) -> Scanner:
        if self._state is not ScannerState.NEW:
            raise ScannerClosedError("a scanner can be started only once; create a new instance")
        self._loop = asyncio.get_running_loop()
        self._executor = ThreadPoolExecutor(
            max_workers=self.config.workers, thread_name_prefix="reed-qr"
        )
        self._state = ScannerState.RUNNING
        self._scheduler = self._loop.create_task(self._schedule(), name="reed-qr-scheduler")
        self._scheduler.add_done_callback(self._scheduler_done)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def submit(self, frame: Frame, *, source: SourceRef) -> SubmitOutcome:
        if self._state is not ScannerState.RUNNING:
            raise ScannerClosedError("scanner is not running")
        self._check_loop()
        frame.validate(self.config.decode_options)
        self._increment("frames_received")
        state = self._sources.get(source.source_id)
        if state is None:
            if len(self._sources) >= self.config.max_sources:
                self._increment("frames_capacity_rejected")
                return SubmitOutcome.CAPACITY_REJECTED
            state = _Source(replace(source, generation=next(self._generations)))
            self._sources[source.source_id] = state
            self._order.append(source.source_id)
        elif (state.ref.participant_identity, state.ref.track_sid) != (
            source.participant_identity,
            source.track_sid,
        ):
            raise ValueError("remove the source before replacing its participant or track metadata")
        now = self._clock_ns()
        if now < state.next_sample_ns:
            self._increment("frames_sampled_out")
            return SubmitOutcome.SAMPLED_OUT
        state.next_sample_ns = now + max(1, int(1_000_000_000 / self.config.scan_hz))
        outcome = SubmitOutcome.ACCEPTED
        if state.pending is not None:
            self._increment("frames_replaced")
            outcome = SubmitOutcome.REPLACED
        state.pending = _Pending(frame, now)
        self._wake.set()
        return outcome

    def _next_pending(self) -> tuple[_Source, _Pending] | None:
        for _ in range(len(self._order)):
            source_id = self._order[0]
            self._order.rotate(-1)
            state = self._sources[source_id]
            if state.busy or state.pending is None:
                continue
            pending, state.pending = state.pending, None
            if self._clock_ns() - pending.received_ns > self.config.max_frame_age_s * 1e9:
                self._increment("frames_stale")
                continue
            return state, pending
        return None

    async def _schedule(self) -> None:
        while self._state is ScannerState.RUNNING:
            self._wake.clear()
            while len(self._jobs) < self.config.workers:
                item = self._next_pending()
                if item is None:
                    break
                source, pending = item
                source.busy = True
                task = asyncio.create_task(self._decode(source, pending), name="reed-qr-decode")
                self._jobs.add(task)
                task.add_done_callback(self._job_done)
            await self._wake.wait()

    def _scheduler_done(self, task: asyncio.Task[None]) -> None:
        if self._state is ScannerState.RUNNING:
            error = (
                RuntimeError("scanner scheduler was cancelled")
                if task.cancelled()
                else task.exception()
            )
            self._failure = (
                error
                if isinstance(error, Exception)
                else RuntimeError("scanner scheduler stopped unexpectedly")
            )
            self._begin_close()

    def _job_done(self, task: asyncio.Task[None]) -> None:
        self._jobs.discard(task)
        error = RuntimeError("decode task was cancelled") if task.cancelled() else task.exception()
        if error is not None and self._failure is None:
            self._failure = error if isinstance(error, Exception) else RuntimeError(str(error))
            self._begin_close()
        self._wake.set()

    def _is_current(self, source: _Source) -> bool:
        return (
            self._state is ScannerState.RUNNING
            and self._sources.get(source.ref.source_id) is source
        )

    async def _decode(self, source: _Source, pending: _Pending) -> None:
        assert self._loop is not None and self._executor is not None
        try:
            try:
                detections = await self._loop.run_in_executor(
                    self._executor,
                    lambda: decode_frame(pending.frame, options=self.config.decode_options),
                )
            except ReedQRError as error:
                self._increment("frames_failed")
                if self._is_current(source):
                    self._emit(source, pending, (), error=error)
                    self._remove_source(source.ref.source_id)
                return
            self._increment("frames_decoded")
            if not self._is_current(source):
                self._increment("late_results_discarded")
                return
            self._increment("detections_found", len(detections))
            if not detections:
                self._increment("frames_missed")
                return
            maximum = self.config.max_detections_per_frame
            truncated = len(detections) > maximum
            self._increment("detections_truncated", max(0, len(detections) - maximum))
            filtered = self._filter(source, detections[:maximum], pending.received_ns)
            if filtered:
                self._emit(source, pending, filtered, truncated=truncated)
        finally:
            source.busy = False

    def _filter(
        self, source: _Source, detections: tuple[Detection, ...], observed_ns: int
    ) -> tuple[Detection, ...]:
        cooldown = self.config.duplicate_cooldown_s * 1e9
        if not cooldown:
            self._increment(
                "unsupported_payloads",
                sum(item.payload_bytes is None and item.text is None for item in detections),
            )
            return detections
        expiry = max(self.config.dedup_idle_expiry_s * 1e9, cooldown)
        while source.cache:
            first = next(iter(source.cache))
            if observed_ns - source.cache[first][1] <= expiry:
                break
            source.cache.popitem(last=False)
        output = []
        seen: set[bytes] = set()
        for item in detections:
            identity = self._identity(item)
            if identity is None:
                self._increment("unsupported_payloads")
                output.append(item)
                continue
            if identity in seen:
                self._increment("detections_suppressed")
                continue
            seen.add(identity)
            previous = source.cache.pop(identity, None)
            if previous is not None and observed_ns - previous[0] < cooldown:
                source.cache[identity] = previous[0], observed_ns
                self._increment("detections_suppressed")
                continue
            source.cache[identity] = observed_ns, observed_ns
            if len(source.cache) > self.config.dedup_capacity_per_source:
                source.cache.popitem(last=False)
            output.append(item)
        return tuple(output)

    @staticmethod
    def _identity(item: Detection) -> bytes | None:
        if item.payload_bytes is not None:
            representation = b"bytes\0" + item.payload_bytes
        elif item.text is not None:
            representation = b"text\0" + item.text.encode("utf-8")
        else:
            return None
        return hashlib.blake2b(
            item.format.encode("utf-8") + b"\0" + representation, digest_size=32
        ).digest()

    def _emit(
        self,
        source: _Source,
        pending: _Pending,
        detections: tuple[Detection, ...],
        *,
        truncated: bool = False,
        error: ReedQRError | None = None,
    ) -> None:
        if len(self._results) == self.config.result_capacity:
            self._results.popleft()
            self._increment("result_batches_dropped")
        frame = pending.frame
        self._results.append(
            ScanEvent(
                self.scanner_id,
                source.ref,
                next(self._sequences),
                detections,
                pending.received_ns,
                self._clock_ns(),
                frame.source_timestamp_us,
                frame.source_clock,
                frame.rotation,
                truncated,
                error,
            )
        )
        self._result_wake.set()

    async def events(self) -> AsyncIterator[ScanEvent]:
        if self._state is ScannerState.NEW:
            raise ScannerClosedError("start the scanner with async with before consuming events")
        self._check_loop()
        if self._consumer_active:
            raise RuntimeError("only one event consumer is supported")
        self._consumer_active = True
        try:
            while True:
                if self._state in (ScannerState.CLOSING, ScannerState.CLOSED):
                    await self.aclose()
                    if self._failure is not None:
                        raise self._failure
                    return
                if self._results:
                    yield self._results.popleft()
                    continue
                self._result_wake.clear()
                await self._result_wake.wait()
        finally:
            self._consumer_active = False

    def _remove_source(self, source_id: str) -> None:
        source = self._sources.pop(source_id, None)
        if source is not None:
            source.pending = None
            source.cache.clear()
            self._order.remove(source_id)
        self._wake.set()

    async def remove_source(self, source_id: str) -> None:
        if self._state is ScannerState.CLOSED:
            return
        self._check_loop()
        self._remove_source(source_id)

    def stats(self) -> ScannerStats:
        if self._loop is not None:
            self._check_loop()
        return ScannerStats(
            **self._counts,
            active_sources=len(self._sources),
            active_workers=len(self._jobs),
            pending_frames=sum(source.pending is not None for source in self._sources.values()),
            queued_results=len(self._results),
            dedup_entries=sum(len(source.cache) for source in self._sources.values()),
        )

    def _begin_close(self) -> None:
        if self._close_task is not None:
            return
        self._state = ScannerState.CLOSING
        self._results.clear()
        for source_id in tuple(self._sources):
            self._remove_source(source_id)
        self._wake.set()
        self._result_wake.set()
        self._close_task = asyncio.create_task(self._close(), name="reed-qr-close")

    async def _close(self) -> None:
        if self._scheduler is not None:
            await asyncio.gather(self._scheduler, return_exceptions=True)
        while self._jobs:
            await asyncio.gather(*tuple(self._jobs), return_exceptions=True)
        if self._executor is not None:
            await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)
            self._executor = None
        self._state = ScannerState.CLOSED
        self._result_wake.set()

    async def aclose(self, *, timeout: float | None = None) -> None:
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and nonnegative, or None")
        if self._state is ScannerState.CLOSED:
            return
        if self._state is ScannerState.NEW:
            self._state = ScannerState.CLOSED
            return
        self._check_loop()
        self._begin_close()
        assert self._close_task is not None
        try:
            await asyncio.wait_for(asyncio.shield(self._close_task), timeout)
        except TimeoutError as error:
            raise ShutdownTimeoutError(
                "scanner is still closing; admitted native work is finishing"
            ) from error
