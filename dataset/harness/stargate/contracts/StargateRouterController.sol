// SPDX-License-Identifier: MIT
pragma solidity 0.7.6;
pragma abicoder v2;

import "../contracts/Bridge.sol";
import "../contracts/Pool.sol";

contract StargateRouterController {
    address public authorizedBridge;
    Pool public configuredPool;

    function setAuthorizedBridge(address bridge) external {
        authorizedBridge = bridge;
    }

    function configurePool(Pool pool, uint16 destinationChainId, uint256 destinationPoolId) external {
        configuredPool = pool;
        pool.createChainPath(destinationChainId, destinationPoolId, 1);
        pool.activateChainPath(destinationChainId, destinationPoolId);
        pool.setDeltaParam(true, 0, 10000, true, true);
    }

    function addLiquidity(Pool pool, address token, uint256 amount, address to) external {
        (bool success, bytes memory data) = token.call(
            abi.encodeWithSelector(bytes4(keccak256("transferFrom(address,address,uint256)")), msg.sender, address(pool), amount)
        );
        require(success && (data.length == 0 || abi.decode(data, (bool))), "Stargate: transferFrom failed");
        pool.mint(to, amount);
    }

    function callDelta(Pool pool) external {
        pool.callDelta(true);
    }

    function sendCredits(
        Bridge bridge,
        Pool pool,
        uint16 destinationChainId,
        uint256 sourcePoolId,
        uint256 destinationPoolId,
        address payable refundAddress
    ) external {
        Pool.CreditObj memory credit = pool.sendCredits(destinationChainId, destinationPoolId);
        bridge.sendCredits(destinationChainId, sourcePoolId, destinationPoolId, refundAddress, credit);
    }

    function creditChainPath(
        uint16 destinationChainId,
        uint256 destinationPoolId,
        uint256 sourcePoolId,
        Pool.CreditObj memory credit
    ) external {
        require(msg.sender == authorizedBridge, "Stargate: unauthorized bridge");
        configuredPool.creditChainPath(destinationChainId, destinationPoolId, credit);
        sourcePoolId;
    }
}
