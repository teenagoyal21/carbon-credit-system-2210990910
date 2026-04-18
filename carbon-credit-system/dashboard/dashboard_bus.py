"""
Dashboard Event Bus
────────────────────
Receives events from AI Engine via POST /event
Serves them to the frontend via Server-Sent Events (SSE) on GET /stream
Also proxies summary stats from AI + Blockchain layers.
"""

import json
import time
import queue
import threading
import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

app   = Flask(__name__)
CORS(app)

AI_URL         = "http://localhost:5001"
BLOCKCHAIN_URL = "http://localhost:5002"

# All SSE subscribers share this queue pool
subscribers: list[queue.Queue] = []
subscribers_lock = threading.Lock()

def broadcast(data: dict):
    msg = f"data: {json.dumps(data)}\n\n"
    with subscribers_lock:
        dead = []
        for q in subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            subscribers.remove(q)

@app.route("/event", methods=["POST"])
def receive_event():
    data = request.json or {}
    broadcast(data)
    return jsonify({"ok": True})

@app.route("/stream")
def stream():
    q = queue.Queue(maxsize=100)
    with subscribers_lock:
        subscribers.append(q)

    def generate():
        yield "data: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=20)
                    yield msg
                except queue.Empty:
                    yield ": heartbeat\n\n"   # keep-alive
        except GeneratorExit:
            with subscribers_lock:
                if q in subscribers:
                    subscribers.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/summary")
def summary():
    ai_stats, bc_stats = {}, {}
    try:
        ai_stats = requests.get(f"{AI_URL}/stats",         timeout=2).json()
    except Exception:
        ai_stats = {"error": "AI engine not reachable"}
    try:
        bc_stats = requests.get(f"{BLOCKCHAIN_URL}/stats", timeout=2).json()
    except Exception:
        bc_stats = {"error": "Blockchain not reachable"}
    return jsonify({"ai": ai_stats, "blockchain": bc_stats})

@app.route("/readings")
def readings():
    try:
        data = requests.get(f"{AI_URL}/readings?n=100", timeout=2).json()
        return jsonify(data)
    except Exception:
        return jsonify([])

@app.route("/ledger")
def ledger():
    try:
        data = requests.get(f"{BLOCKCHAIN_URL}/ledger?limit=20", timeout=2).json()
        return jsonify(data)
    except Exception:
        return jsonify({"blocks": [], "total": 0})

@app.route("/credits")
def credits():
    try:
        data = requests.get(f"{BLOCKCHAIN_URL}/credits", timeout=2).json()
        return jsonify(data)
    except Exception:
        return jsonify({})

if __name__ == "__main__":
    print("[Dashboard Bus] Listening on :5003")
    app.run(host="0.0.0.0", port=5003, debug=False, threaded=True)
