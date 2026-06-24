import * as Dialog from "@radix-ui/react-dialog";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Camera, Factory, Site } from "../api/client";

type Entry =
  | { kind: "factory"; id: string; label: string; subtitle: string; to: string }
  | { kind: "site"; id: string; label: string; subtitle: string; to: string }
  | { kind: "camera"; id: string; label: string; subtitle: string; to: string };

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [factories, setFactories] = useState<Factory[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selected, setSelected] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const fs = await api.listFactories();
      setFactories(fs);
      const cs = await api.listAllCameras();
      setCameras(cs);
      const sl = await Promise.all(fs.map((f) => api.listSitesForFactory(f.id)));
      setSites(sl.flat());
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Global Cmd-K / Ctrl-K to open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Refetch index whenever the palette opens, so newly-created entities appear.
  useEffect(() => {
    if (open) {
      refresh();
      setQuery("");
      setSelected(0);
      // Focus after Radix mounts the input.
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open, refresh]);

  const entries = useMemo<Entry[]>(() => {
    const factoryById = new Map(factories.map((f) => [f.id, f]));
    const siteById = new Map(sites.map((s) => [s.id, s]));

    const list: Entry[] = [];
    for (const f of factories) {
      list.push({
        kind: "factory",
        id: f.id,
        label: f.name,
        subtitle: "factory",
        to: `/factories/${f.id}`,
      });
    }
    for (const s of sites) {
      const f = factoryById.get(s.factory_id);
      list.push({
        kind: "site",
        id: s.id,
        label: s.name,
        subtitle: `site · ${f?.name ?? "?"}`,
        to: `/factories/${s.factory_id}/sites/${s.id}`,
      });
    }
    for (const c of cameras) {
      const s = siteById.get(c.site_id);
      const f = s ? factoryById.get(s.factory_id) : undefined;
      const to =
        s && f
          ? `/factories/${f.id}/sites/${s.id}/cameras/${c.id}/live`
          : `/dashboard`;
      list.push({
        kind: "camera",
        id: c.id,
        label: c.name,
        subtitle: `camera · ${f?.name ?? "?"} › ${s?.name ?? "?"}`,
        to,
      });
    }
    return list;
  }, [factories, sites, cameras]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries.slice(0, 50);
    return entries
      .map((e) => ({ e, score: score(e, q) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 50)
      .map((x) => x.e);
  }, [entries, query]);

  useEffect(() => {
    if (selected >= filtered.length) setSelected(0);
  }, [filtered.length, selected]);

  const onSelect = (entry: Entry) => {
    setOpen(false);
    navigate(entry.to);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((i) => Math.min(filtered.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[selected]) onSelect(filtered[selected]);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50" />
        <Dialog.Content
          className="
            fixed left-1/2 top-[18%] -translate-x-1/2 z-50
            w-[min(640px,92vw)]
            glass rounded-xl shadow-xl
            focus:outline-none overflow-hidden
          "
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Jump to factory, site, or camera…"
            className="
              w-full px-4 py-3 bg-transparent text-text
              border-0 border-b border-border
              outline-none
              placeholder:text-text-dim
              font-mono text-[14px]
            "
          />
          <div className="max-h-[50vh] overflow-y-auto">
            {filtered.length === 0 && (
              <div className="px-4 py-6 text-center text-text-dim text-[12px]">
                no matches
              </div>
            )}
            {filtered.map((e, idx) => (
              <button
                key={`${e.kind}-${e.id}`}
                onClick={() => onSelect(e)}
                onMouseEnter={() => setSelected(idx)}
                className={`
                  w-full text-left flex items-baseline gap-3 px-4 py-2
                  bg-transparent border-0 cursor-pointer
                  ${idx === selected ? "bg-panel-2" : ""}
                `}
                type="button"
              >
                <span
                  className={`
                    inline-block w-1.5 h-1.5 rounded-full
                    ${
                      e.kind === "camera"
                        ? "bg-accent"
                        : e.kind === "site"
                        ? "bg-tertiary"
                        : "bg-amber"
                    }
                  `}
                />
                <span className="text-text font-medium truncate">{e.label}</span>
                <span className="text-text-dim text-[11px] tracking-[0.12em] truncate ml-auto">
                  {e.subtitle}
                </span>
              </button>
            ))}
          </div>
          <div className="
            flex items-center gap-4 px-4 py-2 border-t border-border
            text-[10px] tracking-[0.16em] text-text-dim
          ">
            <span>↑↓ NAV</span>
            <span>↵ JUMP</span>
            <span>ESC CLOSE</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function score(e: Entry, q: string): number {
  const label = e.label.toLowerCase();
  const sub = e.subtitle.toLowerCase();
  if (label.startsWith(q)) return 100;
  if (label.includes(q)) return 60;
  if (sub.includes(q)) return 20;
  // Fuzzy: every char of q in label in order.
  let i = 0;
  for (const ch of label) {
    if (ch === q[i]) i++;
    if (i === q.length) return 10;
  }
  return 0;
}
