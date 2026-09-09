// SPDX-License-Identifier: MIT
pragma solidity 0.7.6;
pragma abicoder v2;

import "../contracts/MockERC20.sol";
import "../contracts/StargateEndpointMock.sol";
import "../contracts/StargateRouterController.sol";
import "../contracts/Bridge.sol";
import "../contracts/Pool.sol";

interface StargateVm {
    function startPrank(address sender) external;
    function stopPrank() external;
    function prank(address sender) external;
    function expectRevert(bytes calldata message) external;
}

contract StargateSourceBackedHarnessTest {
    MockERC20 public sourceToken;
    MockERC20 public destinationToken;
    StargateEndpointMock public endpoint;
    StargateRouterController public sourceController;
    StargateRouterController public destinationController;
    Bridge public sourceBridge;
    Bridge public destinationBridge;
    Pool public sourcePool;
    Pool public destinationPool;

    address payable public user = address(0x101);
    StargateVm internal constant vm = StargateVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function setUp() public {
        sourceToken = new MockERC20();
        destinationToken = new MockERC20();
        endpoint = new StargateEndpointMock();
        sourceController = new StargateRouterController();
        destinationController = new StargateRouterController();

        sourceBridge = deployBridge(address(endpoint), address(sourceController));
        destinationBridge = deployBridge(address(endpoint), address(destinationController));
        sourcePool = deployPool(address(sourceController), address(sourceToken), "Source LP", "SLP_SRC");
        destinationPool = deployPool(address(destinationController), address(destinationToken), "Destination LP", "SLP_DST");

        sourceController.configurePool(sourcePool, 2, 1);
        destinationController.configurePool(destinationPool, 1, 1);
        destinationController.setAuthorizedBridge(address(destinationBridge));
        sourceBridge.setBridge(2, abi.encodePacked(address(destinationBridge)));
        destinationBridge.setBridge(1, abi.encodePacked(address(sourceBridge)));
        sourceToken.mint(user, 1000 ether);
    }

    function deployBridge(address endpointAddress, address controller) internal returns (Bridge bridge) {
        bytes memory initCode = abi.encodePacked(type(Bridge).creationCode, abi.encode(endpointAddress, controller));
        address deployed;
        assembly {
            deployed := create(0, add(initCode, 32), mload(initCode))
        }
        require(deployed != address(0), "bridge deployment failed");
        return Bridge(deployed);
    }

    function deployPool(
        address controller,
        address token,
        string memory poolName,
        string memory poolSymbol
    ) internal returns (Pool pool) {
        bytes memory initCode = abi.encodePacked(
            type(Pool).creationCode,
            abi.encode(uint256(1), controller, token, uint256(18), uint256(18), address(1), poolName, poolSymbol)
        );
        address deployed;
        assembly {
            deployed := create(0, add(initCode, 32), mload(initCode))
        }
        require(deployed != address(0), "pool deployment failed");
        return Pool(deployed);
    }

    function test_normal_source_backed_liquidity_credit_delivery() public {
        vm.startPrank(user);
        sourceToken.approve(address(sourceController), 100 ether);
        sourceController.addLiquidity(sourcePool, address(sourceToken), 100 ether, user);
        vm.stopPrank();

        require(sourceToken.balanceOf(address(sourcePool)) == 100 ether, "source pool must hold liquidity");
        require(sourcePool.balanceOf(user) == 100 ether, "user receives source LP tokens");

        sourceController.callDelta(sourcePool);
        sourceController.sendCredits(sourceBridge, sourcePool, 2, 1, 1, user);
        require(endpoint.outboundNonce() == 1, "endpoint must record one outbound message");

        endpoint.deliver(
            address(destinationBridge),
            1,
            abi.encodePacked(address(sourceBridge)),
            1,
            endpoint.lastPayload()
        );

        Pool.ChainPath memory destinationPath = destinationPool.getChainPath(1, 1);
        require(destinationPath.balance == 100 ether, "destination credit must be recorded");
        require(destinationPath.idealBalance == 100 ether, "destination ideal balance must match");
        Pool.ChainPath memory sourcePath = sourcePool.getChainPath(2, 1);
        require(sourcePath.lkb == 100 ether && sourcePath.credits == 0, "source credits must be committed");
    }

    function test_revert_source_backed_direct_lz_receive() public {
        vm.prank(user);
        vm.expectRevert(bytes("Stargate: only LayerZero endpoint can call lzReceive"));
        destinationBridge.lzReceive(1, abi.encodePacked(address(sourceBridge)), 1, bytes("invalid"));
    }

    function test_revert_source_backed_wrong_bridge_binding() public {
        Pool.CreditObj memory credit = Pool.CreditObj(100 ether, 100 ether);
        bytes memory payload = abi.encode(uint8(2), uint256(1), uint256(1), credit);
        vm.expectRevert(bytes("Stargate: bridge does not match"));
        endpoint.deliver(address(destinationBridge), 1, abi.encodePacked(address(0xBEEF)), 1, payload);
    }
}
