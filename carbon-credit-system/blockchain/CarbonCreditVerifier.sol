// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title CarbonCreditVerifier
 * @notice On-chain smart contract for verified carbon credit issuance.
 *         Deploy with Hardhat on a local Hardhat node or Sepolia testnet.
 *
 * Flow:
 *   1. Trusted AI Oracle (off-chain) calls submitVerifiedReading()
 *   2. Contract validates rules + emits ReadingVerified event
 *   3. When accumulated CO2 reduction reaches threshold, issues a credit
 *   4. Credits are ERC-20-like tokens tracked per facility address
 */

contract CarbonCreditVerifier {

    // ── Types ──────────────────────────────────────────────────────────────────
    struct EmissionReading {
        bytes32  readingHash;      // SHA-256 of raw sensor payload
        string   sensorId;
        uint256  co2Ppm;           // × 100 to avoid decimals (420.50 → 42050)
        uint256  energyWh;         // watt-hours
        uint256  timestamp;
        bool     valid;
    }

    struct Facility {
        address  owner;
        uint256  accumulatedReductionGrams;
        uint256  creditsIssued;
        bool     registered;
    }

    // ── State ──────────────────────────────────────────────────────────────────
    address public owner;
    address public aiOracle;                   // trusted AI engine address

    uint256 public constant BASE_CO2_PPM_X100  = 42000; // 420.00 ppm baseline
    uint256 public constant CREDIT_THRESHOLD_G = 100_000; // 100 kg = 100,000 g

    mapping(address => Facility)       public facilities;
    mapping(bytes32  => EmissionReading) public readings;
    bytes32[] public readingIndex;

    // ── Events ─────────────────────────────────────────────────────────────────
    event ReadingSubmitted(bytes32 indexed readingHash, string sensorId, bool valid);
    event CreditIssued(address indexed facility, uint256 creditNumber, uint256 timestamp);
    event FacilityRegistered(address indexed facility, address owner);
    event OracleUpdated(address indexed newOracle);

    // ── Modifiers ──────────────────────────────────────────────────────────────
    modifier onlyOwner()   { require(msg.sender == owner,    "Not owner");   _; }
    modifier onlyOracle()  { require(msg.sender == aiOracle, "Not oracle");  _; }

    // ── Constructor ────────────────────────────────────────────────────────────
    constructor(address _aiOracle) {
        owner    = msg.sender;
        aiOracle = _aiOracle;
    }

    // ── Admin ──────────────────────────────────────────────────────────────────
    function setOracle(address _oracle) external onlyOwner {
        aiOracle = _oracle;
        emit OracleUpdated(_oracle);
    }

    function registerFacility(address facilityAddr) external onlyOwner {
        require(!facilities[facilityAddr].registered, "Already registered");
        facilities[facilityAddr] = Facility({
            owner:                    facilityAddr,
            accumulatedReductionGrams: 0,
            creditsIssued:            0,
            registered:               true
        });
        emit FacilityRegistered(facilityAddr, facilityAddr);
    }

    // ── Core: Submit verified reading (called by AI Oracle) ───────────────────
    /**
     * @param sensorId      e.g. "SENSOR-001"
     * @param co2PpmX100    CO2 in ppm × 100 (e.g. 41050 = 410.50 ppm)
     * @param energyWh      energy in watt-hours
     * @param ts            Unix timestamp of reading
     * @param isValid       AI classification result
     * @param rawHash       SHA-256 of raw sensor JSON payload
     * @param facilityAddr  registered facility address
     */
    function submitVerifiedReading(
        string  calldata sensorId,
        uint256 co2PpmX100,
        uint256 energyWh,
        uint256 ts,
        bool    isValid,
        bytes32 rawHash,
        address facilityAddr
    ) external onlyOracle {
        // Rule 1: No replay attacks
        require(readings[rawHash].timestamp == 0, "Reading already committed");

        // Rule 2: Facility must be registered
        require(facilities[facilityAddr].registered, "Facility not registered");

        // Rule 3: CO2 must be in valid sensor range
        require(co2PpmX100 >= 1000 && co2PpmX100 <= 500_000, "CO2 out of range");

        // Store reading
        readings[rawHash] = EmissionReading({
            readingHash: rawHash,
            sensorId:    sensorId,
            co2Ppm:      co2PpmX100,
            energyWh:    energyWh,
            timestamp:   ts,
            valid:       isValid
        });
        readingIndex.push(rawHash);

        emit ReadingSubmitted(rawHash, sensorId, isValid);

        // Only VALID readings contribute to credits
        if (!isValid) return;

        // Calculate CO2 reduction vs baseline
        if (co2PpmX100 < BASE_CO2_PPM_X100) {
            uint256 reductionPpmX100 = BASE_CO2_PPM_X100 - co2PpmX100;
            // Convert ppm reduction to grams (1 ppm in standard facility ≈ 1.83 g)
            uint256 reductionGrams = (reductionPpmX100 * 183) / 100_000;

            Facility storage f = facilities[facilityAddr];
            f.accumulatedReductionGrams += reductionGrams;

            // Issue credit(s) if threshold crossed
            while (f.accumulatedReductionGrams >= CREDIT_THRESHOLD_G) {
                f.accumulatedReductionGrams -= CREDIT_THRESHOLD_G;
                f.creditsIssued += 1;
                emit CreditIssued(facilityAddr, f.creditsIssued, block.timestamp);
            }
        }
    }

    // ── Views ──────────────────────────────────────────────────────────────────
    function getCredits(address facilityAddr) external view returns (uint256) {
        return facilities[facilityAddr].creditsIssued;
    }

    function totalReadings() external view returns (uint256) {
        return readingIndex.length;
    }

    function verifyReading(bytes32 rawHash) external view returns (bool exists, bool valid) {
        EmissionReading storage r = readings[rawHash];
        exists = r.timestamp != 0;
        valid  = r.valid;
    }
}
