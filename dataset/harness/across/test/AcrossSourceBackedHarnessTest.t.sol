// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.30;

import "../contracts/spoke-pools/Ethereum_SpokePool.sol";
import "../contracts/interfaces/V3SpokePoolInterface.sol";
import "../contracts/MockERC20.sol";

interface AcrossVm {
    function startPrank(address sender) external;
    function stopPrank() external;
    function prank(address sender) external;
    function expectRevert() external;
}

/// @dev A minimal immutable-implementation proxy keeps the source contract's
/// constructor lock intact while exercising initialize and all state through a
/// separate proxy storage context, as the deployed upgradeable contract expects.
contract AcrossHarnessProxy {
    address private immutable implementation;

    constructor(address implementation_, bytes memory initializationData) {
        implementation = implementation_;
        (bool ok, bytes memory returndata) = implementation_.delegatecall(initializationData);
        if (!ok) {
            assembly {
                revert(add(returndata, 32), mload(returndata))
            }
        }
    }

    fallback() external payable {
        address target = implementation;
        assembly {
            calldatacopy(0, 0, calldatasize())
            let ok := delegatecall(gas(), target, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch ok
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }

    receive() external payable {}
}

contract AcrossSourceBackedHarnessTest {
    Ethereum_SpokePool public sourcePool;
    Ethereum_SpokePool public destinationPool;
    MockERC20 public sourceToken;
    MockERC20 public destinationToken;
    MockERC20 public sourceWrappedNative;
    MockERC20 public destinationWrappedNative;

    address public user = address(0x101);
    address public relayer = address(0x202);
    address public eve = address(0x303);
    AcrossVm internal constant vm = AcrossVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    uint256 internal constant TRANSFER_AMOUNT = 100 ether;
    uint256 internal constant INITIAL_BALANCE = 1000 ether;

    function setUp() public {
        sourceToken = new MockERC20("Across Source Token", "SRC");
        destinationToken = new MockERC20("Across Destination Token", "DST");
        sourceWrappedNative = new MockERC20("Source Wrapped Native", "sWNATIVE");
        destinationWrappedNative = new MockERC20("Destination Wrapped Native", "dWNATIVE");

        Ethereum_SpokePool sourceImplementation = new Ethereum_SpokePool(
            address(sourceWrappedNative),
            1 days,
            1 days,
            address(0)
        );
        Ethereum_SpokePool destinationImplementation = new Ethereum_SpokePool(
            address(destinationWrappedNative),
            1 days,
            1 days,
            address(0)
        );

        sourcePool = Ethereum_SpokePool(
            payable(address(
                new AcrossHarnessProxy(
                    address(sourceImplementation),
                    abi.encodeWithSelector(Ethereum_SpokePool.initialize.selector, 0, address(this))
                )
            ))
        );
        destinationPool = Ethereum_SpokePool(
            payable(address(
                new AcrossHarnessProxy(
                    address(destinationImplementation),
                    abi.encodeWithSelector(Ethereum_SpokePool.initialize.selector, 0, address(this))
                )
            ))
        );

        sourceToken.mint(user, INITIAL_BALANCE);
        destinationToken.mint(relayer, INITIAL_BALANCE);
    }

    function _deposit(uint32 exclusivityParameter, address exclusiveRelayer) internal returns (uint32 fillDeadline) {
        uint32 quoteTimestamp = uint32(block.timestamp);
        fillDeadline = uint32(block.timestamp + 1 hours);

        vm.startPrank(user);
        sourceToken.approve(address(sourcePool), TRANSFER_AMOUNT);
        sourcePool.depositV3(
            user,
            user,
            address(sourceToken),
            address(destinationToken),
            TRANSFER_AMOUNT,
            TRANSFER_AMOUNT,
            2,
            exclusiveRelayer,
            quoteTimestamp,
            fillDeadline,
            exclusivityParameter,
            ""
        );
        vm.stopPrank();
    }

    function _relay(uint32 fillDeadline, uint32 exclusivityDeadline, address exclusiveRelayer)
        internal
        view
        returns (V3SpokePoolInterface.V3RelayData memory relayData)
    {
        relayData = V3SpokePoolInterface.V3RelayData({
            depositor: bytes32(uint256(uint160(user))),
            recipient: bytes32(uint256(uint160(user))),
            exclusiveRelayer: bytes32(uint256(uint160(exclusiveRelayer))),
            inputToken: bytes32(uint256(uint160(address(sourceToken)))),
            outputToken: bytes32(uint256(uint160(address(destinationToken)))),
            inputAmount: TRANSFER_AMOUNT,
            outputAmount: TRANSFER_AMOUNT,
            originChainId: 1,
            depositId: 0,
            fillDeadline: fillDeadline,
            exclusivityDeadline: exclusivityDeadline,
            message: ""
        });
    }

    function test_normal_source_backed_deposit_and_fast_fill() public {
        uint32 fillDeadline = _deposit(0, address(0));
        assertEq(sourcePool.numberOfDeposits(), 1, "source deposit nonce increments");
        assertEq(sourceToken.balanceOf(address(sourcePool)), TRANSFER_AMOUNT, "source escrow holds input");

        V3SpokePoolInterface.V3RelayData memory relayData = _relay(fillDeadline, 0, address(0));
        vm.startPrank(relayer);
        destinationToken.approve(address(destinationPool), TRANSFER_AMOUNT);
        destinationPool.fillRelay(relayData, 1, bytes32(uint256(uint160(relayer))));
        vm.stopPrank();

        assertEq(destinationToken.balanceOf(user), TRANSFER_AMOUNT, "recipient receives destination output");
        assertEq(destinationToken.balanceOf(relayer), INITIAL_BALANCE - TRANSFER_AMOUNT, "relayer funds output");
        assertEq(destinationToken.balanceOf(address(destinationPool)), 0, "pool does not retain fast-fill funds");
    }

    function test_revert_source_backed_relay_replay() public {
        uint32 fillDeadline = _deposit(0, address(0));
        V3SpokePoolInterface.V3RelayData memory relayData = _relay(fillDeadline, 0, address(0));

        vm.startPrank(relayer);
        destinationToken.approve(address(destinationPool), type(uint256).max);
        destinationPool.fillRelay(relayData, 1, bytes32(uint256(uint160(relayer))));
        vm.expectRevert();
        destinationPool.fillRelay(relayData, 1, bytes32(uint256(uint160(relayer))));
        vm.stopPrank();
    }

    function test_revert_source_backed_exclusive_relayer_boundary() public {
        uint32 exclusivityParameter = 600;
        uint32 fillDeadline = _deposit(exclusivityParameter, relayer);
        uint32 exclusivityDeadline = uint32(block.timestamp + exclusivityParameter);
        V3SpokePoolInterface.V3RelayData memory relayData = _relay(fillDeadline, exclusivityDeadline, relayer);

        vm.prank(eve);
        vm.expectRevert();
        destinationPool.fillRelay(relayData, 1, bytes32(uint256(uint160(eve))));

        vm.startPrank(relayer);
        destinationToken.approve(address(destinationPool), TRANSFER_AMOUNT);
        destinationPool.fillRelay(relayData, 1, bytes32(uint256(uint160(relayer))));
        vm.stopPrank();
        assertEq(destinationToken.balanceOf(user), TRANSFER_AMOUNT, "exclusive relayer can fill");
    }

    function assertEq(uint256 actual, uint256 expected, string memory message) internal pure {
        require(actual == expected, message);
    }
}
