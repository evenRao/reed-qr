import asyncio
import threading
from dataclasses import replace
from importlib import import_module

import pytest
from reed_qr import (
    CodecError,
    Detection,
    Frame,
    PayloadStatus,
    Scanner,
    ScannerClosedError,
    ScannerConfig,
    ScannerState,
    ShutdownTimeoutError,
    SourceRef,
    SubmitOutcome,
    encode_text,
)

scanner_module = import_module("reed_qr.scanner")


def frame(label):
    data = label.encode()
    return Frame(data, len(data), 1, len(data))


def detection(label):
    return Detection("QR_CODE", label.encode(), label, PayloadStatus.EXACT_BYTES, (), ())


def fake_decode(value, *, options=None):
    return (detection(value.data.decode()),)


async def wait_until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def fast_config(**kwargs):
    return ScannerConfig(scan_hz=1e9, duplicate_cooldown_s=0, **kwargs)


def test_actual_native_decode_carries_source_and_clock_metadata():
    async def scenario():
        image = encode_text("LIVE FRAMES")
        value = replace(
            image.as_frame(), source_timestamp_us=123, source_clock="transport", rotation=90
        )
        async with Scanner(fast_config()) as scanner:
            scanner.submit(value, source=SourceRef("camera", participant_identity="operator"))
            events = scanner.events()
            result = await asyncio.wait_for(anext(events), 5)
            assert result.detections[0].text == "LIVE FRAMES"
            assert result.source.participant_identity == "operator"
            assert result.source.generation == 1
            assert result.source_timestamp_us == 123
            assert result.source_clock == "transport"
            assert result.rotation == 90
            assert result.decoded_monotonic_ns >= result.received_monotonic_ns
            await events.aclose()
        assert scanner.state is ScannerState.CLOSED
        assert scanner.stats().active_workers == 0

    asyncio.run(scenario())


def test_overload_retains_latest_frame_and_keeps_event_loop_responsive(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked(value, *, options=None):
        calls.append(value.data.decode())
        entered.set()
        assert release.wait(5)
        return fake_decode(value)

    monkeypatch.setattr(scanner_module, "decode_frame", blocked)

    async def scenario():
        try:
            async with Scanner(fast_config()) as scanner:
                scanner.submit(frame("first"), source=SourceRef("camera"))
                await wait_until(entered.is_set)
                assert (
                    scanner.submit(frame("old"), source=SourceRef("camera"))
                    is SubmitOutcome.ACCEPTED
                )
                assert (
                    scanner.submit(frame("new"), source=SourceRef("camera"))
                    is SubmitOutcome.REPLACED
                )
                assert scanner.stats().pending_frames == 1
                assert scanner.stats().active_workers == 1
                # This loop progresses while the worker is deliberately blocked.
                for _ in range(10):
                    await asyncio.sleep(0)
                assert scanner.stats().frames_decoded == 0
                release.set()
                await wait_until(lambda: scanner.stats().frames_decoded == 2)
                assert calls == ["first", "new"]
                assert scanner.stats().frames_replaced == 1
        finally:
            release.set()

    asyncio.run(scenario())


def test_sampling_duplicate_cooldown_and_source_independence(monkeypatch):
    monkeypatch.setattr(scanner_module, "decode_frame", fake_decode)

    async def scenario():
        async with Scanner(ScannerConfig(scan_hz=5, duplicate_cooldown_s=2)) as scanner:
            now = [0]
            scanner._clock_ns = lambda: now[0]
            a, b = SourceRef("a"), SourceRef("b")
            scanner.submit(frame("same"), source=a)
            await wait_until(lambda: scanner.stats().frames_decoded == 1)
            assert scanner.submit(frame("skip"), source=a) is SubmitOutcome.SAMPLED_OUT
            now[0] = 500_000_000
            scanner.submit(frame("same"), source=a)
            scanner.submit(frame("same"), source=b)
            await wait_until(lambda: scanner.stats().frames_decoded == 3)
            assert scanner.stats().detections_suppressed == 1
            assert scanner.stats().queued_results == 2
            now[0] = 2_000_000_000
            scanner.submit(frame("same"), source=a)
            await wait_until(lambda: scanner.stats().frames_decoded == 4)
            assert scanner.stats().queued_results == 3  # Suppression did not extend cooldown.

    asyncio.run(scenario())


def test_slow_consumer_has_bounded_events_and_observable_sequence_gaps(monkeypatch):
    monkeypatch.setattr(scanner_module, "decode_frame", fake_decode)

    async def scenario():
        async with Scanner(fast_config(result_capacity=2)) as scanner:
            for index in range(4):
                scanner.submit(frame(str(index)), source=SourceRef("camera"))
                await wait_until(
                    lambda expected=index + 1: scanner.stats().frames_decoded == expected
                )
            assert scanner.stats().queued_results == 2
            assert scanner.stats().result_batches_dropped == 2
            events = scanner.events()
            first, second = await anext(events), await anext(events)
            assert (first.sequence, second.sequence) == (3, 4)
            assert [first.detections[0].text, second.detections[0].text] == ["2", "3"]
            await events.aclose()

    asyncio.run(scenario())


def test_source_replacement_discards_old_inflight_results(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked(value, *, options=None):
        if value.data == b"old":
            entered.set()
            assert release.wait(5)
        return fake_decode(value)

    monkeypatch.setattr(scanner_module, "decode_frame", blocked)

    async def scenario():
        try:
            async with Scanner(fast_config()) as scanner:
                scanner.submit(frame("old"), source=SourceRef("camera", track_sid="old"))
                await wait_until(entered.is_set)
                await scanner.remove_source("camera")
                scanner.submit(frame("new"), source=SourceRef("camera", track_sid="new"))
                release.set()
                await wait_until(lambda: scanner.stats().frames_decoded == 2)
                events = scanner.events()
                result = await anext(events)
                assert result.detections[0].text == "new"
                assert result.source.generation == 2
                assert result.source.track_sid == "new"
                assert scanner.stats().late_results_discarded == 1
                assert scanner.stats().queued_results == 0
                await events.aclose()
        finally:
            release.set()

    asyncio.run(scenario())


def test_stale_pending_frames_and_source_capacity(monkeypatch):
    monkeypatch.setattr(scanner_module, "decode_frame", fake_decode)

    async def scenario():
        async with Scanner(fast_config(max_sources=1, max_frame_age_s=1)) as scanner:
            now = [0]
            scanner._clock_ns = lambda: now[0]
            scanner.submit(frame("stale"), source=SourceRef("a"))
            assert (
                scanner.submit(frame("extra"), source=SourceRef("b"))
                is SubmitOutcome.CAPACITY_REJECTED
            )
            now[0] = 2_000_000_000
            await wait_until(lambda: scanner.stats().frames_stale == 1)
            assert scanner.stats().frames_decoded == 0
            assert scanner.stats().pending_frames == 0

    asyncio.run(scenario())


def test_source_fault_is_reported_but_does_not_stop_other_sources(monkeypatch):
    def decoder(value, *, options=None):
        if value.data == b"bad":
            raise CodecError("fixture fault")
        return fake_decode(value)

    monkeypatch.setattr(scanner_module, "decode_frame", decoder)

    async def scenario():
        async with Scanner(fast_config()) as scanner:
            scanner.submit(frame("bad"), source=SourceRef("bad"))
            scanner.submit(frame("good"), source=SourceRef("good"))
            await wait_until(
                lambda: scanner.stats().frames_failed == scanner.stats().frames_decoded == 1
            )
            events = scanner.events()
            fault, good = await anext(events), await anext(events)
            assert isinstance(fault.error, CodecError)
            assert good.detections[0].text == "good"
            assert scanner.stats().active_sources == 1
            await events.aclose()

    asyncio.run(scenario())


def test_internal_worker_failure_terminates_and_cleans_up(monkeypatch):
    def broken(value, *, options=None):
        if value.data == b"good":
            return fake_decode(value)
        raise RuntimeError("unexpected worker failure")

    monkeypatch.setattr(scanner_module, "decode_frame", broken)

    async def scenario():
        scanner = Scanner(fast_config(result_capacity=1))
        async with scanner:
            scanner.submit(frame("good"), source=SourceRef("camera"))
            await wait_until(lambda: scanner.stats().queued_results == 1)
            scanner.submit(frame("broken"), source=SourceRef("camera"))
            await wait_until(lambda: scanner.state is ScannerState.CLOSED)
            with pytest.raises(RuntimeError, match="unexpected worker failure"):
                await asyncio.wait_for(anext(scanner.events()), 5)
            assert scanner.state is ScannerState.CLOSED
            assert scanner.stats().active_workers == 0
        await scanner.aclose()

    asyncio.run(scenario())


def test_multiple_workers_are_bounded_and_sources_are_not_starved(monkeypatch):
    release = threading.Event()
    lock = threading.Lock()
    running, peak, calls = [0], [0], []

    def blocked(value, *, options=None):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            calls.append(value.data.decode())
        try:
            assert release.wait(5)
            return fake_decode(value)
        finally:
            with lock:
                running[0] -= 1

    monkeypatch.setattr(scanner_module, "decode_frame", blocked)

    async def scenario():
        try:
            async with Scanner(fast_config(workers=2)) as scanner:
                scanner.submit(frame("a0"), source=SourceRef("a"))
                scanner.submit(frame("b0"), source=SourceRef("b"))
                await wait_until(lambda: len(calls) == 2)
                scanner.submit(frame("a1"), source=SourceRef("a"))
                scanner.submit(frame("b1"), source=SourceRef("b"))
                scanner.submit(frame("c0"), source=SourceRef("c"))
                assert scanner.stats().active_workers == 2
                assert scanner.stats().pending_frames == 3
                assert len(calls) == 2
                release.set()
                await wait_until(lambda: scanner.stats().frames_decoded == 5)
                assert sorted(calls) == ["a0", "a1", "b0", "b1", "c0"]
                assert peak[0] == 2
        finally:
            release.set()

    asyncio.run(scenario())


def test_one_consumer_and_close_wakes_a_waiting_iterator():
    async def scenario():
        scanner = Scanner()
        async with scanner:
            events = scanner.events()
            waiting = asyncio.create_task(anext(events))
            await wait_until(lambda: scanner._consumer_active)
            with pytest.raises(RuntimeError, match="one event consumer"):
                await anext(scanner.events())
            await scanner.aclose()
            with pytest.raises(StopAsyncIteration):
                await waiting

    asyncio.run(scenario())


def test_frame_truncation_and_same_batch_duplicates_with_a_small_cache(monkeypatch):
    def decoder(value, *, options=None):
        return tuple(detection(text) for text in ["a", "b", "c", "a", "d"])

    monkeypatch.setattr(scanner_module, "decode_frame", decoder)

    async def scenario():
        async with Scanner(
            ScannerConfig(max_detections_per_frame=4, dedup_capacity_per_source=2)
        ) as scanner:
            scanner.submit(frame("batch"), source=SourceRef("camera"))
            events = scanner.events()
            result = await asyncio.wait_for(anext(events), 5)
            assert [item.text for item in result.detections] == ["a", "b", "c"]
            assert result.truncated
            assert scanner.stats().detections_truncated == 1
            assert scanner.stats().detections_suppressed == 1
            assert scanner.stats().dedup_entries <= 2
            await events.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scan_hz": float("nan")},
        {"workers": 0},
        {"result_capacity": 0},
        {"duplicate_cooldown_s": -1},
    ],
)
def test_invalid_scanner_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ScannerConfig(**kwargs)


def test_shutdown_timeout_retains_ownership_then_completes(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked(value, *, options=None):
        entered.set()
        assert release.wait(5)
        return fake_decode(value)

    monkeypatch.setattr(scanner_module, "decode_frame", blocked)

    async def scenario():
        scanner = Scanner(fast_config())
        await scanner.__aenter__()
        try:
            scanner.submit(frame("busy"), source=SourceRef("camera"))
            await wait_until(entered.is_set)
            with pytest.raises(ShutdownTimeoutError):
                await scanner.aclose(timeout=0.01)
            assert scanner.state is ScannerState.CLOSING
            assert scanner.stats().active_workers == 1
            with pytest.raises(ScannerClosedError):
                scanner.submit(frame("extra"), source=SourceRef("camera"))
        finally:
            release.set()
            await scanner.aclose()
        assert scanner.state is ScannerState.CLOSED

    asyncio.run(scenario())


def test_cancelled_close_caller_does_not_abandon_native_work(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked(value, *, options=None):
        entered.set()
        assert release.wait(5)
        return fake_decode(value)

    monkeypatch.setattr(scanner_module, "decode_frame", blocked)

    async def scenario():
        scanner = Scanner(fast_config())
        await scanner.__aenter__()
        try:
            scanner.submit(frame("busy"), source=SourceRef("camera"))
            await wait_until(entered.is_set)
            close = asyncio.create_task(scanner.aclose())
            await wait_until(lambda: scanner.state is ScannerState.CLOSING)
            close.cancel()
            with pytest.raises(asyncio.CancelledError):
                await close
            assert scanner.stats().active_workers == 1
        finally:
            release.set()
            await scanner.aclose()
        assert scanner.stats().active_workers == 0

    asyncio.run(scenario())


def test_duplicate_cache_is_bounded_and_repeated_lifecycle_is_clean(monkeypatch):
    monkeypatch.setattr(scanner_module, "decode_frame", fake_decode)

    async def scenario():
        for _ in range(3):
            async with Scanner(ScannerConfig(scan_hz=1e9, dedup_capacity_per_source=2)) as scanner:
                for index in range(5):
                    scanner.submit(frame(str(index)), source=SourceRef("camera"))
                    await wait_until(
                        lambda expected=index + 1: scanner.stats().frames_decoded == expected
                    )
                assert scanner.stats().dedup_entries == 2
            assert scanner.stats().active_sources == scanner.stats().active_workers == 0

    asyncio.run(scenario())
