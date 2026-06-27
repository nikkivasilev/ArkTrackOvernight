"""Render a ``PeriodSummary`` to a polished, multi-section PDF report.

matplotlib (Agg, headless) draws the charts to PNG; fpdf2 lays out the page.
DejaVu Sans (shipped with matplotlib) is registered so Cyrillic camera names
like "IP Камера25" render correctly — the fpdf2 core fonts are latin-1 only.

Layout (A4 portrait):
  1. Cover + Executive summary — title band, KPI dashboard, auto-generated
     insight bullets, and the whole-factory activity split.
  2. Staffing over time — staffing curve with the peak annotated, plus
     busiest / quietest / above-average stats.
  3. Activity breakdown — fine-grained per-activity bars (welding, working,
     walking, …) for the whole factory.
  4. By camera — per camera: headline stats, activity breakdown, and a
     per-zone deep dive (occupancy distribution + in-zone activity mix).
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from fpdf import FPDF  # noqa: E402
from fpdf.enums import XPos, YPos  # noqa: E402

from app.offline.aggregate import ROLLUP_ORDER
from app.offline.day_summary import DaySummary

# --- palette (RGB 0..255) --------------------------------------------------
BAND = (17, 24, 39)       # dark slate header band
ACCENT = (37, 99, 235)    # blue
INK = (30, 41, 59)
MUTED = (100, 116, 139)
HAIR = (226, 232, 240)
CARD_BG = (244, 247, 251)

ROLLUP_RGB = {
    "working": (37, 99, 235),    # blue
    "moving": (245, 158, 11),    # amber
    "idle": (239, 68, 68),       # red
    "unclear": (148, 163, 184),  # slate
}

# Fine-grained activity colours; unknown labels cycle through _FALLBACK.
ACTIVITY_RGB = {
    "welding": (234, 88, 12),
    "working": (37, 99, 235),
    "assembling": (29, 78, 216),
    "drilling": (2, 132, 199),
    "lifting_or_carrying": (13, 148, 136),
    "walking": (16, 185, 129),
    "standing": (250, 204, 21),
    "standing_idle": (245, 158, 11),
    "sitting": (234, 179, 8),
    "chatting": (168, 85, 247),
    "on_phone": (217, 70, 239),
    "sleeping": (239, 68, 68),
    "idle": (239, 68, 68),
    "unknown": (148, 163, 184),
}
_FALLBACK = [
    (59, 130, 246), (14, 165, 233), (20, 184, 166), (132, 204, 22),
    (245, 158, 11), (249, 115, 22), (244, 63, 94), (217, 70, 239),
    (139, 92, 246), (100, 116, 139),
]


def _rgb01(rgb):
    return tuple(c / 255.0 for c in rgb)


def _act_color01(name: str, i: int):
    return _rgb01(ACTIVITY_RGB.get(name, _FALLBACK[i % len(_FALLBACK)]))


def _pretty(name: str) -> str:
    return name.replace("_", " ")


def _font_paths():
    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    reg = base / "DejaVuSans.ttf"
    bold = base / "DejaVuSans-Bold.ttf"
    return str(reg), str(bold if bold.exists() else reg)


def _hours(seconds: float) -> str:
    return f"{seconds / 3600.0:.1f} h"


def _fmt_dur(seconds: float) -> str:
    s = float(seconds or 0.0)
    if s >= 3600:
        return f"{s / 3600.0:.1f} h"
    if s >= 60:
        return f"{s / 60.0:.0f} min"
    return f"{s:.0f} s"


def _fig_png(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _bin_minutes(timeline: list[dict]) -> float:
    if len(timeline) >= 2:
        dt = (timeline[1]["t"] - timeline[0]["t"]).total_seconds() / 60.0
        if dt > 0:
            return dt
    return 30.0


# --- charts ----------------------------------------------------------------
def _staffing_chart(timeline: list[dict], tz: ZoneInfo, kind: str = "intraday") -> io.BytesIO:
    xs = [t["t"].astimezone(tz) for t in timeline]
    ys = [t["avg_headcount"] for t in timeline]
    fig, ax = plt.subplots(figsize=(7.4, 2.4))
    color = _rgb01(ACCENT)
    if kind == "daily":
        ax.bar(xs, ys, width=0.8, color=color, align="center")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b", tz=tz))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    else:
        ax.fill_between(xs, ys, color=color, alpha=0.22)
        ax.plot(xs, ys, color=color, lw=1.8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    # annotate the peak bin
    if ys and max(ys) > 0:
        pi = max(range(len(ys)), key=lambda i: ys[i])
        ax.scatter([xs[pi]], [ys[pi]], color=_rgb01((234, 88, 12)), zorder=5, s=18)
        ax.annotate(
            f"peak {ys[pi]:.1f}\n{xs[pi]:%H:%M}", (xs[pi], ys[pi]),
            textcoords="offset points", xytext=(0, 8), ha="center",
            fontsize=7, color=_rgb01((234, 88, 12)), weight="bold",
        )
    ax.set_ylabel("avg people", fontsize=8)
    ax.set_ylim(bottom=0)
    ax.margins(y=0.18)
    ax.tick_params(labelsize=8)
    ax.grid(True, axis="y", color=_rgb01(HAIR), lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return _fig_png(fig)


def _split_bar(rollup_pct: dict[str, float]) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(7.4, 0.7))
    left = 0.0
    for key in ROLLUP_ORDER:
        v = rollup_pct.get(key, 0.0)
        if v <= 0:
            continue
        ax.barh(0, v, left=left, color=_rgb01(ROLLUP_RGB[key]), height=0.6)
        if v >= 6:
            ax.text(left + v / 2, 0, f"{key}\n{v:.0f}%", ha="center", va="center",
                    fontsize=7, color="white", weight="bold")
        left += v
    ax.set_xlim(0, 100)
    ax.axis("off")
    return _fig_png(fig)


def _activity_chart(act_pct: dict, act_sec: dict, max_rows: int = 12) -> io.BytesIO | None:
    items = [(k, v) for k, v in act_pct.items() if v > 0]
    items.sort(key=lambda kv: -kv[1])
    items = items[:max_rows]
    if not items:
        return None
    labels = [_pretty(k) for k, _ in items]
    vals = [v for _, v in items]
    colors = [_act_color01(k, i) for i, (k, _) in enumerate(items)]
    fig, ax = plt.subplots(figsize=(7.4, 0.34 * len(items) + 0.5))
    ypos = range(len(items))
    ax.barh(list(ypos), vals, color=colors, height=0.66)
    ax.set_yticks(list(ypos))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals) * 1.18 + 1)
    for i, (k, v) in enumerate(items):
        ax.text(v + max(vals) * 0.015, i, f"{v:.1f}%  ·  {_fmt_dur(act_sec.get(k, 0))}",
                va="center", fontsize=7, color=_rgb01(INK))
    ax.tick_params(axis="x", labelsize=7)
    ax.grid(True, axis="x", color=_rgb01(HAIR), lw=0.5)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    return _fig_png(fig)


def _occupancy_chart(seconds_at: dict) -> io.BytesIO | None:
    if not seconds_at:
        return None
    counts = sorted(int(k) for k in seconds_at)
    mins = [seconds_at[str(c)] / 60.0 for c in counts]
    colors = [_rgb01((239, 68, 68) if c == 0 else ACCENT) for c in counts]
    fig, ax = plt.subplots(figsize=(3.5, 1.9))
    ax.bar([str(c) for c in counts], mins, color=colors, width=0.7)
    ax.set_xlabel("people in zone", fontsize=7)
    ax.set_ylabel("minutes", fontsize=7)
    ax.tick_params(labelsize=7)
    ax.grid(True, axis="y", color=_rgb01(HAIR), lw=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return _fig_png(fig)


def _zone_activity_chart(pct: dict, max_rows: int = 6) -> io.BytesIO | None:
    items = [(k, v) for k, v in pct.items() if v > 0]
    items.sort(key=lambda kv: -kv[1])
    items = items[:max_rows]
    if not items:
        return None
    labels = [_pretty(k) for k, _ in items]
    vals = [v for _, v in items]
    colors = [_act_color01(k, i) for i, (k, _) in enumerate(items)]
    fig, ax = plt.subplots(figsize=(3.5, 0.3 * len(items) + 0.4))
    ypos = range(len(items))
    ax.barh(list(ypos), vals, color=colors, height=0.62)
    ax.set_yticks(list(ypos))
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals) * 1.2 + 1)
    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.02, i, f"{v:.0f}%", va="center", fontsize=6.5, color=_rgb01(INK))
    ax.tick_params(axis="x", labelsize=6.5)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    return _fig_png(fig)


# --- insights --------------------------------------------------------------
def _insights(summary: DaySummary) -> list[str]:
    fs = summary.factory_summary
    rp = fs.get("rollup_pct", {})
    ap = fs.get("activity_pct", {})
    out: list[str] = []

    out.append(
        f"{summary.total_recordings} recordings ({_hours(summary.total_footage_s)}) analysed across "
        f"{len(summary.cameras)} camera(s); {_hours(fs.get('worker_seconds', 0))} of worker-time observed."
    )

    # Peak time from the staffing timeline.
    tl = [t for t in summary.timeline if t.get("avg_headcount", 0) > 0]
    if tl:
        tz = ZoneInfo(summary.tz)
        peak = max(tl, key=lambda t: t["avg_headcount"])
        quiet = min(tl, key=lambda t: t["avg_headcount"])
        out.append(
            f"Staffing peaked around {peak['t'].astimezone(tz):%H:%M} "
            f"(~{peak['avg_headcount']:.1f} avg, {fs.get('peak_headcount', 0)} max); "
            f"quietest around {quiet['t'].astimezone(tz):%H:%M} (~{quiet['avg_headcount']:.1f})."
        )

    work = rp.get("working", 0.0)
    idle = rp.get("idle", 0.0)
    out.append(
        f"{work:.0f}% of worker-time was productive; {idle:.0f}% idle "
        f"({_fmt_dur(fs.get('rollup_seconds', {}).get('idle', 0))})."
    )

    if ap:
        top = sorted(ap.items(), key=lambda kv: -kv[1])[:3]
        out.append(
            "Most common tasks: "
            + ", ".join(f"{_pretty(k)} {v:.0f}%" for k, v in top) + "."
        )

    # Per-zone unmanned time (occupancy at 0 people).
    zocc = fs.get("zone_occupancy", {})
    for zid, o in zocc.items():
        name = summary.zone_names.get(zid, zid)
        unmanned = (o.get("seconds_at", {}) or {}).get("0", 0)
        msg = f"Zone “{name}”: avg {o.get('avg', 0):.1f} / peak {o.get('peak', 0)} people"
        if unmanned:
            msg += f"; unmanned {_fmt_dur(unmanned)}"
        out.append(msg + ".")
    return out


# --- document --------------------------------------------------------------
class _Report(FPDF):
    def __init__(self, summary: DaySummary):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.summary = summary
        reg, bold = _font_paths()
        self.add_font("DejaVu", "", reg)
        self.add_font("DejaVu", "B", bold)
        self.set_auto_page_break(True, margin=15)

    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", "", 7)
        self.set_text_color(*MUTED)
        gen = self.summary.generated_at.astimezone(ZoneInfo(self.summary.tz))
        self.cell(0, 5, f"ArkTrack workforce report · generated {gen:%Y-%m-%d %H:%M %Z}", align="L")
        self.cell(0, 5, f"page {self.page_no()}", align="R")

    # building blocks
    def cover(self, title: str, factory: str, subtitle: str, coverage: str):
        self.set_fill_color(*BAND)
        self.rect(0, 0, self.w, 34, style="F")
        self.set_xy(self.l_margin, 9)
        self.set_font("DejaVu", "B", 21)
        self.set_text_color(255, 255, 255)
        self.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_x(self.l_margin)
        self.set_font("DejaVu", "", 11)
        self.set_text_color(203, 213, 225)
        self.cell(0, 6, f"{factory}   ·   {subtitle}")
        self.set_y(40)
        self.set_text_color(*MUTED)
        self.set_font("DejaVu", "", 9)
        self.cell(0, 5, coverage, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def h2(self, text: str):
        if self.get_y() > self.h - 45:
            self.add_page()
        self.ln(2)
        self.set_font("DejaVu", "B", 13)
        self.set_text_color(*INK)
        self.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.5)
        y = self.get_y()
        self.line(self.l_margin, y, self.l_margin + 28, y)
        self.set_draw_color(*HAIR)
        self.set_line_width(0.2)
        self.line(self.l_margin + 28, y, self.w - self.r_margin, y)
        self.ln(3)

    def h3(self, text: str):
        self.set_font("DejaVu", "B", 11)
        self.set_text_color(*INK)
        self.cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def muted(self, text: str, size: float = 9):
        self.set_font("DejaVu", "", size)
        self.set_text_color(*MUTED)
        self.cell(0, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def kpi_grid(self, cards: list[tuple[str, str, tuple]], per_row: int = 4, card_h: float = 20):
        avail = self.w - self.l_margin - self.r_margin
        gap = 4
        cw = (avail - gap * (per_row - 1)) / per_row
        x0 = self.l_margin
        row_y = self.get_y()
        for idx, (label, value, color) in enumerate(cards):
            col = idx % per_row
            if col == 0 and idx > 0:
                row_y += card_h + gap
            x = x0 + col * (cw + gap)
            self.set_fill_color(*CARD_BG)
            self.rect(x, row_y, cw, card_h, style="F")
            self.set_fill_color(*color)
            self.rect(x, row_y, 1.6, card_h, style="F")  # accent edge
            self.set_xy(x + 4, row_y + 3.5)
            self.set_font("DejaVu", "B", 15)
            self.set_text_color(*color)
            self.cell(cw - 8, 8, value)
            self.set_xy(x + 4, row_y + 12)
            self.set_font("DejaVu", "", 7.5)
            self.set_text_color(*MUTED)
            self.cell(cw - 8, 5, label.upper())
        self.set_xy(x0, row_y + card_h + gap + 1)

    def bullets(self, items: list[str]):
        self.set_font("DejaVu", "", 9.5)
        for it in items:
            self.set_text_color(*ACCENT)
            self.cell(4, 5, "•")
            self.set_text_color(*INK)
            self.multi_cell(0, 5, it, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(0.5)

    def image_full(self, png: io.BytesIO, h: float | None = None, w: float | None = None):
        width = w or (self.w - self.l_margin - self.r_margin)
        self.image(png, x=self.l_margin, w=width, h=h or 0)
        self.ln(2)

    def stat_line(self, pairs: list[tuple[str, str]]):
        """A row of inline 'label: value' chips."""
        self.set_font("DejaVu", "", 8.5)
        parts = "    ".join(f"{l}: {v}" for l, v in pairs)
        self.set_text_color(*MUTED)
        self.multi_cell(0, 5, parts, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _staffing_stats(summary: DaySummary) -> list[tuple[str, str]]:
    tl = [t for t in summary.timeline if t.get("avg_headcount", 0) > 0]
    if not tl:
        return []
    tz = ZoneInfo(summary.tz)
    bw = _bin_minutes(summary.timeline)
    peak = max(tl, key=lambda t: t["avg_headcount"])
    quiet = min(tl, key=lambda t: t["avg_headcount"])
    avg = sum(t["avg_headcount"] for t in tl) / len(tl)
    above = sum(1 for t in tl if t["avg_headcount"] >= avg) * bw
    staffed = len(tl) * bw
    label = "%H:%M" if summary.timeline_kind == "intraday" else "%d %b"
    return [
        ("busiest", f"{peak['t'].astimezone(tz):{label}} (~{peak['avg_headcount']:.1f})"),
        ("quietest", f"{quiet['t'].astimezone(tz):{label}} (~{quiet['avg_headcount']:.1f})"),
        ("staffed span", _fmt_dur(staffed * 60)),
        ("above-avg", _fmt_dur(above * 60)),
    ]


def _camera_section(pdf: _Report, summary: DaySummary, cam) -> None:
    cs = cam.summary
    crp = cs.get("rollup_pct", {})
    if pdf.get_y() > pdf.h - 80:
        pdf.add_page()
    pdf.h3(cam.name)
    pdf.stat_line([
        ("worker-time", _hours(cs.get("worker_seconds", 0))),
        ("avg/peak", f"{cs.get('avg_headcount', 0):.1f} / {cs.get('peak_headcount', 0)}"),
        ("recordings", f"{cam.recordings} ({_hours(cam.footage_s)})"),
        ("working", f"{crp.get('working', 0):.0f}%"),
        ("idle", f"{crp.get('idle', 0):.0f}%"),
    ])
    if crp:
        pdf.image_full(_split_bar(crp), h=10)
    act = _activity_chart(cs.get("activity_pct", {}), cs.get("activity_seconds", {}))
    if act:
        pdf.image_full(act)

    # Per-zone deep dive.
    occ = cs.get("zone_occupancy", {})
    actv = cs.get("zone_activity", {})
    half = (pdf.w - pdf.l_margin - pdf.r_margin - 6) / 2
    for zid in sorted(set(occ) | set(actv), key=lambda z: cam.zone_names.get(z, z)):
        name = cam.zone_names.get(zid, zid)
        o = occ.get(zid, {})
        za = actv.get(zid, {}).get("pct", {})
        unmanned = (o.get("seconds_at", {}) or {}).get("0", 0)
        # Charts render at width=half; their height follows the figure aspect.
        # Advance by the taller one and page-break before splitting the block.
        n_act = min(sum(1 for v in za.values() if v > 0), 6) or 1
        charts_h = max(half * 1.9 / 3.5, half * (0.3 * n_act + 0.4) / 3.5)
        if pdf.get_y() + 13 + charts_h + 4 > pdf.h - 16:
            pdf.add_page()
        pdf.ln(1)
        pdf.set_font("DejaVu", "B", 9.5)
        pdf.set_text_color(*INK)
        pdf.cell(0, 6, f"Zone · {name}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.stat_line([
            ("avg", f"{o.get('avg', 0):.1f}"),
            ("peak", str(o.get("peak", 0))),
            ("monitored", _fmt_dur(o.get("total_s", 0))),
            ("unmanned", _fmt_dur(unmanned)),
        ])
        y = pdf.get_y()
        occ_png = _occupancy_chart(o.get("seconds_at", {}))
        if occ_png:
            pdf.image(occ_png, x=pdf.l_margin, y=y, w=half)
        za_png = _zone_activity_chart(za)
        if za_png:
            pdf.image(za_png, x=pdf.l_margin + half + 6, y=y, w=half)
        pdf.set_y(y + charts_h + 4)
    pdf.ln(2)


def render_period_pdf(summary: DaySummary, out_path: Path | None = None) -> Path:
    tz = ZoneInfo(summary.tz)
    titles = {
        "day": "Daily Workforce Report",
        "week": "Weekly Workforce Report",
        "month": "Monthly Workforce Report",
        "range": "Workforce Report",
    }
    if summary.period == "week":
        subtitle = f"{summary.start:%d %b} – {summary.end:%d %b %Y}"
        default_name = f"week_{summary.start:%G-W%V}_{summary.factory_name}.pdf"
    elif summary.period == "month":
        subtitle = f"{summary.start:%B %Y}"
        default_name = f"month_{summary.start:%Y-%m}_{summary.factory_name}.pdf"
    elif summary.period == "range":
        subtitle = f"{summary.start:%d %b %Y} – {summary.end:%d %b %Y}"
        default_name = f"range_{summary.start:%Y-%m-%d}_{summary.end:%Y-%m-%d}_{summary.factory_name}.pdf"
    else:
        subtitle = f"{summary.start:%A, %d %B %Y}"
        default_name = f"day_{summary.start:%Y-%m-%d}_{summary.factory_name}.pdf"

    if out_path is None:
        from app.config import settings
        out_path = Path(settings.offline_report_dir) / default_name

    fs = summary.factory_summary
    rp = fs.get("rollup_pct", {})
    coverage = (f"{summary.total_recordings} recordings · {_hours(summary.total_footage_s)} of footage "
                f"· timezone {summary.tz}")

    pdf = _Report(summary)
    pdf.add_page()

    # ---- 1. Cover + executive summary ----
    pdf.cover(titles.get(summary.period, "Workforce Report"),
              summary.factory_name, subtitle, coverage)

    # Busiest hour for the KPI grid.
    tl = [t for t in summary.timeline if t.get("avg_headcount", 0) > 0]
    busiest = "—"
    if tl:
        pk = max(tl, key=lambda t: t["avg_headcount"])
        busiest = f"{pk['t'].astimezone(tz):%H:%M}" if summary.timeline_kind == "intraday" \
            else f"{pk['t'].astimezone(tz):%d %b}"

    pdf.kpi_grid([
        ("worker-hours", f"{fs.get('worker_seconds', 0) / 3600:.1f}", ACCENT),
        ("avg people", f"{fs.get('avg_headcount', 0):.1f}", INK),
        ("peak people", str(fs.get("peak_headcount", 0)), INK),
        ("working", f"{rp.get('working', 0):.0f}%", ROLLUP_RGB["working"]),
        ("idle", f"{rp.get('idle', 0):.0f}%", ROLLUP_RGB["idle"]),
        ("footage", _hours(summary.total_footage_s), MUTED),
        ("recordings", str(summary.total_recordings), MUTED),
        ("busiest", busiest, ROLLUP_RGB["moving"]),
    ])

    pdf.h3("Key insights")
    pdf.bullets(_insights(summary))
    pdf.ln(1)
    if rp:
        pdf.h3("Activity split — whole factory")
        pdf.image_full(_split_bar(rp), h=12)

    # ---- 2. Staffing over time ----
    pdf.add_page()
    pdf.h2(f"Staffing over the {summary.period}")
    if any(t["avg_headcount"] > 0 for t in summary.timeline):
        pdf.image_full(_staffing_chart(summary.timeline, tz, summary.timeline_kind), h=46)
        stats = _staffing_stats(summary)
        if stats:
            pdf.stat_line(stats)
    else:
        pdf.muted("No footage with detected people in this period.")

    # ---- 3. Activity breakdown (whole factory) ----
    pdf.h2("Activity breakdown — whole factory")
    act = _activity_chart(fs.get("activity_pct", {}), fs.get("activity_seconds", {}))
    if act:
        pdf.muted("Share of observed worker-time per task (worker-weighted).", 8.5)
        pdf.image_full(act)
    else:
        pdf.muted("No activity recorded.")

    # ---- 4. By camera ----
    pdf.add_page()
    pdf.h2(f"By camera · {len(summary.cameras)}")
    if not summary.cameras:
        pdf.muted("No cameras contributed footage in this period.")
    for cam in summary.cameras:
        _camera_section(pdf, summary, cam)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path


# Back-compat alias: existing callers (reports.py, verify scripts) import this.
render_day_pdf = render_period_pdf
