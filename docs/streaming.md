# Generic streaming contract

Use `Scanner` as an async context manager on one asyncio event loop. Frame sources
and event-consumer tasks belong to the application. The scanner owns its scheduler,
decode executor and outstanding native work, and closes those resources itself.

```python
from reed_qr import Scanner, ScannerConfig, SourceRef

async with Scanner(ScannerConfig(scan_hz=5)) as scanner:
    # The application's frame reader calls this without awaiting a decoder:
    scanner.submit(frame, source=SourceRef("camera"))
    async for event in scanner.events():
        handle(event)
```

The application must keep feeding frames in a separate owned task, then cancel
and await that task on shutdown. `examples/frame_stream.py` demonstrates the full
lifecycle with generated 720p frames, without a camera, LiveKit, or model API.

## Input and work bounds

- Inputs are immutable `Frame` objects. `Frame.from_buffer` snapshots mutable
  camera storage. Packed row strides and decode limits are validated on admission,
  before a frame can occupy scanner state, and again in Rust at the FFI boundary.
- Sampling applies per source, based on local monotonic arrival time. The reader
  should continue draining its transport; a sampled-out submission does no decode.
- Each admitted source has one replaceable pending frame. Workers receive recent
  frames in round-robin source order. Pending frames over `max_frame_age_s` are
  discarded rather than decoded late.
- At most `workers` jobs are submitted to the dedicated executor, and at most one
  decode is active per source. More incoming frames cannot grow the executor queue.
- `max_sources`, pixel/storage limits, per-frame retained detections, result queue,
  and per-source digest cache bound toolkit retention. This is not a hard bound on
  dependency scratch allocations, upstream transports or process RSS.
- Configuration is immutable for a scanner's lifetime. Native CPU work releases
  the GIL. Buffer copies and result conversion still have costs to measure.
- Initial packed RGBA/BGRA conversion uses RGB channels and ignores alpha; callers
  needing transparency compositing should supply an explicitly composited frame.

## Events and duplicate policy

Events batch detections from one frame and include a scanner ID, source metadata,
scanner-assigned generation, sequence, local receipt/completion times, and optional
source timestamp/clock and rotation metadata. Coordinates remain in the input
pixel space; metadata alone does not rotate the buffer. Receipt and completion
times use the high-resolution monotonic `perf_counter_ns()` clock. Compare those
values within their local clock domain, independently of transport timestamps.

Duplicate suppression is per source generation, format and faithful payload
identity. Byte and text representations use distinct fixed-size digest keys.
Cooldown uses observation time and is not extended by suppressed observations.
Zero disables suppression, including deduplication within the same frame.
With suppression enabled, repeated identities in a batch produce one event entry,
even when the long-lived cache is smaller than the batch.

The cache has an entry cap and idle expiry; effective expiry is at least the
cooldown so expiry cannot shorten a requested cooldown. Cache eviction can allow
an earlier notification under many distinct payloads. Unsupported payloads without
a faithful identity are returned without suppression. Reappearance behavior is
not implemented because missed/dropped frames do not establish disappearance.

`result_capacity` limits queued batches. The oldest queued batch is evicted under
overload, with a drop counter and visible event sequence gaps. Cooldown state may
remember an evicted event. Events are lossy notifications, not transaction commits.
There is one event consumer at a time; applications own any further fan-out.

Successful empty frames increment a miss counter without emitting events.
Operational `ReedQRError` failures remove that source and emit a source-fault event;
that event shares the ordinary lossy delivery queue. Unexpected worker failures
close the scanner and are raised by the event iterator independently of queue
capacity. Closing discards undelivered data and wakes blocked consumers.

## Source removal and shutdown

`remove_source()` immediately removes pending work and duplicate state. Existing
native work remains owned by the scanner; its late result is discarded. Reattaching
the same source ID assigns a new generation, preventing attribution to a new track.
Replace participant/track metadata only after removing the previous source.

`aclose()` is idempotent and stops admission, removes pending frames, wakes the
scheduler/consumer, waits for active jobs and shuts down its executor off the event
loop. A scanner cannot restart; construct a new instance after closing it.

`aclose(timeout=...)` can raise `ShutdownTimeoutError` while the scanner remains
`CLOSING`. It retains and finishes the bounded outstanding work. Cancelling the
caller also leaves the owned close task running; it does not cancel a native
decoder or start replacement workers. Await `aclose()` again to observe completion.
Hard termination deadlines still require a separately justified process boundary.

## Current evidence

Tests use real native decoding plus controllably blocked workers, fake monotonic
observation times, slow consumers and source replacement. They cover admission,
sampling, queue eviction, duplicate bounds, truncation, multiple workers, faults,
timeout/caller cancellation, single-consumer behavior and repeated lifecycle cleanup.
This is correctness evidence; performance budgets and a camera/transport memory
soak are not yet established.
