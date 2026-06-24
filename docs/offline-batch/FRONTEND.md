# Frontend (Operator UI)

React 18 + Vite + TypeScript, Tailwind v4 (`@theme` tokens) + Radix primitives, React
Router v6. The dev server (`npm run dev`, port 5173) proxies `/api → :8002`
(`frontend/vite.config.ts`). All offline data flows over **REST** — no WebSocket, no MJPEG.

---

## 1. Pages & routes (`frontend/src/routes.tsx`)

| Route | Page | Purpose |
|---|---|---|
| `/dashboard` | `features/dashboard/DashboardPage` | Overview + `WorkforceOverview` (system-wide metrics, REST). |
| `/factories` | `features/factories/FactoriesPage` | List/create factories. |
| `/factories/:fid` | `features/factories/FactoryPage` | Factory detail + **Reports** / **Recordings** entry links + sites list. |
| `/factories/:fid/reports` | `features/reports/ReportsPage` | **Day/week/month reports** (interactive + PDF download). |
| `/factories/:fid/recordings` | `features/recordings/RecordingsPage` | The **ingest ledger** table. |
| `/factories/:fid/sites/:sid` | `features/sites/SitePage` | Cameras under a site. |
| `/factories/:fid/sites/:sid/cameras/new` | `features/cameras/CameraCreatePage` | Upload a file camera (optional). |
| `/factories/:fid/sites/:sid/cameras/:cid` | `features/cameras/CameraPage` → `zones` / `rules` tabs | Per-camera **zone & rule authoring**. (The `live` tab is live-only.) |

Layout shell: `layout/AppShell` + `NavTree` (factory→site→camera tree) + `Breadcrumb` +
`BottomNav` + `CommandPalette`. State: `state/AppContext`.

---

## 2. The two new pages

### ReportsPage (`features/reports/ReportsPage.tsx`)

- Controls: period toggle (day/week/month), `<input type="date">` anchor, bars/pie toggle,
  **Download PDF** link (`api.reportPdfUrl`).
- Fetches `api.getReport(fid, period, date)` → `PeriodSummary` and renders:
  - coverage line + KPI tiles (worker-hours, avg/peak people, working %, idle %) via `ui/StatReadout`;
  - **`StaffingTimelineChart`** (new) — dependency-free bars; intraday `HH:mm` for a day,
    per-day `DD MMM` for week/month (branches on `timeline_kind`);
  - factory `MetricsBreakdown` (status + activity);
  - per-camera sections: `MetricsBreakdown` (showMeta=false) + a `ZoneCard` per zone.
- Seeds each zone's default understaffing **N** from its `count_min` rule
  (`api.listRulesForCamera` → `params.threshold`), else 1.

### RecordingsPage (`features/recordings/RecordingsPage.tsx`)

- Read-only table from `api.listRecordings(fid, status?)`: camera, filename, recorded
  start→end (local), footage hours, frames, a status pill, and a `file_exists` badge.
- Status filter chips (All / Done / Processing / Failed).

---

## 3. Reused / shared components

| Component | Reuse |
|---|---|
| `features/cameras/MetricsBreakdown.tsx` | **Presentational** — takes `metrics?: MetricsSummary`, renders the rollup status bar + activity bars. Used by ReportsPage, AnalysisPanel, WorkforceOverview. |
| `features/cameras/ZoneCard.tsx` | **Presentational** — one zone's occupancy (bars/donut) + activity + understaffing stepper. Extracted from `ZoneOccupancyPanel` so Reports and the Live zone panel share it. Props: `name, occ, act, view, defaultN`. |
| `features/reports/StaffingTimelineChart.tsx` | New, dependency-free SVG/div bars. Props: `timeline, kind, tz`. |
| `features/dashboard/WorkforceOverview.tsx` + `aggregateMetrics.ts` | System-wide fold across cameras' `…/metrics`; REST-driven, no WS. |
| `features/cameras/AnalysisPanel.tsx`, `ZoneOccupancyPanel.tsx` | Per-camera analytics. Work offline via the REST path (don't pass `liveMetrics`); the 600 s live window is the only WS-bound mode. |
| `ui/*` (Button, Panel, Toolbar, StatReadout, Pill, Icon, Input, ConfirmDialog, DataCard) | Generic primitives (drop only `Hud`, which is live-only). |

---

## 4. Zone authoring data flow (`ZonesTab.tsx` + `PolygonSvg.tsx`)

1. A frame scrubber (`<input type=range>` from 0 to `camera.duration_s`) sets the time `t`.
2. The frame `<img>` src = `api.frameUrl(cameraId, t)` (cache-busted). The backend decodes
   that frame from the camera's recording (`GET /cameras/{id}/frame?t=`), falling back to the
   newest on-disk recording if the original file rotated away.
3. `PolygonSvg` overlays an editor: click to add vertices, double-click to close (≥3 pts),
   drag to adjust. Coordinates are stored **normalized 0..1** so they render at any resolution.
4. Save → `api.createZone(cameraId, name, points, excluded)`. "Not monitored" sets `excluded`.

> Because offline cameras are **auto-created by ingest**, the scrubber needs `camera.duration_s`
> — the ingest path now probes and sets it. (See the Phase-3 fix in
> [../../CLAUDE.md](../../CLAUDE.md)/the offline-app memory.)

---

## 5. Styling & tokens

- `frontend/src/styles.css` — global CSS vars and component classes:
  - **Rollup palette** `--ru-working` (blue) / `--ru-moving` (indigo) / `--ru-idle` (amber)
    / `--ru-group_idle` / `--ru-unclear`; **activity palette** `--act-*`; surfaces, glass,
    borders, text, accent/warn/danger.
  - Component classes used by the offline UI: `.glass`, `.tech-grid`, `.hint`, `.window-tabs`/
    `.window-tab`, `.stacked-bar`/`.seg`, `.analysis*`, `.activity-bar*`/`.activity-bg-*`,
    `.zone-*` (sections, pie, legend, understaffed, stepper), `.editor-wrap`.
- `frontend/src/theme.css` — Tailwind v4 `@theme` mapping the CSS vars to Tailwind tokens
  (colors, fonts: Outfit body / Space Grotesk display+mono, radius, type scale).
- Fonts via `@fontsource-variable/*` (in `main.tsx`) + Material Symbols (in `index.html`).

---

## 6. Data flow summary

- **Setup** (CRUD): factories/sites/cameras/zones/rules via `api.*` (POST/PATCH/DELETE).
- **Reports**: `api.getReport` (JSON) + `api.reportPdfUrl` (download).
- **Recordings**: `api.listRecordings`.
- **Per-camera analytics**: `GET /cameras/{id}/metrics?since=&until=` (historical) — the
  offline UI never needs the live 600 s window.

### Shared-types note for extraction

`MetricsSummary`, `ZoneOccupancy`, `ZoneActivity` are currently **defined in**
`hooks/useEventsWS.ts` (the live WS hook). `ReportsPage`, `ZoneCard`, `MetricsBreakdown`,
`AnalysisPanel`, `ZoneOccupancyPanel`, `WorkforceOverview`, and `aggregateMetrics.ts` import
them from there. When extracting (dropping the WS hook), **move these type definitions** into
a standalone module (e.g. `api/metrics.ts`) and repoint those imports. See
[EXTRACTION.md](EXTRACTION.md).
