"""
AI Inference & Validation Engine
─────────────────────────────────
• Receives IoT readings via REST POST /ingest
• Runs LSTM time-series prediction (rolling window per sensor)
• Runs XGBoost classifier to label VALID / ANOMALY
• Forwards VALID readings to Blockchain layer via POST /commit
• Exposes GET /readings  — last N validated readings
• Exposes GET /stats     — accuracy metrics
"""

import os
import json
import time
import math
import random
import logging
import threading
import requests
import numpy as np
from datetime import datetime
from collections import deque, defaultdict
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── Optional heavy deps (graceful fallback to simple heuristic) ────────────────
try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    import tensorflow as tf
    HAS_TF = True
except ImportError:
    HAS_TF = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [AI] %(message)s")
log = logging.getLogger(__name__)

BLOCKCHAIN_URL  = os.getenv("BLOCKCHAIN_URL",  "http://localhost:5002/commit")
DASHBOARD_URL   = os.getenv("DASHBOARD_URL",   "http://localhost:5003/event")
WINDOW_SIZE     = 10      # LSTM sequence length
CO2_UPPER       = 1000    # ppm — hard anomaly threshold
CO2_LOWER       = 50
ENERGY_UPPER    = 200     # kWh — hard anomaly threshold

app = Flask(__name__)
CORS(app)

# ── In-memory state ────────────────────────────────────────────────────────────
sensor_windows: dict[str, deque] = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
readings_log: list   = []
stats = {"total": 0, "valid": 0, "anomaly": 0, "correct_detections": 0}
lock  = threading.Lock()

# ── XGBoost model (simple synthetic training on startup) ──────────────────────
xgb_model = None

def train_xgboost():
    global xgb_model
    if not HAS_XGB:
        log.warning("XGBoost not installed — using heuristic classifier")
        return

    log.info("Training XGBoost classifier on synthetic data…")
    rng = np.random.default_rng(42)
    N   = 2000

    # Features: [co2_ppm, energy_kwh, temp_c, humidity_pct, prediction_error, rate_of_change]
    # Valid samples
    co2_v   = rng.normal(420, 30, N)
    eng_v   = rng.normal(70,  15, N)
    tmp_v   = rng.normal(22,   1, N)
    hum_v   = rng.normal(45,   3, N)
    err_v   = rng.normal(0,    8, N)
    roc_v   = rng.normal(0,    5, N)
    X_valid = np.column_stack([co2_v, eng_v, tmp_v, hum_v, err_v, roc_v])
    y_valid = np.zeros(N)

    # Anomaly samples
    co2_a   = np.concatenate([rng.normal(1200, 200, N//2), rng.normal(0, 5, N//2)])
    eng_a   = rng.normal(160, 30, N)
    err_a   = rng.normal(300, 50, N)
    roc_a   = rng.normal(80,  20, N)
    X_anom  = np.column_stack([co2_a, eng_a, tmp_v, hum_v, err_a, roc_a])
    y_anom  = np.ones(N)

    X = np.vstack([X_valid, X_anom])
    y = np.concatenate([y_valid, y_anom])

    xgb_model = xgb.XGBClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.1,
        use_label_encoder=False, eval_metric="logloss",
        random_state=42, verbosity=0
    )
    xgb_model.fit(X, y)
    log.info("XGBoost training complete.")

# ── LSTM-like rolling predictor (simplified as Exponential Smoothing) ──────────
def lstm_predict(window: deque, key="co2_ppm") -> float:
    """
    In production: use a real LSTM (TensorFlow/Keras).
    Here: exponential weighted mean over the window (same conceptual role —
    predict 'expected' next value to compute prediction error).
    """
    vals = [r[key] for r in window if key in r]
    if not vals:
        return 420.0
    alpha = 0.3
    pred  = vals[0]
    for v in vals[1:]:
        pred = alpha * v + (1 - alpha) * pred
    return pred

# ── Feature extraction ─────────────────────────────────────────────────────────
def extract_features(reading: dict, window: deque) -> np.ndarray:
    co2    = reading.get("co2_ppm", 420)
    energy = reading.get("energy_kwh", 70)
    temp   = reading.get("temp_c", 22)
    humid  = reading.get("humidity_pct", 45)

    predicted_co2 = lstm_predict(window, "co2_ppm")
    pred_error    = abs(co2 - predicted_co2)

    # Rate of change (vs last reading)
    roc = 0.0
    if len(window) >= 2:
        prev_co2 = list(window)[-1].get("co2_ppm", co2)
        roc = abs(co2 - prev_co2)

    return np.array([[co2, energy, temp, humid, pred_error, roc]])

# ── Classifier ─────────────────────────────────────────────────────────────────
def classify(reading: dict, window: deque) -> tuple[str, float]:
    """Returns (label, confidence). Label: 'VALID' or 'ANOMALY'."""
    co2    = reading.get("co2_ppm", 420)
    energy = reading.get("energy_kwh", 70)

    # Hard rule fallback (always applied)
    if co2 < CO2_LOWER or co2 > CO2_UPPER or energy > ENERGY_UPPER or energy < 0:
        return "ANOMALY", 0.99

    if xgb_model is not None:
        feats = extract_features(reading, window)
        prob  = float(xgb_model.predict_proba(feats)[0][1])  # P(anomaly)
        label = "ANOMALY" if prob > 0.5 else "VALID"
        return label, round(prob if label == "ANOMALY" else 1 - prob, 4)

    # Heuristic fallback
    predicted = lstm_predict(window, "co2_ppm")
    error     = abs(co2 - predicted)
    if error > 150:
        return "ANOMALY", min(0.95, error / 300)
    return "VALID", round(1 - error / 300, 4)

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "xgboost": HAS_XGB, "tensorflow": HAS_TF})

@app.route("/ingest", methods=["POST"])
def ingest():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    sensor_id = data.get("sensor_id", "UNKNOWN")
    window    = sensor_windows[sensor_id]
    label, confidence = classify(data, window)
    window.append(data)

    was_anomaly_injected = bool(data.get("anomaly_injected"))
    result = {
        **data,
        "label":      label,
        "confidence": confidence,
        "processed_at": datetime.utcnow().isoformat() + "Z",
    }

    with lock:
        stats["total"] += 1
        if label == "VALID":
            stats["valid"] += 1
        else:
            stats["anomaly"] += 1
        if (label == "ANOMALY") == was_anomaly_injected:
            stats["correct_detections"] += 1

        readings_log.append(result)
        if len(readings_log) > 500:
            readings_log.pop(0)

    log.info(f"[{label:7s}] {sensor_id} CO2={data.get('co2_ppm'):7.1f} "
             f"conf={confidence:.2f} injected={was_anomaly_injected}")

    # Forward VALID readings to blockchain
    if label == "VALID":
        threading.Thread(target=push_to_blockchain, args=(result,), daemon=True).start()

    # Push event to dashboard (fire-and-forget)
    threading.Thread(target=push_to_dashboard, args=(result,), daemon=True).start()

    return jsonify({"label": label, "confidence": confidence}), 200

@app.route("/readings")
def get_readings():
    n = int(request.args.get("n", 50))
    with lock:
        return jsonify(readings_log[-n:])

@app.route("/stats")
def get_stats():
    with lock:
        acc = round(stats["correct_detections"] / max(stats["total"], 1) * 100, 2)
        return jsonify({**stats, "accuracy_pct": acc})

# ── Outbound pushes ───────────────────────────────────────────────────────────
def push_to_blockchain(record: dict):
    try:
        r = requests.post(BLOCKCHAIN_URL, json=record, timeout=5)
        if r.status_code != 200:
            log.warning(f"Blockchain rejected: {r.text[:120]}")
    except Exception as e:
        log.debug(f"Blockchain push failed: {e}")

def push_to_dashboard(record: dict):
    try:
        requests.post(DASHBOARD_URL, json=record, timeout=2)
    except Exception:
        pass  # Dashboard is optional

# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    threading.Thread(target=train_xgboost, daemon=True).start()
    log.info("AI Engine listening on :5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
