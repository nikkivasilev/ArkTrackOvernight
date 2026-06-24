import { useEffect, useRef, useState } from "react";
import { useEventsWS, type CameraStateData, type WsMessage } from "./useEventsWS";

/**
 * Subscribe to the global WS stream and surface only `state` messages
 * matching a single camera. Rate-limits React renders to ~10 Hz even if
 * the backend pushes faster, so the dashboard stays responsive while
 * keeping the underlying messages fresh enough for tracking visuals.
 */
export function useCameraState(cameraId: string | undefined) {
  const [state, setState] = useState<CameraStateData | null>(null);
  const latestRef = useRef<CameraStateData | null>(null);
  const pendingRef = useRef(false);

  const flush = () => {
    pendingRef.current = false;
    if (latestRef.current) setState(latestRef.current);
  };

  const { connected } = useEventsWS((m: WsMessage) => {
    if (!cameraId || m.type !== "state") return;
    if (m.data.camera_id !== cameraId) return;
    latestRef.current = m.data;
    if (!pendingRef.current) {
      pendingRef.current = true;
      // Coalesce bursts: at most one render per animation frame (~60 Hz cap).
      requestAnimationFrame(flush);
    }
  });

  useEffect(() => {
    setState(null);
    latestRef.current = null;
  }, [cameraId]);

  return { state, wsConnected: connected };
}
