// SPDX-License-Identifier: GPL-3.0-only
pragma solidity >=0.8.0 <0.9.0;

import "forge-std/Test.sol";
import "../contracts/CBridge.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract SourceMutationProbeToken is ERC20 {
    constructor() ERC20("Source Mutation Token", "SMT") {}

    function mint(address account, uint256 amount) external {
        _mint(account, amount);
    }
}

contract SourceMutationProbeTest is Test {
    CBridge private bridge;
    SourceMutationProbeToken private token;
    address private constant SENDER = address(0x1111);
    address private constant RECEIVER = address(0x2222);
    uint256 private constant AMOUNT = 100 ether;
    uint64 private constant FUTURE_TIMELOCK = 7 days;
    bytes32 private constant HASHLOCK = keccak256("source-backed-mutation");

    function setUp() public {
        bridge = new CBridge();
        token = new SourceMutationProbeToken();
        token.mint(SENDER, 1000 ether);
        vm.prank(SENDER);
        token.approve(address(bridge), type(uint256).max);
    }

    function _transferId(uint64 timelock) internal returns (bytes32) {
        vm.prank(SENDER);
        bridge.transferOut(
            RECEIVER,
            address(token),
            AMOUNT,
            HASHLOCK,
            uint64(block.timestamp) + timelock,
            42161,
            RECEIVER
        );
        return keccak256(abi.encodePacked(SENDER, RECEIVER, HASHLOCK, block.chainid));
    }

    function test_replay_nonce_control() public {
        _transferId(1000);
        vm.prank(SENDER);
        vm.expectRevert("transfer exists");
        bridge.transferOut(
            RECEIVER,
            address(token),
            AMOUNT,
            HASHLOCK,
            uint64(block.timestamp) + 1000,
            42161,
            RECEIVER
        );
        assertEq(token.balanceOf(address(bridge)), AMOUNT);
    }

    function test_replay_nonce_mutant() public {
        _transferId(1000);
        vm.prank(SENDER);
        bridge.transferOut(
            RECEIVER,
            address(token),
            AMOUNT,
            HASHLOCK,
            uint64(block.timestamp) + 1000,
            42161,
            RECEIVER
        );
        assertEq(token.balanceOf(address(bridge)), AMOUNT * 2);
    }

    function test_finality_window_control() public {
        bytes32 id = _transferId(FUTURE_TIMELOCK);
        vm.expectRevert("timelock not yet passed");
        bridge.refund(id);
    }

    function test_finality_window_mutant() public {
        bytes32 id = _transferId(FUTURE_TIMELOCK);
        bridge.refund(id);
        (, , , , , , CBridge.TransferStatus status) = bridge.transfers(id);
        assertTrue(status == CBridge.TransferStatus.Refunded);
        assertEq(token.balanceOf(SENDER), 1000 ether);
    }
}
