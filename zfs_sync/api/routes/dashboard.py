import asyncio
import json
from datetime import datetime
from typing import Set

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pathlib import Path

router = APIRouter()


class SSEConnection:
    """Represents a single SSE connection."""

    def __init__(self):
        self.queue = asyncio.Queue()
        self.closed = False

    async def send(self, event: str, data: dict):
        """Send an event to this connection."""
        if not self.closed:
            message = json.dumps({"event": event, "data": data, "timestamp": datetime.utcnow().isoformat()})
            await self.queue.put(f"event: {event}\ndata: {message}\n\n")

    async def close(self):
        """Close this connection."""
        self.closed = True
        await self.queue.put(None)  # Signal to stop


class Broadcaster:
    """Manages SSE connections and broadcasts events to all connected clients."""

    def __init__(self):
        self.connections: Set[SSEConnection] = set()

    async def connect(self) -> SSEConnection:
        """Create a new SSE connection."""
        connection = SSEConnection()
        self.connections.add(connection)
        return connection

    async def disconnect(self, connection: SSEConnection):
        """Remove an SSE connection."""
        if connection in self.connections:
            self.connections.remove(connection)
            await connection.close()

    async def broadcast(self, event: str, data: dict):
        """Broadcast an event to all connected clients."""
        if not self.connections:
            return
        # Send to all connections concurrently
        await asyncio.gather(
            *[conn.send(event, data) for conn in self.connections.copy()], return_exceptions=True
        )
        # Remove any closed connections
        self.connections = {conn for conn in self.connections if not conn.closed}


broadcaster = Broadcaster()


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Serves the main dashboard HTML file."""
    dashboard_path = Path(__file__).parent.parent.parent / "static/dashboard/index.html"
    with open(dashboard_path, "r") as f:
        return HTMLResponse(content=f.read())


@router.get("/api/v1/dashboard/events")
async def dashboard_events(request: Request):
    """SSE endpoint for real-time dashboard updates."""

    async def event_generator():
        connection = await broadcaster.connect()
        try:
            # Send initial connection message
            await connection.send("connected", {"message": "SSE connection established"})

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Wait for next message (with timeout to check disconnection)
                try:
                    message = await asyncio.wait_for(connection.queue.get(), timeout=1.0)
                    if message is None:  # Connection closed signal
                        break
                    yield message
                except asyncio.TimeoutError:
                    # Send keepalive comment to prevent connection timeout
                    yield ": keepalive\n\n"
                    continue
        finally:
            await broadcaster.disconnect(connection)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering in nginx
        },
    )


# Function to broadcast events from other parts of the application
async def broadcast_event(event: str, data: dict):
    """Broadcast an event to all connected SSE clients."""
    await broadcaster.broadcast(event, data)
