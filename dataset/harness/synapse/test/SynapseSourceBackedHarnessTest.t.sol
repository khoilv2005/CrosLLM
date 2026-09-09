// SPDX-License-Identifier: MIT
pragma solidity 0.6.12;

import "../contracts/SynapseMockERC20.sol";
import "../contracts/bridge/SynapseBridge.sol";

interface Vm {
    function startPrank(address sender) external;
    function stopPrank() external;
    function prank(address sender) external;
    function expectRevert(bytes calldata message) external;
}

contract SynapseSourceBackedHarnessTest {
    SynapseMockERC20 public sourceToken;
    SynapseMockERC20 public destinationToken;
    SynapseBridge public sourceBridge;
    SynapseBridge public destinationBridge;

    address payable public user = address(0x101);
    address public nodeGroup = address(0x202);
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function setUp() public {
        sourceToken = new SynapseMockERC20();
        destinationToken = new SynapseMockERC20();
        sourceBridge = new SynapseBridge();
        destinationBridge = new SynapseBridge();

        sourceBridge.initialize();
        destinationBridge.initialize();
        destinationBridge.grantRole(destinationBridge.NODEGROUP_ROLE(), nodeGroup);
        sourceToken.mint(user, 1000 ether);
    }

    function test_normal_source_backed_deposit_and_node_mint() public {
        vm.startPrank(user);
        sourceToken.approve(address(sourceBridge), 100 ether);
        sourceBridge.deposit(user, 2, IERC20(address(sourceToken)), 100 ether);
        vm.stopPrank();

        assertEq(sourceToken.balanceOf(address(sourceBridge)), 100 ether, "source escrow must hold deposit");

        bytes32 kappa = keccak256("synapse_source_backed_01");
        vm.prank(nodeGroup);
        destinationBridge.mint(user, IERC20Mintable(address(destinationToken)), 100 ether, 1 ether, kappa);

        assertEq(destinationToken.balanceOf(user), 99 ether, "user receives net minted amount");
        assertEq(destinationToken.balanceOf(address(destinationBridge)), 1 ether, "fee remains in bridge");
        assertEq(destinationBridge.getFeeBalance(address(destinationToken)), 1 ether, "fee accounting");
        assertEq(destinationToken.totalSupply(), 100 ether, "minted amount is conserved");
        assertTrue(destinationBridge.kappaExists(kappa), "kappa must be marked executed");
    }

    function test_revert_source_backed_kappa_replay() public {
        bytes32 kappa = keccak256("synapse_source_backed_02");
        vm.prank(nodeGroup);
        destinationBridge.mint(user, IERC20Mintable(address(destinationToken)), 50 ether, 1 ether, kappa);

        vm.prank(nodeGroup);
        vm.expectRevert(bytes("Kappa is already present"));
        destinationBridge.mint(user, IERC20Mintable(address(destinationToken)), 50 ether, 1 ether, kappa);
    }

    function test_revert_source_backed_unauthorized_node() public {
        vm.prank(user);
        vm.expectRevert(bytes("Caller is not a node group"));
        destinationBridge.mint(user, IERC20Mintable(address(destinationToken)), 10 ether, 1 ether, keccak256("unauthorized"));
    }

    function assertEq(uint256 actual, uint256 expected, string memory message) internal pure {
        require(actual == expected, message);
    }

    function assertTrue(bool condition, string memory message) internal pure {
        require(condition, message);
    }
}
