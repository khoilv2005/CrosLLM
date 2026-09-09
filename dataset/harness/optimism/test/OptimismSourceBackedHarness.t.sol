// SPDX-License-Identifier: MIT
pragma solidity 0.8.15;

import "forge-std/Test.sol";
import "../contracts/packages/contracts-bedrock/src/L1/L1CrossDomainMessenger.sol";
import "../contracts/packages/contracts-bedrock/interfaces/L1/IOptimismPortal2.sol";
import "../contracts/packages/contracts-bedrock/interfaces/L1/ISystemConfig.sol";

contract OptimismProxyAdminProbe {
    address public immutable owner;

    constructor(address owner_) {
        owner = owner_;
    }

}

contract OptimismSystemConfigProbe {
    function paused() external pure returns (bool) { return false; }
    function superchainConfig() external pure returns (ISuperchainConfig) {
        return ISuperchainConfig(address(0));
    }

    function owner() external pure returns (address) { return address(0); }
}

contract OptimismPortalDepositProbe {
    address public lastTo;
    uint256 public lastValue;
    uint64 public lastGasLimit;
    bool public lastIsCreation;
    bytes public lastData;
    uint256 public depositCalls;

    function depositTransaction(
        address to,
        uint256 value,
        uint64 gasLimit,
        bool isCreation,
        bytes memory data
    ) external payable {
        lastTo = to;
        lastValue = value;
        lastGasLimit = gasLimit;
        lastIsCreation = isCreation;
        lastData = data;
        depositCalls++;
    }
}

contract OptimismStorageProxy {
    bytes32 private constant IMPLEMENTATION_SLOT =
        0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;
    bytes32 private constant PROXY_OWNER_SLOT =
        0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103;

    constructor(address implementation, address proxyAdmin) {
        assembly {
            sstore(IMPLEMENTATION_SLOT, implementation)
            sstore(PROXY_OWNER_SLOT, proxyAdmin)
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
}

contract OptimismSourceBackedHarnessTest is Test {
    L1CrossDomainMessenger public messenger;
    OptimismProxyAdminProbe public proxyAdmin;
    OptimismSystemConfigProbe public systemConfig;
    OptimismPortalDepositProbe public portal;

    address public constant OWNER = address(0x101);
    address public constant USER = address(0x202);
    address public constant TARGET = address(0x303);

    function setUp() public {
        L1CrossDomainMessenger implementation = new L1CrossDomainMessenger();
        proxyAdmin = new OptimismProxyAdminProbe(OWNER);
        systemConfig = new OptimismSystemConfigProbe();
        portal = new OptimismPortalDepositProbe();
        OptimismStorageProxy proxy = new OptimismStorageProxy(address(implementation), address(proxyAdmin));
        messenger = L1CrossDomainMessenger(address(proxy));

        vm.prank(OWNER);
        messenger.initialize(ISystemConfig(address(systemConfig)), IOptimismPortal2(payable(address(portal))));
    }

    function test_normal_source_backed_message_deposit() public {
        bytes memory message = hex"1234567890";
        uint256 value = 0.25 ether;
        uint32 minGasLimit = 100_000;
        vm.deal(USER, value);

        vm.prank(USER);
        messenger.sendMessage{value: value}(TARGET, message, minGasLimit);

        assertEq(portal.depositCalls(), 1);
        assertEq(portal.lastValue(), value);
        assertFalse(portal.lastIsCreation());
        assertGt(portal.lastGasLimit(), minGasLimit);
        assertEq(messenger.messageNonce(), (uint256(1) << 240) | 1);
        assertTrue(portal.lastData().length > 0);
    }

    function test_source_backed_proxy_initialization_and_owner_boundary() public {
        assertEq(messenger.proxyAdminOwner(), OWNER);
        assertEq(address(messenger.proxyAdmin()), address(proxyAdmin));
        assertEq(address(messenger.portal()), address(portal));
        assertEq(address(messenger.systemConfig()), address(systemConfig));
        assertEq(address(messenger.otherMessenger()), address(0x4200000000000000000000000000000000000007));
    }

    function test_source_backed_rejects_unauthorized_initialization() public {
        L1CrossDomainMessenger implementation = new L1CrossDomainMessenger();
        OptimismProxyAdminProbe secondAdmin = new OptimismProxyAdminProbe(OWNER);
        OptimismStorageProxy proxy = new OptimismStorageProxy(address(implementation), address(secondAdmin));
        L1CrossDomainMessenger secondMessenger = L1CrossDomainMessenger(address(proxy));

        vm.prank(USER);
        vm.expectRevert();
        secondMessenger.initialize(ISystemConfig(address(systemConfig)), IOptimismPortal2(payable(address(portal))));
    }
}
