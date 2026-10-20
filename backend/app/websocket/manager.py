
import json
import logging
from typing import Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, hvac_id: str):
        await websocket.accept()
        self.active_connections.setdefault(hvac_id, []).append(websocket)
        logger.info(
            "WebSocket connected: hvac_id=%s, clients=%d",
            hvac_id,
            len(self.active_connections[hvac_id]),
        )

    def disconnect(self, websocket: WebSocket, hvac_id: str):
        connections = self.active_connections.get(hvac_id, [])

        if websocket in connections:
            connections.remove(websocket)

        if not connections and hvac_id in self.active_connections:
            del self.active_connections[hvac_id]

        logger.info(
            "WebSocket disconnected: hvac_id=%s, remaining_clients=%d",
            hvac_id,
            len(self.active_connections.get(hvac_id, [])),
        )

    async def broadcast_to_hvac(
        self,
        hvac_id: str,
        event_type: str,
        payload: dict,
    ):
        connections = list(self.active_connections.get(hvac_id, []))

        logger.info(
            "Broadcasting %s to %s; connected_clients=%d",
            event_type,
            hvac_id,
            len(connections),
        )

        message = json.dumps(
            {
                "event": event_type,
                "hvac_id": hvac_id,
                "data": payload,
            },
            default=str,
        )

        dead = []

        for connection in connections:
            try:
                await connection.send_text(message)
                logger.debug(
                    "WebSocket message sent: event=%s, hvac_id=%s",
                    event_type,
                    hvac_id,
                )
            except Exception:
                logger.exception(
                    "WebSocket send failed: event=%s, hvac_id=%s",
                    event_type,
                    hvac_id,
                )
                dead.append(connection)

        for connection in dead:
            self.disconnect(connection, hvac_id)


manager = ConnectionManager()
