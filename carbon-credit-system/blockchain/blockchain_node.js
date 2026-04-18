/**
 * Blockchain Immutability Layer
 * ─────────────────────────────
 * In production: Hyperledger Fabric peer node + chaincode (Go).
 * Here: a Node.js simulation that mirrors the exact same API surface,
 * so you can swap in real Fabric later with zero changes to other layers.
 *
 * • POST /commit      — AI engine pushes VALID readings
 * • GET  /ledger      — query the immutable ledger
 * • GET  /credits     — carbon credits issued per facility
 * • GET  /verify/:hash — verify a record by SHA-256 hash
 * • POST /smart-contract/trigger — manually fire threshold check
 *
 * Smart contract rules (identical to Go chaincode in paper):
 *   1. Only VALID-labelled records accepted
 *   2. Each record hashed with SHA-256; stored with block metadata
 *   3. Carbon credit issued every 100 kg CO2 reduction verified
 */

const express    = require('express');
const crypto     = require('crypto');
const cors       = require('cors');
const bodyParser = require('body-parser');
const axios      = require('axios');

const app  = express();
const PORT = process.env.PORT || 5002;

app.use(cors());
app.use(bodyParser.json());

// ── In-memory ledger (replace with LevelDB / Fabric SDK in production) ────────
const ledger    = [];          // immutable blocks
const creditMap = {};          // facilityId → credits issued
let   blockNum  = 0;

// ── CO2 reduction threshold for 1 carbon credit (kg) ─────────────────────────
const CREDIT_THRESHOLD_KG = 100;
const BASE_CO2_PPM        = 420;   // atmospheric baseline

// ── Helpers ───────────────────────────────────────────────────────────────────
function sha256(obj) {
  return crypto.createHash('sha256').update(JSON.stringify(obj)).digest('hex');
}

function ppmToKgReduction(co2_ppm) {
  // Simplified: reduction vs baseline × volume factor
  const reduction = Math.max(0, BASE_CO2_PPM - co2_ppm);
  return parseFloat((reduction * 0.00183).toFixed(6)); // 1 ppm in std room ≈ 0.00183 kg
}

function issueCredit(facilityId, kg) {
  if (!creditMap[facilityId]) {
    creditMap[facilityId] = { accumulatedKg: 0, creditsIssued: 0, transactions: [] };
  }
  const facility = creditMap[facilityId];
  facility.accumulatedKg += kg;

  let newCredits = 0;
  while (facility.accumulatedKg >= CREDIT_THRESHOLD_KG) {
    facility.accumulatedKg -= CREDIT_THRESHOLD_KG;
    facility.creditsIssued += 1;
    newCredits += 1;
    facility.transactions.push({
      credit_id: `CC-${facilityId}-${facility.creditsIssued}`,
      issued_at: new Date().toISOString(),
      kg_verified: CREDIT_THRESHOLD_KG,
    });
    console.log(`[Smart Contract] 🏅 Credit issued → ${facilityId} | Total: ${facility.creditsIssued}`);
  }
  return newCredits;
}

// ── Smart Contract validation ──────────────────────────────────────────────────
function smartContractValidate(record) {
  // Rule 1: Must be labelled VALID by AI
  if (record.label !== 'VALID') {
    return { ok: false, reason: 'REJECTED: label is not VALID' };
  }
  // Rule 2: CO2 must be within sensor range
  if (record.co2_ppm < 0 || record.co2_ppm > 5000) {
    return { ok: false, reason: 'REJECTED: co2_ppm out of sensor range' };
  }
  // Rule 3: timestamp must be present
  if (!record.timestamp) {
    return { ok: false, reason: 'REJECTED: missing timestamp' };
  }
  return { ok: true };
}

// ── Routes ─────────────────────────────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({ status: 'ok', blocks: ledger.length, node: 'peer0.org1.carbon.com' });
});

app.post('/commit', (req, res) => {
  const record = req.body;

  // Smart contract execution
  const { ok, reason } = smartContractValidate(record);
  if (!ok) {
    console.log(`[Blockchain] ✗ ${reason}`);
    return res.status(422).json({ error: reason });
  }

  // Build block
  const prevHash   = ledger.length > 0 ? ledger[ledger.length - 1].blockHash : '0'.repeat(64);
  const payload    = { ...record, blockNumber: ++blockNum, previousHash: prevHash };
  const payloadHash = sha256(payload);
  const block = {
    blockNumber:  blockNum,
    blockHash:    payloadHash,
    previousHash: prevHash,
    timestamp:    new Date().toISOString(),
    data:         payload,
    endorsedBy:   ['peer0.org1', 'peer0.org2'],  // simulated endorsement
  };

  ledger.push(block);

  // Carbon credit smart contract
  const facilityId = record.sensor_id || 'FACILITY-001';
  const kgReduced  = ppmToKgReduction(record.co2_ppm);
  const newCredits = issueCredit(facilityId, kgReduced);

  console.log(`[Blockchain] ✓ Block #${blockNum} | hash: ${payloadHash.substring(0, 16)}… | CO2: ${record.co2_ppm} ppm | -${kgReduced.toFixed(4)} kg | credits: ${newCredits}`);

  res.json({
    success:     true,
    blockNumber: blockNum,
    blockHash:   payloadHash,
    kgReduced,
    newCreditsIssued: newCredits,
    totalCredits: creditMap[facilityId]?.creditsIssued || 0,
  });
});

app.get('/ledger', (req, res) => {
  const limit  = parseInt(req.query.limit  || '50');
  const offset = parseInt(req.query.offset || '0');
  res.json({
    total:  ledger.length,
    blocks: ledger.slice(-limit).reverse(),
  });
});

app.get('/credits', (req, res) => {
  res.json(creditMap);
});

app.get('/verify/:hash', (req, res) => {
  const { hash } = req.params;
  const block = ledger.find(b => b.blockHash === hash);
  if (!block) return res.status(404).json({ verified: false, error: 'Hash not found in ledger' });
  res.json({ verified: true, block });
});

app.get('/stats', (req, res) => {
  const totalCredits = Object.values(creditMap).reduce((s, f) => s + f.creditsIssued, 0);
  const totalKg      = Object.values(creditMap).reduce((s, f) => s + (f.creditsIssued * CREDIT_THRESHOLD_KG + f.accumulatedKg), 0);
  res.json({
    totalBlocks:  ledger.length,
    totalCredits,
    totalKgVerified: parseFloat(totalKg.toFixed(2)),
    facilities:   Object.keys(creditMap).length,
  });
});

// ── Chain integrity check ──────────────────────────────────────────────────────
app.get('/integrity', (req, res) => {
  let valid = true;
  for (let i = 1; i < ledger.length; i++) {
    if (ledger[i].previousHash !== ledger[i - 1].blockHash) {
      valid = false;
      break;
    }
  }
  res.json({ chainIntact: valid, blocks: ledger.length });
});

app.listen(PORT, () => {
  console.log(`[Blockchain] Peer node listening on :${PORT}`);
  console.log(`[Blockchain] Smart contracts loaded: EmissionVerifier, CreditIssuer`);
});
