// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "forge-std/Test.sol";
import "../contracts/L1/L1ScrollMessenger.sol";
import "../contracts/L2/L2ScrollMessenger.sol";
import "../contracts/libraries/common/AddressAliasHelper.sol";

/// @dev Test-only queue boundary. It preserves the exact selectors consumed
/// by the source messengers and records the L1/L2 enqueue inputs.
contract ScrollQueueProbe {
    uint256 public nextCrossDomainMessageIndex;
    uint256 public nextMessageIndex;
    uint256 public lastGasLimit;
    address public lastTarget;
    bytes32 public lastMessageHash;
    bytes public lastMessageData;

    function estimateCrossDomainMessageFee(uint256) external pure returns (uint256) {
        return 0;
    }

    function appendCrossDomainMessage(address target, uint256 gasLimit, bytes calldata data) external {
        lastTarget = target;
        lastGasLimit = gasLimit;
        lastMessageData = data;
        nextCrossDomainMessageIndex += 1;
    }

    function appendMessage(bytes32 messageHash) external returns (bytes32) {
        lastMessageHash = messageHash;
        nextMessageIndex += 1;
        return messageHash;
    }
}

contract ScrollRelayReceiver {
    uint256 public received;
    bytes public lastPayload;

    function receiveMessage(bytes calldata payload) external {
        received += 1;
        lastPayload = payload;
    }
}

/// @dev The source messengers disable their implementations. This proxy keeps
/// that constructor lock intact while initializing isolated proxy storage.
contract ScrollMessengerProxy {
    address private immutable implementation;

    constructor(address implementation_, bytes memory initializationData) {
        implementation = implementation_;
        (bool ok, bytes memory returndata) = implementation_.delegatecall(initializationData);
        if (!ok) {
            assembly {
                revert(add(returndata, 32), mload(returndata))
            }
        }
    }

    fallback() external payable {
        address target = implementation;
        assembly {
            calldatacopy(0, 0, calldatasize())
            let ok := delegatecall(gas(), target, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch ok
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }

    receive() external payable {}
}

contract ScrollSourceBackedHarnessTest is Test {
    L1ScrollMessenger public l1Messenger;
    L2ScrollMessenger public l2Messenger;
    ScrollQueueProbe public l1Queue;
    ScrollQueueProbe public l2Queue;
    ScrollRelayReceiver public receiver;

    address public user = address(0x101);
    address public l1Counterpart = address(0x1111);

    function setUp() public {
        l1Queue = new ScrollQueueProbe();
        l2Queue = new ScrollQueueProbe();
        receiver = new ScrollRelayReceiver();

        L1ScrollMessenger l1Implementation = new L1ScrollMessenger(
            l1Counterpart,
            address(0),
            address(l1Queue),
            address(l1Queue),
            address(0)
        );
        l1Messenger = L1ScrollMessenger(
            payable(address(
                new ScrollMessengerProxy(
                    address(l1Implementation),
                    abi.encodeWithSelector(
                        L1ScrollMessenger.initialize.selector,
                        l1Counterpart,
                        address(0),
                        address(0),
                        address(0)
                    )
                )
            ))
        );

        L2ScrollMessenger l2Implementation = new L2ScrollMessenger(address(l1Messenger), address(l2Queue));
        l2Messenger = L2ScrollMessenger(
            payable(address(
                new ScrollMessengerProxy(
                    address(l2Implementation),
                    abi.encodeWithSelector(L2ScrollMessenger.initialize.selector, address(l1Messenger))
                )
            ))
        );
    }

    function test_normal_source_backed_l1_enqueue() public {
        bytes memory payload = hex"aabbcc";
        uint256 gasLimit = 120_000;

        vm.prank(user);
        l1Messenger.sendMessage(address(receiver), 0, payload, gasLimit);

        bytes memory expected = abi.encodeWithSignature(
            "relayMessage(address,address,uint256,uint256,bytes)",
            user,
            address(receiver),
            0,
            0,
            payload
        );
        assertEq(l1Queue.nextCrossDomainMessageIndex(), 1, "L1 queue nonce increments");
        assertEq(l1Queue.lastTarget(), l1Counterpart, "L1 routes to immutable counterpart");
        assertEq(l1Queue.lastGasLimit(), gasLimit, "L1 gas limit is preserved");
        assertEq(l1Queue.lastMessageData(), expected, "L1 relay calldata is encoded by source");
        assertGt(l1Messenger.messageSendTimestamp(keccak256(expected)), 0, "L1 message is recorded");
    }

    function test_normal_source_backed_l2_enqueue() public {
        bytes memory payload = hex"11223344";
        uint256 gasLimit = 90_000;

        vm.prank(user);
        l2Messenger.sendMessage(address(receiver), 0, payload, gasLimit);

        bytes memory expected = abi.encodeWithSignature(
            "relayMessage(address,address,uint256,uint256,bytes)",
            user,
            address(receiver),
            0,
            0,
            payload
        );
        assertEq(l2Queue.nextMessageIndex(), 1, "L2 queue nonce increments");
        assertEq(l2Queue.lastMessageHash(), keccak256(expected), "L2 stores source message hash");
        assertGt(l2Messenger.messageSendTimestamp(keccak256(expected)), 0, "L2 message is recorded");
    }

    function test_source_backed_l2_alias_relay_and_replay_guard() public {
        bytes memory payload = abi.encodeWithSelector(ScrollRelayReceiver.receiveMessage.selector, hex"cafebabe");
        bytes32 messageHash = keccak256(
            abi.encodeWithSignature(
                "relayMessage(address,address,uint256,uint256,bytes)",
                l1Messenger,
                address(receiver),
                0,
                7,
                payload
            )
        );
        address aliasedMessenger = AddressAliasHelper.applyL1ToL2Alias(address(l1Messenger));

        vm.prank(aliasedMessenger);
        l2Messenger.relayMessage(address(l1Messenger), address(receiver), 0, 7, payload);

        assertEq(receiver.received(), 1, "authorized alias reaches receiver");
        assertEq(l2Messenger.isL1MessageExecuted(messageHash), true, "successful relay is terminal");

        vm.prank(aliasedMessenger);
        vm.expectRevert();
        l2Messenger.relayMessage(address(l1Messenger), address(receiver), 0, 7, payload);
    }

    function test_revert_source_backed_l2_relay_wrong_authority() public {
        bytes memory payload = abi.encodeWithSelector(ScrollRelayReceiver.receiveMessage.selector, hex"01");

        vm.prank(user);
        vm.expectRevert();
        l2Messenger.relayMessage(address(l1Messenger), address(receiver), 0, 8, payload);
    }
}
