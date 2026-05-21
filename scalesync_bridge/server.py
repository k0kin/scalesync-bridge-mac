from __future__ import annotations
import asyncio
import json
import logging
import socket
import sys
from websockets.asyncio.server import serve, ServerConnection
from scalesync_bridge.scale_manager import ScaleManager
from scalesync_bridge.config import BridgeConfig

logger = logging.getLogger(__name__)


def _create_server_socket(host: str, port: int) -> socket.socket:
    """Create a server socket with proper options for the platform.

    On Windows, SO_REUSEADDR is dangerous (allows duplicate binds).
    Instead we use SO_EXCLUSIVEADDRUSE to prevent port hijacking,
    and rely on proper cleanup + stale-process killing in the batch file.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        # SO_EXCLUSIVEADDRUSE prevents another process from binding
        # while still allowing rebind after proper close
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen()
    sock.setblocking(False)
    return sock


class BridgeServer:
    def __init__(self, scale_manager: ScaleManager, config: BridgeConfig | None = None):
        self.scale_manager = scale_manager
        self.config = config or BridgeConfig()
        self.clients: set[ServerConnection] = set()

    async def handler(self, websocket: ServerConnection) -> None:
        self.clients.add(websocket)
        logger.info(f"Client connected ({len(self.clients)} total)")

        # Send current status
        await websocket.send(self.scale_manager.status_json())

        try:
            send_task = asyncio.create_task(self._send_readings(websocket))
            recv_task = asyncio.create_task(self._receive_commands(websocket))
            done, pending = await asyncio.wait(
                [send_task, recv_task], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
        finally:
            self.clients.discard(websocket)
            logger.info(f"Client disconnected ({len(self.clients)} total)")

    async def _send_readings(self, websocket: ServerConnection) -> None:
        async for reading in self.scale_manager.stream():
            scale_info = self.scale_manager.scale_info
            msg = json.dumps({
                "type": "weight",
                "weight_g": reading.weight_g,
                "stable": reading.stable,
                "unit": reading.unit,
                "overload": reading.overload,
                "piece_weight_g": reading.piece_weight_g,
                "piece_count": reading.piece_count,
                "scale": scale_info.to_dict() if scale_info else None,
            })
            await websocket.send(msg)

    async def _receive_commands(self, websocket: ServerConnection) -> None:
        async for message in websocket:
            try:
                cmd = json.loads(message)
                cmd_type = cmd.get("type")
                if cmd_type == "tare":
                    await self.scale_manager.tare()
                elif cmd_type == "zero":
                    await self.scale_manager.zero()
                elif cmd_type == "identify":
                    await websocket.send(self.scale_manager.status_json())
            except json.JSONDecodeError:
                logger.warning(f"Invalid message: {message}")

    async def start(self, shutdown_event: asyncio.Event | None = None) -> None:
        logger.info(f"Bridge server starting on ws://{self.config.host}:{self.config.port}")

        # Pre-create the socket with correct platform options
        sock = _create_server_socket(self.config.host, self.config.port)

        try:
            async with serve(self.handler, sock=sock) as ws_server:
                if shutdown_event:
                    await shutdown_event.wait()
                    logger.info("Shutting down WebSocket server...")
                    ws_server.close()
                    await ws_server.wait_closed()
                else:
                    await asyncio.Future()
        finally:
            # Ensure the socket is closed even if serve() fails
            try:
                sock.close()
            except Exception:
                pass
