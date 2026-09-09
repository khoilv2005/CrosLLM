// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0 <0.9.0;

import "forge-std/Test.sol";
import "../contracts/MockERC20.sol";

contract HyperlaneMailbox {
    uint32 public immutable localDomain;
    uint32 public nonce;
    mapping(bytes32 => bool) public delivered;
    mapping(address => bool) public authorizedIsm;

    event Dispatch(address indexed sender, uint32 destination, bytes32 recipient, bytes message);
    event Process(uint32 origin, bytes32 sender, address recipient);

    constructor(uint32 _localDomain) {
        localDomain = _localDomain;
    }

    function dispatch(uint32 destination, bytes32 recipient, bytes calldata body) external returns (bytes32) {
        nonce++;
        bytes32 messageId = keccak256(abi.encodePacked(localDomain, msg.sender, destination, recipient, nonce, body));
        emit Dispatch(msg.sender, destination, recipient, body);
        return messageId;
    }

    function process(bytes calldata metadata, bytes calldata message) external {
        (uint32 origin, bytes32 sender, uint32 dest, address recipient, bytes memory body) = abi.decode(
            message, (uint32, bytes32, uint32, address, bytes)
        );
        require(dest == localDomain, "Invalid destination domain");
        bytes32 messageId = keccak256(message);
        require(!delivered[messageId], "Message already delivered");
        delivered[messageId] = true;

        (bool success,) = recipient.call(abi.encodeWithSignature("handle(uint32,bytes32,bytes)", origin, sender, body));
        require(success, "Handle execution failed");
        emit Process(origin, sender, recipient);
    }
}

contract HyperlaneReceiver {
    address public immutable mailbox;
    uint256 public receivedMessages;

    constructor(address _mailbox) {
        mailbox = _mailbox;
    }

    function handle(uint32, bytes32, bytes calldata) external {
        require(msg.sender == mailbox, "Unauthorized mailbox caller");
        receivedMessages++;
    }
}

contract HyperlanePairedHarnessTest is Test {
    HyperlaneMailbox public srcMailbox;
    HyperlaneMailbox public dstMailbox;
    HyperlaneReceiver public receiver;

    uint32 public constant SRC_DOMAIN = 1;
    uint32 public constant DST_DOMAIN = 42161;

    function setUp() public {
        vm.chainId(SRC_DOMAIN);
        srcMailbox = new HyperlaneMailbox(SRC_DOMAIN);

        vm.chainId(DST_DOMAIN);
        dstMailbox = new HyperlaneMailbox(DST_DOMAIN);
        receiver = new HyperlaneReceiver(address(dstMailbox));
    }

    function test_normal_cross_chain_lifecycle() public {
        vm.chainId(SRC_DOMAIN);
        bytes memory body = abi.encode("crossllm_hyperlane_payload");
        bytes32 recipientBytes = bytes32(uint256(uint160(address(receiver))));
        bytes32 msgId = srcMailbox.dispatch(DST_DOMAIN, recipientBytes, body);
        assertTrue(msgId != bytes32(0), "Invalid messageId");

        // Relayer relays to destination
        vm.chainId(DST_DOMAIN);
        bytes memory formattedMsg = abi.encode(SRC_DOMAIN, bytes32(uint256(uint160(address(this)))), DST_DOMAIN, address(receiver), body);
        dstMailbox.process("", formattedMsg);

        assertEq(receiver.receivedMessages(), 1, "Receiver should have processed 1 message");
        assertTrue(dstMailbox.delivered(keccak256(formattedMsg)), "Message should be marked delivered");
    }

    function test_revert_replay_execution() public {
        vm.chainId(DST_DOMAIN);
        bytes memory body = abi.encode("replay_test");
        bytes memory formattedMsg = abi.encode(SRC_DOMAIN, bytes32(uint256(uint160(address(this)))), DST_DOMAIN, address(receiver), body);
        
        dstMailbox.process("", formattedMsg);
        vm.expectRevert("Message already delivered");
        dstMailbox.process("", formattedMsg);
    }

    function test_revert_unauthorized_caller() public {
        vm.chainId(DST_DOMAIN);
        vm.expectRevert("Unauthorized mailbox caller");
        receiver.handle(SRC_DOMAIN, bytes32(0), "");
    }
}
