
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.websocket.manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/hvac/{hvac_id}")
async def hvac_live_updates(websocket: WebSocket, hvac_id: str):
    print(f"WS ROUTE HIT: hvac_id={hvac_id}", flush=True)

    await manager.connect(websocket, hvac_id)

    print(
        f"WS REGISTERED: hvac_id={hvac_id}, "
        f"clients={len(manager.active_connections.get(hvac_id, []))}",
        flush=True,
    )

    try:
        while True:
            try:
                # Wait up to 20 s for a client message; if none arrives, send a ping
                # to keep the TCP connection alive (prevents silent proxy timeouts).
                await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
            except asyncio.TimeoutError:
                # No message from client — send a lightweight ping to keep alive
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break  # client gone
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, hvac_id)
        print(f"WS DISCONNECTED: hvac_id={hvac_id}", flush=True)
