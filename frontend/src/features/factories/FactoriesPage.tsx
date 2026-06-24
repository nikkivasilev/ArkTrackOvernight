import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Factory } from "../../api/client";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Toolbar } from "../../ui/Toolbar";

export default function FactoriesPage() {
  const [factories, setFactories] = useState<Factory[]>([]);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setFactories(await api.listFactories());
  }, []);

  useEffect(() => {
    refresh().catch(console.error);
  }, [refresh]);

  const create = useCallback(async () => {
    setErr(null);
    try {
      await api.createFactory({ name, address: address || undefined });
      setName("");
      setAddress("");
      refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [name, address, refresh]);

  const remove = useCallback(
    async (id: string) => {
      await api.deleteFactory(id);
      refresh();
    },
    [refresh]
  );

  return (
    <>
      <Toolbar title="Factory Sites" subtitle="Manage and monitor industrial facilities globally." />

      <Panel title="NEW FACTORY" className="mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <input
            placeholder="Name (e.g. Acme Train Works)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ flex: "1 1 200px" }}
          />
          <input
            placeholder="Address (optional)"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            style={{ flex: "1 1 200px" }}
          />
          <Button tone="primary" size="sm" onClick={create} disabled={!name.trim()}>
            CREATE
          </Button>
        </div>
        {err && <div className="mt-2 text-danger text-[12px] font-mono">{err}</div>}
      </Panel>

      <div className="mb-2 font-mono text-label-caps uppercase text-text-dim">
        Factories · {factories.length}
      </div>
      {factories.length === 0 ? (
        <div className="text-text-dim text-[13px]">No factories yet. Add one above.</div>
      ) : (
        <div className="flex flex-col gap-2">
          {factories.map((f) => (
            <div
              key={f.id}
              className="group relative flex items-center gap-3 px-4 py-3 rounded-lg cursor-pointer bg-[var(--glass-bg)] backdrop-blur-xl shadow-[0_2px_8px_-2px_rgba(0,0,0,0.35)] hover:bg-surface-highest/40 transition-all duration-200 ease-in-out"
            >
              <Link
                to={`/factories/${f.id}`}
                aria-label={f.name}
                className="absolute inset-0 rounded-lg"
              />
              <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                <span className="font-display text-[15px] text-text font-semibold truncate">
                  {f.name}
                </span>
                <span className="text-accent text-[12px] font-mono truncate">
                  {f.address ?? "—"}
                </span>
              </div>
              <div className="relative z-10">
                <ConfirmDialog
                  title="DELETE FACTORY"
                  body={
                    <>
                      Delete <span className="font-medium text-text">{f.name}</span> and{" "}
                      <span className="text-danger">all</span> its sites, cameras, zones, rules,
                      and alerts? This cannot be undone.
                    </>
                  }
                  confirmLabel="DELETE"
                  onConfirm={() => remove(f.id)}
                  trigger={
                    <Button tone="danger" size="sm">DELETE</Button>
                  }
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
