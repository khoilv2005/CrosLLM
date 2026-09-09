// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import "forge-std/Test.sol";
import "../contracts/bridge/L1ERC20Bridge.sol";
import "../contracts/bridge/interfaces/IL1Nullifier.sol";
import "../contracts/bridge/asset-router/IL1AssetRouter.sol";
import "../contracts/MockERC20.sol";

/// @dev The external AssetRouter boundary is a test double; L1ERC20Bridge is
/// the exact locked source contract under test. The double consumes the
/// source contract's allowance and records the legacy deposit arguments.
contract ZkSyncAssetRouterProbe {
    uint256 public depositNonce;
    address public lastOriginalCaller;
    address public lastReceiver;
    address public lastToken;
    uint256 public lastAmount;
    uint256 public lastValue;

    function depositLegacyErc20Bridge(
        address _originalCaller,
        address _l2Receiver,
        address _l1Token,
        uint256 _amount,
        uint256,
        uint256,
        address
    ) external payable returns (bytes32 txHash) {
        require(MockERC20(_l1Token).transferFrom(msg.sender, address(this), _amount), "router escrow failed");
        lastOriginalCaller = _originalCaller;
        lastReceiver = _l2Receiver;
        lastToken = _l1Token;
        lastAmount = _amount;
        lastValue = msg.value;
        txHash = keccak256(abi.encode(address(this), depositNonce, _originalCaller, _l2Receiver, _l1Token, _amount));
        depositNonce += 1;
    }
}

/// @dev The Nullifier boundary records the exact finalization payload. Proof
/// verification and L1/L2 message roots remain outside this selected scope.
contract ZkSyncNullifierProbe {
    address public immutable l2Bridge;
    bool public finalizeCalled;
    uint256 public lastChainId;
    uint256 public lastBatchNumber;
    uint256 public lastMessageIndex;
    uint16 public lastTxNumberInBatch;
    bytes32 public lastMessageHash;
    bytes32 public lastProofHash;

    constructor(address _l2Bridge) {
        l2Bridge = _l2Bridge;
    }

    function l2BridgeAddress(uint256) external view returns (address) {
        return l2Bridge;
    }

    function finalizeDeposit(FinalizeL1DepositParams calldata params) external {
        finalizeCalled = true;
        lastChainId = params.chainId;
        lastBatchNumber = params.l2BatchNumber;
        lastMessageIndex = params.l2MessageIndex;
        lastTxNumberInBatch = params.l2TxNumberInBatch;
        lastMessageHash = keccak256(params.message);
        lastProofHash = keccak256(abi.encode(params.merkleProof));
    }
}

/// @dev L1ERC20Bridge initializes its reentrancy guard in proxy storage. This
/// minimal immutable-implementation proxy keeps the constructor lock intact
/// while exercising the source contract through a separate storage context.
contract ZkSyncBridgeProxy {
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

contract ZkSyncEraSourceBackedHarnessTest is Test {
    L1ERC20Bridge public bridge;
    L1ERC20Bridge public implementation;
    MockERC20 public token;
    ZkSyncAssetRouterProbe public assetRouter;
    ZkSyncNullifierProbe public nullifier;

    address public user = address(0x101);
    address public l2Bridge = address(0x202);
    uint256 internal constant CHAIN_ID = 270;
    uint256 internal constant DEPOSIT_AMOUNT = 50 ether;

    function setUp() public {
        token = new MockERC20("zkSync L1 Token", "ERA_L1");
        assetRouter = new ZkSyncAssetRouterProbe();
        nullifier = new ZkSyncNullifierProbe(l2Bridge);

        implementation = new L1ERC20Bridge(
            IL1Nullifier(address(nullifier)),
            IL1AssetRouter(address(assetRouter)),
            IL1NativeTokenVault(address(0)),
            CHAIN_ID
        );
        bridge = L1ERC20Bridge(
            address(
                new ZkSyncBridgeProxy(
                    address(implementation),
                    abi.encodeWithSelector(L1ERC20Bridge.initialize.selector)
                )
            )
        );
        token.mint(user, 500 ether);
    }

    function test_normal_source_backed_deposit_and_escrow() public {
        vm.startPrank(user);
        token.approve(address(bridge), DEPOSIT_AMOUNT);
        assertEq(address(bridge.L1_ASSET_ROUTER()), address(assetRouter), "asset router immutable is wired");
        assertEq(address(bridge.L1_NULLIFIER()), address(nullifier), "nullifier immutable is wired");
        bytes32 txHash = bridge.deposit(
            user,
            address(token),
            DEPOSIT_AMOUNT,
            1_000_000,
            800,
            user
        );
        vm.stopPrank();

        assertEq(token.balanceOf(address(assetRouter)), DEPOSIT_AMOUNT, "asset router holds escrow");
        assertEq(token.balanceOf(address(bridge)), 0, "bridge does not retain spent escrow");
        assertEq(token.allowance(address(bridge), address(assetRouter)), 0, "router allowance is consumed");
        assertEq(bridge.depositAmount(user, address(token), txHash), DEPOSIT_AMOUNT, "deposit is recorded");
        assertEq(assetRouter.lastOriginalCaller(), user, "original caller is preserved");
        assertEq(assetRouter.lastReceiver(), user, "receiver is preserved");
        assertEq(assetRouter.lastAmount(), DEPOSIT_AMOUNT, "amount is preserved");
        assertEq(assetRouter.lastValue(), 0, "no native value is required for ERC20 deposit");
    }

    function test_revert_source_backed_empty_and_eth_deposit() public {
        vm.startPrank(user);
        token.approve(address(bridge), DEPOSIT_AMOUNT);
        vm.expectRevert();
        bridge.deposit(user, address(token), 0, 1_000_000, 800, user);
        vm.expectRevert();
        bridge.deposit(user, address(1), DEPOSIT_AMOUNT, 1_000_000, 800, user);
        vm.stopPrank();
    }

    function test_source_backed_finalize_forwards_legacy_message_context() public {
        bytes memory message = hex"01020304";
        bytes32[] memory proof = new bytes32[](2);
        proof[0] = bytes32(uint256(11));
        proof[1] = bytes32(uint256(22));

        bridge.finalizeWithdrawal(17, 23, 4, message, proof);

        assertTrue(nullifier.finalizeCalled(), "nullifier receives finalization");
        assertEq(nullifier.lastChainId(), CHAIN_ID, "Era chain id is supplied");
        assertEq(nullifier.lastBatchNumber(), 17, "batch number is preserved");
        assertEq(nullifier.lastMessageIndex(), 23, "message index is preserved");
        assertEq(nullifier.lastTxNumberInBatch(), 4, "transaction number is preserved");
        assertEq(nullifier.lastMessageHash(), keccak256(message), "message is preserved");
        assertEq(nullifier.lastProofHash(), keccak256(abi.encode(proof)), "proof is preserved");
        assertEq(bridge.isWithdrawalFinalized(17, 23), false, "external nullifier owns finality state");
    }
}
