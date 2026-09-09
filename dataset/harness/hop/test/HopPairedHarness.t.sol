// SPDX-License-Identifier: MIT
pragma solidity 0.6.12;
pragma experimental ABIEncoderV2;

import "forge-std/Test.sol";
import "../contracts/test/Mock_L1_Bridge.sol";
import "../contracts/test/Mock_L2_Bridge.sol";
import "../contracts/test/MockERC20.sol";
import "../contracts/bridges/BonderRegistry.sol";
import "../contracts/bridges/HopBridgeToken.sol";
import "../contracts/bridges/SwapDataConsumer.sol";

contract HopPairedHarnessTest is Test, SwapDataConsumer {
    MockERC20 public canonicalToken;
    Mock_L1_Bridge public l1Bridge;
    BonderRegistry public bonderRegistry;

    HopBridgeToken public hToken;
    Mock_L2_Bridge public l2Bridge;

    uint256 public constant L1_CHAIN_ID = 1;
    uint256 public constant L2_CHAIN_ID = 2;

    address public governance = address(0xAD);
    address public bonder = address(0xB04D);
    address public alice = address(0xAAA);
    address public bob = address(0xBBB);
    address public eve = address(0xEEE);

    uint256 public constant INITIAL_ALICE = 1000 ether;
    uint256 public constant BONDER_COLLATERAL = 5000 ether;
    uint256 public constant TRANSFER_AMOUNT = 200 ether;

    function setUp() public {
        vm.startPrank(governance);

        // 1. Deploy L1 Infrastructure
        canonicalToken = new MockERC20("Canonical DAI", "DAI");

        address[] memory initialBonders = new address[](1);
        initialBonders[0] = bonder;
        bonderRegistry = new BonderRegistry(initialBonders);

        l1Bridge = new Mock_L1_Bridge(IBonderRegistry(address(bonderRegistry)), address(canonicalToken));

        // 2. Deploy L2 Infrastructure
        hToken = new HopBridgeToken("Hop DAI", "hDAI", 18);

        uint256[] memory activeChainIds = new uint256[](1);
        activeChainIds[0] = L1_CHAIN_ID;

        l2Bridge = new Mock_L2_Bridge(
            L2_CHAIN_ID,
            hToken,
            activeChainIds,
            IBonderRegistry(address(bonderRegistry))
        );

        // Transfer hToken ownership to l2Bridge for mint/burn
        hToken.transferOwnership(address(l2Bridge));

        // 3. Connect L1 and L2 bridges
        l1Bridge.setXDomainConnector(L2_CHAIN_ID, address(l2Bridge));
        l2Bridge.setL1BridgeConnector(address(l1Bridge));

        // 4. Fund Alice and Bonder
        canonicalToken.mint(alice, INITIAL_ALICE);
        canonicalToken.mint(bonder, BONDER_COLLATERAL);

        vm.stopPrank();

        // Alice approves L1 bridge
        vm.prank(alice);
        canonicalToken.approve(address(l1Bridge), type(uint256).max);

        // Bonder approves L1 bridge and stakes collateral
        vm.startPrank(bonder);
        canonicalToken.approve(address(l1Bridge), type(uint256).max);
        l1Bridge.stake(bonder, BONDER_COLLATERAL);
        vm.stopPrank();
    }

    function test_normal_l1_to_l2_transfer() public {
        SwapData memory swapData = SwapData({
            tokenIndex: 0,
            amountOutMin: 0,
            deadline: 0
        });

        // Alice sends 200 DAI from L1 to L2 for Bob
        vm.prank(alice);
        l1Bridge.sendToL2(L2_CHAIN_ID, bob, TRANSFER_AMOUNT, swapData, address(0), 0);

        // 1. Assert L1 State
        assertEq(canonicalToken.balanceOf(alice), INITIAL_ALICE - TRANSFER_AMOUNT, "Alice L1 balance deducted");
        assertEq(canonicalToken.balanceOf(address(l1Bridge)), BONDER_COLLATERAL + TRANSFER_AMOUNT, "L1 bridge holds canonical tokens");
        assertEq(l1Bridge.chainBalance(L2_CHAIN_ID), TRANSFER_AMOUNT, "L1 bridge recorded chainBalance for L2");

        // 2. Assert L2 State
        assertEq(hToken.balanceOf(bob), TRANSFER_AMOUNT, "Bob received hTokens on L2");
        assertEq(hToken.totalSupply(), TRANSFER_AMOUNT, "Total supply of hToken matches bridged amount");

        // 3. Invariants
        // Token conservation: Canonical tokens deposited in L1 Bridge == hToken total supply on L2
        assertEq(canonicalToken.balanceOf(address(l1Bridge)) - BONDER_COLLATERAL, hToken.totalSupply(), "Total supply matches bridge deposit");
        // Global system conservation
        uint256 totalCanonical = canonicalToken.balanceOf(alice) + canonicalToken.balanceOf(bonder) + canonicalToken.balanceOf(address(l1Bridge));
        assertEq(totalCanonical, INITIAL_ALICE + BONDER_COLLATERAL, "Global token conservation");
    }

    function test_revert_send_to_unsupported_chain() public {
        SwapData memory swapData = SwapData({tokenIndex: 0, amountOutMin: 0, deadline: 0});
        uint256 unsupportedChainId = 999;

        vm.prank(alice);
        vm.expectRevert("L1_BRG: chainId not supported");
        l1Bridge.sendToL2(unsupportedChainId, bob, TRANSFER_AMOUNT, swapData, address(0), 0);
    }

    function test_revert_send_zero_amount() public {
        SwapData memory swapData = SwapData({tokenIndex: 0, amountOutMin: 0, deadline: 0});

        vm.prank(alice);
        vm.expectRevert("L1_BRG: Must transfer a non-zero amount");
        l1Bridge.sendToL2(L2_CHAIN_ID, bob, 0, swapData, address(0), 0);
    }

    function test_revert_unauthorized_distribute() public {
        SwapData memory swapData = SwapData({tokenIndex: 0, amountOutMin: 0, deadline: 0});

        vm.prank(eve);
        vm.expectRevert("L2_BRG: xDomain caller must be L1 Bridge");
        l2Bridge.distribute(bob, TRANSFER_AMOUNT, swapData, address(0), 0);
    }

    function test_revert_send_when_chain_paused() public {
        SwapData memory swapData = SwapData({tokenIndex: 0, amountOutMin: 0, deadline: 0});

        vm.prank(governance);
        l1Bridge.setChainIdDepositsPaused(L2_CHAIN_ID, true);

        vm.prank(alice);
        vm.expectRevert("L1_BRG: Sends to this chainId are paused");
        l1Bridge.sendToL2(L2_CHAIN_ID, bob, TRANSFER_AMOUNT, swapData, address(0), 0);
    }
}