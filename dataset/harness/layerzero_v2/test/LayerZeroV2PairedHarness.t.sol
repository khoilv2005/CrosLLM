// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../contracts/EndpointV2.sol";
import "../contracts/messagelib/SimpleMessageLib.sol";
import "../contracts/interfaces/ILayerZeroEndpointV2.sol";
import "../contracts/interfaces/ILayerZeroReceiver.sol";
import "../contracts/libs/Errors.sol";

contract MockReceiver is ILayerZeroReceiver {
    bytes public lastMessage;
    bytes32 public lastGuid;
    uint32 public lastSrcEid;
    bytes32 public lastSender;
    uint64 public messageCount;

    function allowInitializePath(Origin calldata) external pure override returns (bool) {
        return true;
    }

    function nextNonce(uint32, bytes32) external pure override returns (uint64) {
        return 0;
    }

    function lzReceive(
        Origin calldata origin,
        bytes32 guid,
        bytes calldata message,
        address,
        bytes calldata
    ) external payable override {
        lastMessage = message;
        lastGuid = guid;
        lastSrcEid = origin.srcEid;
        lastSender = origin.sender;
        messageCount++;
    }
}

contract LayerZeroV2PairedHarnessTest is Test {
    EndpointV2 public endpointSrc;
    EndpointV2 public endpointDst;
    SimpleMessageLib public msgLibSrc;
    SimpleMessageLib public msgLibDst;
    MockReceiver public receiver;

    uint32 public constant EID_SRC = 1;
    uint32 public constant EID_DST = 2;

    address public admin = address(0xAD);
    address public treasury = address(0x777);
    address public alice = address(0xAAA);
    address public eve = address(0xEEE);

    bytes public constant TEST_PAYLOAD = "CrossLLM Research Payload - LayerZero V2 Verification";

    function setUp() public {
        vm.deal(alice, 10 ether);
        vm.deal(admin, 10 ether);

        vm.startPrank(admin);
        // 1. Deploy Domain 1 (Source)
        endpointSrc = new EndpointV2(EID_SRC, admin);
        msgLibSrc = new SimpleMessageLib(address(endpointSrc), treasury);
        endpointSrc.registerLibrary(address(msgLibSrc));
        endpointSrc.setDefaultSendLibrary(EID_DST, address(msgLibSrc));
        endpointSrc.setDefaultReceiveLibrary(EID_DST, address(msgLibSrc), 0);

        // 2. Deploy Domain 2 (Destination)
        endpointDst = new EndpointV2(EID_DST, admin);
        msgLibDst = new SimpleMessageLib(address(endpointDst), treasury);
        endpointDst.registerLibrary(address(msgLibDst));
        endpointDst.setDefaultSendLibrary(EID_SRC, address(msgLibDst));
        endpointDst.setDefaultReceiveLibrary(EID_SRC, address(msgLibDst), 0);

        // 3. Deploy Receiver Application on Destination
        receiver = new MockReceiver();
        vm.stopPrank();
    }

    function _addressToBytes32(address addr) internal pure returns (bytes32) {
        return bytes32(uint256(uint160(addr)));
    }

    function test_normal_cross_chain_message_send_and_deliver() public {
        bytes32 receiverB32 = _addressToBytes32(address(receiver));
        bytes32 senderB32 = _addressToBytes32(alice);

        MessagingParams memory params = MessagingParams({
            dstEid: EID_DST,
            receiver: receiverB32,
            message: TEST_PAYLOAD,
            options: "",
            payInLzToken: false
        });

        // 1. Quote Fee
        MessagingFee memory fee = endpointSrc.quote(params, alice);
        assertEq(fee.nativeFee, 100, "Native fee matches SimpleMessageLib rate");
        assertEq(fee.lzTokenFee, 0, "No LZ token fee");

        // 2. Alice Sends Message with 250 wei (100 fee + 150 excess refund)
        uint256 alicePreBalance = alice.balance;
        vm.prank(alice);
        MessagingReceipt memory receipt = endpointSrc.send{ value: 250 }(params, payable(alice));

        // Assert Step 1 & 2 Accounting Invariants
        assertEq(receipt.nonce, 1, "Nonce starts at 1");
        assertEq(receipt.fee.nativeFee, 100, "Receipt native fee is 100");
        assertEq(alice.balance, alicePreBalance - 100, "Alice refunded 150 wei");
        assertEq(address(msgLibSrc).balance, 100, "MessageLib received 100 wei fee");
        assertEq(address(endpointSrc).balance, 0, "Zero stranded funds in source endpoint");

        // 3. Packet Verification on Destination Domain
        Origin memory origin = Origin({
            srcEid: EID_SRC,
            sender: senderB32,
            nonce: receipt.nonce
        });

        bytes32 guid = receipt.guid;
        bytes memory fullPayload = abi.encodePacked(guid, TEST_PAYLOAD);
        bytes32 payloadHash = keccak256(fullPayload);

        // Relayer submits verification via msgLibDst
        vm.prank(address(msgLibDst));
        endpointDst.verify(origin, address(receiver), payloadHash);

        assertEq(
            endpointDst.inboundPayloadHash(address(receiver), EID_SRC, senderB32, receipt.nonce),
            payloadHash,
            "Inbound payload hash verified"
        );

        // 4. Packet Delivery (lzReceive execution)
        endpointDst.lzReceive(origin, address(receiver), guid, TEST_PAYLOAD, "");

        // Assert Step 3 & 4 State Invariants
        assertEq(
            endpointDst.inboundPayloadHash(address(receiver), EID_SRC, senderB32, receipt.nonce),
            bytes32(0),
            "Payload hash cleared upon delivery (anti-reentrancy & anti-replay)"
        );
        assertEq(receiver.messageCount(), 1, "Receiver processed 1 message");
        assertEq(receiver.lastMessage(), TEST_PAYLOAD, "Receiver payload matches sent message");
        assertEq(receiver.lastGuid(), guid, "Receiver GUID matches receipt");
        assertEq(receiver.lastSrcEid(), EID_SRC, "Receiver srcEid matches Domain 1");
        assertEq(receiver.lastSender(), senderB32, "Receiver sender matches Alice");
    }

    function test_revert_insufficient_send_fee() public {
        bytes32 receiverB32 = _addressToBytes32(address(receiver));
        MessagingParams memory params = MessagingParams({
            dstEid: EID_DST,
            receiver: receiverB32,
            message: TEST_PAYLOAD,
            options: "",
            payInLzToken: false
        });

        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(Errors.LZ_InsufficientFee.selector, 100, 50, 0, 0));
        endpointSrc.send{ value: 50 }(params, payable(alice));
    }

    function test_revert_unauthorized_receive_library() public {
        Origin memory origin = Origin({
            srcEid: EID_SRC,
            sender: _addressToBytes32(alice),
            nonce: 1
        });
        bytes32 dummyHash = keccak256("dummy");

        // Eve is not the registered receive library
        vm.prank(eve);
        vm.expectRevert(Errors.LZ_InvalidReceiveLibrary.selector);
        endpointDst.verify(origin, address(receiver), dummyHash);
    }

    function test_revert_replay_packet_delivery() public {
        bytes32 receiverB32 = _addressToBytes32(address(receiver));
        bytes32 senderB32 = _addressToBytes32(alice);

        MessagingParams memory params = MessagingParams({
            dstEid: EID_DST,
            receiver: receiverB32,
            message: TEST_PAYLOAD,
            options: "",
            payInLzToken: false
        });

        vm.prank(alice);
        MessagingReceipt memory receipt = endpointSrc.send{ value: 100 }(params, payable(alice));

        Origin memory origin = Origin(EID_SRC, senderB32, receipt.nonce);
        bytes memory fullPayload = abi.encodePacked(receipt.guid, TEST_PAYLOAD);
        bytes32 payloadHash = keccak256(fullPayload);

        vm.prank(address(msgLibDst));
        endpointDst.verify(origin, address(receiver), payloadHash);

        // First delivery succeeds
        endpointDst.lzReceive(origin, address(receiver), receipt.guid, TEST_PAYLOAD, "");

        // Second delivery fails because payload hash was already cleared
        vm.expectRevert(abi.encodeWithSelector(Errors.LZ_PayloadHashNotFound.selector, bytes32(0), payloadHash));
        endpointDst.lzReceive(origin, address(receiver), receipt.guid, TEST_PAYLOAD, "");
    }

    function test_revert_tampered_payload_delivery() public {
        bytes32 receiverB32 = _addressToBytes32(address(receiver));
        bytes32 senderB32 = _addressToBytes32(alice);

        MessagingParams memory params = MessagingParams({
            dstEid: EID_DST,
            receiver: receiverB32,
            message: TEST_PAYLOAD,
            options: "",
            payInLzToken: false
        });

        vm.prank(alice);
        MessagingReceipt memory receipt = endpointSrc.send{ value: 100 }(params, payable(alice));

        Origin memory origin = Origin(EID_SRC, senderB32, receipt.nonce);
        bytes memory fullPayload = abi.encodePacked(receipt.guid, TEST_PAYLOAD);
        bytes32 payloadHash = keccak256(fullPayload);

        vm.prank(address(msgLibDst));
        endpointDst.verify(origin, address(receiver), payloadHash);

        // Attempt delivery with altered payload
        bytes memory tamperedMessage = "Tampered Malicious Message";
        bytes32 tamperedHash = keccak256(abi.encodePacked(receipt.guid, tamperedMessage));
        vm.expectRevert(abi.encodeWithSelector(Errors.LZ_PayloadHashNotFound.selector, payloadHash, tamperedHash));
        endpointDst.lzReceive(origin, address(receiver), receipt.guid, tamperedMessage, "");
    }
}