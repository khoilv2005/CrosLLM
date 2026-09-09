// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0 <0.9.0;

import "forge-std/Test.sol";
import "../contracts/MutationTargets.sol";

contract ReentrancyAttacker {
    address public target;
    uint256 public count;
    constructor(address _target) { target = _target; }
    function reenter() external {
        if (count < 2) {
            count++;
            (bool ok,) = target.call(abi.encodeWithSignature("execute(address)", address(this)));
            require(ok, "Reentry failed");
        }
    }
}

contract MutationTriggerVerificationTest is Test {
    // 1. Replay Nonce
    function test_OP_REPLAY_NONCE_REMOVAL() public {
        TargetReplayNonceMutant mutant = new TargetReplayNonceMutant();
        TargetReplayNonceControl control = new TargetReplayNonceControl();
        bytes32 msgId = keccak256("msg_1");

        // Mutant permits double-execution
        mutant.process(msgId, 100);
        mutant.process(msgId, 100);
        assertEq(mutant.totalMinted(), 200, "Mutant permitted replay double minting");

        // Control blocks replay
        control.process(msgId, 100);
        vm.expectRevert("Already executed");
        control.process(msgId, 100);
        assertEq(control.totalMinted(), 100, "Control blocked replay");
    }

    // 2. Domain Strip
    function test_OP_REPLAY_DOMAIN_STRIP() public {
        TargetDomainStripMutant mutant = new TargetDomainStripMutant();
        TargetDomainStripControl control = new TargetDomainStripControl(1);

        // Mutant accepts cross-domain replay
        assertTrue(mutant.verifyDomain(999, keccak256("sig")));

        // Control blocks unauthorized domain
        vm.expectRevert("Invalid target domain");
        control.verifyDomain(999, keccak256("sig"));
        assertTrue(control.verifyDomain(1, keccak256("sig")));
    }

    // 3. Spoof Sender
    function test_OP_SPOOF_SOURCE_SENDER() public {
        address authorizedPeer = address(0xAA);
        address attacker = address(0xBAD);
        TargetSourceSenderMutant mutant = new TargetSourceSenderMutant();
        TargetSourceSenderControl control = new TargetSourceSenderControl(authorizedPeer);

        // Mutant accepts unauthenticated attacker
        mutant.handle(attacker, "");
        assertEq(mutant.privilegedExecutions(), 1);

        // Control rejects attacker
        vm.expectRevert("Unauthorized remote sender");
        control.handle(attacker, "");
        control.handle(authorizedPeer, "");
        assertEq(control.privilegedExecutions(), 1);
    }

    // 4. Spoof Chain ID
    function test_OP_SPOOF_CHAIN_ID() public {
        TargetChainIdMutant mutant = new TargetChainIdMutant();
        TargetChainIdControl control = new TargetChainIdControl();

        // Mutant accepts wildcard chain 0
        assertTrue(mutant.acceptChain(0));

        // Control rejects invalid chain
        vm.expectRevert("Unsupported chain ID");
        control.acceptChain(0);
        assertTrue(control.acceptChain(1));
    }

    // 5. Invariant Fee Underflow
    function test_OP_INVARIANT_FEE_UNDERFLOW() public {
        TargetFeeConservationMutant mutant = new TargetFeeConservationMutant();
        TargetFeeConservationControl control = new TargetFeeConservationControl();

        // Mutant releases inflated amount
        mutant.release(100, 10);
        assertEq(mutant.totalReleased(), 110, "Mutant inflated release amount");

        // Control preserves conservation
        control.release(100, 10);
        assertEq(control.totalReleased(), 90, "Control correctly deducted fee");
    }

    // 6. Accounting Desync
    function test_OP_INVARIANT_ACCOUNTING_DESYNC() public {
        TargetAccountingDesyncMutant mutant = new TargetAccountingDesyncMutant(1000);
        TargetAccountingDesyncControl control = new TargetAccountingDesyncControl(1000);

        // Mutant fails to deduct reserve
        mutant.fill(100);
        assertEq(mutant.poolReserve(), 1000, "Mutant reserve desynchronized");

        // Control updates reserve atomically
        control.fill(100);
        assertEq(control.poolReserve(), 900, "Control reserve correctly updated");
    }

    // 7. Unverified Caller
    function test_OP_UNVERIFIED_CALLER_BYPASS() public {
        address bridge = address(0xBB);
        TargetUnverifiedCallerMutant mutant = new TargetUnverifiedCallerMutant();
        TargetUnverifiedCallerControl control = new TargetUnverifiedCallerControl(bridge);

        // Mutant allows arbitrary caller
        mutant.executeCallback("");
        assertEq(mutant.sensitiveOperations(), 1);

        // Control enforces bridge only
        vm.expectRevert("Unauthorized endpoint callback");
        control.executeCallback("");
        vm.prank(bridge);
        control.executeCallback("");
        assertEq(control.sensitiveOperations(), 1);
    }

    // 8. Reentrancy
    function test_OP_CALLBACK_REENTRANCY() public {
        TargetReentrancyMutant mutant = new TargetReentrancyMutant();
        TargetReentrancyControl control = new TargetReentrancyControl();

        ReentrancyAttacker attackerMut = new ReentrancyAttacker(address(mutant));
        attackerMut.reenter();
        assertTrue(attackerMut.count() >= 1, "Mutant allowed state reentrancy");

        ReentrancyAttacker attackerCtrl = new ReentrancyAttacker(address(control));
        vm.expectRevert("Reentry failed");
        attackerCtrl.reenter();
    }

    // 9. Quorum Threshold
    function test_OP_QUORUM_THRESHOLD_DECREMENT() public {
        TargetQuorumThresholdMutant mutant = new TargetQuorumThresholdMutant();
        TargetQuorumThresholdControl control = new TargetQuorumThresholdControl();

        // Mutant accepts sub-threshold 1 signature
        assertTrue(mutant.checkQuorum(1));

        // Control requires quorum >= 3
        vm.expectRevert("Insufficient quorum");
        control.checkQuorum(1);
        assertTrue(control.checkQuorum(3));
    }

    // 10. Finality Window
    function test_OP_FINALITY_WINDOW_TRUNCATION() public {
        TargetFinalityWindowMutant mutant = new TargetFinalityWindowMutant();
        TargetFinalityWindowControl control = new TargetFinalityWindowControl();
        uint256 proposal = block.timestamp;

        // Mutant allows immediate finalization
        assertTrue(mutant.finalize(proposal));

        // Control blocks premature finalization
        vm.expectRevert("Challenge window still active");
        control.finalize(proposal);

        vm.warp(block.timestamp + 8 days);
        assertTrue(control.finalize(proposal));
    }
}
