import json
from typing import Dict, List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, hvac_id: str):
        await websocket.accept()
        self.active_connections.setdefault(hvac_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, hvac_id: str):
        connections = self.active_connections.get(hvac_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and hvac_id in self.active_connections:
            del self.active_connections[hvac_id]

    async def broadcast_to_hvac(self, hvac_id: str, event_type: str, payload: dict):
        connections = self.active_connections.get(hvac_id, [])
        message = json.dumps({"event": event_type, "hvac_id": hvac_id, "data": payload}, default=str)
        dead = []
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d, hvac_id)


manager = ConnectionManager()
