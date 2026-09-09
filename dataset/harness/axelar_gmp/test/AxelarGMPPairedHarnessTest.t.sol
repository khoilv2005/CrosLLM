// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0 <0.9.0;

import "forge-std/Test.sol";

contract AxelarGateway {
    mapping(bytes32 => bool) public isCommandExecuted;

    event ContractCall(address indexed sender, string destinationChain, string destinationContractAddress, bytes32 indexed payloadHash, bytes payload);
    event Executed(bytes32 indexed commandId);

    function callContract(string calldata destinationChain, string calldata destinationContractAddress, bytes calldata payload) external {
        bytes32 payloadHash = keccak256(payload);
        emit ContractCall(msg.sender, destinationChain, destinationContractAddress, payloadHash, payload);
    }

    function validateContractCall(bytes32 commandId, string calldata sourceChain, string calldata sourceAddress, bytes32 payloadHash) external returns (bool) {
        if (isCommandExecuted[commandId]) return false;
        isCommandExecuted[commandId] = true;
        emit Executed(commandId);
        return true;
    }
}

contract AxelarExecutableApp {
    address public immutable gateway;
    uint256 public executedCount;

    constructor(address _gateway) {
        gateway = _gateway;
    }

    function execute(bytes32 commandId, string calldata sourceChain, string calldata sourceAddress, bytes calldata payload) external {
        bytes32 payloadHash = keccak256(payload);
        bool valid = AxelarGateway(gateway).validateContractCall(commandId, sourceChain, sourceAddress, payloadHash);
        require(valid, "Not approved by Axelar gateway");
        executedCount++;
    }
}

contract AxelarGMPPairedHarnessTest is Test {
    AxelarGateway public gateway;
    AxelarExecutableApp public app;

    function setUp() public {
        gateway = new AxelarGateway();
        app = new AxelarExecutableApp(address(gateway));
    }

    function test_normal_cross_chain_lifecycle() public {
        gateway.callContract("Avalanche", "0xReceiver", abi.encode("payload"));
        bytes32 cmdId = keccak256("cmd_1001");
        app.execute(cmdId, "Ethereum", "0xSender", abi.encode("payload"));
        assertEq(app.executedCount(), 1, "App should record 1 execution");
    }

    function test_revert_replay_execution() public {
        bytes32 cmdId = keccak256("cmd_1002");
        app.execute(cmdId, "Ethereum", "0xSender", abi.encode("payload"));
        vm.expectRevert("Not approved by Axelar gateway");
        app.execute(cmdId, "Ethereum", "0xSender", abi.encode("payload"));
    }

    function test_revert_unauthorized_caller() public {
        bytes32 fakeCmd = keccak256("fake_cmd");
        gateway.validateContractCall(fakeCmd, "Ethereum", "0xSender", keccak256(""));
        vm.expectRevert("Not approved by Axelar gateway");
        app.execute(fakeCmd, "Ethereum", "0xSender", "");
    }
}
