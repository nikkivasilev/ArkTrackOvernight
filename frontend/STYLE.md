# Frontend style — anti-template rules

The UI is dressed as an industrial control-room (SCADA / NOC), not a marketing
dashboard. The aesthetic is enforced by a few rules, not by a component
library's defaults. When in doubt, default to "denser, sharper, more readable
data."

## Visual rules

1. **Sharp corners on data.** `rounded-data` (0px) for tables, status pills,
   numeric readouts, and anything that frames live data. `rounded-panel` (2px)
   for outer container panels only. Never `rounded-md` / `rounded-lg` / larger.
2. **Borders, not shadows.** Hierarchy comes from `border border-border` + bg
   tone changes. No `shadow-*` utilities on data surfaces — the only allowed
   shadow is on the modal/command-palette overlay.
3. **Monospace for numbers.** All live readouts, IDs, timestamps, counts:
   `font-mono tabular-nums`. Body copy stays sans.
4. **Loud SCREAMING SMALL CAPS for chrome labels.** Section headers, pill
   labels, toolbar subtitles: `text-[10px] tracking-[0.16em] uppercase
   text-text-dim`. Big numbers carry the visual weight; labels stay quiet.
5. **Color is semantic, not decorative.** `accent` (cyan) = primary /
   informational, `accent-2` (green) = ok / running, `amber` = warn / attention,
   `danger` (red) = failure. Never use a color because it "looks nice."
6. **One primary action per surface.** Use `<Button tone="primary">` for the
   single most important action; everything else is `secondary` or `ghost`. If
   two buttons look equally important, demote one.
7. **Asymmetry on purpose.** Avoid 2×2 grids unless the four cells genuinely
   carry equal weight. Prefer one large primary readout + smaller secondary
   metrics around it.

## Primitives

Use the shared primitives in `src/ui/`:

- `Panel` — bordered container with optional title (default: padded; `flush`
  variant for tables).
- `DataCard` — thumb + body interactive tile with semantic left-edge accent.
- `StatReadout` — large mono-tabular numeric readout with small caps label.
- `Pill` — status chip; `tone` prop picks the semantic color.
- `Toolbar` — page-header row: title + subtitle + actions slot.
- `Hud` — fixed-row monospace telemetry strip (live frame/fps/det counts).
- `Button` — `primary | secondary | ghost | danger` tones.

If a new pattern repeats twice, promote it here. Do not invent a new pattern
per page.

## When NOT to follow these rules

These rules are about data surfaces. Free-form text content (alert
descriptions, empty-state copy, multi-paragraph explanations) can break the
SCREAMING SMALL CAPS rule and use sentence-case sans-serif. Use judgment.
