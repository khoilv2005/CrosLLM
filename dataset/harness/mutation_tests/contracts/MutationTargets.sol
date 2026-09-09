// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0 <0.9.0;

// 1. REPLAY: Nonce Tracking
contract TargetReplayNonceMutant {
    uint256 public totalMinted;
    function process(bytes32, uint256 amount) external {
        // MUTATION: Delivery flag not recorded
        totalMinted += amount;
    }
}

contract TargetReplayNonceControl {
    uint256 public totalMinted;
    mapping(bytes32 => bool) public executed;
    function process(bytes32 msgId, uint256 amount) external {
        require(!executed[msgId], "Already executed");
        executed[msgId] = true;
        totalMinted += amount;
    }
}

// 2. REPLAY: Domain Separator
contract TargetDomainStripMutant {
    function verifyDomain(uint32, bytes32) external pure returns (bool) {
        // MUTATION: Domain check omitted
        return true;
    }
}

contract TargetDomainStripControl {
    uint32 public immutable expectedDomain;
    constructor(uint32 _domain) { expectedDomain = _domain; }
    function verifyDomain(uint32 domain, bytes32) external view returns (bool) {
        require(domain == expectedDomain, "Invalid target domain");
        return true;
    }
}

// 3. INPUT VALIDATION: Source Sender Spoofing
contract TargetSourceSenderMutant {
    uint256 public privilegedExecutions;
    function handle(address, bytes calldata) external {
        // MUTATION: Caller / remote peer check omitted
        privilegedExecutions++;
    }
}

contract TargetSourceSenderControl {
    address public immutable trustedRemotePeer;
    uint256 public privilegedExecutions;
    constructor(address _peer) { trustedRemotePeer = _peer; }
    function handle(address remoteSender, bytes calldata) external {
        require(remoteSender == trustedRemotePeer, "Unauthorized remote sender");
        privilegedExecutions++;
    }
}

// 4. INPUT VALIDATION: Chain ID Spoofing
contract TargetChainIdMutant {
    function acceptChain(uint32) external pure returns (bool) {
        // MUTATION: Accepts wildcard/unregistered chain 0
        return true;
    }
}

contract TargetChainIdControl {
    mapping(uint32 => bool) public registeredChains;
    constructor() { registeredChains[1] = true; registeredChains[42161] = true; }
    function acceptChain(uint32 chainId) external view returns (bool) {
        require(registeredChains[chainId], "Unsupported chain ID");
        return true;
    }
}

// 5. LOGIC: Fee Conservation Underflow
contract TargetFeeConservationMutant {
    uint256 public totalReleased;
    function release(uint256 amount, uint256 fee) external {
        // MUTATION: Adds fee instead of subtracting fee
        totalReleased += (amount + fee);
    }
}

contract TargetFeeConservationControl {
    uint256 public totalReleased;
    function release(uint256 amount, uint256 fee) external {
        require(amount > fee, "Amount must exceed fee");
        totalReleased += (amount - fee);
    }
}

// 6. LOGIC: Accounting Desync
contract TargetAccountingDesyncMutant {
    uint256 public poolReserve;
    constructor(uint256 _initial) { poolReserve = _initial; }
    function fill(uint256) external pure {
        // MUTATION: Omits poolReserve -= amount
    }
}

contract TargetAccountingDesyncControl {
    uint256 public poolReserve;
    constructor(uint256 _initial) { poolReserve = _initial; }
    function fill(uint256 amount) external {
        require(poolReserve >= amount, "Insufficient pool reserve");
        poolReserve -= amount;
    }
}

// 7. MESSAGE HANDLING: Unverified Caller
contract TargetUnverifiedCallerMutant {
    uint256 public sensitiveOperations;
    function executeCallback(bytes calldata) external {
        // MUTATION: onlyBridge modifier omitted
        sensitiveOperations++;
    }
}

contract TargetUnverifiedCallerControl {
    address public immutable bridge;
    uint256 public sensitiveOperations;
    constructor(address _bridge) { bridge = _bridge; }
    function executeCallback(bytes calldata) external {
        require(msg.sender == bridge, "Unauthorized endpoint callback");
        sensitiveOperations++;
    }
}

// 8. MESSAGE HANDLING: Reentrancy
contract TargetReentrancyMutant {
    bool public executed;
    function execute(address target) external {
        // MUTATION: External call BEFORE state flag update
        (bool ok,) = target.call(abi.encodeWithSignature("reenter()"));
        require(ok, "Call failed");
        executed = true;
    }
}

contract TargetReentrancyControl {
    bool public executed;
    bool private locked;
    modifier nonReentrant() {
        require(!locked, "ReentrancyGuard: reentrant call");
        locked = true;
        _;
        locked = false;
    }
    function execute(address target) external nonReentrant {
        require(!executed, "Already executed");
        executed = true;
        (bool ok,) = target.call(abi.encodeWithSignature("reenter()"));
        require(ok, "Call failed");
    }
}

// 9. QUORUM: Threshold Decrement
contract TargetQuorumThresholdMutant {
    function checkQuorum(uint256 count) external pure returns (bool) {
        // MUTATION: Threshold reduced to 1 instead of required 3
        require(count >= 1, "Insufficient quorum");
        return true;
    }
}

contract TargetQuorumThresholdControl {
    uint256 public constant REQUIRED_QUORUM = 3;
    function checkQuorum(uint256 count) external pure returns (bool) {
        require(count >= REQUIRED_QUORUM, "Insufficient quorum");
        return true;
    }
}

// 10. FINALITY: Dispute Window Truncation
contract TargetFinalityWindowMutant {
    function finalize(uint256 proposalTime) external view returns (bool) {
        // MUTATION: 0 delay challenge period
        require(block.timestamp >= proposalTime, "Challenge active");
        return true;
    }
}

contract TargetFinalityWindowControl {
    uint256 public constant CHALLENGE_PERIOD = 7 days;
    function finalize(uint256 proposalTime) external view returns (bool) {
        require(block.timestamp >= proposalTime + CHALLENGE_PERIOD, "Challenge window still active");
        return true;
    }
}
