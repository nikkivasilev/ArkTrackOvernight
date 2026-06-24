import { useEffect, useRef, useState } from "react";
export function useEventsWS(onMessage) {
    const [connected, setConnected] = useState(false);
    const handlerRef = useRef(onMessage);
    handlerRef.current = onMessage;
    useEffect(() => {
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${proto}//${window.location.host}/api/ws/events`;
        let ws = null;
        let timer = null;
        let closed = false;
        const connect = () => {
            ws = new WebSocket(url);
            ws.onopen = () => setConnected(true);
            ws.onclose = () => {
                setConnected(false);
                if (!closed)
                    timer = setTimeout(connect, 1500);
            };
            ws.onerror = () => ws?.close();
            ws.onmessage = (ev) => {
                try {
                    handlerRef.current(JSON.parse(ev.data));
                }
                catch { }
            };
        };
        connect();
        return () => {
            closed = true;
            if (timer)
                clearTimeout(timer);
            ws?.close();
        };
    }, []);
    return { connected };
}
