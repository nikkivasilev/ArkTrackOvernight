import { useEffect, useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { api, Camera, Factory, Site } from "../api/client";
import { Icon } from "../ui/Icon";

const EXPAND_KEY = "navtree.expanded";

function loadExpanded(): Set<string> {
  try {
    const raw = localStorage.getItem(EXPAND_KEY);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw) as string[]);
  } catch {
    return new Set();
  }
}

function saveExpanded(s: Set<string>) {
  localStorage.setItem(EXPAND_KEY, JSON.stringify([...s]));
}

export default function NavTree({ collapsed = false }: { collapsed?: boolean }) {
  const params = useParams();
  // When collapsed, the expanded sections hide at every width (icon-only);
  // otherwise they appear at ≥900px.
  const labelVis = collapsed ? "hidden" : "hidden min-[900px]:block";
  const footerVis = collapsed ? "hidden" : "hidden min-[900px]:flex";
  const [factories, setFactories] = useState<Factory[]>([]);
  const [sitesByFactory, setSitesByFactory] = useState<Record<string, Site[]>>({});
  const [camerasBySite, setCamerasBySite] = useState<Record<string, Camera[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(() => loadExpanded());

  useEffect(() => {
    api.listFactories().then(setFactories).catch(console.error);
  }, []);

  useEffect(() => {
    if (!params.fid) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      next.add(`f:${params.fid}`);
      if (params.sid) next.add(`s:${params.sid}`);
      saveExpanded(next);
      return next;
    });
  }, [params.fid, params.sid]);

  useEffect(() => {
    for (const key of expanded) {
      if (!key.startsWith("f:")) continue;
      const fid = key.slice(2);
      if (sitesByFactory[fid]) continue;
      api
        .listSitesForFactory(fid)
        .then((sites) => setSitesByFactory((m) => ({ ...m, [fid]: sites })))
        .catch(console.error);
    }
  }, [expanded, sitesByFactory]);

  useEffect(() => {
    for (const key of expanded) {
      if (!key.startsWith("s:")) continue;
      const sid = key.slice(2);
      if (camerasBySite[sid]) continue;
      api
        .listCamerasForSite(sid)
        .then((cams) => setCamerasBySite((m) => ({ ...m, [sid]: cams })))
        .catch(console.error);
    }
  }, [expanded, camerasBySite]);

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      saveExpanded(next);
      return next;
    });
  };

  return (
    <nav className="flex flex-col flex-1 py-3">
      {/* Sidebar header */}
      <div className={`px-3 pb-3 mb-1 ${labelVis}`}>
        <div className="font-display text-[15px] font-semibold tracking-tight text-text">
          ArkTrack
        </div>
        <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-mute">
          Sidebar
        </div>
      </div>

      {/* Top-level nav */}
      <div className="px-2 flex flex-col gap-0.5">
        <NavItem to="/dashboard" icon="dashboard" label="Dashboard" collapsed={collapsed} />
        <NavItem to="/factories" icon="factory" label="Factory Sites" collapsed={collapsed} />
      </div>

      {/* Factory tree */}
      <div className={`mt-3 px-2 ${labelVis}`}>
        <div className="px-2.5 pb-1 font-mono text-[10px] uppercase tracking-[0.16em] text-text-mute">
          Explorer
        </div>
      </div>
      <ul className={`flex-1 px-1 ${labelVis}`}>
        {factories.map((f) => {
          const fk = `f:${f.id}`;
          const open = expanded.has(fk);
          const sites = sitesByFactory[f.id] ?? [];
          return (
            <li key={f.id}>
              <Row
                indent={0}
                onChevron={() => toggle(fk)}
                open={open}
                active={params.fid === f.id && !params.sid}
              >
                <Link to={`/factories/${f.id}`} className="truncate no-underline text-inherit">
                  {f.name}
                </Link>
              </Row>
              {open && (
                <ul>
                  {sites.length === 0 && (
                    <li className="pl-9 py-1 text-text-mute text-[11px] italic">no sites</li>
                  )}
                  {sites.map((s) => {
                    const sk = `s:${s.id}`;
                    const sopen = expanded.has(sk);
                    const cams = camerasBySite[s.id] ?? [];
                    return (
                      <li key={s.id}>
                        <Row
                          indent={1}
                          onChevron={() => toggle(sk)}
                          open={sopen}
                          active={params.sid === s.id && !params.cid}
                        >
                          <Link
                            to={`/factories/${f.id}/sites/${s.id}`}
                            className="truncate no-underline text-inherit"
                          >
                            {s.name}
                          </Link>
                        </Row>
                        {sopen && (
                          <ul>
                            {cams.length === 0 && (
                              <li className="pl-[52px] py-1 text-text-mute text-[11px] italic">
                                no cameras
                              </li>
                            )}
                            {cams.map((c) => {
                              const status = c.status;
                              return (
                                <li key={c.id}>
                                  <CameraRow
                                    name={c.name}
                                    status={status}
                                    to={`/factories/${f.id}/sites/${s.id}/cameras/${c.id}`}
                                    active={params.cid === c.id}
                                  />
                                </li>
                              );
                            })}
                          </ul>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      {/* Footer */}
      <div className={`mt-auto items-center gap-2 px-4 pt-3 pb-2 border-t border-border ${footerVis}`}>
        <div className="relative flex size-1.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
          <span className="relative inline-flex rounded-full size-1.5 bg-accent" />
        </div>
        <span className="font-mono text-[10px] text-text-mute tracking-[0.14em] uppercase">
          // sys · v0.1
        </span>
      </div>
    </nav>
  );
}

function NavItem({
  to,
  icon,
  label,
  collapsed = false,
}: {
  to: string;
  icon: string;
  label: string;
  collapsed?: boolean;
}) {
  const justify = collapsed ? "justify-center" : "justify-center min-[900px]:justify-start";
  const labelVis = collapsed ? "hidden" : "hidden min-[900px]:block";
  return (
    <NavLink
      to={to}
      end
      title={label}
      className={({ isActive }) =>
        `
          relative flex items-center ${justify} gap-3 px-2.5 py-2 rounded-lg no-underline
          font-sans text-[14px] font-medium transition-colors duration-150
          ${
            isActive
              ? "bg-accent-15 text-text " +
                "before:absolute before:-left-2 before:top-1/2 before:h-5 before:w-[3px] " +
                "before:-translate-y-1/2 before:rounded-r-full before:bg-accent"
              : "text-text-dim hover:bg-surface-high/40 hover:text-text"
          }
        `
      }
    >
      {({ isActive }) => (
        <>
          <Icon name={icon} size={20} filled={isActive} className="flex-none" />
          <span className={`${labelVis} truncate`}>{label}</span>
        </>
      )}
    </NavLink>
  );
}

function Row({
  indent,
  onChevron,
  open,
  active,
  children,
}: {
  indent: number;
  onChevron: () => void;
  open: boolean;
  active: boolean;
  children: React.ReactNode;
}) {
  const padLeft = 10 + indent * 16;
  return (
    <div
      className={`
        flex items-center gap-1 py-1 pr-2 cursor-default text-[13px] rounded-md
        ${active
          ? "bg-surface-high/50 text-text"
          : "text-text-dim hover:bg-surface-high/30 hover:text-text"}
      `}
      style={{ paddingLeft: padLeft }}
    >
      <button
        onClick={onChevron}
        className="inline-flex items-center justify-center size-5 text-text-mute hover:text-text bg-transparent border-0 p-0 cursor-pointer"
        type="button"
      >
        <Icon name={open ? "expand_more" : "chevron_right"} size={18} />
      </button>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}

function CameraRow({
  name,
  status,
  to,
  active,
}: {
  name: string;
  status: Camera["status"];
  to: string;
  active: boolean;
}) {
  return (
    <NavLink
      to={to}
      className={`
        flex items-center gap-2 py-1 pr-2 pl-[52px] no-underline truncate
        text-[13px] rounded-md transition-colors
        ${active ? "bg-accent-15 text-text" : "text-text-dim hover:bg-surface-high/30 hover:text-text"}
      `}
    >
      <StatusDot status={status} />
      <span className="truncate flex-1">{name}</span>
    </NavLink>
  );
}

function StatusDot({ status }: { status: Camera["status"] }) {
  const color =
    status === "running"   ? "bg-accent" :
    status === "failed"    ? "bg-danger" :
    status === "cancelled" ? "bg-amber" :
                             "bg-text-mute";
  return <span className={`block size-1.5 rounded-full flex-none ${color}`} />;
}
