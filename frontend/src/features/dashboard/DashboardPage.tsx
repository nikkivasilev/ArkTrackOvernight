import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Camera, Factory, Site } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { Toolbar } from "../../ui/Toolbar";
import { Button } from "../../ui/Button";
import { Pill, PillTone } from "../../ui/Pill";
import { DataCard } from "../../ui/DataCard";
import { StatReadout } from "../../ui/StatReadout";
import { Panel } from "../../ui/Panel";
import { Icon } from "../../ui/Icon";
import WorkforceOverview from "./WorkforceOverview";

type Filter = "all" | "running";

export default function DashboardPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [factories, setFactories] = useState<Factory[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const { cameraStatusOverrides } = useApp();

  const refresh = async () => {
    const [fs, cs] = await Promise.all([api.listFactories(), api.listAllCameras()]);
    setFactories(fs);
    setCameras(cs);
    const siteLists = await Promise.all(fs.map((f) => api.listSitesForFactory(f.id)));
    setSites(siteLists.flat());
  };

  useEffect(() => {
    refresh().catch(console.error);
  }, []);

  const siteById = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);
  const factoryById = useMemo(() => new Map(factories.map((f) => [f.id, f])), [factories]);

  const merged = useMemo(
    () =>
      cameras.map((c) => {
        const override = cameraStatusOverrides[c.id];
        return {
          ...c,
          status: (override?.status ?? c.status) as Camera["status"],
          error: override?.error ?? c.error,
        };
      }),
    [cameras, cameraStatusOverrides]
  );

  const runningCount = useMemo(() => merged.filter((c) => c.status === "running").length, [merged]);
  const failedCount = useMemo(() => merged.filter((c) => c.status === "failed").length, [merged]);
  const tiles = useMemo(
    () => (filter === "running" ? merged.filter((c) => c.status === "running") : merged),
    [merged, filter]
  );

  if (cameras.length === 0) {
    return (
      <>
        <Toolbar title="Dashboard" subtitle="Active feeds across your factory sectors. System status nominal." />
        <Panel className="bg-hero-mesh">
          <div className="text-text-dim text-[14px]">
            No cameras yet. Go to{" "}
            <Link to="/factories" className="text-accent no-underline hover:underline">
              Factories
            </Link>{" "}
            to create a factory, site, and upload a camera.
          </div>
        </Panel>
      </>
    );
  }

  return (
    <>
      <Toolbar title="Dashboard" subtitle="Active feeds across your factory sectors. System status nominal.">
        <Button
          tone={filter === "all" ? "primary" : "outline"}
          size="sm"
          onClick={() => setFilter("all")}
        >
          ALL
        </Button>
        <Button
          tone={filter === "running" ? "primary" : "outline"}
          size="sm"
          onClick={() => setFilter("running")}
        >
          RUNNING
        </Button>
        <Button tone="ghost" size="sm" onClick={refresh}>
          <Icon name="refresh" size={16} /> REFRESH
        </Button>
      </Toolbar>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3 mb-6">
        <StatReadout label="Cameras" value={merged.length} tone="neutral" size="md" />
        <StatReadout label="Running" value={runningCount} tone="ok" size="md" />
        <StatReadout label="Failed" value={failedCount} tone={failedCount > 0 ? "danger" : "neutral"} size="md" />
        <StatReadout label="Sites" value={sites.length} tone="neutral" size="md" />
        <StatReadout label="Factories" value={factories.length} tone="neutral" size="md" />
      </div>

      <WorkforceOverview cameras={merged} />

      <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4 mt-6">
        {tiles.map((c) => {
          const site = siteById.get(c.site_id);
          const factory = site ? factoryById.get(site.factory_id) : undefined;
          const camLink =
            site && factory
              ? `/factories/${factory.id}/sites/${site.id}/cameras/${c.id}`
              : `#`;
          const tone = pillTone(c.status);
          const side = sideTone(c.status);
          return (
            <DataCard
              key={c.id}
              to={camLink}
              accentSide={side}
              live={c.status === "running"}
              feedId={`CAM-${c.id.slice(0, 4).toUpperCase()}`}
              badge={<Pill tone={tone} dot>{c.status}</Pill>}
              thumb={
                c.status === "running" ? (
                  <img src={api.liveUrl(c.id)} alt={c.name} />
                ) : (
                  <span className="text-text-mute text-[11px] tracking-[0.14em] uppercase flex items-center gap-1.5">
                    <Icon name="videocam_off" size={16} /> {c.status}
                  </span>
                )
              }
              title={c.name}
              meta={
                <span>
                  {factory?.name ?? "—"} <span className="text-text-mute">›</span>{" "}
                  {site?.name ?? "—"}
                </span>
              }
            />
          );
        })}
      </div>
    </>
  );
}

function pillTone(s: Camera["status"]): PillTone {
  switch (s) {
    case "running":
      return "ok";
    case "failed":
      return "danger";
    case "cancelled":
      return "warn";
    case "completed":
      return "info";
    default:
      return "neutral";
  }
}

function sideTone(s: Camera["status"]): "ok" | "warn" | "danger" | "info" | "neutral" {
  switch (s) {
    case "running":
      return "ok";
    case "failed":
      return "danger";
    case "cancelled":
      return "warn";
    case "completed":
      return "info";
    default:
      return "neutral";
  }
}
