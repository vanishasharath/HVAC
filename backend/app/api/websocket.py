
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
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, hvac_id)
        print(f"WS DISCONNECTED: hvac_id={hvac_id}", flush=True)
