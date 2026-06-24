"""Ingest layer for the overnight batch — turn files on disk into (camera,
wall-clock span) tuples and a processed-file ledger.

The factory NVR exports filenames like::

    IP Камера25_NVRserver_Montage_20260306095956_20260306100515_372917.mp4
    └── camera label ──┘└ boilerplate ┘ └── start ──┘└─── end ──┘ └ id ┘

so the filename alone carries which camera it is and exactly when it was
filmed. We parse that (the chosen "most accurate" timestamp source), map the
label to a ``Camera`` row (creating one under a configured site on first
sight), and record the file in ``processed_recordings`` so the watcher never
crunches the same file twice.

Files that don't match the NVR pattern (e.g. a hand-dropped ``cam2.mp4``) fall
back to file mtime for the start time and the filename stem for the label, so
nothing is silently skipped.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Camera, CameraKind, ProcessedRecording, Site
from app.workers import frame_sampler

logger = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v"}

# Two consecutive YYYYMMDDHHMMSS stamps = start + end. The non-greedy prefix
# is the camera label + NVR boilerplate.
_PAIR_RE = re.compile(r"(\d{14})_(\d{14})")
_SINGLE_RE = re.compile(r"(\d{14})")
# NVR boilerplate tokens stripped from the trailing edge of the camera label.
_BOILERPLATE = {"nvrserver", "montage", "nvr", "server", "main", "sub", ""}


@dataclass
class ParsedRecording:
    """A recording file resolved to a camera label and its real wall-clock span.

    ``start`` / ``end`` are timezone-aware UTC. ``from_filename`` is False when
    we had to fall back to file mtime (label/timestamp not in the filename).
    """
    path: str
    filename: str
    camera_label: str
    start: datetime
    end: datetime | None
    from_filename: bool


def _stamp_to_utc(stamp: str, tz: ZoneInfo) -> datetime:
    """`20260306095956` (factory-local) -> tz-aware UTC datetime."""
    naive = datetime.strptime(stamp, "%Y%m%d%H%M%S")
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


def _clean_label(prefix: str) -> str:
    """Strip trailing NVR boilerplate tokens from the filename prefix.

    "IP Камера25_NVRserver_Montage" -> "IP Камера25". Underscores inside the
    real name are preserved; only trailing known-boilerplate tokens are dropped.
    """
    tokens = [t for t in prefix.replace("-", "_").split("_")]
    while tokens and tokens[-1].strip().lower() in _BOILERPLATE:
        tokens.pop()
    label = "_".join(t for t in tokens if t).strip()
    return label or prefix.strip("_- ").strip()


def parse_nvr_filename(path: str, tz: ZoneInfo | None = None) -> ParsedRecording:
    """Parse a recording path into camera label + wall-clock span.

    Always returns a ParsedRecording (never None): when the NVR pattern isn't
    present we fall back to file mtime for the start and the filename stem for
    the label, flagging ``from_filename=False``.
    """
    tz = tz or ZoneInfo(settings.factory_tz)
    p = Path(path)
    stem = p.stem

    pair = _PAIR_RE.search(stem)
    if pair:
        start = _stamp_to_utc(pair.group(1), tz)
        end = _stamp_to_utc(pair.group(2), tz)
        if end < start:  # malformed pair — treat end as unknown
            end = None
        label = _clean_label(stem[: pair.start()])
        return ParsedRecording(str(p), p.name, label or stem, start, end, True)

    single = _SINGLE_RE.search(stem)
    if single:
        start = _stamp_to_utc(single.group(1), tz)
        label = _clean_label(stem[: single.start()])
        return ParsedRecording(str(p), p.name, label or stem, start, None, True)

    # No timestamp in the name — fall back to file mtime + stem.
    try:
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except OSError:
        mtime = datetime.now(timezone.utc)
    return ParsedRecording(str(p), p.name, stem, mtime, None, False)


def list_recordings(drop_dir: Path | None = None, tz: ZoneInfo | None = None) -> list[ParsedRecording]:
    """Parse every video file in ``drop_dir`` (recursively), sorted by start."""
    drop_dir = drop_dir or settings.offline_drop_dir
    out: list[ParsedRecording] = []
    for p in sorted(Path(drop_dir).rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            out.append(parse_nvr_filename(str(p), tz))
    out.sort(key=lambda r: r.start)
    return out


async def resolve_camera(session: AsyncSession, label: str, site_id, sample_path: str) -> Camera:
    """Get-or-create the ``Camera`` row for a camera label within a site.

    Cameras are matched by (site_id, name == label). Created cameras are
    ``kind=file`` with sampling_fps=0 (auto-probe native fps). The offline
    runner is handed each file path directly, so ``path_or_url`` is just a
    human reference to the first file seen for this camera.
    """
    existing = (
        await session.execute(
            select(Camera).where(Camera.site_id == site_id, Camera.name == label)
        )
    ).scalars().first()
    if existing is not None:
        return existing
    # Probe duration so the zone-editor scrubber has a range to seek over (the
    # camera is recording-backed; without this its slider max is NULL).
    dur = 0.0
    try:
        dur = frame_sampler.probe(sample_path).duration_s or 0.0
    except Exception as exc:
        logger.warning("duration probe failed for %s (%s)", sample_path, exc)
    cam = Camera(
        site_id=site_id, name=label, kind=CameraKind.file,
        path_or_url=sample_path, sampling_fps=0.0, duration_s=dur,
    )
    session.add(cam)
    await session.commit()
    await session.refresh(cam)
    logger.info("created camera %s (%s) under site %s", cam.id, label, site_id)
    return cam


async def already_processed(session: AsyncSession, path: str) -> bool:
    """True if this file path is recorded as successfully processed."""
    row = (
        await session.execute(
            select(ProcessedRecording).where(ProcessedRecording.path == path)
        )
    ).scalars().first()
    return row is not None and row.status == "done"


async def default_site_id(session: AsyncSession):
    """The site offline cameras are created under.

    MVP: the single existing site (the deployment has one factory/site). Raises
    if none exists — the operator must create a factory+site first.
    """
    site = (await session.execute(select(Site))).scalars().first()
    if site is None:
        raise RuntimeError(
            "no Site exists — create a factory + site before running offline ingest"
        )
    return site.id
