"""Per-source MJPEG pub/sub.

The video worker publishes annotated JPEG bytes here; HTTP MJPEG subscribers
read from per-source queues. Backpressure-safe: if a subscriber is slow, the
oldest queued frame is dropped rather than blocking the worker.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from uuid import UUID

_subscribers: dict[UUID, set[asyncio.Queue]] = defaultdict(set)
_last_frame: dict[UUID, bytes] = {}


def publish(source_id: UUID, jpeg_bytes: bytes) -> None:
    _last_frame[source_id] = jpeg_bytes
    subs = _subscribers.get(source_id)
    if not subs:
        return
    for q in list(subs):
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            q.put_nowait(jpeg_bytes)
        except asyncio.QueueFull:
            pass


def latest(source_id: UUID) -> bytes | None:
    return _last_frame.get(source_id)


def clear(source_id: UUID) -> None:
    _last_frame.pop(source_id, None)
    _subscribers.pop(source_id, None)


@asynccontextmanager
async def subscribe(source_id: UUID, maxsize: int = 2):
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    _subscribers[source_id].add(q)
    try:
        yield q
    finally:
        _subscribers[source_id].discard(q)
        if not _subscribers[source_id]:
            _subscribers.pop(source_id, None)
