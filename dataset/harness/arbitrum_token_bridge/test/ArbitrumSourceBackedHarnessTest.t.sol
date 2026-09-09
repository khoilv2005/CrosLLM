// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.16;

import "forge-std/Test.sol";
import "../contracts/MockERC20.sol";
import {L1GatewayRouter} from "../contracts/tokenbridge/ethereum/gateway/L1GatewayRouter.sol";
import {L2GatewayRouter} from "../contracts/tokenbridge/arbitrum/gateway/L2GatewayRouter.sol";
import {AddressAliasHelper} from "../contracts/tokenbridge/libraries/AddressAliasHelper.sol";

interface ArbitrumERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// @dev The selected router contracts delegate token custody and message
/// delivery to protocol gateway contracts. This bounded probe supplies a
/// transparent gateway double so the exact routers, caller encoding and route
/// authorization are exercised without pretending to emulate Arbitrum Nitro.
contract ArbitrumGatewayProbe {
    address public immutable counterpartGateway;
    address public immutable custodyToken;
    address public immutable remoteToken;
    uint256 public outboundCount;
    address public lastFrom;
    address public lastTo;
    uint256 public lastAmount;
    bytes public lastData;

    constructor(address counterpartGateway_, address custodyToken_, address remoteToken_) {
        counterpartGateway = counterpartGateway_;
        custodyToken = custodyToken_;
        remoteToken = remoteToken_;
    }

    function outboundTransfer(
        address token,
        address to,
        uint256 amount,
        uint256,
        uint256,
        bytes calldata data
    ) external payable returns (bytes memory) {
        (address from, bytes memory userData) = abi.decode(data, (address, bytes));
        require(ArbitrumERC20(custodyToken).transferFrom(from, address(this), amount), "gateway escrow failed");
        outboundCount++;
        lastFrom = from;
        lastTo = to;
        lastAmount = amount;
        lastData = userData;
        return abi.encode(outboundCount);
    }

    function finalizeInboundTransfer(address, address, address, uint256, bytes calldata) external payable {}

    function calculateL2TokenAddress(address) external view returns (address) {
        return remoteToken;
    }

    function getOutboundCalldata(address, address, address, uint256, bytes memory data)
        external
        pure
        returns (bytes memory)
    {
        return data;
    }
}

contract ArbitrumSourceBackedHarnessTest is Test {
    MockERC20 public l1Token;
    MockERC20 public l2Token;
    L1GatewayRouter public l1Router;
    L2GatewayRouter public l2Router;
    ArbitrumGatewayProbe public l1Gateway;
    ArbitrumGatewayProbe public l2Gateway;

    address public user = address(0x101);
    address public owner = address(0x202);
    address public eve = address(0x303);
    uint256 internal constant TRANSFER_AMOUNT = 50 ether;

    function setUp() public {
        l1Token = new MockERC20("Arbitrum L1 Token", "L1T");
        l2Token = new MockERC20("Arbitrum L2 Token", "L2T");
        l1Router = new L1GatewayRouter();
        l2Router = new L2GatewayRouter();
        l1Gateway = new ArbitrumGatewayProbe(address(l2Router), address(l1Token), address(l2Token));
        l2Gateway = new ArbitrumGatewayProbe(address(l1Router), address(l2Token), address(l1Token));

        vm.prank(owner);
        l1Router.initialize(owner, address(l1Gateway), address(0), address(l2Router), address(0x999));
        l2Router.initialize(address(l1Router), address(l2Gateway));

        l1Token.mint(user, 500 ether);
        l2Token.mint(user, 500 ether);
    }

    function test_normal_source_backed_router_routes_l1_deposit() public {
        bytes memory payload = abi.encode("l1-to-l2", uint256(7));
        vm.startPrank(user);
        l1Token.approve(address(l1Gateway), TRANSFER_AMOUNT);
        l1Router.outboundTransfer(address(l1Token), user, TRANSFER_AMOUNT, 0, 0, payload);
        vm.stopPrank();

        assertEq(l1Gateway.outboundCount(), 1, "L1 gateway called once");
        assertEq(l1Gateway.lastFrom(), user, "router preserves original caller");
        assertEq(l1Gateway.lastTo(), user, "router preserves recipient");
        assertEq(l1Gateway.lastAmount(), TRANSFER_AMOUNT, "router preserves amount");
        assertEq(keccak256(l1Gateway.lastData()), keccak256(payload), "router preserves user data");
        assertEq(l1Token.balanceOf(address(l1Gateway)), TRANSFER_AMOUNT, "gateway escrows L1 tokens");
    }

    function test_normal_source_backed_router_routes_l2_withdrawal() public {
        bytes memory payload = abi.encode("l2-to-l1", uint256(9));
        vm.startPrank(user);
        l2Token.approve(address(l2Gateway), TRANSFER_AMOUNT);
        l2Router.outboundTransfer(address(l1Token), user, TRANSFER_AMOUNT, payload);
        vm.stopPrank();

        assertEq(l2Gateway.outboundCount(), 1, "L2 gateway called once");
        assertEq(l2Gateway.lastFrom(), user, "L2 router preserves original caller");
        assertEq(l2Gateway.lastTo(), user, "L2 router preserves recipient");
        assertEq(l2Gateway.lastAmount(), TRANSFER_AMOUNT, "L2 router preserves amount");
        assertEq(keccak256(l2Gateway.lastData()), keccak256(payload), "L2 router preserves user data");
        assertEq(l2Token.balanceOf(address(l2Gateway)), TRANSFER_AMOUNT, "gateway escrows L2 tokens");
    }

    function test_revert_wrong_l2_route_authority_and_accept_alias() public {
        address[] memory tokens = new address[](1);
        address[] memory gateways = new address[](1);
        tokens[0] = address(l1Token);
        gateways[0] = address(l1Gateway);

        vm.prank(eve);
        vm.expectRevert("ONLY_COUNTERPART_GATEWAY");
        l2Router.setGateway(tokens, gateways);

        address l1RouterAlias = AddressAliasHelper.applyL1ToL2Alias(address(l1Router));
        vm.prank(l1RouterAlias);
        l2Router.setGateway(tokens, gateways);
        assertEq(l2Router.getGateway(address(l1Token)), address(l1Gateway), "aliased counterpart may set route");
    }
}
