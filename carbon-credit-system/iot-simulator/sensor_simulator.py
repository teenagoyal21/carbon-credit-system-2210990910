"""
IoT Sensor Simulator
Simulates CO2 sensors, energy meters, temperature/humidity sensors.
Publishes data via MQTT or REST to the AI engine.
"""

import time
import math
import json
import random
import requests
import argparse
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
AI_ENGINE_URL = "http://localhost:5001/ingest"
NUM_SENSORS    = 5          # number of virtual sensor nodes
INTERVAL_SEC   = 5          # reading interval (seconds)
ANOMALY_RATE   = 0.10       # 10% injected anomalies

# ── Sensor physics helpers ────────────────────────────────────────────────────
def base_co2(t: float) -> float:
    """Realistic CO2 baseline with daily cycle + trend (ppm)."""
    daily  = 30  * math.sin(2 * math.pi * t / 86400)   # daily swing
    trend  = -0.02 * t / 3600                            # slow reduction over time
    return 420 + daily + trend

def base_energy(t: float) -> float:
    """Energy consumption kWh — business-hours peak."""
    hour = (t % 86400) / 3600
    peak = math.exp(-((hour - 14) ** 2) / 18)          # peak around 2 PM
    return 50 + 40 * peak

def inject_anomaly(reading: dict) -> dict:
    """Randomly spike values to simulate data manipulation / sensor fault."""
    kind = random.choice(["spike", "zero", "drift"])
    if kind == "spike":
        reading["co2_ppm"]    *= random.uniform(2.5, 4.0)
        reading["energy_kwh"] *= random.uniform(2.0, 3.5)
    elif kind == "zero":
        reading["co2_ppm"]    = 0.0
        reading["energy_kwh"] = 0.0
    elif kind == "drift":
        reading["co2_ppm"]    += random.uniform(500, 1200)
    reading["anomaly_injected"] = kind
    return reading

# ── Main loop ─────────────────────────────────────────────────────────────────
def run(dry_run: bool = False):
    t0 = time.time()
    print(f"[IoT Simulator] Starting {NUM_SENSORS} sensors → {AI_ENGINE_URL}")
    print(f"[IoT Simulator] Interval: {INTERVAL_SEC}s | Anomaly rate: {ANOMALY_RATE*100:.0f}%\n")

    cycle = 0
    while True:
        cycle += 1
        t = time.time() - t0

        for sensor_id in range(1, NUM_SENSORS + 1):
            is_anomaly = random.random() < ANOMALY_RATE

            reading = {
                "sensor_id":    f"SENSOR-{sensor_id:03d}",
                "timestamp":    datetime.utcnow().isoformat() + "Z",
                "cycle":        cycle,
                "co2_ppm":      round(base_co2(t) + random.gauss(0, 3), 2),
                "energy_kwh":   round(base_energy(t) + random.gauss(0, 1.5), 3),
                "temp_c":       round(22.5 + random.gauss(0, 0.5), 2),
                "humidity_pct": round(45 + random.gauss(0, 2), 1),
                "anomaly_injected": None,
            }

            if is_anomaly:
                reading = inject_anomaly(reading)

            tag = "⚠ ANOMALY" if reading["anomaly_injected"] else "  OK     "
            print(f"[{tag}] {reading['sensor_id']} | CO2: {reading['co2_ppm']:7.1f} ppm "
                  f"| Energy: {reading['energy_kwh']:6.2f} kWh | {reading['timestamp']}")

            if not dry_run:
                try:
                    resp = requests.post(AI_ENGINE_URL, json=reading, timeout=3)
                    if resp.status_code != 200:
                        print(f"          ↳ AI engine error: {resp.status_code} {resp.text[:80]}")
                except requests.exceptions.ConnectionError:
                    print(f"          ↳ AI engine not reachable — is it running on port 5001?")

        print()
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IoT Carbon Credit Sensor Simulator")
    parser.add_argument("--dry-run", action="store_true", help="Print readings only, no HTTP calls")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
