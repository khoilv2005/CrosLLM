// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import "forge-std/Test.sol";
import "../contracts/AgglayerBridge.sol";
import "../contracts/MockERC20.sol";

/// @dev Boundary double for the proxy-admin owner lookup performed by the
/// exact AgglayerBridge initializer.
contract PolygonProxyAdminProbe {
    address public immutable owner;

    constructor(address owner_) {
        owner = owner_;
    }
}

/// @dev Minimal EIP-1967 proxy used only to provide the storage context and
/// admin slot required by AgglayerBridge._setProxiedTokensManagerFromProxy.
contract PolygonBridgeProxy {
    bytes32 private constant ADMIN_SLOT =
        0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103;
    bytes32 private constant IMPLEMENTATION_SLOT =
        0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    constructor(address implementation, address admin, bytes memory initData) {
        assembly {
            sstore(ADMIN_SLOT, admin)
            sstore(IMPLEMENTATION_SLOT, implementation)
        }
        (bool success, bytes memory returndata) = implementation.delegatecall(initData);
        if (!success) {
            assembly {
                revert(add(returndata, 0x20), mload(returndata))
            }
        }
    }

    fallback() external payable {
        assembly {
            let implementation := sload(IMPLEMENTATION_SLOT)
            calldatacopy(0, 0, calldatasize())
            let success := delegatecall(gas(), implementation, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch success
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }

    receive() external payable {}
}

contract PolygonZkEVMSourcedBridgeHarnessTest is Test {
    AgglayerBridge public bridge;
    MockERC20 public token;
    PolygonProxyAdminProbe public proxyAdmin;

    address public constant USER = address(0x101);
    address public constant PROXY_OWNER = address(0x202);
    uint256 public constant AMOUNT = 100 ether;

    function setUp() public {
        AgglayerBridge implementation = new AgglayerBridge();
        proxyAdmin = new PolygonProxyAdminProbe(PROXY_OWNER);
        bytes memory initData = abi.encodeCall(
            AgglayerBridge.initialize,
            (
                uint32(0),
                address(0),
                uint32(0),
                IBaseLegacyAgglayerGER(address(0)),
                address(0),
                bytes("")
            )
        );
        PolygonBridgeProxy proxy = new PolygonBridgeProxy(
            address(implementation),
            address(proxyAdmin),
            initData
        );
        bridge = AgglayerBridge(address(proxy));

        token = new MockERC20("Polygon source token", "PST");
        token.mint(USER, AMOUNT);
    }

    function test_normal_source_backed_asset_escrow_and_leaf() public {
        bytes32 rootBefore = bridge.getRoot();

        vm.startPrank(USER);
        token.approve(address(bridge), AMOUNT);
        bridge.bridgeAsset(1, USER, AMOUNT, address(token), false, "");
        vm.stopPrank();

        assertEq(bridge.networkID(), 0);
        assertEq(bridge.depositCount(), 1);
        assertEq(token.balanceOf(address(bridge)), AMOUNT);
        assertEq(token.balanceOf(USER), 0);
        assertTrue(bridge.getRoot() != rootBefore);
    }

    function test_source_backed_rejects_same_network_destination() public {
        vm.startPrank(USER);
        token.approve(address(bridge), AMOUNT);
        vm.expectRevert();
        bridge.bridgeAsset(0, USER, AMOUNT, address(token), false, "");
        vm.stopPrank();

        assertEq(bridge.depositCount(), 0);
        assertEq(token.balanceOf(address(bridge)), 0);
    }

    function test_source_backed_rejects_msg_value_for_erc20() public {
        vm.deal(USER, 1 ether);
        vm.startPrank(USER);
        vm.expectRevert();
        bridge.bridgeAsset{value: 1}(1, USER, 1, address(token), false, "");
        vm.stopPrank();

        assertEq(bridge.depositCount(), 0);
        assertEq(token.balanceOf(address(bridge)), 0);
    }
}
