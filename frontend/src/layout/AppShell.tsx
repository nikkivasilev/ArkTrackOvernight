import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { useApp } from "../state/AppContext";
import NavTree from "./NavTree";
import CommandPalette from "./CommandPalette";
import BottomNav from "./BottomNav";
import { Icon } from "../ui/Icon";
import Breadcrumb from "./Breadcrumb";

function openPalette() {
  // CommandPalette listens for Cmd/Ctrl-K globally; reuse it for the search box.
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, ctrlKey: true }));
}

export default function AppShell() {
  const { wsConnected } = useApp();

  // Desktop (≥900px) sidebar collapse — persisted. Below 900px the grid stays
  // an icon-rail / bottom-nav regardless, so this only affects the wide layout.
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem("sidebar.collapsed") === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("sidebar.collapsed", collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  return (
    <div className="relative h-screen overflow-hidden bg-bg text-text">
      {/* Fixed ambient background */}
      <div className="pointer-events-none fixed inset-0 z-0">
        <div className="absolute inset-0 tech-grid" />
        <div className="absolute inset-0 app-glow-a" />
        <div className="absolute inset-0 app-glow-b" />
      </div>

      {/* Header — fixed glass overlay; content scrolls under it for the blur */}
      <header className="fixed top-0 inset-x-0 z-30 h-[52px] flex items-center gap-3 px-3 md:px-4 glass">
          {/* Sidebar collapse toggle (desktop only) */}
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="hidden min-[900px]:flex size-9 items-center justify-center rounded-lg text-text-dim hover:text-text hover:bg-surface-high/50 transition-colors"
          >
            <Icon name={collapsed ? "left_panel_open" : "left_panel_close"} size={20} />
          </button>
          <Link
            to="/"
            className="flex items-center gap-2 pr-3 md:pr-4 h-full no-underline"
          >
            <span className="flex-none size-7 rounded-lg bg-accent-15 text-accent flex items-center justify-center">
              <Icon name="radar" size={18} />
            </span>
            <span className="hidden md:block font-display font-bold tracking-tight text-accent text-[18px]">
              ArkTrack
            </span>
          </Link>

        <div className="flex justify-center w-full mx-auto">
          {/* Search → command palette */}
          <button
            type="button"
            onClick={openPalette}
            className="
              hidden sm:flex items-center gap-2 h-9 px-3 min-w-[200px] max-w-[360px] flex-1
              rounded-lg border border-input bg-surface-low/60
              text-text-dim hover:text-text hover:border-accent-40 transition-colors
              font-sans text-[13px]
            "
          >
            <Icon name="search" size={18} />
            <span>Search operations…</span>
          </button>
        </div>
          <div className="ml-auto flex items-center gap-2 md:gap-3">
            <span
              className={`
                inline-flex items-center gap-1.5 font-mono text-[11px] tracking-[0.16em] uppercase
                ${wsConnected ? "text-accent" : "text-danger"}
              `}
            >
              <span className="relative flex size-2">
                {wsConnected && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
                )}
                <span
                  className={`relative inline-flex rounded-full size-2 ${
                    wsConnected ? "bg-accent" : "bg-danger"
                  }`}
                />
              </span>
              <span className="hidden sm:inline">{wsConnected ? "LIVE" : "OFFLINE"}</span>
            </span>
          </div>
      </header>

      <div
        className={`
          relative z-10 grid h-screen
          grid-cols-[minmax(0,1fr)]
          min-[600px]:grid-cols-[60px_minmax(0,1fr)]
          ${collapsed
            ? "min-[900px]:grid-cols-[60px_minmax(0,1fr)]"
            : "min-[900px]:grid-cols-[240px_minmax(0,1fr)]"}
          transition-[grid-template-columns] duration-200 ease-in-out
        `}
      >
        {/* Sidebar — glass (hidden below 600px; icon-rail 600–900; full ≥900 unless collapsed) */}
        <aside className="col-start-1 hidden min-[600px]:flex glass overflow-y-auto flex-col relative z-10 pt-[52px]">
          <NavTree collapsed={collapsed} />
        </aside>

        {/* Main content — scrolls under the fixed header */}
        <main className="col-start-1 min-[600px]:col-start-2 min-w-0 overflow-auto pt-[52px] pb-20 min-[600px]:pb-0">
          <div className="mx-auto max-w-[1600px] px-5 py-8 md:px-10 xl:px-12">

            <Breadcrumb/>
            <Outlet />
          </div>
        </main>
      </div>

      <BottomNav />
      <CommandPalette />
    </div>
  );
}
