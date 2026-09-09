// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import {AxelarAmplifierGateway} from "../contracts/gateway/AxelarAmplifierGateway.sol";
import {AxelarAmplifierGatewayProxy} from "../contracts/gateway/AxelarAmplifierGatewayProxy.sol";
import {CommandType, Message} from "../contracts/types/AmplifierGatewayTypes.sol";
import {Proof, WeightedSigner, WeightedSigners} from "../contracts/types/WeightedMultisigTypes.sol";

contract AxelarHarnessRecipient {
    function consume(
        AxelarAmplifierGateway gateway,
        string calldata sourceChain,
        string calldata messageId,
        string calldata sourceAddress,
        bytes32 payloadHash
    ) external returns (bool) {
        return gateway.validateMessage(sourceChain, messageId, sourceAddress, payloadHash);
    }
}

contract AxelarSourceBackedHarnessTest is Test {
    uint256 internal constant SIGNER_KEY = 0xA11CE;
    bytes32 internal constant DOMAIN_SEPARATOR = keccak256("crossllm-axelar-development-domain");

    AxelarAmplifierGateway internal gateway;
    AxelarHarnessRecipient internal recipient;
    address internal signer;

    function setUp() public {
        signer = vm.addr(SIGNER_KEY);
        AxelarAmplifierGateway implementation = new AxelarAmplifierGateway(
            0,
            DOMAIN_SEPARATOR,
            0
        );

        WeightedSigners memory signers = _currentSigners();
        WeightedSigners[] memory signerSets = new WeightedSigners[](1);
        signerSets[0] = signers;
        bytes memory setupParams = abi.encode(address(this), signerSets);

        gateway = AxelarAmplifierGateway(
            address(new AxelarAmplifierGatewayProxy(address(implementation), address(this), setupParams))
        );
        recipient = new AxelarHarnessRecipient();

        assertEq(gateway.owner(), address(this));
        assertEq(gateway.epoch(), 1);
    }

    function test_outbound_and_approved_message_lifecycle() public {
        bytes memory payload = bytes("crossllm-axelar-payload");
        gateway.callContract("Arbitrum", "0x1234", payload);

        bytes32 payloadHash = keccak256(payload);
        _approveMessage("message-1", payloadHash);

        assertTrue(
            gateway.isMessageApproved(
                "Ethereum",
                "message-1",
                "0xsource",
                address(recipient),
                payloadHash
            )
        );

        bool valid = recipient.consume(
            gateway,
            "Ethereum",
            "message-1",
            "0xsource",
            payloadHash
        );
        assertTrue(valid);
        assertTrue(gateway.isMessageExecuted("Ethereum", "message-1"));

        bool replay = recipient.consume(
            gateway,
            "Ethereum",
            "message-1",
            "0xsource",
            payloadHash
        );
        assertFalse(replay);
    }

    function test_revert_on_invalid_weighted_proof() public {
        Message[] memory messages = new Message[](1);
        messages[0] = Message({
            sourceChain: "Ethereum",
            messageId: "message-invalid-proof",
            sourceAddress: "0xsource",
            contractAddress: address(recipient),
            payloadHash: keccak256(bytes("payload"))
        });
        bytes[] memory signatures = new bytes[](0);

        vm.expectRevert();
        gateway.approveMessages(messages, Proof({signers: _currentSigners(), signatures: signatures}));
    }

    function _approveMessage(string memory messageId, bytes32 payloadHash) internal {
        Message[] memory messages = new Message[](1);
        messages[0] = Message({
            sourceChain: "Ethereum",
            messageId: messageId,
            sourceAddress: "0xsource",
            contractAddress: address(recipient),
            payloadHash: payloadHash
        });
        WeightedSigners memory signers = _currentSigners();
        bytes32 dataHash = keccak256(abi.encode(CommandType.ApproveMessages, messages));
        bytes32 signersHash = keccak256(abi.encode(signers));
        bytes32 signedHash = gateway.messageHashToSign(signersHash, dataHash);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(SIGNER_KEY, signedHash);
        bytes[] memory signatures = new bytes[](1);
        signatures[0] = abi.encodePacked(r, s, v);
        gateway.approveMessages(messages, Proof({signers: signers, signatures: signatures}));
    }

    function _currentSigners() internal view returns (WeightedSigners memory signers) {
        WeightedSigner[] memory entries = new WeightedSigner[](1);
        entries[0] = WeightedSigner({signer: signer, weight: 1});
        signers = WeightedSigners({signers: entries, threshold: 1, nonce: bytes32(uint256(1))});
    }
}
