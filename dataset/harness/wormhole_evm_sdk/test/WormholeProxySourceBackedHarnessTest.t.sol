// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {Proxy} from "../contracts/proxy/Proxy.sol";
import {implementationState} from "../contracts/proxy/Eip1967Implementation.sol";

contract WormholeProxyHarnessLogic {
    uint256 public value;

    function checkedUpgrade(bytes calldata data) external {
        if (implementationState().initialized) revert("already initialized");
        implementationState().initialized = true;
        value = abi.decode(data, (uint256));
    }

    function setValue(uint256 nextValue) external {
        value = nextValue;
    }
}

contract WormholeProxyHarnessBadLogic {}

contract WormholeProxySourceBackedHarnessTest is Test {
    function test_proxy_initialization_and_delegation() public {
        WormholeProxyHarnessLogic logic = new WormholeProxyHarnessLogic();
        Proxy proxy = new Proxy(address(logic), abi.encode(uint256(17)));

        assertEq(WormholeProxyHarnessLogic(address(proxy)).value(), 17);
        WormholeProxyHarnessLogic(address(proxy)).setValue(23);
        assertEq(WormholeProxyHarnessLogic(address(proxy)).value(), 23);
    }

    function test_revert_when_logic_lacks_checked_upgrade() public {
        WormholeProxyHarnessBadLogic logic = new WormholeProxyHarnessBadLogic();

        vm.expectRevert();
        new Proxy(address(logic), abi.encode(uint256(1)));
    }
}
