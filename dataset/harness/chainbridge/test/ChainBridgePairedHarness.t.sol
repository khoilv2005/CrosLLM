// SPDX-License-Identifier: LGPL-3.0-only
pragma solidity 0.8.11;

import "forge-std/Test.sol";
import "../contracts/Bridge.sol";
import "../contracts/MockERC20.sol";

interface IERC20HandlerTest {
    function _bridgeAddress() external view returns (address);
    function _resourceIDToTokenContractAddress(bytes32) external view returns (address);
    function _contractWhitelist(address) external view returns (bool);
}

contract ChainBridgePairedHarnessTest is Test {
    Bridge public bridgeSrc;
    Bridge public bridgeDst;
    address public handlerSrc;
    address public handlerDst;
    MockERC20 public tokenSrc;
    MockERC20 public tokenDst;

    uint8 public constant DOMAIN_SRC = 1;
    uint8 public constant DOMAIN_DST = 2;
    uint256 public constant RELAYER_THRESHOLD = 2;
    uint256 public constant FEE = 0;
    uint256 public constant EXPIRY = 100;

    address public admin = address(0xAD);
    address public relayer1 = address(0x111);
    address public relayer2 = address(0x222);
    address public relayer3 = address(0x333);
    address public alice = address(0xAAA);
    address public bob = address(0xBBB);
    address public eve = address(0xEEE);

    bytes32 public resourceID = keccak256("CHAINBRIDGE_ERC20_RESOURCE");

    uint256 public constant INITIAL_ALICE = 1000 ether;
    uint256 public constant INITIAL_DST_LIQUIDITY = 5000 ether;
    uint256 public constant TRANSFER_AMOUNT = 250 ether;

    function setUp() public {
        address[] memory initialRelayers = new address[](3);
        initialRelayers[0] = relayer1;
        initialRelayers[1] = relayer2;
        initialRelayers[2] = relayer3;

        vm.startPrank(admin);
        // Deploy Domain 1
        bridgeSrc = new Bridge(DOMAIN_SRC, initialRelayers, RELAYER_THRESHOLD, FEE, EXPIRY);
        handlerSrc = deployCode("ERC20Handler.sol:ERC20Handler", abi.encode(address(bridgeSrc)));
        tokenSrc = new MockERC20("TokenSrc", "TKS");

        // Deploy Domain 2
        bridgeDst = new Bridge(DOMAIN_DST, initialRelayers, RELAYER_THRESHOLD, FEE, EXPIRY);
        handlerDst = deployCode("ERC20Handler.sol:ERC20Handler", abi.encode(address(bridgeDst)));
        tokenDst = new MockERC20("TokenDst", "TKD");

        // Link Resource ID on both domains
        bridgeSrc.adminSetResource(handlerSrc, resourceID, address(tokenSrc));
        bridgeDst.adminSetResource(handlerDst, resourceID, address(tokenDst));

        // Fund accounts
        tokenSrc.mint(alice, INITIAL_ALICE);
        tokenDst.mint(handlerDst, INITIAL_DST_LIQUIDITY);
        vm.stopPrank();

        // Alice approves source handler
        vm.prank(alice);
        tokenSrc.approve(handlerSrc, type(uint256).max);
    }

    function _buildERCDepositData(uint256 amount, address recipient) internal pure returns (bytes memory) {
        return abi.encodePacked(amount, uint256(20), recipient);
    }

    function test_normal_cross_chain_lock_and_relay() public {
        bytes memory data = _buildERCDepositData(TRANSFER_AMOUNT, bob);

        // 1. Alice deposits on Domain 1 (Source)
        vm.prank(alice);
        bridgeSrc.deposit(DOMAIN_DST, resourceID, data);

        // Assert Domain 1 states
        assertEq(tokenSrc.balanceOf(alice), INITIAL_ALICE - TRANSFER_AMOUNT, "Alice balance deducted on src");
        assertEq(tokenSrc.balanceOf(handlerSrc), TRANSFER_AMOUNT, "Handler locked tokens on src");
        assertEq(bridgeSrc._depositCounts(DOMAIN_DST), 1, "Deposit nonce incremented");

        uint64 depositNonce = 1;

        // 2. Relayer 1 votes on Domain 2 (Destination)
        vm.prank(relayer1);
        bridgeDst.voteProposal(DOMAIN_SRC, depositNonce, resourceID, data);

        bytes32 dataHash = keccak256(abi.encodePacked(handlerDst, data));
        Bridge.Proposal memory p1 = bridgeDst.getProposal(DOMAIN_SRC, depositNonce, dataHash);
        assertEq(uint(p1._status), uint(Bridge.ProposalStatus.Active), "Proposal status Active after 1 vote");
        assertEq(p1._yesVotesTotal, 1, "Yes votes count is 1");
        assertEq(tokenDst.balanceOf(bob), 0, "Bob has not received tokens yet");

        // 3. Relayer 2 votes on Domain 2 -> Threshold reached (2/2) -> auto-executes!
        vm.prank(relayer2);
        bridgeDst.voteProposal(DOMAIN_SRC, depositNonce, resourceID, data);

        Bridge.Proposal memory p2 = bridgeDst.getProposal(DOMAIN_SRC, depositNonce, dataHash);
        assertEq(uint(p2._status), uint(Bridge.ProposalStatus.Executed), "Proposal status Executed after 2 votes");
        assertEq(p2._yesVotesTotal, 2, "Yes votes count is 2");

        // 4. Assert Domain 2 states
        assertEq(tokenDst.balanceOf(bob), TRANSFER_AMOUNT, "Bob received transferred tokens on dst");
        assertEq(tokenDst.balanceOf(handlerDst), INITIAL_DST_LIQUIDITY - TRANSFER_AMOUNT, "Handler released tokens on dst");

        // 5. Assert End-to-End Accounting Invariants
        // Src domain conservation:
        assertEq(tokenSrc.balanceOf(alice) + tokenSrc.balanceOf(handlerSrc), INITIAL_ALICE, "Src token conservation");
        // Dst domain conservation:
        assertEq(tokenDst.balanceOf(bob) + tokenDst.balanceOf(handlerDst), INITIAL_DST_LIQUIDITY, "Dst token conservation");
        // Total global value conserved across domains:
        uint256 totalGlobal = tokenSrc.balanceOf(alice) + tokenSrc.balanceOf(handlerSrc) +
                              tokenDst.balanceOf(bob) + tokenDst.balanceOf(handlerDst);
        assertEq(totalGlobal, INITIAL_ALICE + INITIAL_DST_LIQUIDITY, "Global cross-domain conservation");
    }

    function test_revert_non_relayer_cannot_vote() public {
        bytes memory data = _buildERCDepositData(TRANSFER_AMOUNT, bob);

        vm.prank(eve);
        vm.expectRevert("sender doesn't have relayer role");
        bridgeDst.voteProposal(DOMAIN_SRC, 1, resourceID, data);
    }

    function test_revert_duplicate_relayer_vote() public {
        bytes memory data = _buildERCDepositData(TRANSFER_AMOUNT, bob);

        vm.prank(relayer1);
        bridgeDst.voteProposal(DOMAIN_SRC, 1, resourceID, data);

        vm.prank(relayer1);
        vm.expectRevert("relayer already voted");
        bridgeDst.voteProposal(DOMAIN_SRC, 1, resourceID, data);
    }

    function test_revert_deposit_unmapped_resource() public {
        bytes32 unmappedID = keccak256("UNMAPPED_RESOURCE");
        bytes memory data = _buildERCDepositData(TRANSFER_AMOUNT, bob);

        vm.prank(alice);
        vm.expectRevert("resourceID not mapped to handler");
        bridgeSrc.deposit(DOMAIN_DST, unmappedID, data);
    }

    function test_revert_vote_already_executed_proposal() public {
        bytes memory data = _buildERCDepositData(TRANSFER_AMOUNT, bob);

        vm.prank(alice);
        bridgeSrc.deposit(DOMAIN_DST, resourceID, data);

        uint64 depositNonce = 1;

        vm.prank(relayer1);
        bridgeDst.voteProposal(DOMAIN_SRC, depositNonce, resourceID, data);

        vm.prank(relayer2);
        bridgeDst.voteProposal(DOMAIN_SRC, depositNonce, resourceID, data);

        // Relayer 3 tries to vote on already executed proposal
        vm.prank(relayer3);
        vm.expectRevert("proposal already executed/cancelled");
        bridgeDst.voteProposal(DOMAIN_SRC, depositNonce, resourceID, data);
    }
}