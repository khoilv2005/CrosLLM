#!/usr/bin/env python3
"""Build and attest the development paired harnesses from locked source.

The repository contains small Foundry projects so that the development hosts
can be exercised offline.  This module makes the distinction between those
projects and source-backed evidence explicit: a harness is promoted only when
its Solidity inputs match the locked checkout byte-for-byte, its artifact
selection is present, the locked compiler is used, and the normal workflow
tests pass in a network-isolated container.

The command intentionally does not modify a harness or source receipt after a
failed probe.  This keeps a timeout/compiler failure from being mistaken for
an admitted source build.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset.tools import extract_all_artifacts


HARNESS_ROOT = ROOT / "dataset" / "harness"
ARTIFACT_ROOT = ROOT / "dataset" / "artifacts"
REPORT_DEFAULT = ROOT / "dataset" / "reports" / "source_backed_harnesses.json"
FOUNDRY_IMAGE = extract_all_artifacts.DOCKER_FOUNDRY
HEX64 = re.compile(r"^[0-9a-f]{64}$")


# The source prefix is needed only for LayerZero: its harness keeps the
# protocol package under contracts/, while the locked checkout is a monorepo.
# Celer and ChainBridge use the same relative path on both sides.  MockERC20 is
# deliberately support code and is never counted as upstream source evidence.
HARNESS_LAYOUT: dict[str, dict[str, Any]] = {
    "hop": {
        "test_contract": "HopPairedHarnessTest",
        "source_prefix": "",
        "support_paths": set(),
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys the exact Hop source test bridges with the upstream BonderRegistry, HopBridgeToken and token boundary doubles",
                "source_contracts": ["L1_Bridge", "L2_Bridge", "Bridge", "Accounting", "BonderRegistry"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["L1_Bridge.sendToL2", "source_token_escrow", "Mock_L2_Bridge.distribute", "destination_hToken_mint", "conservation_assertions"],
                "assertions": ["alice_debit", "bridge_escrow", "chain_balance", "destination_supply", "token_conservation"],
                "test": "test_normal_l1_to_l2_transfer",
            },
            "allowed_actions": {
                "user": ["L1_Bridge.sendToL2"],
                "bonder": ["L1_Bridge.stake"],
                "upstream_l2_connector": ["L2_Bridge.distribute"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.timestamp at L1_Bridge.sendToL2",
                "destination": "Foundry block.timestamp at Mock_L2_Bridge.distribute",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "source escrow, destination hToken mint and bridge token-conservation invariant",
                "status": "normal_liquidity_transfer_boundary_tested_without_transfer_root_challenge_or_external_finality",
            },
            "attestation": {
                "mechanism": "exact upstream L1/L2 bridge source requires the configured chain and x-domain connector before settlement",
                "insufficient_or_wrong_actor_test": "test_revert_unauthorized_distribute",
            },
            "callbacks": {
                "destination_callback": "Mock_L1_Bridge -> Mock_L2_Bridge source connector path",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys token, registry, bridges and hToken for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "wormhole_evm_sdk": {
        "test_contract": "WormholeProxySourceBackedHarnessTest",
        "source_prefix": "src",
        "source_strip_prefix": "contracts/",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys the locked EIP-1967 Proxy with an isolated logic contract",
                "source_contracts": ["Proxy", "implementationState"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["proxy_constructor", "checkedUpgrade", "fallback_delegatecall", "state_read_write"],
                "assertions": ["implementation_state", "initialized_guard", "delegated_storage"],
                "test": "test_proxy_initialization_and_delegation",
            },
            "allowed_actions": {
                "deployer": ["Proxy.constructor"],
                "application": ["Proxy.fallback -> logic.setValue"],
                "logic": ["implementationState"],
                "eve": [],
            },
            "clocks": {
                "source": "EVM block.number at proxy deployment",
                "destination": "EVM block.number at delegated state update",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "proxy initialization flag and EIP-1967 implementation slot",
                "status": "initialization_and_delegation_boundary_tested",
            },
            "attestation": {
                "mechanism": "proxy constructor delegates checkedUpgrade to the supplied logic contract",
                "insufficient_or_wrong_actor_test": "test_revert_when_logic_lacks_checked_upgrade",
            },
            "callbacks": {
                "destination_callback": "fallback delegatecall to the configured logic contract",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp deploys a fresh logic and proxy pair for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "stargate": {
        "test_contract": "StargateSourceBackedHarnessTest",
        "source_prefix": "",
        "support_paths": {
            "contracts/MockERC20.sol",
            "contracts/StargateEndpointMock.sol",
            "contracts/StargateRouterController.sol",
        },
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys locked Router/Factory/Bridge/Pool pairs on isolated source and destination domains",
                "source_contracts": ["Router", "Factory", "Bridge", "Pool", "LPTokenERC20"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["approve", "addLiquidity", "callDelta", "sendCredits", "endpoint_deliver", "lzReceive", "credit_chain_path"],
                "assertions": ["source_pool_escrow", "lp_mint", "outbound_nonce", "source_bridge_binding", "destination_credit"],
                "test": "test_normal_source_backed_liquidity_credit_delivery",
            },
            "allowed_actions": {
                "liquidity_provider": ["Router.addLiquidity"],
                "router_operator": ["Router.callDelta", "Router.sendCredits"],
                "endpoint": ["Bridge.lzReceive"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.number at addLiquidity/sendCredits",
                "destination": "Foundry block.number at endpoint delivery",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "LayerZero endpoint identity plus configured source-bridge binding for credit delivery",
                "status": "liquidity_credit_and_endpoint_binding_tested_without_external_message_finality_delay",
            },
            "attestation": {
                "mechanism": "source Bridge requires the configured endpoint and destination Bridge checks the registered source address",
                "insufficient_or_wrong_actor_test": "test_revert_source_backed_direct_lz_receive",
            },
            "callbacks": {
                "destination_callback": "Bridge.lzReceive -> Router.creditChainPath -> Pool.creditChainPath",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys endpoint, routers, factories, bridges, pools and tokens for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "across": {
        "test_contract": "AcrossSourceBackedHarnessTest",
        "source_prefix": "",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys locked Ethereum_SpokePool implementations behind isolated immutable-implementation proxy storage",
                "source_contracts": ["Ethereum_SpokePool", "SpokePool"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["depositV3", "source_escrow", "relayer_approval", "fillRelay", "recipient_transfer"],
                "assertions": ["deposit_nonce", "source_escrow", "destination_recipient_balance", "fast_fill_balance", "replay_status"],
                "test": "test_normal_source_backed_deposit_and_fast_fill",
            },
            "allowed_actions": {
                "depositor": ["SpokePool.depositV3"],
                "relayer": ["SpokePool.fillRelay"],
                "owner_setup": ["Ethereum_SpokePool.initialize"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.timestamp at depositV3",
                "destination": "Foundry block.timestamp at fillRelay",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "SpokePool fill deadline, exclusivity boundary and terminal fill status",
                "status": "deposit_and_fast_fill_boundary_tested_without_hub_root_or_optimistic_challenge_delay",
            },
            "attestation": {
                "mechanism": "source SpokePool checks fill deadline/exclusive relayer and records terminal fill status before transferring output",
                "insufficient_or_wrong_actor_test": "test_revert_source_backed_exclusive_relayer_boundary",
            },
            "callbacks": {
                "destination_callback": "empty message path; no recipient callback selected",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys tokens, source/destination implementations and proxy storage for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "arbitrum_token_bridge": {
        "test_contract": "ArbitrumSourceBackedHarnessTest",
        "source_prefix": "",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys exact L1GatewayRouter and L2GatewayRouter source contracts with isolated gateway/token doubles",
                "source_contracts": ["L1GatewayRouter", "L2GatewayRouter", "GatewayRouter", "TokenGateway"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["L1Router.outboundTransfer", "caller_encoding", "L1_gateway_escrow", "L2Router.outboundTransfer", "L2_gateway_escrow"],
                "assertions": ["original_caller", "recipient", "amount", "payload", "route_selection"],
                "test": "test_normal_source_backed_router_routes_l1_deposit",
            },
            "allowed_actions": {
                "l1_user": ["L1GatewayRouter.outboundTransfer"],
                "l2_user": ["L2GatewayRouter.outboundTransfer"],
                "counterpart": ["L2GatewayRouter.setGateway"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry EVM block number at L1 router call",
                "destination": "Foundry EVM block number at L2 router call",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "router route selection and aliased counterpart authorization",
                "status": "router_and_authority_boundary_tested_without_Arbitrum_Nitro_retryable_or_outbox_finality",
            },
            "attestation": {
                "mechanism": "L1/L2 routers wrap original caller data and L2 router enforces AddressAliasHelper counterpart identity",
                "insufficient_or_wrong_actor_test": "test_revert_wrong_l2_route_authority_and_accept_alias",
            },
            "callbacks": {
                "destination_callback": "gateway probe receives encoded router call; Nitro delivery is outside selected source scope",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys both source routers, gateway probes and tokens for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "zksync_era": {
        "test_contract": "ZkSyncEraSourceBackedHarnessTest",
        "source_prefix": "l1-contracts",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys exact L1ERC20Bridge source behind an immutable-implementation proxy with isolated AssetRouter and Nullifier boundary doubles",
                "source_contracts": ["L1ERC20Bridge", "ReentrancyGuard", "L1ContractErrors", "L2ContractHelper"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["approve", "L1ERC20Bridge.deposit", "source_escrow", "AssetRouter.depositLegacyErc20Bridge", "deposit_record", "L1ERC20Bridge.finalizeWithdrawal", "Nullifier.finalizeDeposit"],
                "assertions": ["original_caller", "receiver", "amount", "router_escrow", "allowance_consumed", "finalize_context"],
                "test": "test_normal_source_backed_deposit_and_escrow",
            },
            "allowed_actions": {
                "depositor": ["L1ERC20Bridge.deposit"],
                "asset_router": ["IL1AssetRouter.depositLegacyErc20Bridge"],
                "nullifier": ["IL1Nullifier.finalizeDeposit"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.timestamp at L1ERC20Bridge.deposit",
                "destination": "Foundry block.timestamp at L1ERC20Bridge.finalizeWithdrawal",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "source deposit accounting plus forwarding of legacy withdrawal context to the configured L1 Nullifier",
                "status": "deposit_escrow_and_finalize_forwarding_tested_without_L1_L2_message_proof_or_external_finality",
            },
            "attestation": {
                "mechanism": "exact L1ERC20Bridge source enforces nonzero/non-ETH deposits, consumes AssetRouter allowance, records deposit amount, and forwards the Nullifier context",
                "insufficient_or_wrong_actor_test": "test_revert_source_backed_empty_and_eth_deposit",
            },
            "callbacks": {
                "destination_callback": "L1ERC20Bridge.finalizeWithdrawal -> IL1Nullifier.finalizeDeposit boundary",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys token, source implementation, proxy, AssetRouter probe and Nullifier probe for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "scroll": {
        "test_contract": "ScrollSourceBackedHarnessTest",
        "source_prefix": "src",
        "source_strip_prefix": "contracts/",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys exact L1ScrollMessenger and L2ScrollMessenger implementations behind isolated initializer proxies with queue and receiver boundary probes",
                "source_contracts": ["L1ScrollMessenger", "L2ScrollMessenger", "ScrollMessengerBase", "L2MessageQueue"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["L1.sendMessage", "L1_queue_append", "L2.sendMessage", "L2_queue_append", "alias_authorization", "relayMessage", "receiver_callback", "replay_guard"],
                "assertions": ["relay_calldata", "queue_nonce", "message_hash", "alias_counterpart", "receiver_payload", "terminal_relay_state"],
                "test": "test_normal_source_backed_l1_enqueue",
            },
            "allowed_actions": {
                "user": ["L1ScrollMessenger.sendMessage", "L2ScrollMessenger.sendMessage"],
                "aliased_l1_messenger": ["L2ScrollMessenger.relayMessage"],
                "receiver": ["ScrollRelayReceiver.receiveMessage"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.timestamp at L1/L2 sendMessage",
                "destination": "Foundry block.timestamp at L2 relayMessage",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "source enqueue hash/nonce, alias-authorized delivery and terminal replay state",
                "status": "enqueue_alias_relay_and_replay_boundary_tested_without_ScrollChain_batch_finality_or_proof_trie",
            },
            "attestation": {
                "mechanism": "exact source messengers enforce queue calls, message identity and L1-to-L2 alias counterpart authorization",
                "insufficient_or_wrong_actor_test": "test_revert_source_backed_l2_relay_wrong_authority",
            },
            "callbacks": {
                "destination_callback": "L2ScrollMessenger.relayMessage -> ScrollRelayReceiver.receiveMessage",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys source implementations, proxy storage, queues and receiver for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "polygon_zkevm": {
        "test_contract": "PolygonZkEVMSourcedBridgeHarnessTest",
        "source_prefix": "",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys the exact AgglayerBridge source behind an isolated EIP-1967 storage proxy with a proxy-admin owner boundary",
                "source_contracts": ["AgglayerBridge", "DepositContractV2", "DepositContractBase", "BridgeLib", "TokenWrappedBridgeUpgradeable"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["proxy_initialize", "approve", "AgglayerBridge.bridgeAsset", "source_escrow", "deposit_leaf", "Merkle_root_update"],
                "assertions": ["network_id", "deposit_count", "token_escrow", "caller_balance", "root_changed"],
                "test": "test_normal_source_backed_asset_escrow_and_leaf",
            },
            "allowed_actions": {
                "user": ["AgglayerBridge.bridgeAsset"],
                "proxy_admin": ["IProxyAdmin.owner"],
                "global_exit_root_manager": [],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.timestamp at AgglayerBridge.bridgeAsset",
                "destination": "Not exercised; destination claim requires an external global exit root and SMT proof",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "source escrow and canonical deposit-tree leaf insertion",
                "status": "asset_escrow_and_root_update_tested_without_Agglayer_global_exit_root_submission_rollup_finality_or_claim_proof",
            },
            "attestation": {
                "mechanism": "exact source bridge rejects same-network destinations and ERC20 msg.value, transfers the approved amount, records one leaf and changes the canonical root",
                "insufficient_or_wrong_actor_test": "test_source_backed_rejects_same_network_destination",
            },
            "callbacks": {
                "destination_callback": "None in selected source scope; AgglayerBridge.bridgeAsset emits/records the outbound leaf",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys the exact implementation, proxy storage, proxy-admin probe and token for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "linea": {
        "test_contract": "LineaRollupSourceBackedHarnessTest",
        "source_prefix": "",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys the exact LineaRollup source behind an isolated implementation-slot proxy and initializes the Linea message service/rate limiter roles",
                "source_contracts": ["LineaRollup", "ZkEvmV2", "L1MessageService", "L1MessageManager", "RateLimiter", "PauseManager"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["proxy_initialize", "role_setup", "sendMessage", "message_hash", "rolling_hash"],
                "assertions": ["initial_state_root", "operator_role", "message_number", "message_identity", "rolling_hash"],
                "test": "test_normal_source_backed_message_enqueue",
            },
            "allowed_actions": {
                "user": ["L1MessageService.sendMessage"],
                "security_council": ["AccessControl role initialization"],
                "operator": [],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.timestamp at LineaRollup.initialize and L1MessageService.sendMessage",
                "destination": "Not exercised; destination claim requires an anchored L2 Merkle root and proof",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "Linea L1 message enqueue with source rolling-hash commitment",
                "status": "initialization_and_outbound_message_identity_tested_without_blob_submission_plonk_proof_L2_root_anchor_or_claim_finality",
            },
            "attestation": {
                "mechanism": "exact source service rejects zero recipient and fee greater than msg.value, increments the source nonce and stores the rolling hash",
                "insufficient_or_wrong_actor_test": "test_source_backed_rejects_invalid_message_boundaries",
            },
            "callbacks": {
                "destination_callback": "None in selected source scope; outbound sendMessage only records the canonical message commitment",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys implementation, proxy storage and all initializer state for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "optimism": {
        "test_contract": "OptimismSourceBackedHarnessTest",
        "source_prefix": "",
        "source_strip_prefix": "contracts/",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys the exact L1CrossDomainMessenger behind isolated implementation and proxy-owner storage slots with a portal deposit boundary probe",
                "source_contracts": ["L1CrossDomainMessenger", "CrossDomainMessenger", "ProxyAdminOwnedBase", "ReinitializableBase"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["proxy_owner_initialization", "sendMessage", "base_gas", "portal.depositTransaction", "versioned_nonce"],
                "assertions": ["proxy_admin_owner", "portal_value", "portal_gas_limit", "deposit_call", "message_nonce"],
                "test": "test_normal_source_backed_message_deposit",
            },
            "allowed_actions": {
                "user": ["CrossDomainMessenger.sendMessage"],
                "proxy_admin_owner": ["L1CrossDomainMessenger.initialize"],
                "portal": ["IOptimismPortal2.depositTransaction"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.timestamp at L1CrossDomainMessenger.initialize/sendMessage",
                "destination": "Not exercised; L2 relay requires the paired messenger and portal delivery",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "source cross-domain message encoding and portal deposit handoff",
                "status": "message_identity_nonce_and_portal_deposit_boundary_tested_without_L2_relay_fault_proof_or_withdrawal_finality",
            },
            "attestation": {
                "mechanism": "exact source messenger enforces proxy-admin-owner initialization, computes versioned message nonce/base gas and hands the encoded relay call to the configured portal",
                "insufficient_or_wrong_actor_test": "test_source_backed_rejects_unauthorized_initialization",
            },
            "callbacks": {
                "destination_callback": "IOptimismPortal2.depositTransaction boundary receives the source-generated relay calldata",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys source implementation, proxy storage, proxy-admin probe, system-config probe and portal probe for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "synapse": {
        "test_contract": "SynapseSourceBackedHarnessTest",
        "source_prefix": "",
        "support_paths": {"contracts/SynapseMockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys the locked SynapseBridge source contract on isolated source and destination domains",
                "source_contracts": ["SynapseBridge"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["approve", "deposit", "node_group_role", "mint", "kappa_record"],
                "assertions": ["source_escrow", "net_mint_amount", "fee_accounting", "replay_identity"],
                "test": "test_normal_source_backed_deposit_and_node_mint",
            },
            "allowed_actions": {
                "user": ["SynapseBridge.deposit"],
                "node_group": ["SynapseBridge.mint"],
                "admin_setup": ["AccessControl.grantRole"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.number at deposit",
                "destination": "Foundry block.number at node-group mint",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "node-group role authorization plus one-time kappa execution record",
                "status": "role_boundary_and_replay_protection_tested_without_external_consensus_delay",
            },
            "attestation": {
                "mechanism": "source SynapseBridge checks NODEGROUP_ROLE before mint and records kappa before settlement",
                "insufficient_or_wrong_actor_test": "test_revert_source_backed_unauthorized_node",
            },
            "callbacks": {
                "destination_callback": "IERC20Mintable.mint followed by SafeERC20 transfer; no application callback in selected source scope",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys both locked bridges and tokens for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "axelar_gmp": {
        "test_contract": "AxelarSourceBackedHarnessTest",
        "source_prefix": "",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys the locked AxelarAmplifierGateway behind its locked proxy and seeds one weighted signer set",
                "source_contracts": ["AxelarAmplifierGateway", "AxelarAmplifierGatewayProxy"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["callContract", "approveMessages", "validateMessage", "executed_state"],
                "assertions": ["outbound_payload_hash", "weighted_proof", "approval_identity", "replay_blocked"],
                "test": "test_outbound_and_approved_message_lifecycle",
            },
            "allowed_actions": {
                "application": ["IAxelarGateway.callContract"],
                "signer": ["AxelarAmplifierGateway.approveMessages"],
                "recipient": ["AxelarAmplifierGateway.validateMessage"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.timestamp for outbound call",
                "destination": "Foundry block.timestamp for approval/consumption",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "weighted signer proof with threshold one in the development profile",
                "status": "proof_threshold_and_executed_state_tested",
            },
            "attestation": {
                "mechanism": "source gateway validates an ECDSA proof over the command and current signer set",
                "insufficient_or_wrong_actor_test": "test_revert_on_invalid_weighted_proof",
            },
            "callbacks": {
                "destination_callback": "application consumer invokes validateMessage; gateway has no direct callback in selected scope",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys implementation, proxy, signer set and recipient for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "hyperlane": {
        "test_contract": "HyperlaneSourceBackedHarnessTest",
        "source_prefix": "solidity",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys the locked Mailbox implementation on two local EVM domains",
                "source_contracts": ["Mailbox"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["build_message", "dispatch", "ISM_verify", "process", "recipient_callback"],
                "assertions": ["nonce_and_message_id", "destination_domain", "delivery_record", "callback_payload"],
                "test": "test_normal_cross_chain_message_send_and_process",
            },
            "allowed_actions": {
                "sender": ["Mailbox.dispatch"],
                "relayer": ["Mailbox.process"],
                "recipient": ["IMessageRecipient.handle"],
                "eve": [],
            },
            "clocks": {
                "source": "Foundry block.number at dispatch",
                "destination": "Foundry block.number at process",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "registered interchain security module verification",
                "status": "verification_boundary_tested_without_time_delay",
            },
            "attestation": {
                "mechanism": "source Mailbox resolves the recipient/default ISM and requires verify(metadata, message)",
                "insufficient_or_wrong_actor_test": "test_revert_when_ism_rejects_message",
            },
            "callbacks": {
                "destination_callback": "IMessageRecipient.handle(origin, sender, body)",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys Mailbox, ISM, hooks and recipient for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "layerzero_v2": {
        "test_contract": "LayerZeroV2PairedHarnessTest",
        "source_prefix": "packages/layerzero-v2/evm/protocol",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys EndpointV2 and SimpleMessageLib on two EIDs",
                "source_contracts": ["EndpointV2", "SimpleMessageLib"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["quote", "send", "verify", "lzReceive"],
                "assertions": ["nonce_and_fee", "payload_hash_cleared", "receiver_callback"],
                "test": "test_normal_cross_chain_message_send_and_deliver",
            },
            "allowed_actions": {
                "alice": ["EndpointV2.send"],
                "message_library": ["EndpointV2.verify"],
                "executor": ["EndpointV2.lzReceive"],
                "eve": [],
            },
            "clocks": {
                "source": "EVM block clock; no artificial delay in this profile",
                "destination": "EVM block clock; no artificial delay in this profile",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "DVN/library verification is represented by the registered receive library",
                "status": "profiled_not_time_delayed",
            },
            "attestation": {
                "mechanism": "registered receive library verifies the payload hash",
                "insufficient_or_wrong_actor_test": "test_revert_unauthorized_receive_library",
            },
            "callbacks": {
                "destination_callback": "ILayerZeroReceiver.lzReceive",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys both domains for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "celer_cbridge": {
        "test_contract": "CBridgePairedHarnessTest",
        "source_prefix": "",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys CBridge and source/destination token accounts",
                "source_contracts": ["CBridge"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["approve", "transferOut", "transferIn", "confirm"],
                "assertions": ["hashlock_identity", "token_conservation", "confirmed_status"],
                "test": "test_normal_cross_chain_transfer_and_confirm",
            },
            "allowed_actions": {
                "sender": ["CBridge.transferOut"],
                "bridge_relayer": ["CBridge.transferIn", "CBridge.confirm"],
                "public": ["CBridge.refund"],
            },
            "clocks": {
                "source": "block.timestamp at transferOut",
                "destination": "block.timestamp plus explicit timelock",
                "explicit_time_warp": True,
            },
            "finality": {
                "model": "hashlock confirmation or timelock refund",
                "status": "workflow_and_timeout_tested",
            },
            "attestation": {
                "mechanism": "hashlock preimage",
                "insufficient_or_wrong_actor_test": "test_revert_confirm_incorrect_preimage",
            },
            "callbacks": {
                "destination_callback": "SafeERC20 transfer to receiver",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys bridges and tokens for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
    "chainbridge": {
        "test_contract": "ChainBridgePairedHarnessTest",
        "source_prefix": "",
        "support_paths": {"contracts/MockERC20.sol"},
        "workflow": {
            "state_initialization": {
                "mechanism": "Foundry setUp deploys two Bridge/handler pairs and configures resource IDs",
                "source_contracts": ["Bridge", "ERC20Handler"],
                "isolated_per_test": True,
            },
            "normal_workflow": {
                "steps": ["deposit", "relayer_vote_1", "relayer_vote_2", "handler_execute"],
                "assertions": ["deposit_nonce", "threshold", "resource_binding", "token_conservation"],
                "test": "test_normal_cross_chain_lock_and_relay",
            },
            "allowed_actions": {
                "alice": ["Bridge.deposit"],
                "relayer_1": ["Bridge.voteProposal"],
                "relayer_2": ["Bridge.voteProposal"],
                "eve": [],
                "admin": ["Bridge.adminSetResource"],
            },
            "clocks": {
                "source": "block.number at deposit/proposal creation",
                "destination": "proposal expiry uses locked Bridge _expiry",
                "explicit_time_warp": False,
            },
            "finality": {
                "model": "m-of-n relayer threshold",
                "status": "threshold_and_duplicate_vote_tested",
            },
            "attestation": {
                "mechanism": "relayer role membership and proposal vote bitmap",
                "insufficient_or_wrong_actor_test": "test_revert_non_relayer_cannot_vote",
            },
            "callbacks": {
                "destination_callback": "Bridge.executeProposal -> ERC20Handler.executeProposal",
                "ordering_asserted": True,
            },
            "reset_isolation": {
                "mechanism": "Foundry setUp redeploys bridge, handlers and tokens for every test",
                "cross_test_state_reuse": False,
            },
        },
    },
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def canonical_hash(value: object) -> str:
    return _sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _source_rel_for_harness(
    relative: str,
    source_prefix: str,
    source_strip_prefix: str = "",
) -> str:
    prefix = Path(source_prefix) if source_prefix else Path()
    if source_strip_prefix and relative.startswith(source_strip_prefix):
        relative = relative[len(source_strip_prefix):]
    # The LayerZero harness keeps upstream test doubles under contracts/mocks
    # for a stable Foundry import path, while the locked upstream checkout
    # stores the same files under protocol/test/mocks.
    if source_prefix and relative.startswith("contracts/mocks/"):
        relative = relative.replace("contracts/mocks/", "test/mocks/", 1)
    return (prefix / relative).as_posix()


def _validate_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _git_value(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=source_root, capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _source_worktree_dirty(source_root: Path) -> bool:
    """Report source edits while excluding locally generated build outputs.

    Some source-backed probes need the upstream dependency tree present in the
    locked checkout.  Foundry/Hardhat then creates untracked output folders
    beside that tree; those outputs are not source edits and must not turn a
    reproducible source snapshot into a false dirty-worktree report.
    """

    generated_roots = {
        "node_modules", ".yarn", "cache", "out", "out_foundry", "artifacts",
        "build", "dist", "coverage", "dependencies",
    }
    status = _git_value(source_root, "status", "--porcelain=v1", "--untracked-files=all")
    for line in status.splitlines():
        if line.startswith("?? "):
            path = line[3:].replace("\\", "/")
            parts = Path(path).parts
            if any(part in generated_roots for part in parts):
                continue
        if line.strip():
            return True
    return False


def _source_snapshot(source_root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    commit = _git_value(source_root, "rev-parse", "HEAD")
    if commit != spec["commit"]:
        raise ValueError(f"source commit mismatch: {commit} != {spec['commit']}")
    remote = _git_value(source_root, "config", "--get", "remote.origin.url")
    if remote != spec["source_repo"]:
        raise ValueError(f"source repository mismatch: {remote} != {spec['source_repo']}")
    dirty = _source_worktree_dirty(source_root)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=source_root,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if archive.returncode != 0:
        # Windows Git cannot unpack some valid upstream tree paths (Polygon's
        # pinned commit contains a timestamped JSON path with ':' in its
        # filename).  Re-run the same archive command in the digest-pinned
        # Linux toolchain image so the recorded archive remains reproducible.
        docker_archive = subprocess.run(
            [
                "docker", "run", "--rm", "--pull=never", "--network=none",
                "--read-only", "--mount",
                f"type=bind,source={source_root.resolve()},target=/src,readonly",
                "--workdir", "/src", "--entrypoint", "git", FOUNDRY_IMAGE,
                "-c", "safe.directory=/src", "archive", "--format=tar", "HEAD",
            ],
            capture_output=True,
            check=False,
            timeout=180,
        )
        if docker_archive.returncode != 0:
            detail = docker_archive.stderr.decode(errors="replace").strip()
            host_detail = archive.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git archive failed on host and Docker fallback: {host_detail}; {detail}")
        archive = docker_archive
    return {
        "source_commit": commit,
        "source_repository": remote,
        "source_archive_sha256": _sha256_bytes(archive.stdout),
        "dirty_worktree": dirty,
    }


def build_source_manifest(
    lineage_id: str,
    *,
    root: Path = ROOT,
    source_cache: Path | None = None,
) -> dict[str, Any]:
    """Validate and describe every upstream Solidity file used by a harness."""

    if lineage_id not in HARNESS_LAYOUT:
        raise ValueError(f"unsupported development harness: {lineage_id}")
    layout = HARNESS_LAYOUT[lineage_id]
    spec = extract_all_artifacts.LINEAGE_SPECS[lineage_id]
    root = root.resolve()
    source_cache = (source_cache or (root.parent / "crossllm_private_sources")).resolve()
    source_root = source_cache / lineage_id
    harness_root = root / "dataset" / "harness" / lineage_id
    artifact_root = root / "dataset" / "artifacts" / lineage_id
    if not source_root.is_dir() or not harness_root.is_dir() or not artifact_root.is_dir():
        raise ValueError(f"{lineage_id}: source, harness or artifact root is missing")

    snapshot = _source_snapshot(source_root, spec)
    config = _load_json(harness_root / "harness_config.json")
    source_lock = _load_json(root / "dataset" / "sources" / "source_lock.json")
    locked = next(
        (row for row in source_lock.get("lineages", []) if isinstance(row, dict) and row.get("lineage_id") == lineage_id),
        None,
    )
    if not isinstance(locked, dict):
        raise ValueError(f"{lineage_id}: source lock record is missing")
    if config.get("source_commit") != locked.get("commit"):
        raise ValueError(f"{lineage_id}: harness config source commit does not match source lock")

    source_files: list[dict[str, Any]] = []
    support_files: list[dict[str, Any]] = []
    contracts_root = harness_root / "contracts"
    for path in sorted(contracts_root.rglob("*.sol")):
        harness_rel = _relative(path, harness_root)
        if harness_rel in layout["support_paths"]:
            support_files.append({
                "harness_path": harness_rel,
                "sha256": _sha256_file(path),
                "role": "generated_test_support",
            })
            continue
        source_rel = _source_rel_for_harness(
            harness_rel,
            str(layout["source_prefix"]),
            str(layout.get("source_strip_prefix", "")),
        )
        source_path = source_root / source_rel
        if not source_path.is_file():
            raise ValueError(f"{lineage_id}: harness source has no locked counterpart: {source_rel}")
        harness_hash = _sha256_file(path)
        source_hash = _sha256_file(source_path)
        if harness_hash != source_hash:
            raise ValueError(f"{lineage_id}: source mismatch for {harness_rel}")
        source_files.append({
            "harness_path": harness_rel,
            "source_path": source_rel,
            "sha256": source_hash,
            "role": "upstream_harness_input",
        })

    build_info = _load_json(artifact_root / "build_info.json")
    selection = _load_json(artifact_root / "selection.json")
    selected_paths = selection.get("selected_paths")
    if not isinstance(selected_paths, list) or not all(isinstance(path, str) for path in selected_paths):
        raise ValueError(f"{lineage_id}: selection.json has no selected_paths")
    if build_info.get("source_selection_hash") not in {None, selection.get("selection_hash")}:
        raise ValueError(f"{lineage_id}: build/source selection hash mismatch")

    artifact_sources: list[dict[str, Any]] = []
    for selected in selected_paths:
        source_path = source_root / selected
        if source_path.is_file() and source_path.suffix.lower() == ".sol":
            artifact_sources.append({
                "source_path": selected,
                "sha256": _sha256_file(source_path),
                "role": "artifact_selection_input",
            })

    workflow = layout["workflow"]
    required_workflow = {
        "state_initialization", "normal_workflow", "allowed_actions", "clocks",
        "finality", "attestation", "callbacks", "reset_isolation",
    }
    if set(workflow) != required_workflow:
        raise ValueError(f"{lineage_id}: workflow coverage is incomplete")
    if workflow["reset_isolation"].get("cross_test_state_reuse") is not False:
        raise ValueError(f"{lineage_id}: reset isolation must forbid state reuse")

    test_path = harness_root / "test" / f"{layout['test_contract'].replace('PairedHarnessTest', 'PairedHarness')}.t.sol"
    # ChainBridge and Celer use the same convention; retain a fallback for a
    # future suite where the filename differs from the contract name.
    if not test_path.is_file():
        candidates = sorted((harness_root / "test").glob("*.t.sol"))
        if len(candidates) != 1:
            raise ValueError(f"{lineage_id}: cannot identify one harness test source")
        test_path = candidates[0]
    runner_path = harness_root / "normal_workflow_test.py"
    runner_text = runner_path.read_text(encoding="utf-8")
    if "@sha256:" not in runner_text or "--read-only" not in runner_text:
        raise ValueError(f"{lineage_id}: runner is not digest-pinned/read-only")

    manifest = {
        "schema_version": 1,
        "lineage_id": lineage_id,
        "source_commit": spec["commit"],
        "source_repository": spec["source_repo"],
        "source_archive_sha256": snapshot["source_archive_sha256"],
        "dirty_worktree": snapshot["dirty_worktree"],
        "compiler_version": spec["solc"],
        "compiler_image": extract_all_artifacts.solc_image_for_version(spec["solc"]),
        "optimizer": bool(spec.get("optimizer", False)),
        "optimizer_runs": int(spec.get("optimizer_runs", 200)),
        "source_selection_hash": selection.get("selection_hash"),
        "artifact_manifest_sha256": _sha256_file(artifact_root / "manifest.json"),
        "upstream_harness_files": sorted(source_files, key=lambda item: item["harness_path"]),
        "artifact_selection_files": sorted(artifact_sources, key=lambda item: item["source_path"]),
        "generated_support_files": sorted(support_files, key=lambda item: item["harness_path"]),
        "test_source": {
            "path": _relative(test_path, harness_root),
            "sha256": _sha256_file(test_path),
            "role": "generated_harness_test_over_locked_source",
        },
        "workflow_coverage": workflow,
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    return manifest


def _container_command(
    lineage_id: str,
    harness_root: Path,
    compiler_volume: str,
    test_contract: str,
) -> list[str]:
    container_name = f"crossllm-source-harness-{lineage_id}-{os.getpid()}"
    return [
        "docker", "run", "--rm", "--name", container_name,
        "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit", "128",
        "--memory", "2g", "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
        "--tmpfs", "/home/foundry:rw,exec,nosuid,size=512m,uid=1000,gid=1000,mode=700",
        "-e", "FOUNDRY_CACHE_PATH=/tmp/crossllm-cache",
        "-e", "FOUNDRY_OUT=/tmp/crossllm-out",
        "--mount", f"type=bind,source={harness_root.resolve()},target=/work,readonly",
        "--mount", f"type=volume,source={compiler_volume},target=/compiler,readonly",
        "--workdir", "/work", "--entrypoint", "/usr/local/bin/forge",
        FOUNDRY_IMAGE, "test", "--root", "/work", "--out", "/tmp/crossllm-out",
        "--cache-path", "/tmp/crossllm-cache", "--use", "/compiler/solc",
        "--match-contract", test_contract, "--json",
    ]


def _count_foundry_tests(stdout: str) -> tuple[int, int, int]:
    """Extract test counts without treating malformed JSON as a pass."""
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        statuses: list[str] = []

        def visit(value: object) -> None:
            if isinstance(value, dict):
                results = value.get("test_results")
                if isinstance(results, dict):
                    for item in results.values():
                        if isinstance(item, dict) and isinstance(item.get("status"), str):
                            statuses.append(item["status"].lower())
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
        if statuses:
            passed = sum(status in {"success", "passed", "pass"} for status in statuses)
            return len(statuses), passed, len(statuses) - passed
    return 0, 0, 0


def run_source_probe(
    lineage_id: str,
    manifest: dict[str, Any],
    *,
    root: Path = ROOT,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Run one source-backed harness with the exact locked compiler."""

    layout = HARNESS_LAYOUT[lineage_id]
    harness_root = root / "dataset" / "harness" / lineage_id
    volume = extract_all_artifacts.create_compiler_cache_volume(lineage_id)
    started = datetime.now(timezone.utc)
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    reason: str | None = None
    compiler_info: dict[str, str] | None = None
    try:
        compiler_info = extract_all_artifacts.populate_compiler_cache_volume(
            volume, str(manifest["compiler_version"])
        )
        command = _container_command(lineage_id, harness_root, volume, layout["test_contract"])
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
            stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            stdout = str(error.stdout or "")
            stderr = str(error.stderr or "")
            reason = "timeout"
            subprocess.run(
                ["docker", "rm", "-f", f"crossllm-source-harness-{lineage_id}-{os.getpid()}"],
                capture_output=True, text=True, check=False,
            )
    except (OSError, RuntimeError, ValueError) as error:
        reason = f"compiler_or_container_setup:{error}"
    finally:
        extract_all_artifacts.remove_compiler_cache_volume(volume)

    total, passed, failed = _count_foundry_tests(stdout)
    status = "pass" if reason is None and exit_code == 0 and total > 0 and failed == 0 else "fail"
    if reason is None and status != "pass":
        reason = "foundry_nonzero_exit" if exit_code not in {None, 0} else "foundry_output_missing_or_failed"
    row: dict[str, Any] = {
        "schema_version": 1,
        "lineage_id": lineage_id,
        "status": status,
        "exit_code": exit_code,
        "reason": reason,
        "compiler": compiler_info,
        "compiler_version": manifest["compiler_version"],
        "compiler_image": manifest["compiler_image"],
        "foundry_image": FOUNDRY_IMAGE,
        "network_mode": "none",
        "mount_mode": "read_only_source_and_compiler",
        "test_contract": layout["test_contract"],
        "test_count": total,
        "passed_tests": passed,
        "failed_tests": failed,
        "stdout_sha256": _sha256_bytes(stdout.encode("utf-8", errors="replace")),
        "stderr_sha256": _sha256_bytes(stderr.encode("utf-8", errors="replace")),
        "source_manifest_sha256": manifest["manifest_sha256"],
        "started_at": started.isoformat().replace("+00:00", "Z"),
    }
    row["probe_row_sha256"] = canonical_hash(row)
    return row


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _refresh_artifact_manifest(artifact_root: Path) -> str:
    """Rehash an artifact pack after an in-pack provenance status update."""

    manifest_path = artifact_root / "manifest.json"
    existing = _load_json(manifest_path)
    file_hashes: dict[str, str] = {}
    for path in sorted(artifact_root.rglob("*")):
        if path.is_file() and path.name not in {"checksums.sha256", "manifest.json"}:
            relative = path.relative_to(artifact_root).as_posix()
            file_hashes[relative] = _sha256_file(path)
    manifest = {
        "lineage_id": existing.get("lineage_id"),
        "protocol": existing.get("protocol"),
        "split": existing.get("split"),
        "artifact_count": len(file_hashes),
        "files": file_hashes,
    }
    _atomic_json(manifest_path, manifest)
    checksum_lines = [f"{digest}  {relative}" for relative, digest in sorted(file_hashes.items())]
    manifest_hash = _sha256_file(manifest_path)
    checksum_lines.append(f"{manifest_hash}  manifest.json")
    (artifact_root / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    return manifest_hash


def finalize_source_backed_metadata(
    lineage_id: str,
    manifest: dict[str, Any],
    probe: dict[str, Any],
    *,
    root: Path = ROOT,
    report_path: Path = REPORT_DEFAULT,
) -> None:
    """Promote metadata only after all source-backed checks have passed."""

    if probe.get("status") != "pass":
        raise ValueError(f"{lineage_id}: refusing to finalize a non-passing probe")
    harness_root = root / "dataset" / "harness" / lineage_id
    artifact_root = root / "dataset" / "artifacts" / lineage_id
    config = _load_json(harness_root / "harness_config.json")

    # The receipt is part of the artifact manifest. Refresh that manifest
    # before binding the source manifest/config so all three identities agree.
    receipt = _load_json(artifact_root / "source_receipt.json")
    # Keep artifact provenance independent from harness metadata. Binding a
    # receipt to the harness manifest would create a checksum cycle because
    # the artifact manifest also hashes this receipt. Harness evidence is
    # bound by harness_config.json and the probe report instead.
    for key in (
        "harness_source_manifest_sha256",
        "harness_probe_row_sha256",
        "harness_probe_report",
    ):
        receipt.pop(key, None)
    receipt.update({
        "artifact_admission_status": "source_pinned_and_built",
        "harness_status": "source_backed_development",
        "compiler_binary_sha256": config.get("compiler", {}).get("binary_sha256"),
    })
    _atomic_json(artifact_root / "source_receipt.json", receipt)
    manifest["artifact_manifest_sha256"] = _refresh_artifact_manifest(artifact_root)
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = canonical_hash(manifest)
    source_manifest_path = harness_root / "source_manifest.json"
    _atomic_json(source_manifest_path, manifest)

    probe["source_manifest_sha256"] = manifest["manifest_sha256"]
    probe_without_hash = dict(probe)
    probe_without_hash.pop("probe_row_sha256", None)
    probe["probe_row_sha256"] = canonical_hash(probe_without_hash)
    config.update({
        "harness_version": "2.0.0",
        "harness_status": "source_backed_development",
        "source_backed": True,
        "source_repository": manifest["source_repository"],
        "source_selection_hash": manifest["source_selection_hash"],
        "source_manifest": source_manifest_path.name,
        "source_manifest_sha256": _sha256_file(source_manifest_path),
        "artifact_manifest_sha256": manifest["artifact_manifest_sha256"],
        "compiler": {
            "version": manifest["compiler_version"],
            "image": manifest["compiler_image"],
            "binary_sha256": probe.get("compiler", {}).get("binary_sha256") if isinstance(probe.get("compiler"), dict) else None,
            "optimizer": manifest["optimizer"],
            "optimizer_runs": manifest["optimizer_runs"],
        },
        "test_contract": probe["test_contract"],
        "workflow_coverage": manifest["workflow_coverage"],
        "evidence": {
            "probe_report": _relative(report_path, root),
            "probe_row_sha256": probe["probe_row_sha256"],
            "probe_status": "pass",
        },
    })
    _atomic_json(harness_root / "harness_config.json", config)

    report = _load_json(report_path)
    rows = report.get("probes")
    if isinstance(rows, list):
        for index, row in enumerate(rows):
            if isinstance(row, dict) and row.get("lineage_id") == lineage_id:
                rows[index] = probe
                break
    lineages = report.get("lineages")
    if isinstance(lineages, dict) and lineage_id in lineages:
        lineages[lineage_id]["source_manifest_sha256"] = manifest["manifest_sha256"]
    report.pop("report_hash", None)
    report["report_hash"] = canonical_hash(report)
    _atomic_json(report_path, report)


def build_report(
    manifests: dict[str, dict[str, Any]],
    probes: Iterable[dict[str, Any]],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    rows = list(probes)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": "development_source_backed_harness_probe",
        "source_admission": "only passing rows may be finalized",
        "foundry_image": FOUNDRY_IMAGE,
        "network_mode": "none",
        "mount_mode": "read_only_source_and_compiler",
        "lineages": {
            lineage: {
                "source_manifest_sha256": manifest["manifest_sha256"],
                "source_commit": manifest["source_commit"],
                "source_selection_hash": manifest["source_selection_hash"],
            }
            for lineage, manifest in sorted(manifests.items())
        },
        "probes": rows,
    }
    payload["report_hash"] = canonical_hash(payload)
    return payload


def _merge_report_history(existing: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Retain passing rows when one lineage is probed per source cache."""

    merged = dict(current)
    old_lineages = existing.get("lineages")
    new_lineages = current.get("lineages")
    if isinstance(old_lineages, dict) and isinstance(new_lineages, dict):
        merged["lineages"] = {**old_lineages, **new_lineages}
    old_rows = existing.get("probes")
    new_rows = current.get("probes")
    if isinstance(old_rows, list) and isinstance(new_rows, list):
        replaced = {
            row.get("lineage_id"): row
            for row in new_rows
            if isinstance(row, dict) and isinstance(row.get("lineage_id"), str)
        }
        rows = [
            row for row in old_rows
            if not isinstance(row, dict) or row.get("lineage_id") not in replaced
        ]
        rows.extend(new_rows)
        merged["probes"] = sorted(
            rows,
            key=lambda row: row.get("lineage_id", "") if isinstance(row, dict) else "",
        )
    merged.pop("report_hash", None)
    merged["report_hash"] = canonical_hash(merged)
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-cache", type=Path, default=None)
    parser.add_argument("--lineage", action="append", choices=sorted(HARNESS_LAYOUT), default=None)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="write source manifests/configs/receipts for passing probes",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report_path = args.report if args.report.is_absolute() else (root / args.report).resolve()
    lineages = args.lineage or sorted(HARNESS_LAYOUT)
    manifests: dict[str, dict[str, Any]] = {}
    probes: list[dict[str, Any]] = []
    for lineage in lineages:
        try:
            manifest = build_source_manifest(lineage, root=root, source_cache=args.source_cache)
            manifests[lineage] = manifest
            probe = run_source_probe(lineage, manifest, root=root, timeout_seconds=args.timeout_seconds)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            probe = {
                "schema_version": 1,
                "lineage_id": lineage,
                "status": "fail",
                "reason": f"pre_probe_validation:{error}",
            }
            probe["probe_row_sha256"] = canonical_hash(probe)
        probes.append(probe)
        print(f"{lineage}: {probe['status']} ({probe.get('reason') or 'ok'})")

    report = build_report(manifests, probes, root=root)
    try:
        existing = _load_json(report_path)
    except (OSError, json.JSONDecodeError, ValueError):
        existing = {}
    if isinstance(existing, dict):
        report = _merge_report_history(existing, report)
    _atomic_json(report_path, report)
    if args.finalize:
        for lineage, manifest in manifests.items():
            probe = next(row for row in probes if row.get("lineage_id") == lineage)
            finalize_source_backed_metadata(lineage, manifest, probe, root=root, report_path=report_path)
        print("finalized passing source-backed development metadata")
    passed = sum(row.get("status") == "pass" for row in probes)
    print(f"summary: {passed}/{len(probes)} pass; report={report_path}")
    return 0 if probes and passed == len(probes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
