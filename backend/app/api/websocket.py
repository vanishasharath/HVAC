from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/hvac/{hvac_id}")
async def hvac_live_updates(websocket: WebSocket, hvac_id: str):
    await manager.connect(websocket, hvac_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, hvac_id)
