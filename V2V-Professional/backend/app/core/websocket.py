from fastapi import WebSocket
from typing import Dict
import json
import asyncio


class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, project_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[project_id] = websocket

    def disconnect(self, project_id: str):
        if project_id in self.active_connections:
            del self.active_connections[project_id]

    async def send_progress(
        self, project_id: str, progress: float, message: str, stage: str = "processing"
    ):
        if project_id in self.active_connections:
            await self.active_connections[project_id].send_json(
                {
                    "type": "progress",
                    "progress": progress,
                    "message": message,
                    "stage": stage,
                }
            )

    async def send_log(self, project_id: str, message: str, level: str = "info"):
        if project_id in self.active_connections:
            await self.active_connections[project_id].send_json(
                {"type": "log", "message": message, "level": level}
            )

    async def send_error(self, project_id: str, error: str):
        if project_id in self.active_connections:
            await self.active_connections[project_id].send_json(
                {"type": "error", "message": error}
            )

    async def send_complete(self, project_id: str, output_path: str):
        if project_id in self.active_connections:
            await self.active_connections[project_id].send_json(
                {"type": "complete", "output_path": output_path}
            )

    async def broadcast(self, project_id: str, data: dict):
        if project_id in self.active_connections:
            await self.active_connections[project_id].send_json(data)


ws_manager = WebSocketManager()
