# API, CLI & Data Contracts

Everything an integrator or the operator UI needs: the recording filename contract,
the CLI, the REST endpoints, and the JSON shapes.

---

## 1. Recording filename contract

The camera identity and the recording's real time both come from the **filename**.
Example (Cyrillic-safe):

```
IP Камера25_NVRserver_Montage_20260306095956_20260306100515_372917.mp4
└ camera label ┘ └ boilerplate ┘ └ start ──────┘ └ end ────────┘ └ seq ┘
```

Pattern: `<camera-label>_<boilerplate>_<startYYYYMMDDHHMMSS>_<endYYYYMMDDHHMMSS>_<seq>.<ext>`

- **Camera label** (leading text) is the identity → get-or-create `Camera` by
  `(site, label)`. Zones/rules attach to that row and persist across nights as long as
  the label is stable. The trailing `seq` (`372917`) is opaque and ignored for identity.
- **start/end** are two consecutive `YYYYMMDDHHMMSS` stamps in **factory-local** time
  (`factory_tz`), converted to UTC for storage. `bucket_start = start + video_time`.
- **Boilerplate tokens** (`NVRserver`, `Montage`, `NVR`, `server`, `main`, `sub`, …) are
  stripped from the label.
- **Fallbacks**: a single stamp → `start` only; no stamps → file mtime as start + filename
  stem as label (nothing is silently skipped).
- Recognized extensions: `.mp4 .mkv .avi .mov .m4v`.

The parser is the **single place to change** if the factory's naming differs:
`app/offline/ingest.py :: parse_nvr_filename`.

---

## 2. CLI — `python -m app.offline`

Run from `backend/`. Each subcommand ensures the DB schema exists first. Global
`--tz <ZONE>` overrides `factory_tz` for that run.

| Command | What it does |
|---|---|
| `ingest [--dir DIR] [--reprocess]` | Crunch every new recording in `DIR` (default `offline_drop_dir`) into `metric_samples`. Skips files already in the ledger unless `--reprocess`. |
| `report --date YYYY-MM-DD [--period day\|week\|month] [--factory NAME\|ID] [--out DIR]` | Build the PDF for the period **containing** `--date` (any day inside the week/month). Default period `day`, default factory = the only one. |
| `run [--dir DIR] [--factory NAME\|ID]` | `ingest`, then generate a **day** report for every date that got footage. |
| `watch [--dir DIR]` | Watch `DIR` forever; ingest + regenerate day reports as files land. The most-automated trigger (run under a service for unattended overnight). |

Examples:
```bash
python -m app.offline --tz Europe/Sofia run
python -m app.offline report --date 2026-03-06 --period month --factory "fact"
python -m app.offline watch
```

> Ingest is GPU-bound and processed **one file at a time** (CPU/GIL-bound; concurrency in a
> single process buys little). There is intentionally **no HTTP trigger** for ingest — it
> stays on the watcher/CLI so a request can't block a worker or double-drive the GPU.

---

## 3. REST API

Served by `uvicorn app.main:app` (dev: port **8002**). All under `/api`. The operator UI
talks to these; the vite dev server proxies `/api → :8002`.

### Reports (`app/api/reports.py`)

| Method & path | Query | Returns |
|---|---|---|
| `GET /api/factories/{id}/report` | `period=day\|week\|month` (default `day`), `date=YYYY-MM-DD` (any day in the period; default = today in `factory_tz`) | `PeriodSummary` JSON (§5) |
| `GET /api/factories/{id}/report.pdf` | same | `application/pdf` download (FileResponse) |

Both call the same `build_*_summary` builders, so the in-app view and the PDF never
disagree. 404 if the factory is unknown; 422 on a malformed `date`.

### Recordings (`app/api/recordings.py`)

| Method & path | Query | Returns |
|---|---|---|
| `GET /api/factories/{id}/recordings` | `status=done\|processing\|failed` (optional) | `ProcessedRecording[]` (§5), newest first, with joined `camera_name` and a `file_exists` flag (surfaces rotated/deleted footage). Read-only. |

### Cameras, zones, rules (CRUD used for setup) — `app/api/{cameras,zones,rules,sites,factories}.py`

| Method & path | Purpose |
|---|---|
| `GET /api/factories` · `GET /api/factories/{id}` · `POST` · `PATCH` · `DELETE` | Factory CRUD |
| `GET /api/factories/{fid}/sites` · `POST` · `GET /api/sites/{id}` · `DELETE` | Site CRUD |
| `GET /api/sites/{sid}/cameras` · `GET /api/cameras` · `GET /api/cameras/{id}` · `DELETE` | Camera read/delete |
| `POST /api/sites/{sid}/cameras` | Upload a file camera (multipart) — optional; offline cameras are usually auto-created by ingest |
| `GET /api/cameras/{id}/frame?t=SECONDS` | Decode one frame for the **zone editor scrubber**. Falls back to the newest on-disk `ProcessedRecording.path` if `path_or_url` is gone. |
| `GET /api/cameras/{cid}/zones` · `POST` · `PATCH /api/zones/{zid}` · `DELETE /api/zones/{zid}` | Zone CRUD (polygon normalized 0..1, `excluded` flag) |
| `GET /api/cameras/{cid}/rules` · `POST /api/cameras/{cid}/rules` · `POST /api/zones/{zid}/rules` · `PATCH /api/rules/{id}` · `DELETE` | Rule CRUD |
| `GET /api/cameras/{id}/metrics` | `window_s=` (rolling) **or** `since=&until=` (ISO-8601 UTC range). Per-camera summary from the DB (or live aggregator). Powers AnalysisPanel / ZoneOccupancyPanel / dashboard. |

### Live-only routers (drop in a standalone offline build)

`app/api/ws.py` (WebSocket `/api/ws/events`), `app/api/alerts.py`, and the live-only routes
inside `cameras.py` (`/start`, `/cancel`, `/live.mjpg`) and `control.py` (module/detector
toggles). See [EXTRACTION.md](EXTRACTION.md).

---

## 4. Trigger types (rules)

`TriggerType`: `detection`, `count_min`, `count_max`, `duration`, `absence`,
`resting_worker`. In the **offline** build, rules are **metrics-only** — `count_min`/
`count_max` are `METRIC_ONLY_TRIGGERS` (no alerts). The Reports page reads an enabled
zone-scoped `count_min` rule's `params.threshold` to seed that zone's default
"understaffed (< N)" line; everything else stays threshold-agnostic at query time.
Alert-firing triggers (`detection`, `resting_worker`) are live-only here.

---

## 5. JSON shapes

### `PeriodSummary` (GET …/report)

```jsonc
{
  "factory_id": "uuid", "factory_name": "fact",
  "period": "week",                  // day | week | month
  "start": "2026-03-02", "end": "2026-03-08",   // inclusive local dates
  "tz": "UTC",
  "generated_at": "2026-06-23T18:52:48Z",
  "start_utc": "2026-03-02T00:00:00Z", "end_utc": "2026-03-09T00:00:00Z",
  "factory_summary": { /* MetricsSummary, whole factory */ },
  "timeline": [ {"t":"2026-03-02T00:00:00Z","date":"2026-03-02","avg_headcount":0.17}, ... ],
  "timeline_kind": "daily",          // intraday (day) | daily (week/month)
  "cameras": [ {
      "camera_id":"uuid", "name":"IP Камера25",
      "summary": { /* MetricsSummary */ },
      "zone_names": {"<zone_id>":"Welding bay"},
      "recordings": 2, "footage_s": 645.0
  } ],
  "zone_names": {"<zone_id>":"Welding bay"},
  "total_recordings": 2, "total_footage_s": 645.0
}
```

### `MetricsSummary` (factory_summary, each camera's summary, and `…/metrics`)

```jsonc
{
  "window_s": 604800.0,
  "worker_seconds": 5312.1,
  "activity_seconds": {"welding": 3500.0, "walking": 140.0, ...},
  "rollup_seconds":   {"working": 4980.0, "moving": 140.0, "idle": 190.0, "unclear": 0.0},
  "activity_pct":     {"welding": 65.8, ...},
  "rollup_pct":       {"working": 93.6, "moving": 2.6, "idle": 3.9},
  "avg_headcount": 7.95, "peak_headcount": 18, "frames": 5350,
  "zone_occupancy": { "<zone_id>": {
      "seconds_at": {"0": 10.0, "1": 250.0, "2": 340.0},   // time at exactly k people
      "total_s": 600.0, "avg": 1.78, "peak": 3 } },
  "zone_activity":  { "<zone_id>": {
      "seconds": {"welding": 300.0, "walking": 150.0},     // worker-weighted person-seconds
      "total_s": 600.0, "pct": {"welding": 50.0, "walking": 25.0} } }
}
```

`understaffed(< N)` is derived client-side: `Σ seconds_at[k<N] / total_s`. Nothing is baked
into capture, so any N can be queried after the fact.

### `ProcessedRecording` (GET …/recordings)

```jsonc
{
  "id":"uuid", "camera_id":"uuid", "camera_name":"IP Камера25",
  "path":"data/incoming/IP Камера25_..._372917.mp4",
  "filename":"IP Камера25_..._372917.mp4",
  "recorded_start":"2026-03-06T09:59:56Z", "recorded_end":"2026-03-06T10:05:15Z",
  "frames":2550, "footage_s":319.0,
  "status":"done", "error":null,
  "processed_at":"2026-06-22T...Z", "created_at":"2026-06-22T...Z",
  "file_exists": true
}
```

### Metric bucket (`metric_samples` row, written by the runner)

`(camera_id, bucket_start)` unique; `bucket_start = recording start + video-time`, UTC;
`duration_s≈10`; plus `worker_seconds`, `frames`, `peak_headcount`, `avg_headcount`, and the
four JSONB maps (`activity_seconds`, `rollup_seconds`, `zone_occupancy_seconds`,
`zone_activity_seconds`). Inserted with `ON CONFLICT DO NOTHING`.

---

## 6. Verification scripts (`backend/tools/`)

Synthetic, no GPU needed for the report layer; talk to Postgres on the configured DSN.

| Script | Checks |
|---|---|
| `verify_ingest_parse.py` | NVR filename parsing (incl. Cyrillic, single-stamp, mtime fallback). |
| `verify_offline_runner.py` | Runner anchors buckets at `start + 0/10/20s` (real wall-clock). |
| `verify_batch.py` | Folder ingest end-to-end: creates camera, writes ledger + metrics, re-run skips. |
| `verify_day_report.py` | Day summary + PDF from synthetic metrics. |
| `verify_period_report.py` | Week/month folding: daily timeline length, per-day averages, zero-footage day, DST week = 167 h, week+month PDF render. |
