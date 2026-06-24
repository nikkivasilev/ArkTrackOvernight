import { createContext, useContext } from "react";
import { Camera } from "../../api/client";

type CameraContextValue = {
  camera: Camera;
  refresh: () => Promise<void>;
};

export const CameraCtx = createContext<CameraContextValue | null>(null);

export function useCameraCtx(): CameraContextValue {
  const v = useContext(CameraCtx);
  if (!v) throw new Error("useCameraCtx must be used inside CameraPage");
  return v;
}
