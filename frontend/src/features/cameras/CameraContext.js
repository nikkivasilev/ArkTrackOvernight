import { createContext, useContext } from "react";
export const CameraCtx = createContext(null);
export function useCameraCtx() {
    const v = useContext(CameraCtx);
    if (!v)
        throw new Error("useCameraCtx must be used inside CameraPage");
    return v;
}
