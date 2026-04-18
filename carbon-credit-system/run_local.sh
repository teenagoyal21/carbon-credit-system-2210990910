#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Carbon Credit Verification System — Local Startup Script
#  Usage:  chmod +x run_local.sh && ./run_local.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'; AMBER='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${AMBER}[!]${NC} $*"; }
die()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
command -v python3  >/dev/null 2>&1 || die "python3 not found"
command -v node     >/dev/null 2>&1 || die "node not found"
command -v npm      >/dev/null 2>&1 || die "npm not found"

# ── Install deps ──────────────────────────────────────────────────────────────
log "Installing Python deps for AI engine…"
pip install -q -r "$ROOT/ai-engine/requirements.txt"

log "Installing Python deps for Dashboard Bus…"
pip install -q -r "$ROOT/dashboard/requirements.txt"

log "Installing Python deps for IoT Simulator…"
pip install -q -r "$ROOT/iot-simulator/requirements.txt"

log "Installing Node.js deps for Blockchain…"
(cd "$ROOT/blockchain" && npm install --silent)

# ── Kill old processes on our ports ───────────────────────────────────────────
for PORT in 5001 5002 5003; do
  PID=$(lsof -ti tcp:$PORT 2>/dev/null || true)
  [ -n "$PID" ] && kill -9 $PID 2>/dev/null && warn "Killed old process on :$PORT"
done

# ── Start services ────────────────────────────────────────────────────────────
log "Starting Blockchain node on :5002…"
node "$ROOT/blockchain/blockchain_node.js" > /tmp/carbon-blockchain.log 2>&1 &
BC_PID=$!

sleep 1

log "Starting AI Engine on :5001…"
python3 "$ROOT/ai-engine/ai_engine.py" > /tmp/carbon-ai.log 2>&1 &
AI_PID=$!

sleep 2

log "Starting Dashboard Bus on :5003…"
python3 "$ROOT/dashboard/dashboard_bus.py" > /tmp/carbon-dashboard.log 2>&1 &
DB_PID=$!

sleep 1

log "Starting IoT Simulator…"
python3 "$ROOT/iot-simulator/sensor_simulator.py" > /tmp/carbon-iot.log 2>&1 &
IOT_PID=$!

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  🌿 Carbon Credit System — RUNNING${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Dashboard UI  →  open ${AMBER}$ROOT/dashboard/index.html${NC} in browser"
echo -e "  AI Engine     →  http://localhost:5001/stats"
echo -e "  Blockchain    →  http://localhost:5002/ledger"
echo -e "  Dashboard Bus →  http://localhost:5003/summary"
echo ""
echo -e "  Logs:"
echo -e "    tail -f /tmp/carbon-ai.log"
echo -e "    tail -f /tmp/carbon-blockchain.log"
echo -e "    tail -f /tmp/carbon-iot.log"
echo ""
echo -e "  Press ${RED}Ctrl+C${NC} to stop all services"
echo ""

# ── Trap Ctrl+C ───────────────────────────────────────────────────────────────
cleanup() {
  echo ""
  warn "Stopping all services…"
  kill $BC_PID $AI_PID $DB_PID $IOT_PID 2>/dev/null || true
  echo -e "${GREEN}All stopped.${NC}"
}
trap cleanup INT TERM

wait
