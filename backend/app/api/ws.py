"""WebSocket hub. Sends a snapshot on connect; broadcast() pushes live updates
from within the API process (the worker is a separate process and polls in v1).
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.session import SessionLocal
from app.models.regime import Regime
from app.models.strategy import Strategy

router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


def _snapshot() -> dict:
    with SessionLocal() as db:
        r = db.query(Regime).filter_by(symbol="SPY").order_by(Regime.ts.desc()).first()
        return {
            "type": "snapshot",
            "regime": (
                {"label": r.label, "confidence": r.confidence, "unstable": r.unstable}
                if r
                else None
            ),
            "strategies": db.query(Strategy).count(),
        }


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        await ws.send_json(_snapshot())
        while True:
            await ws.receive_text()  # keepalive; client messages are ignored
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
