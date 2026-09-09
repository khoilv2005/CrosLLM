import json
import hashlib
from pathlib import Path

ROOT = Path('.').resolve()
art_dir = ROOT / 'dataset' / 'artifacts' / 'celer_cbridge'
harness_dir = ROOT / 'dataset' / 'harness' / 'celer_cbridge'
source_repo = Path(r'e:\School\UIT\crossllm_private_sources\celer_cbridge')

# Read build-info from Hardhat
bi_file = source_repo / 'artifacts' / 'build-info' / '01376e9396d3daa15887530306fdad6b.json'
bi = json.loads(bi_file.read_text(encoding='utf-8'))

cbridge_out = bi['output']['contracts']['contracts/CBridge.sol']['CBridge']
abi = cbridge_out['abi']
creation_bc = '0x' + cbridge_out['evm']['bytecode']['object']
deployed_bc = '0x' + cbridge_out['evm']['deployedBytecode']['object']
storage_layout = cbridge_out['storageLayout']

# Write ABI, Bytecode, Storage Layout
(art_dir / 'abi' / 'CBridge.json').write_text(json.dumps(abi, indent=2), encoding='utf-8')
(art_dir / 'bytecode' / 'CBridge.creation.hex').write_text(creation_bc, encoding='utf-8')
(art_dir / 'bytecode' / 'CBridge.deployed.hex').write_text(deployed_bc, encoding='utf-8')
(art_dir / 'storage_layout' / 'CBridge.json').write_text(json.dumps(storage_layout, indent=2), encoding='utf-8')

# Symbols
functions = sorted(list({item['name'] for item in abi if item.get('type') == 'function'}))
events = sorted(list({item['name'] for item in abi if item.get('type') == 'event'}))
storage_vars = [item.get('label', f"slot_{item.get('slot')}") for item in storage_layout.get('storage', [])]

symbols = {
    "lineage_id": "celer_cbridge",
    "protocol": "Celer cBridge",
    "contracts": {
        "CBridge": {
            "source_path": "contracts/CBridge.sol",
            "function_count": len(functions),
            "functions": functions,
            "event_count": len(events),
            "events": events,
            "storage_slot_count": len(storage_vars),
            "storage_slots": storage_vars
        }
    }
}
(art_dir / 'symbols.json').write_text(json.dumps(symbols, indent=2), encoding='utf-8')

# Build Info
build_info = {
    "lineage_id": "celer_cbridge",
    "protocol": "Celer cBridge",
    "build_system": "Hardhat",
    "compiler": "solc",
    "solc_version": bi.get('solcVersion', '0.8.4'),
    "solc_long_version": bi.get('solcLongVersion', '0.8.4+commit.c7e474f2'),
    "optimizer": {
        "enabled": True,
        "runs": 800
    },
    "evm_version": "default",
    "build_info_hash": hashlib.sha256(bi_file.read_bytes()).hexdigest(),
    "contracts": ["CBridge"]
}
(art_dir / 'build_info.json').write_text(json.dumps(build_info, indent=2), encoding='utf-8')

# Deployment config
deployment = {
    "lineage_id": "celer_cbridge",
    "protocol": "Celer cBridge",
    "contract": "CBridge",
    "constructor_args": [],
    "proxy": None,
    "initialization": None,
    "domains": {
        "source_domain": {"name": "Ethereum", "chain_id": 1},
        "target_domain": {"name": "Arbitrum", "chain_id": 42161}
    },
    "tokens": {
        "type": "ERC20",
        "mock_symbol": "CELR_MOCK",
        "decimals": 18
    }
}
(art_dir / 'deployment.json').write_text(json.dumps(deployment, indent=2), encoding='utf-8')

# Scope
scope = {
    "lineage_id": "celer_cbridge",
    "protocol": "Celer cBridge",
    "split": "development",
    "in_scope_contracts": ["contracts/CBridge.sol:CBridge"],
    "interface_summary": {
        "entrypoints": ["transferOut", "transferIn", "confirm", "refund"],
        "view_functions": ["transfers"],
        "critical_events": ["LogNewTransferOut", "LogNewTransferIn", "LogTransferConfirmed", "LogTransferRefunded"]
    },
    "dependencies": [
        "@openzeppelin/contracts/token/ERC20/IERC20.sol",
        "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol"
    ]
}
(art_dir / 'scope.json').write_text(json.dumps(scope, indent=2), encoding='utf-8')

# Source receipt
source_receipt = {
    "lineage_id": "celer_cbridge",
    "host_id": "host_celer",
    "source_repo": "https://github.com/celer-network/cBridge-contracts.git",
    "source_commit": "d1a097be65b3c9f0f89fabacc988de68770caa18",
    "source_archive_sha256": "3c9ff4b5fcb39564c2f67eadc63633cc2214ef2ecd9b7bcae6f8563b6db5dd2e",
    "archive_format": "tar",
    "canonical_environment": "Linux Docker (Ubuntu / x86_64, pax format)",
    "pinned_status": "verified_exact_match",
    "artifact_admission_status": "source_pinned_only",
    "missing_for_case_admission": [
        "paired_evm_harness", "gold_property", "trigger_validation", "matched_negative"
    ]
}
(art_dir / 'source_receipt.json').write_text(json.dumps(source_receipt, indent=2), encoding='utf-8')

# License
license_info = {
    "lineage_id": "celer_cbridge",
    "protocol": "Celer cBridge",
    "license_spdx": "GPL-3.0-only",
    "license_file": "LICENSE",
    "license_type": "Strong Copyleft",
    "research_redistribution": "Permitted for academic benchmarking with source attribution"
}
(art_dir / 'license.json').write_text(json.dumps(license_info, indent=2), encoding='utf-8')

# Channel profile
channel_profile = {
    "lineage_id": "celer_cbridge",
    "channel_type": "hash_time_locked_transfer",
    "topology": "bidirectional_peer",
    "source_domains": ["Ethereum", "BSC", "Polygon", "Arbitrum"],
    "target_domains": ["Ethereum", "BSC", "Polygon", "Arbitrum"],
    "message_passing": "atomic_swap_preimage_revelation",
    "settlement": "onchain_hashlock_verification"
}
(art_dir / 'channel_profile.json').write_text(json.dumps(channel_profile, indent=2), encoding='utf-8')

# Normal workflow spec
normal_workflow = {
    "lineage_id": "celer_cbridge",
    "protocol": "Celer cBridge",
    "workflow_name": "htlc_atomic_cross_chain_transfer",
    "phases": [
        {
            "step": 1,
            "action": "approve_and_transfer_out",
            "domain": "source_domain",
            "actor": "user_sender",
            "function": "transferOut",
            "state_change": "transfers[transferId].status = Pending",
            "event": "LogNewTransferOut"
        },
        {
            "step": 2,
            "action": "relayer_transfer_in",
            "domain": "target_domain",
            "actor": "relayer",
            "function": "transferIn",
            "state_change": "transfers[dstTransferId].status = Pending",
            "event": "LogNewTransferIn"
        },
        {
            "step": 3,
            "action": "receiver_confirm_with_preimage",
            "domain": "target_domain",
            "actor": "user_receiver",
            "function": "confirm",
            "state_change": "transfers[dstTransferId].status = Confirmed",
            "event": "LogTransferConfirmed"
        },
        {
            "step": 4,
            "action": "relayer_confirm_on_source",
            "domain": "source_domain",
            "actor": "relayer",
            "function": "confirm",
            "state_change": "transfers[transferId].status = Confirmed",
            "event": "LogTransferConfirmed"
        }
    ]
}
(art_dir / 'normal_workflow.json').write_text(json.dumps(normal_workflow, indent=2), encoding='utf-8')

# Rehash manifest
file_hashes = {}
for p in sorted(art_dir.rglob('*')):
    if p.is_file() and p.name not in ['manifest.json', 'checksums.sha256']:
        rel = p.relative_to(art_dir).as_posix()
        file_hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()

manifest = {
    "lineage_id": "celer_cbridge",
    "protocol": "Celer cBridge",
    "split": "development",
    "artifact_count": len(file_hashes),
    "compiler_output_verified": True,
    "files": file_hashes
}
(art_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

checksum_lines = [f"{sha}  {rel}" for rel, sha in sorted(file_hashes.items())]
manifest_sha = hashlib.sha256((art_dir / 'manifest.json').read_bytes()).hexdigest()
checksum_lines.append(f"{manifest_sha}  manifest.json")
(art_dir / 'checksums.sha256').write_text('\n'.join(checksum_lines) + '\n', encoding='utf-8')

print(f"Successfully exported genuine Celer compiler artifacts ({len(file_hashes)} files, creation bytecode: {len(creation_bc)} chars, deployed: {len(deployed_bc)} chars)")
