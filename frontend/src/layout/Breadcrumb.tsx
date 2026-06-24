import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";

type Cache = {
  factories: Record<string, string>;
  sites: Record<string, string>;
  cameras: Record<string, string>;
};

const cache: Cache = { factories: {}, sites: {}, cameras: {} };

export default function Breadcrumb() {
  const { fid, sid, cid } = useParams();
  const [, force] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const tasks: Promise<unknown>[] = [];
    if (fid && !cache.factories[fid]) {
      tasks.push(
        api
          .getFactory(fid)
          .then((f) => {
            cache.factories[fid] = f.name;
          })
          .catch(() => {})
      );
    }
    if (sid && !cache.sites[sid]) {
      tasks.push(
        api
          .getSite(sid)
          .then((s) => {
            cache.sites[sid] = s.name;
          })
          .catch(() => {})
      );
    }
    if (cid && !cache.cameras[cid]) {
      tasks.push(
        api
          .getCamera(cid)
          .then((c) => {
            cache.cameras[cid] = c.name;
          })
          .catch(() => {})
      );
    }
    if (tasks.length > 0) {
      Promise.all(tasks).then(() => {
        if (!cancelled) force((n) => n + 1);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [fid, sid, cid]);

  if (!fid) return <div className="flex-1" />;

  return (
    <div className="flex items-center text-[12px] text-text-dim gap-1.5 min-w-0 mb-3">
      <Crumb
        to={`/factories/${fid}`}
        label={cache.factories[fid] ?? "…"}
        active={!sid}
      />
      {sid && (
        <>
          <Sep />
          <Crumb
            to={`/factories/${fid}/sites/${sid}`}
            label={cache.sites[sid] ?? "…"}
            active={!cid}
          />
        </>
      )}
      {sid && cid && (
        <>
          <Sep />
          <Crumb
            to={`/factories/${fid}/sites/${sid}/cameras/${cid}`}
            label={cache.cameras[cid] ?? "…"}
            active
          />
        </>
      )}
    </div>
  );
}

function Crumb({ to, label, active }: { to: string; label: string; active: boolean }) {
  return (
    <Link
      to={to}
      className={`
        no-underline truncate max-w-[28ch]
        ${active ? "text-text" : "text-text-dim hover:text-text"}
      `}
    >
      {label}
    </Link>
  );
}

function Sep() {
  return <span className="text-text-dim/60 px-0.5">›</span>;
}
