"""CLI for the overnight batch.

    python -m app.offline ingest [--dir DIR] [--reprocess]
        Crunch every new recording in DIR (default: settings.offline_drop_dir)
        into metric_samples. Skips files already in the ledger.

    python -m app.offline report --date YYYY-MM-DD [--period day|week|month] [--factory NAME|ID] [--out DIR]
        Build the factory day/week/month report PDF for the period containing --date.

    python -m app.offline run [--dir DIR] [--factory NAME|ID]
        ingest, then generate a report for every date that got footage.

    python -m app.offline watch [--dir DIR]
        Watch DIR forever; ingest + (re)generate reports as files land.
        This is the most-automated trigger (overnight unattended).

Schema note: the offline package adds the ``processed_recordings`` table; this
CLI ensures all tables exist (Base.metadata.create_all) before running, so it
works even if the FastAPI app hasn't started since the model was added.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Cyrillic NVR filenames break the default cp1252 Windows console.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.config import settings
from app.db import Base, engine


async def _ensure_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def cmd_ingest(args) -> int:
    from app.offline.batch import ingest_folder

    tz = ZoneInfo(args.tz or settings.factory_tz)
    rows = await ingest_folder(
        Path(args.dir) if args.dir else None, tz, reprocess=args.reprocess
    )
    done = sum(1 for r in rows if r.status == "done")
    failed = [r for r in rows if r.status != "done"]
    print(f"processed {len(rows)} file(s): {done} done, {len(failed)} failed")
    for r in failed:
        print(f"  FAILED {r.filename}: {r.error}")
    return 0 if not failed else 1


async def cmd_report(args) -> int:
    from app.offline.reports import generate_report

    tz = ZoneInfo(args.tz or settings.factory_tz)
    day = datetime.strptime(args.date, "%Y-%m-%d").date()
    path = await generate_report(
        args.factory, day, tz, Path(args.out) if args.out else None, period=args.period
    )
    print(f"report -> {path}")
    return 0


async def cmd_run(args) -> int:
    from app.offline.batch import ingest_folder
    from app.offline.reports import generate_report

    tz = ZoneInfo(args.tz or settings.factory_tz)
    rows = await ingest_folder(Path(args.dir) if args.dir else None, tz)
    days: set[date] = {
        r.recorded_start.astimezone(tz).date()
        for r in rows if r.status == "done" and r.recorded_start
    }
    print(f"processed {len(rows)} file(s); generating reports for {len(days)} day(s)")
    for day in sorted(days):
        path = await generate_report(args.factory, day, tz)
        print(f"  {day} -> {path}")
    return 0


async def cmd_watch(args) -> int:
    from app.offline.watcher import watch

    tz = ZoneInfo(args.tz or settings.factory_tz)
    await watch(Path(args.dir) if args.dir else None, tz)
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    ap = argparse.ArgumentParser(prog="python -m app.offline")
    ap.add_argument("--tz", help="override factory timezone (default: settings.factory_tz)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="crunch new recordings into metric_samples")
    p.add_argument("--dir")
    p.add_argument("--reprocess", action="store_true", help="ignore the ledger")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("report", help="generate a day/week/month report PDF")
    p.add_argument("--date", required=True, help="YYYY-MM-DD (factory-local); any day inside the period")
    p.add_argument("--period", choices=["day", "week", "month"], default="day",
                   help="report period (default: day)")
    p.add_argument("--factory", help="factory name or id (default: the only one)")
    p.add_argument("--out", help="output directory")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("run", help="ingest then report for every day with footage")
    p.add_argument("--dir")
    p.add_argument("--factory")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("watch", help="watch the drop dir; ingest + report as files land")
    p.add_argument("--dir")
    p.set_defaults(fn=cmd_watch)

    args = ap.parse_args()

    async def _go() -> int:
        await _ensure_schema()
        return await args.fn(args)

    return asyncio.run(_go())


if __name__ == "__main__":
    sys.exit(main())
