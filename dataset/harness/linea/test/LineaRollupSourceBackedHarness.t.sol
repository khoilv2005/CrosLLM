// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "forge-std/Test.sol";
import "../contracts/LineaRollup.sol";

/// @dev Minimal proxy used to exercise the exact upgradeable LineaRollup in
/// its intended delegatecall storage context.
contract LineaRollupProxy {
    bytes32 private constant IMPLEMENTATION_SLOT =
        0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    constructor(address implementation, bytes memory initData) {
        assembly {
            sstore(IMPLEMENTATION_SLOT, implementation)
        }
        (bool success, bytes memory returndata) = implementation.delegatecall(initData);
        if (!success) {
            assembly {
                revert(add(returndata, 0x20), mload(returndata))
            }
        }
    }

    fallback() external payable {
        assembly {
            let implementation := sload(IMPLEMENTATION_SLOT)
            calldatacopy(0, 0, calldatasize())
            let success := delegatecall(gas(), implementation, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch success
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }
}

contract LineaRollupSourceBackedHarnessTest is Test {
    LineaRollup public rollup;

    address public constant USER = address(0x101);
    address public constant SECURITY_COUNCIL = address(0x202);
    address public constant OPERATOR = address(0x303);
    address public constant DEFAULT_VERIFIER = address(0x404);
    address public constant RECIPIENT = address(0x505);
    bytes32 public constant INITIAL_STATE_ROOT = bytes32(uint256(0x1234));
    uint256 public constant INITIAL_L2_BLOCK = 100;

    function setUp() public {
        LineaRollup implementation = new LineaRollup();
        address[] memory operators = new address[](1);
        operators[0] = OPERATOR;

        bytes memory initData = abi.encodeCall(
            LineaRollup.initialize,
            (
                INITIAL_STATE_ROOT,
                INITIAL_L2_BLOCK,
                DEFAULT_VERIFIER,
                SECURITY_COUNCIL,
                operators,
                uint256(3600),
                uint256(100 ether),
                block.timestamp
            )
        );

        LineaRollupProxy proxy = new LineaRollupProxy(address(implementation), initData);
        rollup = LineaRollup(address(proxy));
    }

    function test_normal_source_backed_message_enqueue() public {
        uint256 fee = 0.1 ether;
        uint256 valueSent = 0.9 ether;
        bytes memory messageData = hex"1234567890";
        vm.deal(USER, fee + valueSent);

        vm.prank(USER);
        rollup.sendMessage{value: fee + valueSent}(RECIPIENT, fee, messageData);

        bytes32 messageHash = keccak256(
            abi.encode(USER, RECIPIENT, fee, valueSent, uint256(1), messageData)
        );
        bytes32 expectedRollingHash = keccak256(abi.encode(bytes32(0), messageHash));

        assertEq(rollup.nextMessageNumber(), 2);
        assertEq(rollup.rollingHashes(1), expectedRollingHash);
        assertTrue(expectedRollingHash != bytes32(0));
    }

    function test_source_backed_initialization_sets_roles_and_state() public {
        assertEq(rollup.currentL2BlockNumber(), INITIAL_L2_BLOCK);
        assertEq(rollup.stateRootHashes(INITIAL_L2_BLOCK), INITIAL_STATE_ROOT);
        assertEq(rollup.nextMessageNumber(), 1);
        assertTrue(rollup.hasRole(rollup.DEFAULT_ADMIN_ROLE(), SECURITY_COUNCIL));
        assertTrue(rollup.hasRole(rollup.OPERATOR_ROLE(), OPERATOR));
        assertTrue(rollup.hasRole(rollup.VERIFIER_SETTER_ROLE(), SECURITY_COUNCIL));
    }

    function test_source_backed_rejects_invalid_message_boundaries() public {
        vm.startPrank(USER);
        vm.expectRevert();
        rollup.sendMessage(address(0), 0, "");

        vm.expectRevert();
        rollup.sendMessage{value: 1}(RECIPIENT, 2, "");
        vm.stopPrank();

        assertEq(rollup.nextMessageNumber(), 1);
        assertEq(rollup.rollingHashes(1), bytes32(0));
    }
}
