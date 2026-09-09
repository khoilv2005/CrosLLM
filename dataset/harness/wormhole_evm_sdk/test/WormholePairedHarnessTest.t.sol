// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0 <0.9.0;

import "forge-std/Test.sol";

contract MockWormholeRelayer {
    mapping(bytes32 => bool) public isDelivered;

    event SendEvent(uint16 targetChain, address targetAddress, bytes payload, bytes32 deliveryHash);

    function sendPayloadToEvm(uint16 targetChain, address targetAddress, bytes calldata payload) external returns (bytes32) {
        bytes32 deliveryHash = keccak256(abi.encode(targetChain, targetAddress, payload, block.timestamp));
        emit SendEvent(targetChain, targetAddress, payload, deliveryHash);
        return deliveryHash;
    }

    function deliver(address target, bytes calldata payload, bytes32 deliveryHash) external {
        require(!isDelivered[deliveryHash], "Payload already delivered");
        isDelivered[deliveryHash] = true;
        (bool ok,) = target.call(abi.encodeWithSignature("receiveWormholeMessages(bytes,bytes32)", payload, deliveryHash));
        require(ok, "Delivery execution failed");
    }
}

contract WormholeReceiverApp {
    address public immutable relayer;
    uint256 public messageCount;

    constructor(address _relayer) {
        relayer = _relayer;
    }

    function receiveWormholeMessages(bytes calldata, bytes32) external {
        require(msg.sender == relayer, "Unauthorized relayer caller");
        messageCount++;
    }
}

contract WormholePairedHarnessTest is Test {
    MockWormholeRelayer public relayer;
    WormholeReceiverApp public app;

    function setUp() public {
        relayer = new MockWormholeRelayer();
        app = new WormholeReceiverApp(address(relayer));
    }

    function test_normal_cross_chain_lifecycle() public {
        bytes memory payload = abi.encode("wormhole_test_message");
        bytes32 h = relayer.sendPayloadToEvm(2, address(app), payload);
        relayer.deliver(address(app), payload, h);
        assertEq(app.messageCount(), 1, "App received message");
        assertTrue(relayer.isDelivered(h), "Delivery hash recorded");
    }

    function test_revert_replay_execution() public {
        bytes memory payload = abi.encode("replay");
        bytes32 h = keccak256("wh_hash_1");
        relayer.deliver(address(app), payload, h);

        vm.expectRevert("Payload already delivered");
        relayer.deliver(address(app), payload, h);
    }

    function test_revert_unauthorized_caller() public {
        vm.expectRevert("Unauthorized relayer caller");
        app.receiveWormholeMessages(abi.encode("bad"), keccak256("bad"));
    }
}
