// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0 <0.9.0;

import "forge-std/Test.sol";
import "../contracts/CBridge.sol";
import "../contracts/MockERC20.sol";

contract CBridgePairedHarnessTest is Test {
    CBridge public cBridgeSource;
    CBridge public cBridgeDest;
    MockERC20 public tokenSource;
    MockERC20 public tokenDest;

    address public userSender = address(0x1111111111111111111111111111111111111111);
    address public bridgeRelayer = address(0x2222222222222222222222222222222222222222);
    address public userReceiver = address(0x3333333333333333333333333333333333333333);

    uint64 public constant SRC_CHAIN_ID = 1;
    uint64 public constant DST_CHAIN_ID = 42161;
    uint256 public constant TRANSFER_AMOUNT = 100 * 1e18;
    uint256 public constant INITIAL_BALANCE = 1000 * 1e18;

    bytes32 public secretPreimage = keccak256("crossllm_celer_secret_preimage_2026");
    bytes32 public hashlock;

    event LogNewTransferOut(
        bytes32 transferId,
        address sender,
        address receiver,
        address token,
        uint256 amount,
        bytes32 hashlock,
        uint64 timelock,
        uint64 dstChainId,
        address dstAddress
    );

    event LogNewTransferIn(
        bytes32 transferId,
        address sender,
        address receiver,
        address token,
        uint256 amount,
        bytes32 hashlock,
        uint64 timelock,
        uint64 srcChainId,
        bytes32 srcTransferId
    );

    event LogTransferConfirmed(bytes32 transferId, bytes32 preimage);
    event LogTransferRefunded(bytes32 transferId);

    function setUp() public {
        hashlock = keccak256(abi.encodePacked(secretPreimage));

        // Deploy Source domain contracts
        vm.chainId(SRC_CHAIN_ID);
        cBridgeSource = new CBridge();
        tokenSource = new MockERC20("Celer Mock Source Token", "CELR_SRC");

        // Deploy Destination domain contracts
        cBridgeDest = new CBridge();
        tokenDest = new MockERC20("Celer Mock Dest Token", "CELR_DST");

        // Fund accounts
        tokenSource.mint(userSender, INITIAL_BALANCE);
        tokenDest.mint(bridgeRelayer, INITIAL_BALANCE);
    }

    function assertTransferPending(CBridge bridge, bytes32 transferId, address expectedSender, address expectedReceiver, uint256 expectedAmount) internal {
        (address sender, address receiver, , uint256 amount, , , CBridge.TransferStatus status) = bridge.transfers(transferId);
        assertEq(sender, expectedSender, "Sender mismatch");
        assertEq(receiver, expectedReceiver, "Receiver mismatch");
        assertEq(amount, expectedAmount, "Amount mismatch");
        assertTrue(status == CBridge.TransferStatus.Pending, "Transfer status should be Pending");
    }

    function assertTransferConfirmed(CBridge bridge, bytes32 transferId) internal {
        (, , , , , , CBridge.TransferStatus status) = bridge.transfers(transferId);
        assertTrue(status == CBridge.TransferStatus.Confirmed, "Transfer status should be Confirmed");
    }

    function test_normal_cross_chain_transfer_and_confirm() public {
        uint64 timelock = uint64(block.timestamp + 3600);

        // ==========================================
        // Phase 1: Source Chain - transferOut
        // ==========================================
        vm.chainId(SRC_CHAIN_ID);
        vm.startPrank(userSender);
        tokenSource.approve(address(cBridgeSource), TRANSFER_AMOUNT);

        bytes32 expectedSrcTransferId = keccak256(
            abi.encodePacked(userSender, bridgeRelayer, hashlock, uint256(SRC_CHAIN_ID))
        );

        vm.expectEmit(true, true, true, true);
        emit LogNewTransferOut(
            expectedSrcTransferId,
            userSender,
            bridgeRelayer,
            address(tokenSource),
            TRANSFER_AMOUNT,
            hashlock,
            timelock,
            DST_CHAIN_ID,
            userReceiver
        );

        cBridgeSource.transferOut(
            bridgeRelayer,
            address(tokenSource),
            TRANSFER_AMOUNT,
            hashlock,
            timelock,
            DST_CHAIN_ID,
            userReceiver
        );
        vm.stopPrank();

        // Verify Source state after transferOut
        assertEq(tokenSource.balanceOf(userSender), INITIAL_BALANCE - TRANSFER_AMOUNT, "Sender source balance reduced");
        assertEq(tokenSource.balanceOf(address(cBridgeSource)), TRANSFER_AMOUNT, "Source bridge holds locked tokens");
        assertTransferPending(cBridgeSource, expectedSrcTransferId, userSender, bridgeRelayer, TRANSFER_AMOUNT);

        // ==========================================
        // Phase 2: Destination Chain - transferIn
        // ==========================================
        vm.chainId(DST_CHAIN_ID);
        vm.startPrank(bridgeRelayer);
        tokenDest.approve(address(cBridgeDest), TRANSFER_AMOUNT);

        bytes32 expectedDstTransferId = keccak256(
            abi.encodePacked(bridgeRelayer, userReceiver, hashlock, uint256(DST_CHAIN_ID))
        );

        vm.expectEmit(true, true, true, true);
        emit LogNewTransferIn(
            expectedDstTransferId,
            bridgeRelayer,
            userReceiver,
            address(tokenDest),
            TRANSFER_AMOUNT,
            hashlock,
            timelock,
            SRC_CHAIN_ID,
            expectedSrcTransferId
        );

        cBridgeDest.transferIn(
            userReceiver,
            address(tokenDest),
            TRANSFER_AMOUNT,
            hashlock,
            timelock,
            SRC_CHAIN_ID,
            expectedSrcTransferId
        );
        vm.stopPrank();

        // Verify Destination state after transferIn
        assertEq(tokenDest.balanceOf(bridgeRelayer), INITIAL_BALANCE - TRANSFER_AMOUNT, "Relayer dest balance reduced");
        assertEq(tokenDest.balanceOf(address(cBridgeDest)), TRANSFER_AMOUNT, "Dest bridge holds locked tokens");
        assertTransferPending(cBridgeDest, expectedDstTransferId, bridgeRelayer, userReceiver, TRANSFER_AMOUNT);

        // ==========================================
        // Phase 3: Destination Chain - confirm with preimage
        // ==========================================
        vm.startPrank(userReceiver);
        vm.expectEmit(true, false, false, true);
        emit LogTransferConfirmed(expectedDstTransferId, secretPreimage);

        cBridgeDest.confirm(expectedDstTransferId, secretPreimage);
        vm.stopPrank();

        // Verify Destination state after confirm
        assertEq(tokenDest.balanceOf(userReceiver), TRANSFER_AMOUNT, "Receiver claimed tokens on dest");
        assertEq(tokenDest.balanceOf(address(cBridgeDest)), 0, "Dest bridge has zero remaining balance");
        assertTransferConfirmed(cBridgeDest, expectedDstTransferId);

        // ==========================================
        // Phase 4: Source Chain - confirm with preimage
        // ==========================================
        vm.chainId(SRC_CHAIN_ID);
        vm.startPrank(bridgeRelayer);
        vm.expectEmit(true, false, false, true);
        emit LogTransferConfirmed(expectedSrcTransferId, secretPreimage);

        cBridgeSource.confirm(expectedSrcTransferId, secretPreimage);
        vm.stopPrank();

        // Verify Source state after confirm
        assertEq(tokenSource.balanceOf(bridgeRelayer), TRANSFER_AMOUNT, "Relayer claimed tokens on source");
        assertEq(tokenSource.balanceOf(address(cBridgeSource)), 0, "Source bridge has zero remaining balance");
        assertTransferConfirmed(cBridgeSource, expectedSrcTransferId);

        // ==========================================
        // Global Invariant Assertions
        // ==========================================
        assertEq(
            tokenSource.balanceOf(userSender) + tokenSource.balanceOf(bridgeRelayer),
            INITIAL_BALANCE,
            "Source token conservation invariant strictly holds"
        );
        assertEq(
            tokenDest.balanceOf(bridgeRelayer) + tokenDest.balanceOf(userReceiver),
            INITIAL_BALANCE,
            "Dest token conservation invariant strictly holds"
        );
    }

    function test_transfer_timeout_and_refund() public {
        uint64 timelock = uint64(block.timestamp + 1800);

        vm.chainId(SRC_CHAIN_ID);
        vm.startPrank(userSender);
        tokenSource.approve(address(cBridgeSource), TRANSFER_AMOUNT);

        bytes32 transferId = keccak256(
            abi.encodePacked(userSender, bridgeRelayer, hashlock, uint256(SRC_CHAIN_ID))
        );

        cBridgeSource.transferOut(
            bridgeRelayer,
            address(tokenSource),
            TRANSFER_AMOUNT,
            hashlock,
            timelock,
            DST_CHAIN_ID,
            userReceiver
        );

        // Before timelock: refund should revert
        vm.expectRevert("timelock not yet passed");
        cBridgeSource.refund(transferId);

        // Fast-forward past timelock
        vm.warp(timelock + 1);

        // Now refund succeeds
        vm.expectEmit(true, false, false, false);
        emit LogTransferRefunded(transferId);
        cBridgeSource.refund(transferId);
        vm.stopPrank();

        // Verify tokens returned to sender
        assertEq(tokenSource.balanceOf(userSender), INITIAL_BALANCE, "Sender balance fully restored on refund");
        assertEq(tokenSource.balanceOf(address(cBridgeSource)), 0, "Bridge balance zero after refund");

        (
            ,
            ,
            ,
            ,
            ,
            ,
            CBridge.TransferStatus status
        ) = cBridgeSource.transfers(transferId);
        assertTrue(status == CBridge.TransferStatus.Refunded, "Status should be Refunded");
    }

    function test_revert_confirm_incorrect_preimage() public {
        uint64 timelock = uint64(block.timestamp + 3600);

        vm.chainId(SRC_CHAIN_ID);
        vm.startPrank(userSender);
        tokenSource.approve(address(cBridgeSource), TRANSFER_AMOUNT);

        bytes32 transferId = keccak256(
            abi.encodePacked(userSender, bridgeRelayer, hashlock, uint256(SRC_CHAIN_ID))
        );

        cBridgeSource.transferOut(
            bridgeRelayer,
            address(tokenSource),
            TRANSFER_AMOUNT,
            hashlock,
            timelock,
            DST_CHAIN_ID,
            userReceiver
        );
        vm.stopPrank();

        bytes32 wrongPreimage = keccak256("wrong_preimage_attack");
        vm.expectRevert("incorrect preimage");
        cBridgeSource.confirm(transferId, wrongPreimage);
    }
}
