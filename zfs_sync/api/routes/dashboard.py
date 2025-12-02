import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pathlib import Path

router = APIRouter()

# In a real application, this would be a more robust pub/sub system
# like Redis, but for this example, we'll use a simple in-memory queue.
class Broadcaster:
    def __init__(self):
        self.connections = set()
        self.queue = asyncio.Queue()

    async def connect(self, websocket):
        self.connections.add(websocket)

    def disconnect(self, websocket):
        self.connections.remove(websocket)

    async def push(self, event: str, data: dict):
        await self.queue.put(json.dumps({"event": event, "data": data}))

    async def listen(self):
        while True:
            message = await self.queue.get()
            yield f"data: {message}\n\n"

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
        # This is a simplified example. In a real app, you'd have a
        # mechanism to get real-time events from your services.
        # We'll simulate some events for demonstration.
        
        # For now, we just listen to the broadcaster
        async for message in broadcaster.listen():
            # Check if client is still connected
            if await request.is_disconnected():
                break
            yield message

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Example of how other parts of the application could push events
# This is just for demonstration and would be integrated into your services
async def simulate_events():
    await asyncio.sleep(5)
    await broadcaster.push("system_heartbeat", {"system_hostname": "server-1", "status": "online"})
    await asyncio.sleep(10)
    await broadcaster.push("sync_state_changed", {"dataset": "pool1/data", "system_hostname": "server-2", "state": "out_of_sync"})
    await asyncio.sleep(15)
    await broadcaster.push("conflict_detected", {"conflict_type": "diverged", "pool": "pool1", "dataset": "data"})

# You would typically not run this here, but it's useful for a standalone example.
# In the main app, you might start this as a background task.
# from fastapi import FastAPI
# app = FastAPI()
# @app.on_event("startup")
# async def startup_event():
#     asyncio.create_task(simulate_events())
#     app.include_router(router)
