from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime.broadcaster import broadcaster

router = APIRouter()


@router.websocket("/events")
async def ws_events(ws: WebSocket) -> None:
    await broadcaster.connect(ws)
    try:
        while True:
            # We only push; ignore inbound text but consume to keep socket alive.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(ws)
