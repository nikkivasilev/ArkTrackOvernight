"""Unit-ish check for app.offline.ingest.parse_nvr_filename against the real
factory filenames. No DB / GPU needed."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.offline.ingest import parse_nvr_filename  # noqa: E402

UTC = ZoneInfo("UTC")

CASES = [
    (
        "IP Камера25_NVRserver_Montage_20260306095956_20260306100515_372917.mp4",
        "IP Камера25",
        datetime(2026, 3, 6, 9, 59, 56, tzinfo=timezone.utc),
        datetime(2026, 3, 6, 10, 5, 15, tzinfo=timezone.utc),
        True,
    ),
    (
        "IP Камера25_NVRserver_Montage_20260306101104_20260306101654_717413.mp4",
        "IP Камера25",
        datetime(2026, 3, 6, 10, 11, 4, tzinfo=timezone.utc),
        datetime(2026, 3, 6, 10, 16, 54, tzinfo=timezone.utc),
        True,
    ),
    # single-stamp variant
    (
        "Cam_07_20260306080000.mkv",
        "Cam_07",
        datetime(2026, 3, 6, 8, 0, 0, tzinfo=timezone.utc),
        None,
        True,
    ),
]


def main() -> int:
    ok = True
    for name, exp_label, exp_start, exp_end, exp_ff in CASES:
        # Parse against an arbitrary dir so no real file is needed; mtime path
        # is exercised separately below.
        r = parse_nvr_filename(str(Path("C:/incoming") / name), tz=UTC)
        passed = (
            r.camera_label == exp_label
            and r.start == exp_start
            and r.end == exp_end
            and r.from_filename == exp_ff
        )
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
        print(f"        label={r.camera_label!r} start={r.start.isoformat()} "
              f"end={r.end.isoformat() if r.end else None} from_filename={r.from_filename}")
        if not passed:
            print(f"        EXPECTED label={exp_label!r} start={exp_start.isoformat()} "
                  f"end={exp_end.isoformat() if exp_end else None} from_filename={exp_ff}")

    # Fallback: a no-timestamp name on a real file → from_filename False, label = stem.
    real = ROOT / "tools" / "verify_ingest_parse.py"
    r = parse_nvr_filename(str(real), tz=UTC)
    fb_ok = (r.from_filename is False and r.camera_label == real.stem and r.end is None)
    ok = ok and fb_ok
    print(f"[{'PASS' if fb_ok else 'FAIL'}] mtime-fallback for {real.name}: "
          f"label={r.camera_label!r} from_filename={r.from_filename}")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
