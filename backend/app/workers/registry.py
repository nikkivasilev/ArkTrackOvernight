from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional
from uuid import UUID

if TYPE_CHECKING:
    from app.pipeline.runtime import CameraPipeline

_tasks: dict[UUID, asyncio.Task] = {}
_pipelines: dict[UUID, "CameraPipeline"] = {}


def register(source_id: UUID, task: asyncio.Task) -> None:
    _tasks[source_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(source_id, None))


def is_running(source_id: UUID) -> bool:
    t = _tasks.get(source_id)
    return t is not None and not t.done()


def cancel(source_id: UUID) -> bool:
    t = _tasks.get(source_id)
    if t and not t.done():
        t.cancel()
        return True
    return False


def attach_pipeline(source_id: UUID, pipeline: "CameraPipeline") -> None:
    _pipelines[source_id] = pipeline


def detach_pipeline(source_id: UUID) -> None:
    _pipelines.pop(source_id, None)


def get_pipeline(source_id: UUID) -> Optional["CameraPipeline"]:
    return _pipelines.get(source_id)
