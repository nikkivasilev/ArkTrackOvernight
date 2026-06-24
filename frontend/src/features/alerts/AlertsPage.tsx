import { useMemo, useState } from "react";
import { useApp } from "../../state/AppContext";
import AlertCard from "./AlertCard";
import { Toolbar } from "../../ui/Toolbar";
import { Button } from "../../ui/Button";
import { Panel } from "../../ui/Panel";

type Filter = "all" | "unacked";

export default function AlertsPage() {
  const { alerts } = useApp();
  const [filter, setFilter] = useState<Filter>("all");

  const list = useMemo(
    () => (filter === "unacked" ? alerts.filter((a) => !a.acknowledged) : alerts),
    [alerts, filter]
  );

  const unackedCount = useMemo(() => alerts.filter((a) => !a.acknowledged).length, [alerts]);

  return (
    <>
      <Toolbar
        title="System Alerts"
        subtitle={`${list.length} shown · ${unackedCount} unacked`}
      >
        <Button
          tone={filter === "all" ? "primary" : "outline"}
          size="sm"
          onClick={() => setFilter("all")}
        >
          ALL
        </Button>
        <Button
          tone={filter === "unacked" ? "primary" : "outline"}
          size="sm"
          onClick={() => setFilter("unacked")}
        >
          UNACKED
        </Button>
      </Toolbar>
      {list.length === 0 ? (
        <Panel>
          <div className="text-text-dim text-[13px]">No alerts yet.</div>
        </Panel>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
          {list.map((a) => (
            <AlertCard key={a.id} alert={a} />
          ))}
        </div>
      )}
    </>
  );
}
