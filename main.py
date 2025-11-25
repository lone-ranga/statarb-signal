# main.py – StatArb Signal Server (fixed for Render port detection)
import os
from fastapi import FastAPI, HTTPException, Request
import uvicorn
import json
import hmac
import hashlib
import logging
from typing import Dict
from fastapi import WebSocket, WebSocketDisconnect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="StatArb Signal Server")

# █████████████████████████████████████████████████████████████████
# ONLY CHANGE THESE TWO LINES – MUST MATCH signal_emitter.py EXACTLY
MASTER_SECRET = "1042584568245260345824057204356324765274548572845624256456204866"
ALLOWED_MASTER_IPS = []        # optional: add your VPS IP here later
# █████████████████████████████████████████████████████████████████

class ConnectionManager:
    def __init__(self):
        self.clients: Dict[str, WebSocket] = {}

    async def connect(self, client_id: str, ws: WebSocket):
        await ws.accept()
        self.clients[client_id] = ws
        print(f"Connected: {client_id} | Total live: {len(self.clients)}")

    def disconnect(self, client_id: str):
        self.clients.pop(client_id, None)
        print(f"Disconnected: {client_id} | Remaining: {len(self.clients)}")

    async def broadcast(self, message: str):
        dead = []
        for cid, ws in self.clients.items():
            try:
                await ws.send_text(message)
            except:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

manager = ConnectionManager()

def verify(payload: str, sig: str) -> bool:
    expected = hmac.new(MASTER_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)

@app.get("/")
async def root():
    return {"status": "StatArb Signal Server Live", "endpoints": ["/master-signal", "/ws/{client_id}"]}

@app.post("/webhook")
async def legacy_webhook(request: Request):
    body = await request.body()
    payload = body.decode()
    try:
        signal = json.loads(payload)
        logger.info(f"LEGACY WEBHOOK → {signal}")
        await manager.broadcast(json.dumps(signal))
    except:
        logger.warning(f"Bad legacy webhook payload: {payload}")
    return {"status": "ok"}
    
@app.post("/master-signal")
async def master_signal(request: Request, data: dict):
    payload = data.get("payload")
    sig = data.get("sig")
    
    if not payload or not sig or not verify(payload, sig):
        logger.warning(f"Invalid signature from {request.client.host}")
        raise HTTPException(401, "Invalid signature")
    
    signal = json.loads(payload)
    logger.info(f"SIGNAL RECEIVED → {signal['action']} {signal.get('symbol', '')} | "
                f"Z={signal.get('z_score', 'N/A'):.3f} | "
                f"From IP: {request.client.host}")
    
    await manager.broadcast(payload)
    return {"status": "ok", "clients": len(manager.clients)}
    
@app.websocket("/ws/{client_id}")
async def ws_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(client_id, websocket)
    try:
        while True:
            await websocket.receive_text()   # keep-alive
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except:
        manager.disconnect(client_id)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # ← Render dynamic port fix
    uvicorn.run(app, host="0.0.0.0", port=port)
