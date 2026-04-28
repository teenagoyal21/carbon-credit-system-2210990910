# 🌿 Blockchain Integrated AI Framework for Carbon Credit Verification
**Teena Goyal | Chitkara University Institute of Engineering & Technology**

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    LAYER 1: IoT Data Acquisition                  │
│   sensor_simulator.py  →  5 virtual sensors every 5 seconds      │
│   CO₂ | Energy | Temp | Humidity  (10% anomaly injection)        │
└─────────────────────────────┬────────────────────────────────────┘
                              │ POST /ingest (JSON)
┌─────────────────────────────▼────────────────────────────────────┐
│                    LAYER 2: AI Inference Engine                   │
│   ai_engine.py   (Flask, port 5001)                              │
│   LSTM rolling predictor → XGBoost classifier                    │
│   Labels: VALID | ANOMALY   Accuracy: ~96%                       │
└──────────────┬──────────────────────────────┬────────────────────┘
               │ POST /commit (VALID only)    │ POST /event (all)
┌──────────────▼──────────────┐  ┌────────────▼───────────────────┐
│  LAYER 3: Blockchain Node   │  │  Dashboard Event Bus           │
│  blockchain_node.js  :5002  │  │  dashboard_bus.py       :5003  │
│  Smart Contract rules       │  │  SSE stream to browser         │
│  SHA-256 hash per block     │  └────────────┬───────────────────┘
│  Carbon credit issuance     │               │ EventSource SSE
│  Chain integrity check      │  ┌────────────▼───────────────────┐
└─────────────────────────────┘  │  Dashboard UI  index.html      │
                                 │  Open in browser               │
                                 └────────────────────────────────┘
```

---

## Quick Start (Local & No Docker)

### Prerequisites
- Python 3.10+
- Node.js 18+
- npm

### One command
```bash
chmod +x run_local.sh
./run_local.sh
```
Then open `dashboard/index.html` in your browser.

---

## Quick Start (Docker)

```bash
# Make sure Docker Desktop is running
cd docker
docker compose up --build

# Dashboard: http://localhost:8080
# AI Engine: http://localhost:5001/stats
# Blockchain: http://localhost:5002/ledger
```

---

## Manual Start (separate terminal)

```bash
# Terminal 1 — Blockchain Node
cd blockchain && npm install && node blockchain_node.js

# Terminal 2 — AI Engine
cd ai-engine && pip install -r requirements.txt && python ai_engine.py

# Terminal 3 — Dashboard Bus
cd dashboard && pip install -r requirements.txt && python dashboard_bus.py

# Terminal 4 — IoT Simulator
cd iot-simulator && pip install -r requirements.txt && python sensor_simulator.py

# Browser — open dashboard/index.html
```

---

## API Reference

### AI Engine (port 5001)
| Method | Endpoint     | Description                        |
|--------|--------------|------------------------------------|
| POST   | `/ingest`    | Submit IoT reading for validation  |
| GET    | `/readings`  | Last N validated readings          |
| GET    | `/stats`     | Accuracy, total, valid, anomalies  |
| GET    | `/health`    | Service health check               |

### Blockchain Node (port 5002)
| Method | Endpoint          | Description                      |
|--------|-------------------|----------------------------------|
| POST   | `/commit`         | Store VALID reading as block     |
| GET    | `/ledger`         | Query immutable ledger           |
| GET    | `/credits`        | Carbon credits per facility      |
| GET    | `/verify/:hash`   | Verify a block by SHA-256 hash   |
| GET    | `/integrity`      | Check chain hash continuity      |
| GET    | `/stats`          | Total blocks, credits, kg        |

### Dashboard Bus (port 5003)
| Method | Endpoint    | Description                        |
|--------|-------------|------------------------------------|
| GET    | `/stream`   | SSE stream for live events         |
| GET    | `/summary`  | Combined AI + blockchain stats     |
| GET    | `/readings` | Proxy to AI readings               |
| GET    | `/ledger`   | Proxy to blockchain ledger         |
| GET    | `/credits`  | Proxy to blockchain credits        |

---

## Smart Contract (Solidity)

`blockchain/CarbonCreditVerifier.sol` — deploy with Hardhat:

```bash
npm install --save-dev hardhat @nomicfoundation/hardhat-toolbox
npx hardhat init
cp blockchain/CarbonCreditVerifier.sol contracts/
npx hardhat compile
npx hardhat node                    # local Ethereum node
npx hardhat run scripts/deploy.js --network localhost
```

Rules enforced on-chain:
1. Only AI-labelled `VALID` readings accepted
2. No replay attacks (SHA-256 deduplication)
3. Facility must be registered
4. CO₂ in valid sensor range (10–5000 ppm)
5. Carbon credit issued per 100 kg CO₂ reduction verified

---

## Project Structure

```
carbon-credit-system/
├── iot-simulator/
│   ├── sensor_simulator.py     # IoT sensor simulation
│   └── requirements.txt
├── ai-engine/
│   ├── ai_engine.py            # Flask + LSTM + XGBoost
│   └── requirements.txt
├── blockchain/
│   ├── blockchain_node.js      # Hyperledger Fabric simulation
│   ├── CarbonCreditVerifier.sol  # Solidity smart contract
│   └── package.json
├── dashboard/
│   ├── dashboard_bus.py        # SSE event bus
│   ├── index.html              # Real-time dashboard UI
│   └── requirements.txt
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.python
│   └── Dockerfile.node
├── run_local.sh                # One-click local startup
└── README.md
```

---

## Technology Mapping (Paper ↔ Code)

| Paper Component       | Implementation                              |
|-----------------------|---------------------------------------------|
| IoT Sensing Layer     | `sensor_simulator.py` — NDIR CO₂, energy   |
| LSTM Predictor        | Exp. weighted predictor in `ai_engine.py`   |
| XGBoost Classifier    | `xgboost.XGBClassifier` in `ai_engine.py`  |
| Hyperledger Fabric    | `blockchain_node.js` (same API surface)     |
| Go Chaincode          | `CarbonCreditVerifier.sol` (Solidity equiv) |
| Smart Contracts       | Rules in `smartContractValidate()`          |
| SHA-256 Hashing       | `crypto.createHash('sha256')` in Node.js   |
| Carbon Credit Trigger | `issueCredit()` per 100 kg threshold        |
| Dashboard             | `index.html` — SSE real-time stream        |

---

## Extending to Real Hyperledger Fabric

Replace `blockchain_node.js` with the Fabric SDK:
```bash
npm install fabric-network
```
The POST `/commit` and GET `/ledger` APIs remain identical — only the internal storage changes from in-memory to Fabric channels.

---

*Chitkara University · B.E. Computer Science · Research Paper Implementation*
