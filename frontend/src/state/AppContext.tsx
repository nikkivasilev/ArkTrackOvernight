import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Alert, Camera, api } from "../api/client";
import { useEventsWS, WsMessage } from "../hooks/useEventsWS";

type AppContextValue = {
  alerts: Alert[];
  unackCount: number;
  cameraStatusOverrides: Record<string, Pick<Camera, "status" | "error">>;
  wsConnected: boolean;
  refreshAlerts: () => Promise<void>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [cameraStatusOverrides, setCameraStatusOverrides] = useState<
    Record<string, Pick<Camera, "status" | "error">>
  >({});

  const refreshAlerts = useCallback(async () => {
    const list = await api.listAlerts({ limit: 200 });
    setAlerts(list);
  }, []);

  useEffect(() => {
    refreshAlerts().catch(console.error);
  }, [refreshAlerts]);

  const handle = useCallback((msg: WsMessage) => {
    if (msg.type === "alert.created") {
      const row = msg.data as Alert;
      setAlerts((prev) => [row, ...prev].slice(0, 500));
    } else if (msg.type === "alert.acknowledged") {
      const { id, acknowledged_at } = msg.data;
      setAlerts((prev) =>
        prev.map((a) => (a.id === id ? { ...a, acknowledged: true, acknowledged_at } : a))
      );
    } else if (msg.type === "alert.resolved") {
      const { id, end_timestamp_in_video } = msg.data;
      setAlerts((prev) =>
        prev.map((a) => (a.id === id ? { ...a, end_timestamp_in_video } : a))
      );
    } else if (msg.type === "alert.deleted") {
      const { id } = msg.data;
      setAlerts((prev) => prev.filter((a) => a.id !== id));
    } else if (msg.type === "camera.updated") {
      const { id, status, error } = msg.data;
      setCameraStatusOverrides((prev) => ({
        ...prev,
        [id]: { status: status as Camera["status"], error: error ?? null },
      }));
    }
  }, []);

  const { connected } = useEventsWS(handle);

  const unackCount = useMemo(() => alerts.filter((a) => !a.acknowledged).length, [alerts]);

  const value: AppContextValue = useMemo(
    () => ({ alerts, unackCount, cameraStatusOverrides, wsConnected: connected, refreshAlerts }),
    [alerts, unackCount, cameraStatusOverrides, connected, refreshAlerts]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const v = useContext(AppContext);
  if (!v) throw new Error("useApp must be used within AppProvider");
  return v;
}
