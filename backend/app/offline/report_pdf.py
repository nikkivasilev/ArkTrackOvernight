"""Render a ``DaySummary`` to a PDF day report.

matplotlib (Agg, headless) draws the charts to PNG; fpdf2 lays out the page.
DejaVu Sans (shipped with matplotlib) is registered so Cyrillic camera names
like "IP Камера25" render correctly — the fpdf2 core fonts are latin-1 only.

Layout (A4 portrait):
  - Header: factory, local date, coverage line.
  - Factory headline: KPI cards (worker-hours, avg / peak headcount, working %)
    + staffing-over-day area chart + working/moving/idle/unclear split bar.
  - Per camera: stats line, activity split bar, per-zone occupancy/activity table.
"""
from __future__ import annotations

import io
import os
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

# RGB palette, shared by charts (0..1 floats) and PDF fills (0..255 ints).
ROLLUP_RGB = {
    "working": (37, 99, 235),    # blue
    "moving": (245, 158, 11),    # amber
    "idle": (239, 68, 68),       # red
    "unclear": (148, 163, 184),  # slate
}
INK = (30, 41, 59)
MUTED = (100, 116, 139)
HAIR = (226, 232, 240)


def _rgb01(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return tuple(c / 255.0 for c in rgb)


def _font_paths() -> tuple[str, str]:
    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    reg = base / "DejaVuSans.ttf"
    bold = base / "DejaVuSans-Bold.ttf"
    return str(reg), str(bold if bold.exists() else reg)


def _hours(seconds: float) -> str:
    h = seconds / 3600.0
    return f"{h:.1f} h"


def _fig_png(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _staffing_chart(timeline: list[dict], tz: ZoneInfo, kind: str = "intraday") -> io.BytesIO:
    xs = [t["t"].astimezone(tz) for t in timeline]
    ys = [t["avg_headcount"] for t in timeline]
    fig, ax = plt.subplots(figsize=(7.2, 2.2))
    color = _rgb01(ROLLUP_RGB["working"])
    if kind == "daily":
        # Week/month: one bar per calendar day reads better than a sparse curve.
        ax.bar(xs, ys, width=0.8, color=color, align="center")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b", tz=tz))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=10))
    else:
        ax.fill_between(xs, ys, color=color, alpha=0.25)
        ax.plot(xs, ys, color=color, lw=1.6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax.set_ylabel("avg people", fontsize=8)
    ax.set_ylim(bottom=0)
    ax.tick_params(labelsize=8)
    ax.grid(True, axis="y", color=_rgb01(HAIR), lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return _fig_png(fig)


def _split_bar(rollup_pct: dict[str, float]) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(7.2, 0.7))
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
        self.cell(0, 5, f"ArkTrack {self.summary.period} report · generated {gen:%Y-%m-%d %H:%M %Z}",
                  align="L")
        self.cell(0, 5, f"page {self.page_no()}", align="R")

    # --- building blocks ------------------------------------------------
    def h1(self, text: str):
        self.set_font("DejaVu", "B", 18)
        self.set_text_color(*INK)
        self.cell(0, 10, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def h2(self, text: str):
        self.ln(2)
        self.set_font("DejaVu", "B", 12)
        self.set_text_color(*INK)
        self.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*HAIR)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def muted(self, text: str, size: int = 9):
        self.set_font("DejaVu", "", size)
        self.set_text_color(*MUTED)
        self.cell(0, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def kpi_row(self, cards: list[tuple[str, str, tuple[int, int, int]]]):
        avail = self.w - self.l_margin - self.r_margin
        gap = 4
        cw = (avail - gap * (len(cards) - 1)) / len(cards)
        x0, y0 = self.get_x(), self.get_y()
        for i, (label, value, color) in enumerate(cards):
            x = x0 + i * (cw + gap)
            self.set_fill_color(*color)
            self.rect(x, y0, cw, 18, style="F")
            self.set_xy(x + 3, y0 + 2.5)
            self.set_font("DejaVu", "B", 15)
            self.set_text_color(255, 255, 255)
            self.cell(cw - 6, 8, value, new_x=XPos.LEFT, new_y=YPos.NEXT)
            self.set_x(x + 3)
            self.set_font("DejaVu", "", 8)
            self.cell(cw - 6, 5, label)
        self.set_xy(x0, y0 + 18 + 3)

    def image_full(self, png: io.BytesIO, h: float | None = None):
        w = self.w - self.l_margin - self.r_margin
        self.image(png, x=self.l_margin, w=w, h=h or 0)
        self.ln(2)

    def zone_table(self, cam):
        occ = cam.summary["zone_occupancy"]
        actv = cam.summary["zone_activity"]
        if not occ and not actv:
            return
        self.set_font("DejaVu", "B", 8.5)
        self.set_text_color(*MUTED)
        widths = [60, 22, 18, 80]
        heads = ["Zone", "avg occ", "peak", "top activities"]
        for w_, hd in zip(widths, heads):
            self.cell(w_, 6, hd, border="B")
        self.ln(6)
        self.set_font("DejaVu", "", 8.5)
        self.set_text_color(*INK)
        for zid in sorted(set(occ) | set(actv)):
            name = cam.zone_names.get(zid, zid)[:34]
            o = occ.get(zid, {})
            a = actv.get(zid, {}).get("pct", {})
            top = ", ".join(
                f"{k} {v:.0f}%" for k, v in sorted(a.items(), key=lambda kv: -kv[1])[:3]
            )
            self.cell(widths[0], 5.5, name)
            self.cell(widths[1], 5.5, f"{o.get('avg', 0):.1f}")
            self.cell(widths[2], 5.5, str(o.get("peak", 0)))
            self.cell(widths[3], 5.5, top[:46])
            self.ln(5.5)
        self.ln(1)


def render_period_pdf(summary: DaySummary, out_path: Path | None = None) -> Path:
    tz = ZoneInfo(summary.tz)
    titles = {
        "day": "Daily Workforce Summary",
        "week": "Weekly Workforce Summary",
        "month": "Monthly Workforce Summary",
    }
    if summary.period == "week":
        subtitle = f"{summary.start:%d %b} – {summary.end:%d %b %Y}"
        default_name = f"week_{summary.start:%G-W%V}_{summary.factory_name}.pdf"
    elif summary.period == "month":
        subtitle = f"{summary.start:%B %Y}"
        default_name = f"month_{summary.start:%Y-%m}_{summary.factory_name}.pdf"
    else:
        subtitle = f"{summary.start:%A, %d %B %Y}"
        default_name = f"day_{summary.start:%Y-%m-%d}_{summary.factory_name}.pdf"

    if out_path is None:
        from app.config import settings
        out_path = Path(settings.offline_report_dir) / default_name

    pdf = _Report(summary)
    pdf.add_page()

    # Header
    pdf.h1(titles.get(summary.period, "Workforce Summary"))
    pdf.set_font("DejaVu", "B", 12)
    pdf.set_text_color(*INK)
    pdf.cell(0, 7, f"{summary.factory_name} · {subtitle}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    cov = (f"{summary.total_recordings} recordings · "
           f"{_hours(summary.total_footage_s)} of footage · timezone {summary.tz}")
    pdf.muted(cov)
    pdf.ln(3)

    fs = summary.factory_summary
    rp = fs["rollup_pct"]
    pdf.kpi_row([
        ("worker-hours", _hours(fs["worker_seconds"]), ROLLUP_RGB["working"]),
        ("avg people present", f"{fs['avg_headcount']:.1f}", INK),
        ("peak people", str(fs["peak_headcount"]), MUTED),
        ("working", f"{rp.get('working', 0):.0f}%", ROLLUP_RGB["working"]),
        ("idle", f"{rp.get('idle', 0):.0f}%", ROLLUP_RGB["idle"]),
    ])

    pdf.h2(f"Staffing through the {summary.period}")
    if any(t["avg_headcount"] > 0 for t in summary.timeline):
        pdf.image_full(_staffing_chart(summary.timeline, tz, summary.timeline_kind), h=42)
    else:
        pdf.muted("No footage with detected people in this period.")

    pdf.h2("Activity split (whole factory)")
    if rp:
        pdf.image_full(_split_bar(rp), h=14)
    else:
        pdf.muted("No activity recorded.")

    # Per camera
    pdf.h2("By camera")
    if not summary.cameras:
        pdf.muted("No cameras contributed footage on this day.")
    for cam in summary.cameras:
        cs = cam.summary
        crp = cs["rollup_pct"]
        if pdf.get_y() > pdf.h - 70:
            pdf.add_page()
        pdf.set_font("DejaVu", "B", 11)
        pdf.set_text_color(*INK)
        pdf.cell(0, 7, cam.name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.muted(
            f"{_hours(cs['worker_seconds'])} worker-time · avg {cs['avg_headcount']:.1f} "
            f"/ peak {cs['peak_headcount']} people · {cam.recordings} recordings "
            f"({_hours(cam.footage_s)}) · working {crp.get('working', 0):.0f}% "
            f"idle {crp.get('idle', 0):.0f}%",
            size=8.5,
        )
        if crp:
            pdf.image_full(_split_bar(crp), h=11)
        pdf.zone_table(cam)
        pdf.ln(2)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path


# Back-compat alias: existing callers (reports.py, verify scripts) import this.
render_day_pdf = render_period_pdf
