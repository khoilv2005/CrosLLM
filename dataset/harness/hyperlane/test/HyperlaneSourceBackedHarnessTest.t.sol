// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;

import "forge-std/Test.sol";
import {Mailbox} from "../contracts/Mailbox.sol";
import {Message} from "../contracts/libs/Message.sol";
import {TypeCasts} from "../contracts/libs/TypeCasts.sol";
import {IInterchainSecurityModule} from "../contracts/interfaces/IInterchainSecurityModule.sol";
import {IPostDispatchHook} from "../contracts/interfaces/hooks/IPostDispatchHook.sol";
import {IMessageRecipient} from "../contracts/interfaces/IMessageRecipient.sol";

contract HyperlaneHarnessIsm is IInterchainSecurityModule {
    bool public accept = true;

    function setAccept(bool value) external {
        accept = value;
    }

    function moduleType() external pure returns (uint8) {
        return uint8(Types.UNUSED);
    }

    function verify(bytes calldata, bytes calldata) external view returns (bool) {
        return accept;
    }
}

contract HyperlaneHarnessHook is IPostDispatchHook {
    function hookType() external pure returns (uint8) {
        return uint8(HookTypes.UNUSED);
    }

    function supportsMetadata(bytes calldata) external pure returns (bool) {
        return true;
    }

    function postDispatch(bytes calldata, bytes calldata) external payable {}

    function quoteDispatch(bytes calldata, bytes calldata) external pure returns (uint256) {
        return 0;
    }
}

contract HyperlaneHarnessRecipient is IMessageRecipient {
    address public immutable mailbox;
    uint32 public receivedOrigin;
    bytes32 public receivedSender;
    bytes public receivedBody;
    uint256 public callbackCount;

    constructor(address mailbox_) {
        mailbox = mailbox_;
    }

    function handle(uint32 origin, bytes32 sender, bytes calldata body) external payable {
        require(msg.sender == mailbox, "unexpected mailbox");
        receivedOrigin = origin;
        receivedSender = sender;
        receivedBody = body;
        callbackCount += 1;
    }
}

contract HyperlaneHarnessMailbox is Mailbox {
    constructor(uint32 localDomain) Mailbox(localDomain) {}

    function buildMessage(
        uint32 destinationDomain,
        bytes32 recipient,
        bytes calldata body
    ) external view returns (bytes memory) {
        return _buildMessage(destinationDomain, recipient, body);
    }
}

contract HyperlaneSourceBackedHarnessTest is Test {
    using Message for bytes;
    using TypeCasts for address;

    uint32 internal constant SOURCE_DOMAIN = 1;
    uint32 internal constant DESTINATION_DOMAIN = 42161;

    HyperlaneHarnessMailbox internal sourceMailbox;
    HyperlaneHarnessMailbox internal destinationMailbox;
    HyperlaneHarnessIsm internal ism;
    HyperlaneHarnessHook internal hook;
    HyperlaneHarnessRecipient internal recipient;

    function setUp() public {
        ism = new HyperlaneHarnessIsm();
        hook = new HyperlaneHarnessHook();
        sourceMailbox = new HyperlaneHarnessMailbox(SOURCE_DOMAIN);
        destinationMailbox = new HyperlaneHarnessMailbox(DESTINATION_DOMAIN);

        sourceMailbox.initialize(address(this), address(ism), address(hook), address(hook));
        destinationMailbox.initialize(address(this), address(ism), address(hook), address(hook));
        recipient = new HyperlaneHarnessRecipient(address(destinationMailbox));
    }

    function test_normal_cross_chain_message_send_and_process() public {
        bytes memory body = bytes("crossllm_hyperlane_source");
        bytes32 recipientAddress = address(recipient).addressToBytes32();
        bytes memory message = sourceMailbox.buildMessage(DESTINATION_DOMAIN, recipientAddress, body);

        bytes32 dispatchedId = sourceMailbox.dispatch(DESTINATION_DOMAIN, recipientAddress, body);
        assertEq(dispatchedId, message.id());
        assertEq(sourceMailbox.nonce(), 1);

        destinationMailbox.process(bytes("valid-ism-metadata"), message);

        assertTrue(destinationMailbox.delivered(dispatchedId));
        assertEq(destinationMailbox.processor(dispatchedId), address(this));
        assertEq(recipient.callbackCount(), 1);
        assertEq(recipient.receivedOrigin(), SOURCE_DOMAIN);
        assertEq(recipient.receivedSender(), address(this).addressToBytes32());
        assertEq(keccak256(recipient.receivedBody()), keccak256(body));

        vm.expectRevert("Mailbox: already delivered");
        destinationMailbox.process(bytes("valid-ism-metadata"), message);
    }

    function test_revert_when_ism_rejects_message() public {
        bytes memory body = bytes("rejected-message");
        bytes32 recipientAddress = address(recipient).addressToBytes32();
        bytes memory message = sourceMailbox.buildMessage(DESTINATION_DOMAIN, recipientAddress, body);
        sourceMailbox.dispatch(DESTINATION_DOMAIN, recipientAddress, body);

        ism.setAccept(false);
        vm.expectRevert("Mailbox: ISM verification failed");
        destinationMailbox.process(bytes("invalid-ism-metadata"), message);

        assertFalse(destinationMailbox.delivered(message.id()));
        assertEq(recipient.callbackCount(), 0);
    }
}
