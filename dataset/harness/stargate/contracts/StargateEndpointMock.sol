// SPDX-License-Identifier: MIT
pragma solidity 0.7.6;

interface IStargateBridgeReceiver {
    function lzReceive(
        uint16 srcChainId,
        bytes calldata srcAddress,
        uint64 nonce,
        bytes calldata payload
    ) external;
}

contract StargateEndpointMock {
    uint64 public outboundNonce;
    bytes public lastDestination;
    bytes public lastPayload;

    function getOutboundNonce(uint16, address) external view returns (uint64) {
        return outboundNonce;
    }

    function send(
        uint16,
        bytes calldata destination,
        bytes calldata payload,
        address payable,
        address,
        bytes calldata
    ) external payable {
        outboundNonce = outboundNonce + 1;
        lastDestination = destination;
        lastPayload = payload;
    }

    function deliver(
        address bridge,
        uint16 srcChainId,
        bytes calldata srcAddress,
        uint64 nonce,
        bytes calldata payload
    ) external {
        IStargateBridgeReceiver(bridge).lzReceive(srcChainId, srcAddress, nonce, payload);
    }
}
