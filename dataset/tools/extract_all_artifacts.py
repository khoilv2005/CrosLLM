#!/usr/bin/env python3
"""CrossLLM Master Dataset Artifact Extractor.
Extracts compiler artifacts, storage layouts, ABIs, bytecodes, manifests,
and harness configs across all 16 CrossLLM lineages.
"""

from __future__ import annotations

import hashlib
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

from crossllm.artifacts.builder import ArtifactPackSelector

ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = ROOT / "dataset"
ARTIFACTS_DIR = DATASET_DIR / "artifacts"
HARNESS_DIR = DATASET_DIR / "harness"
PRIVATE_SOURCES = Path(
    os.environ.get("CROSSLLM_SOURCE_CACHE", str(ROOT.parent / "crossllm_private_sources"))
)
SOURCE_LOCK_PATH = DATASET_DIR / "sources" / "source_lock.json"
TOOLCHAIN_LOCK_PATH = ROOT / "containers" / "toolchain.lock.json"
SOLC_LOCK_PATH = ROOT / "containers" / "solc.lock.json"

DOCKER_FOUNDRY = "ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17"
_DIGEST_REF = re.compile(r"@sha256:[0-9a-fA-F]{64}$")
_DOCKER_VOLUME_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_SOLC_PATH = "/compiler/solc"


def _canonical_hash(value: object) -> str:
    """Hash JSON metadata with the same stable encoding used by the package."""
    payload = json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path) -> str:
    """Return a raw SHA-256 for one regular file."""
    if not path.is_file():
        raise RuntimeError(f"expected regular source/artifact file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


_SOLIDITY_DECLARATION = re.compile(
    r"(?m)^\s*(?:(abstract)\s+)?(contract|interface|library)\s+([A-Za-z_]\w*)\b"
)


def _strip_solidity_comments(text: str) -> str:
    """Blank Solidity comments while preserving line numbers for diagnostics."""

    def replace(match: re.Match[str]) -> str:
        return "".join("\n" if character == "\n" else " " for character in match.group(0))

    return re.sub(r"//[^\n]*|/\*.*?\*/", replace, text, flags=re.DOTALL)


def source_target_metadata(source_file: Path, contract_name: str) -> dict[str, object]:
    """Classify the selected source declaration before invoking the compiler.

    Compiler output is still the authoritative deployability check, but this
    source-level gate makes an abstract/interface/library selection explicit
    and avoids spending a long container probe on a target that cannot produce
    deployable bytecode.  Comments are ignored and the declaration line is
    retained as review evidence.
    """
    try:
        text = source_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RuntimeError(f"unable to read selected source target {source_file}: {error}") from error
    declarations = [
        match for match in _SOLIDITY_DECLARATION.finditer(_strip_solidity_comments(text))
        if match.group(3) == contract_name
    ]
    if not declarations:
        raise RuntimeError(
            f"selected source target {contract_name} is not declared in {source_file}"
        )
    if len(declarations) > 1:
        raise RuntimeError(
            f"selected source target {contract_name} has multiple declarations in {source_file}"
        )
    declaration = declarations[0]
    declared_kind = declaration.group(2)
    is_abstract = declaration.group(1) == "abstract"
    kind = "abstract_contract" if is_abstract else declared_kind
    return {
        "contract_name": contract_name,
        "kind": kind,
        "deployable_source_target": kind == "contract",
        "declaration_line": text.count("\n", 0, declaration.start(2)) + 1,
    }


def require_concrete_source_target(source_file: Path, contract_name: str) -> dict[str, object]:
    """Fail closed unless the selected declaration is a concrete contract."""
    metadata = source_target_metadata(source_file, contract_name)
    if not metadata["deployable_source_target"]:
        raise RuntimeError(
            f"{contract_name} source target is {metadata['kind']} in {source_file}; "
            "select a concrete production contract instead of a test mock"
        )
    return metadata


def dependency_closure(
    source_root: Path,
    extra_roots: tuple[str, ...] = (),
) -> dict[str, object]:
    """Hash dependency trees that can affect a source-backed compiler probe.

    Git archives intentionally omit ignored package trees such as
    ``node_modules``.  Those inputs therefore need their own deterministic
    inventory.  Only the conventional dependency roots are included; build
    products and nested Git metadata are excluded so a compiler cache cannot
    masquerade as a source dependency.
    """
    root = source_root.resolve()
    records: list[dict[str, str]] = []
    roots: list[str] = []
    excluded_names = {".git", "cache", "out", "artifacts", "build", "dist", "coverage"}
    root_names = ("node_modules", "lib", "dependencies", *extra_roots)
    for root_name in root_names:
        dependency_root = root / root_name
        if not dependency_root.is_dir():
            continue
        roots.append(root_name)
        for path in sorted(dependency_root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if any(part in excluded_names for part in Path(relative).parts):
                continue
            if path.is_symlink():
                raise RuntimeError(f"dependency closure contains unsupported symlink: {relative}")
            if path.is_file():
                records.append({"path": relative, "sha256": _file_hash(path)})
    return {
        "roots": roots,
        "file_count": len(records),
        "files": records,
        "sha256": _canonical_hash(records),
    }


def deterministic_source_selection(
    source_root: Path, subpath: str, contracts: dict[str, str]
) -> dict[str, object]:
    """Resolve the public source/document closure without basename inference."""
    root = source_root.resolve()
    entry_paths = [
        (Path(subpath) / Path(target.split(":", 1)[0])).as_posix()
        if subpath
        else Path(target.split(":", 1)[0]).as_posix()
        for target in contracts.values()
    ]
    document_paths = [
        path.name
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower())
        if path.is_file()
        and (
            path.name.lower().startswith("readme")
            or path.name.lower() in {"license", "license.md", "license.txt", "copying", "copying.md"}
        )
    ]
    selection = ArtifactPackSelector().select(
        root,
        entry_paths,
        document_paths=document_paths,
        allow_unresolved_imports=True,
    )
    return selection.as_dict()


def _abi_type(item: dict[str, object]) -> str:
    """Return a canonical ABI type, including tuple component types."""
    value = item.get("type")
    if not isinstance(value, str) or not value:
        raise RuntimeError("compiler ABI item has no type")
    if not value.startswith("tuple"):
        return value
    components = item.get("components")
    if not isinstance(components, list):
        raise RuntimeError("compiler ABI tuple item has no components")
    suffix = value[len("tuple"):]
    return "(" + ",".join(_abi_type(component) for component in components) + ")" + suffix


def stable_abi_symbols(
    contract_name: str,
    source_path: str,
    source_file_sha256: str,
    abi: list[dict[str, object]],
    storage_layout: dict[str, object],
    domain: str,
) -> list[dict[str, object]]:
    """Create deterministic, domain-explicit IDs for compiler-exposed symbols."""
    if domain not in {"source", "destination", "shared"}:
        raise ValueError(f"invalid symbol domain: {domain}")
    result: list[dict[str, object]] = []
    for item in abi:
        item_type = item.get("type")
        if not isinstance(item_type, str):
            continue
        if item_type in {"function", "event", "error", "constructor"}:
            name = item.get("name")
            if item_type == "constructor":
                name = "constructor"
            if not isinstance(name, str):
                continue
            inputs = item.get("inputs", [])
            if not isinstance(inputs, list):
                raise RuntimeError(f"ABI {item_type} {name} has malformed inputs")
            signature = f"{name}({','.join(_abi_type(value) for value in inputs)})"
            kind = f"abi_{item_type}"
        elif item_type in {"fallback", "receive"}:
            signature = f"{item_type}()"
            kind = f"abi_{item_type}"
            name = item_type
        else:
            continue
        identity_hash = hashlib.sha256(
            f"{contract_name}:{kind}:{signature}".encode("utf-8")
        ).hexdigest()
        result.append({
            "symbol_id": f"{kind}.{contract_name}.{identity_hash}",
            "contract": contract_name,
            "name": name,
            "signature": signature,
            "kind": kind,
            "domain": domain,
            "source_path": source_path,
            "source_file_sha256": source_file_sha256,
        })
    storage = storage_layout.get("storage", [])
    if not isinstance(storage, list):
        raise RuntimeError(f"storage layout for {contract_name} has no storage list")
    for entry in storage:
        if not isinstance(entry, dict):
            raise RuntimeError(f"storage layout for {contract_name} has malformed entry")
        label, slot, storage_type = entry.get("label"), entry.get("slot"), entry.get("type")
        if not all(isinstance(value, str) and value for value in (label, slot, storage_type)):
            raise RuntimeError(f"storage layout for {contract_name} has incomplete entry")
        result.append({
            "symbol_id": f"storage.{contract_name}.slot_{slot}.{label}",
            "contract": contract_name,
            "name": label,
            "signature": f"storage({slot})",
            "kind": "storage",
            "type": storage_type,
            "domain": domain,
            "source_path": source_path,
            "source_file_sha256": source_file_sha256,
        })
    result.sort(key=lambda item: str(item["symbol_id"]))
    ids = [str(item["symbol_id"]) for item in result]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"duplicate stable symbol ID in {contract_name}")
    return result


def _contract_declared_name(target: str) -> str:
    """Return the Solidity declaration named by a ``path:Contract`` target."""
    declared_name = target.rsplit(":", 1)[-1].strip()
    if not declared_name or declared_name == target:
        raise RuntimeError(f"contract target must use path:Contract syntax: {target}")
    return declared_name


def _resolve_contract_source(source_root: Path, subpath: str, target: str) -> Path:
    """Resolve a contract source while keeping it inside the locked checkout."""
    source_name = target.partition(":")[0]
    candidate = (source_root / subpath / source_name).resolve()
    try:
        candidate.relative_to(source_root.resolve())
    except ValueError as error:
        raise RuntimeError(f"contract source escapes locked checkout: {target}") from error
    return candidate
DEV_HARNESS_SUITES = {
    "hop": "HopPairedHarnessTest",
    "layerzero_v2": "LayerZeroV2PairedHarnessTest",
    "celer_cbridge": "CBridgePairedHarnessTest",
    "chainbridge": "ChainBridgePairedHarnessTest",
}

# Generated harnesses exist for the evaluation lineages as well.  They remain
# development fixtures until a source-backed harness manifest and probe are
# produced, but the artifact extractor must still be able to refresh the
# locked artifact pack without silently leaving a half-written output tree.
HARNESS_SUITES = {
    **DEV_HARNESS_SUITES,
    "hyperlane": "HyperlanePairedHarnessTest",
    "axelar_gmp": "AxelarGMPPairedHarnessTest",
    "synapse": "SynapsePairedHarnessTest",
    "wormhole_evm_sdk": "WormholePairedHarnessTest",
    "across": "AcrossPairedHarnessTest",
    "stargate": "StargatePairedHarnessTest",
    "arbitrum_token_bridge": "ArbitrumBridgePairedHarnessTest",
    "optimism": "OptimismBridgePairedHarnessTest",
    "zksync_era": "ZkSyncEraPairedHarnessTest",
    "polygon_zkevm": "PolygonZkEVMPairedHarnessTest",
    "scroll": "ScrollBridgePairedHarnessTest",
    "linea": "LineaBridgePairedHarnessTest",
}

HARNESS_RUNNER_TEMPLATE = '''"""Harness test executing a pinned-container EVM workflow for __LINEAGE__ (__PROTOCOL__)."""

import json
import os
import subprocess
from pathlib import Path

DEFAULT_FOUNDRY_IMAGE = "__FOUNDRY_IMAGE__"


def run_forge_test(harness_dir: Path, contract_name: str):
    """Run Forge through argv with read-only source and disposable scratch."""
    image = os.environ.get("CROSSLLM_FOUNDRY_IMAGE", DEFAULT_FOUNDRY_IMAGE)
    if "@sha256:" not in image:
        raise ValueError("CROSSLLM_FOUNDRY_IMAGE must be digest-pinned")
    container_name = f"crossllm-harness-{harness_dir.name}-{os.getpid()}"
    command = [
        "docker", "run", "--rm", "--name", container_name, "--network=bridge",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit", "128", "--memory", "2g",
        "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
        "--tmpfs", "/home/foundry:rw,exec,nosuid,size=512m,uid=1000,gid=1000,mode=700",
        "-e", "FOUNDRY_CACHE_PATH=/tmp/crossllm-cache",
        "-e", "FOUNDRY_OUT=/tmp/crossllm-out",
        "--mount", f"type=bind,source={harness_dir.resolve()},target=/work,readonly",
        "--workdir", "/work", "--entrypoint", "/usr/local/bin/forge",
        image, "test", "--root", "/work", "--out", "/tmp/crossllm-out",
        "--cache-path", "/tmp/crossllm-cache", "--match-contract", contract_name,
        "--json",
    ]
    try:
        result = subprocess.run(
            command, cwd=harness_dir, capture_output=True, text=True,
            timeout=300, check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, text=True, check=False,
        )
        return 124, str(error.stdout or ""), str(error.stderr or "") + "\\nforge timeout"
    except OSError as error:
        return 127, "", str(error)


def test___LINEAGE___normal_workflow():
    harness_dir = Path(__file__).resolve().parent
    contract_test = "__SUITE__"
    ret, stdout, stderr = run_forge_test(harness_dir, contract_test)
    assert ret == 0, f"Foundry fixture harness failed for __LINEAGE__:\\n{stderr}\\n{stdout}"
    output_lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    assert output_lines, "No JSON test results returned by forge test"
    json.loads(output_lines[-1])

    fixtures_dir = harness_dir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    trace_record = {
        "lineage_id": "__LINEAGE__",
        "protocol": "__PROTOCOL__",
        "test_suite": contract_test,
        "execution_engine": "Foundry EVM in pinned Docker image",
        "status": "PASS",
        "evidence_scope": "generated_development_harness_smoke_only",
    }
    with (fixtures_dir / "execution_trace.json").open("w", encoding="utf-8") as stream:
        json.dump(trace_record, stream, indent=2)


if __name__ == "__main__":
    test___LINEAGE___normal_workflow()
'''


def render_harness_runner(lineage_id: str, spec: dict) -> str:
    """Render the common pinned Docker runner for a generated harness."""
    suite_name = HARNESS_SUITES.get(lineage_id)
    if suite_name is None:
        raise ValueError(f"{lineage_id}: no generated harness suite is registered")
    return (
        HARNESS_RUNNER_TEMPLATE
        .replace("__LINEAGE__", lineage_id)
        .replace("__PROTOCOL__", str(spec["protocol"]))
        .replace("__SUITE__", suite_name)
        .replace("__FOUNDRY_IMAGE__", DOCKER_FOUNDRY)
    )

LINEAGE_SPECS = {
    "hop": {
        "host_id": "hop_bridge",
        "split": "development",
        "workdir": "hop",
        "contracts": {
            "L1_Bridge": "contracts/test/Mock_L1_Bridge.sol:Mock_L1_Bridge",
            "L2_Bridge": "contracts/test/Mock_L2_Bridge.sol:Mock_L2_Bridge"
        },
        "contract_domains": {"L1_Bridge": "source", "L2_Bridge": "destination"},
        "solc": "0.6.12",
        "optimizer": True,
        "optimizer_runs": 50000,
        "license": "MIT",
        "protocol": "Hop Protocol",
        "source_repo": "https://github.com/hop-protocol/contracts.git",
        "commit": "0726ffa0e14745134116e552178fd7e0edcfa8e6",
        "archive_sha256": "054ce4a64cadd40732987268d628c76ca63cbd036c31323c0b774595ee2f87c4",
        "channel_profile": {
            "channel_type": "liquidity_bridge",
            "topology": "hub_and_spoke",
            "source_domains": ["Ethereum", "Arbitrum", "Optimism", "Polygon"],
            "target_domains": ["Ethereum", "Arbitrum", "Optimism", "Polygon"],
            "message_passing": "bonder_relayed_with_l1_roots",
            "settlement": "optimistic_challenge_window"
        }
    },
    "layerzero_v2": {
        "host_id": "layerzero_v2_endpoint",
        "split": "development",
        "workdir": "layerzero_v2",
        "subpath": "packages/layerzero-v2/evm/messagelib",
        "contracts": {
            "SendUln302": "contracts/uln/uln302/SendUln302.sol:SendUln302"
        },
        "contract_domains": {"SendUln302": "shared"},
        "solc": "0.8.36",
        "optimizer": True,
        "optimizer_runs": 20000,
        "license": "BUSL-1.1",
        "protocol": "LayerZero v2",
        "source_repo": "https://github.com/LayerZero-Labs/LayerZero-v2.git",
        "commit": "9c741e7f9790639537b1710a203bcdfd73b0b9ac",
        "dependency_root": "node_modules",
        "dependency_mounts": [
            {"source": "packages/layerzero-v2/evm/protocol", "target": "/deps/protocol"},
        ],
        "dependency_remappings": [
            {"prefix": "@openzeppelin/contracts/", "target": "/deps/node_modules/@openzeppelin/contracts/"},
            {"prefix": "@openzeppelin/contracts-upgradeable/", "target": "/deps/node_modules/@openzeppelin/contracts-upgradeable/"},
            {"prefix": "hardhat-deploy/", "target": "/deps/node_modules/hardhat-deploy/"},
            {"prefix": "solidity-bytes-utils/", "target": "/deps/node_modules/solidity-bytes-utils/"},
            {"prefix": "@chainlink/contracts-ccip/", "target": "/deps/node_modules/@chainlink/contracts-ccip/"},
            {"prefix": "@axelar-network/axelar-gmp-sdk-solidity/", "target": "/deps/node_modules/@axelar-network/axelar-gmp-sdk-solidity/"},
            {"prefix": "@layerzerolabs/lz-evm-v1-0.7/", "target": "/deps/node_modules/@layerzerolabs/lz-evm-v1-0.7/"},
            {"prefix": "@layerzerolabs/lz-evm-protocol-v2/", "target": "/deps/protocol/"},
        ],
        "archive_sha256": "5239a31abc33148080fb8cc2179e9b96967fa8e2910f33a0c14b8164ce9e333d",
        "channel_profile": {
            "channel_type": "arbitrary_messaging",
            "topology": "any_to_any",
            "source_domains": ["Ethereum", "Arbitrum", "Optimism", "BNB Chain"],
            "target_domains": ["Ethereum", "Arbitrum", "Optimism", "BNB Chain"],
            "message_passing": "decentralized_verifier_network",
            "settlement": "dvn_threshold_verification"
        }
    },
    "celer_cbridge": {
        "host_id": "celer_cbridge",
        "split": "development",
        "workdir": "celer_cbridge",
        "contracts": {
            "CBridge": "contracts/CBridge.sol:CBridge"
        },
        "contract_domains": {"CBridge": "shared"},
        "solc": "0.8.9",
        "optimizer": True,
        "optimizer_runs": 800,
        "license": "GPL-3.0",
        "protocol": "Celer cBridge",
        "source_repo": "https://github.com/celer-network/cBridge-contracts.git",
        "commit": "d1a097be65b3c9f0f89fabacc988de68770caa18",
        "archive_sha256": "3c9ff4b5fcb39564c2f67eadc63633cc2214ef2ecd9b7bcae6f8563b6db5dd2e",
        "channel_profile": {
            "channel_type": "liquidity_pool",
            "topology": "any_to_any",
            "source_domains": ["Ethereum", "BSC", "Polygon", "Arbitrum"],
            "target_domains": ["Ethereum", "BSC", "Polygon", "Arbitrum"],
            "message_passing": "sgn_multisig_attestation",
            "settlement": "sgn_validator_quorum"
        }
    },
    "chainbridge": {
        "host_id": "chainbridge_core",
        "split": "development",
        "workdir": "chainbridge",
        "contracts": {
            "Bridge": "contracts/Bridge.sol:Bridge",
            "ERC20Handler": "contracts/handlers/ERC20Handler.sol:ERC20Handler"
        },
        "contract_domains": {"Bridge": "shared", "ERC20Handler": "shared"},
        "solc": "0.8.11",
        "optimizer": True,
        "optimizer_runs": 200,
        "license": "LGPL-3.0-only",
        "protocol": "ChainBridge",
        "source_repo": "https://github.com/ChainSafe/chainbridge-solidity.git",
        "commit": "b929c980afcdffae10d61c7065a5655479638519",
        "archive_sha256": "d14c1039eaa8088a404343f53945a84b97dbea58725ae42931967e6e299fb82d",
        "channel_profile": {
            "channel_type": "lock_mint_burn_release",
            "topology": "bidirectional_peer",
            "source_domains": ["Ethereum", "Substrate_EVM"],
            "target_domains": ["Ethereum", "Substrate_EVM"],
            "message_passing": "relayer_quorum_vote",
            "settlement": "m_of_n_relayer_signatures"
        }
    },
    "hyperlane": {
        "host_id": "hyperlane_mailbox",
        "split": "evaluation",
        "workdir": "hyperlane/solidity",
        "dependency_roots": ["solidity/dependencies"],
        "contracts": {
            "Mailbox": "contracts/Mailbox.sol:Mailbox"
        },
        "contract_domains": {"Mailbox": "shared"},
        "solc": "0.8.33",
        "license": "Apache-2.0",
        "protocol": "Hyperlane",
        "source_repo": "https://github.com/hyperlane-xyz/hyperlane-monorepo.git",
        "commit": "8ae786a778857216ad31325f741e9f9cb01b3088",
        "archive_sha256": "c765eeef6a7aae29bb27bd9f5b7ecc13d86cdfde413ff4a778acd0d2a3b5a4ed",
        "channel_profile": {
            "channel_type": "modular_messaging",
            "topology": "any_to_any",
            "source_domains": ["Ethereum", "Arbitrum", "Optimism", "Polygon", "Base"],
            "target_domains": ["Ethereum", "Arbitrum", "Optimism", "Polygon", "Base"],
            "message_passing": "interchain_security_module",
            "settlement": "ism_verification_dispatch"
        }
    },
    "axelar_gmp": {
        "host_id": "axelar_gmp_gateway",
        "split": "evaluation",
        "workdir": "axelar_gmp",
        "contracts": {
            "AxelarAmplifierGateway": "contracts/gateway/AxelarAmplifierGateway.sol:AxelarAmplifierGateway"
        },
        "contract_domains": {"AxelarAmplifierGateway": "shared"},
        "solc": "0.8.36",
        "license": "MIT",
        "protocol": "Axelar GMP",
        "source_repo": "https://github.com/axelarnetwork/axelar-gmp-sdk-solidity.git",
        "commit": "30196ca7cb9479fd5f79f0668523bd2a488093ed",
        "archive_sha256": "ca877c98ee8d4494b9507c8e275cb1f12cbb3bce62d58a78104ed46e19881df8",
        "channel_profile": {
            "channel_type": "general_message_passing",
            "topology": "hub_and_spoke",
            "source_domains": ["Ethereum", "Avalanche", "Polygon", "Fantom"],
            "target_domains": ["Ethereum", "Avalanche", "Polygon", "Fantom"],
            "message_passing": "axelar_proof_verification",
            "settlement": "weighted_multisig_gateway_approval"
        }
    },
    "synapse": {
        "host_id": "synapse_bridge",
        "split": "evaluation",
        "workdir": "synapse",
        "contracts": {
            "SynapseBridge": "contracts/bridge/SynapseBridge.sol:SynapseBridge"
        },
        "contract_domains": {"SynapseBridge": "shared"},
        "solc": "0.6.12",
        "license": "MIT",
        "protocol": "Synapse Protocol",
        "source_repo": "https://github.com/synapsecns/synapse-contracts.git",
        "commit": "60f1c25cf2f115911e11255f515e1450fe96100c",
        "archive_sha256": "293b8e7be9f0636101c1c1ee22f84a16c5d56314763a1dc54bb2d4dd6726e66f",
        "channel_profile": {
            "channel_type": "cross_chain_liquidity_and_messaging",
            "topology": "any_to_any",
            "source_domains": ["Ethereum", "Arbitrum", "Optimism", "Avalanche"],
            "target_domains": ["Ethereum", "Arbitrum", "Optimism", "Avalanche"],
            "message_passing": "validator_attestation_kappa",
            "settlement": "node_group_signature"
        }
    },
    "wormhole_evm_sdk": {
        "host_id": "wormhole_core_bridge",
        "split": "evaluation",
        "workdir": "wormhole_evm_sdk",
        "contracts": {
            "Proxy": "src/proxy/Proxy.sol:Proxy"
        },
        "contract_domains": {"Proxy": "shared"},
        "solc": "0.8.30",
        "license": "Apache-2.0",
        "protocol": "Wormhole",
        "source_repo": "https://github.com/wormhole-foundation/wormhole-solidity-sdk.git",
        "commit": "2cb855ea9d0a6c28470620a6d37c04d0496ea919",
        "archive_sha256": "77078163d0ae9a099d104e20fd801c0bf35f05bcc4a150609bf3f77546f56163",
        "channel_profile": {
            "channel_type": "vaa_attestation_bridge",
            "topology": "any_to_any",
            "source_domains": ["Ethereum", "Solana", "BSC", "Polygon", "Arbitrum"],
            "target_domains": ["Ethereum", "Solana", "BSC", "Polygon", "Arbitrum"],
            "message_passing": "guardian_network_vaa",
            "settlement": "13_of_19_guardian_quorum"
        }
    },
    "across": {
        "host_id": "across_spokepool",
        "split": "evaluation",
        "workdir": "across",
        "contracts": {
            "Ethereum_SpokePool": "contracts/spoke-pools/Ethereum_SpokePool.sol:Ethereum_SpokePool"
        },
        "contract_domains": {"Ethereum_SpokePool": "shared"},
        "solc": "0.8.30",
        "license": "BUSL-1.1",
        "protocol": "Across Protocol",
        "source_repo": "https://github.com/across-protocol/contracts.git",
        "commit": "19e346a5415e2ebb18fafe590f76dc90f413d1b5",
        "archive_sha256": "102b405b61e54a9f9787a70bf31aadc659e9cf018626ab226d672190026c1f15",
        "channel_profile": {
            "channel_type": "intent_based_relayer_pool",
            "topology": "hub_and_spoke",
            "source_domains": ["Ethereum", "Arbitrum", "Optimism", "Polygon", "Base"],
            "target_domains": ["Ethereum", "Arbitrum", "Optimism", "Polygon", "Base"],
            "message_passing": "uma_optimistic_oracle",
            "settlement": "relayer_fill_and_root_bundle"
        }
    },
    "stargate": {
        "host_id": "stargate_bridge",
        "split": "evaluation",
        "workdir": "stargate",
        "contracts": {
            "Bridge": "contracts/Bridge.sol:Bridge",
            "Pool": "contracts/Pool.sol:Pool",
            "Router": "contracts/Router.sol:Router"
        },
        "contract_domains": {"Bridge": "shared", "Pool": "shared", "Router": "shared"},
        "solc": "0.7.6",
        "license": "BUSL-1.1",
        "protocol": "Stargate Finance",
        "source_repo": "https://github.com/stargate-protocol/stargate.git",
        "commit": "c4212c2ee76997b1099ee9b34da0f1ed32dcf9c4",
        "archive_sha256": "06b1549bbb45ec8beb0a9f6ec95bb0853057a740f06c439d8f73020803b28167",
        "channel_profile": {
            "channel_type": "unified_liquidity_bridge",
            "topology": "mesh",
            "source_domains": ["Ethereum", "BNB Chain", "Avalanche", "Polygon", "Arbitrum"],
            "target_domains": ["Ethereum", "BNB Chain", "Avalanche", "Polygon", "Arbitrum"],
            "message_passing": "layerzero_relayer_oracle",
            "settlement": "instant_guaranteed_finality"
        }
    },
    "arbitrum_token_bridge": {
        "host_id": "arbitrum_token_bridge",
        "split": "evaluation",
        "workdir": "arbitrum_token_bridge",
        "contracts": {
            "L1GatewayRouter": "contracts/tokenbridge/ethereum/gateway/L1GatewayRouter.sol:L1GatewayRouter",
            "L2GatewayRouter": "contracts/tokenbridge/arbitrum/gateway/L2GatewayRouter.sol:L2GatewayRouter"
        },
        "contract_domains": {"L1GatewayRouter": "source", "L2GatewayRouter": "destination"},
        "solc": "0.8.16",
        "license": "Apache-2.0",
        "protocol": "Arbitrum Token Bridge",
        "source_repo": "https://github.com/OffchainLabs/token-bridge-contracts.git",
        "commit": "7ef9d4ed4257ec035aeaa1fd7457c537b8f7c7c5",
        "archive_sha256": "e89cb4aee4d3f106f8b63f36322345b9b01cf32b4cbf1851c8b5a692d6ba5dee",
        "channel_profile": {
            "channel_type": "rollup_canonical_token_bridge",
            "topology": "l1_l2_paired",
            "source_domains": ["Ethereum"],
            "target_domains": ["Arbitrum One"],
            "message_passing": "inbox_retryable_tickets",
            "settlement": "nitro_fraud_proof_rollup"
        }
    },
    "optimism": {
        "host_id": "optimism_bedrock",
        "split": "evaluation",
        "workdir": "optimism/packages/contracts-bedrock",
        "contracts": {
            "OptimismPortal2": "src/L1/OptimismPortal2.sol:OptimismPortal2",
            "L1CrossDomainMessenger": "src/L1/L1CrossDomainMessenger.sol:L1CrossDomainMessenger"
        },
        "contract_domains": {"OptimismPortal2": "source", "L1CrossDomainMessenger": "source"},
        "solc": "0.8.15",
        "license": "MIT",
        "protocol": "Optimism Bedrock",
        "source_repo": "https://github.com/ethereum-optimism/optimism.git",
        "commit": "392b395e8c7618a939e34174b6c9cea7eee5df0e",
        "archive_sha256": "34814c4eaff6cd498d025d3fe082dfff47296bcd00c37241f423a7d02762fea3",
        "channel_profile": {
            "channel_type": "rollup_canonical_cross_domain_messenger",
            "topology": "l1_l2_paired",
            "source_domains": ["Ethereum"],
            "target_domains": ["OP Mainnet"],
            "message_passing": "portal_deposit_and_relay",
            "settlement": "fault_proof_system_portal2"
        },
        "dependency_remappings": [
            {
                "prefix": "@solady/",
                "target": "/src/packages/contracts-bedrock/lib/solady/src/"
            }
        ],
        "scratch_mounts": [
            "/src/packages/contracts-bedrock/artifacts/build-info"
        ]
    },
    "zksync_era": {
        "host_id": "zksync_era_bridge",
        "split": "evaluation",
        "workdir": "zksync_era",
        "subpath": "l1-contracts",
        "dependency_mounts": [
            {"source": "lib", "target": "/src/l1-contracts/lib"},
        ],
        "contracts": {
            "L1ERC20Bridge": "contracts/bridge/L1ERC20Bridge.sol:L1ERC20Bridge"
        },
        "contract_domains": {"L1ERC20Bridge": "source"},
        "solc": "0.8.28",
        "license": "MIT",
        "protocol": "zkSync Era",
        "source_repo": "https://github.com/matter-labs/era-contracts.git",
        "commit": "ad5a4783a3f05b18049af62a2f31885ce4c70c3c",
        "archive_sha256": "edc5d1efb2052cc5e62041ebe5d8eb9dc778a31dadd4cc6a4065265bb359c33b",
        "channel_profile": {
            "channel_type": "zk_rollup_canonical_bridge",
            "topology": "l1_l2_paired",
            "source_domains": ["Ethereum"],
            "target_domains": ["zkSync Era"],
            "message_passing": "priority_queue_and_l2_log",
            "settlement": "snark_validity_proof"
        }
    },
    "polygon_zkevm": {
        "host_id": "polygon_zkevm_agglayer",
        "split": "evaluation",
        "workdir": "polygon_zkevm",
        "contracts": {
            "AgglayerBridge": "contracts/AgglayerBridge.sol:AgglayerBridge"
        },
        "contract_domains": {"AgglayerBridge": "shared"},
        "solc": "0.8.28",
        "license": "AGPL-3.0",
        "protocol": "Polygon zkEVM / Agglayer",
        "source_repo": "https://github.com/0xPolygonHermez/zkevm-contracts.git",
        "commit": "110bda5a03e70ee7331bc06407a8e79226d3e520",
        "archive_sha256": "c4793b6fc2016ddb2ede4ec205ea264367ce711ba8e1b99304ae8edc514e6848",
        "sparse_checkout_roots": [
            "contracts",
            "foundry.toml",
            "package.json",
            "package-lock.json",
            "src",
        ],
        "dependency_remappings": [
            {
                "prefix": "@openzeppelin/contracts/",
                "target": "/src/node_modules/@openzeppelin/contracts5/",
            },
            {
                "prefix": "@openzeppelin/contracts-upgradeable/",
                "target": "/src/node_modules/@openzeppelin/contracts-upgradeable5/",
            },
        ],
        "channel_profile": {
            "channel_type": "agglayer_shared_bridge",
            "topology": "hub_and_spoke_unified_exit_root",
            "source_domains": ["Ethereum", "Polygon zkEVM"],
            "target_domains": ["Ethereum", "Polygon zkEVM"],
            "message_passing": "global_exit_root_manager",
            "settlement": "zk_snark_state_transition"
        }
    },
    "scroll": {
        "host_id": "scroll_messenger",
        "split": "evaluation",
        "workdir": "scroll",
        "contracts": {
            "L1ScrollMessenger": "src/L1/L1ScrollMessenger.sol:L1ScrollMessenger",
            "L2ScrollMessenger": "src/L2/L2ScrollMessenger.sol:L2ScrollMessenger"
        },
        "contract_domains": {"L1ScrollMessenger": "source", "L2ScrollMessenger": "destination"},
        "solc": "0.8.24",
        "license": "MIT",
        "protocol": "Scroll",
        "source_repo": "https://github.com/scroll-tech/scroll-contracts.git",
        "commit": "dfbd661520ac30505a773881728cc5cfb005978b",
        "archive_sha256": "ecdb59ab1379c8ab63057d8d4b6fa2347986e0641c81e6aa515c7f1e3a644028",
        "channel_profile": {
            "channel_type": "zk_rollup_cross_domain_messenger",
            "topology": "l1_l2_paired",
            "source_domains": ["Ethereum"],
            "target_domains": ["Scroll"],
            "message_passing": "l1_message_queue_and_relay",
            "settlement": "halo2_validity_proof"
        }
    },
    "linea": {
        "host_id": "linea_rollup",
        "split": "evaluation",
        "workdir": "linea",
        "contracts": {
            "LineaRollup": "contracts/LineaRollup.sol:LineaRollup"
        },
        "contract_domains": {"LineaRollup": "shared"},
        "solc": "0.8.24",
        "license": "Apache-2.0",
        "protocol": "Linea",
        "source_repo": "https://github.com/Consensys/linea-contracts.git",
        "commit": "b64fe259195f00e840d1e2a3f08b8e95e7c90918",
        "archive_sha256": "0fdad7e1e844acc5f7a60943cf6f0f8213fe23c876dd3ba321d77519b7d5b93e",
        "channel_profile": {
            "channel_type": "type2_zkevm_canonical_rollup",
            "topology": "l1_l2_paired",
            "source_domains": ["Ethereum"],
            "target_domains": ["Linea"],
            "message_passing": "l1_l2_message_service",
            "settlement": "plonk_validity_proof"
        }
    }
}


def load_source_lock(path: Path = SOURCE_LOCK_PATH) -> dict:
    """Load the repository's single authoritative lineage lock."""
    with path.open(encoding="utf-8") as handle:
        lock = json.load(handle)
    if not isinstance(lock, dict) or not isinstance(lock.get("lineages"), list):
        raise ValueError(f"invalid source lock structure: {path}")
    return lock


def validate_lineage_specs(
    specs: dict[str, dict], source_lock: dict
) -> list[str]:
    """Return all metadata mismatches that would make extraction unsafe.

    The extractor historically carried a second, stale copy of repository and
    commit metadata.  A successful extraction from that copy could therefore
    overwrite an artifact pack while claiming a different source.  This pure
    check keeps the lock as the authority and is deliberately fail-closed.
    """
    records = source_lock.get("lineages")
    if not isinstance(records, list):
        return ["source lock has no lineages list"]

    locked = {
        row.get("lineage_id"): row
        for row in records
        if isinstance(row, dict) and row.get("lineage_id")
    }
    errors: list[str] = []
    spec_ids = set(specs)
    lock_ids = set(locked)
    for lineage_id in sorted(spec_ids - lock_ids):
        errors.append(f"{lineage_id}: missing from source_lock.json")
    for lineage_id in sorted(lock_ids - spec_ids):
        errors.append(f"{lineage_id}: missing from extractor LINEAGE_SPECS")

    for lineage_id in sorted(spec_ids & lock_ids):
        spec = specs[lineage_id]
        row = locked[lineage_id]
        comparisons = {
            "source_repo": (spec.get("source_repo"), row.get("repository")),
            "commit": (spec.get("commit"), row.get("commit")),
            "split": (spec.get("split"), row.get("split")),
        }
        for field, (actual, expected) in comparisons.items():
            if actual != expected:
                errors.append(
                    f"{lineage_id}: {field}={actual!r} does not match locked {expected!r}"
                )
        solc = spec.get("solc")
        if not isinstance(solc, str) or re.fullmatch(r"\d+\.\d+\.\d+", solc) is None:
            errors.append(f"{lineage_id}: solc must use x.y.z")
        optimizer = spec.get("optimizer", False)
        if not isinstance(optimizer, bool):
            errors.append(f"{lineage_id}: optimizer must be boolean")
        optimizer_runs = spec.get("optimizer_runs", 200)
        if (
            not isinstance(optimizer_runs, int)
            or isinstance(optimizer_runs, bool)
            or optimizer_runs <= 0
        ):
            errors.append(f"{lineage_id}: optimizer_runs must be a positive integer")
        dependency_roots = spec.get("dependency_roots", [])
        if not isinstance(dependency_roots, list):
            errors.append(f"{lineage_id}: dependency_roots must be a list")
        else:
            for dependency_root in dependency_roots:
                root_path = Path(str(dependency_root))
                if (
                    not isinstance(dependency_root, str)
                    or not dependency_root
                    or root_path.is_absolute()
                    or "." in root_path.parts
                    or ".." in root_path.parts
                ):
                    errors.append(
                        f"{lineage_id}: dependency root must be a safe relative path: {dependency_root!r}"
                    )
        sparse_checkout_roots = spec.get("sparse_checkout_roots", [])
        if not isinstance(sparse_checkout_roots, list):
            errors.append(f"{lineage_id}: sparse_checkout_roots must be a list")
        else:
            for sparse_root in sparse_checkout_roots:
                root_path = Path(str(sparse_root))
                if (
                    not isinstance(sparse_root, str)
                    or not sparse_root
                    or root_path.is_absolute()
                    or "." in root_path.parts
                    or ".." in root_path.parts
                ):
                    errors.append(
                        f"{lineage_id}: sparse checkout root must be a safe relative path: {sparse_root!r}"
                    )
        contracts = spec.get("contracts")
        if not isinstance(contracts, dict) or not contracts:
            errors.append(f"{lineage_id}: contracts must be a non-empty mapping")
        else:
            contract_domains = spec.get("contract_domains")
            if not isinstance(contract_domains, dict):
                errors.append(f"{lineage_id}: contract_domains must be an explicit mapping")
            else:
                missing_domains = set(contracts) - set(contract_domains)
                extra_domains = set(contract_domains) - set(contracts)
                for contract_name in sorted(missing_domains):
                    errors.append(f"{lineage_id}: missing domain for {contract_name}")
                for contract_name in sorted(extra_domains):
                    errors.append(f"{lineage_id}: domain assigned to unknown contract {contract_name}")
                for contract_name, domain in sorted(contract_domains.items()):
                    if domain not in {"source", "destination", "shared"}:
                        errors.append(f"{lineage_id}: invalid domain {domain!r} for {contract_name}")
            for contract_name, target in contracts.items():
                if not isinstance(contract_name, str) or not contract_name:
                    errors.append(f"{lineage_id}: contract names must be non-empty strings")
                if not isinstance(target, str):
                    errors.append(f"{lineage_id}: contract target for {contract_name!r} must be a string")
                    continue
                source_path, separator, source_name = target.partition(":")
                if (
                    not separator
                    or not source_path
                    or not source_name
                    or Path(source_path).is_absolute()
                    or ".." in Path(source_path).parts
                ):
                    errors.append(f"{lineage_id}: malformed contract target {target!r}")
    return errors


def validate_toolchain_image(path: Path = TOOLCHAIN_LOCK_PATH) -> list[str]:
    """Ensure the extraction command uses the pinned development image."""
    with path.open(encoding="utf-8") as handle:
        lock = json.load(handle)
    expected = lock.get("images", {}).get("foundry", {}).get("ref")
    if not expected:
        return ["toolchain.lock.json has no pinned Foundry image"]
    if DOCKER_FOUNDRY != expected:
        return [
            f"DOCKER_FOUNDRY={DOCKER_FOUNDRY!r} does not match pinned {expected!r}"
        ]
    return []


def validate_solc_lock(path: Path = SOLC_LOCK_PATH) -> list[str]:
    """Validate the immutable compiler image map used by source extraction."""
    try:
        with path.open(encoding="utf-8") as handle:
            lock = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        return [f"unable to read solc lock: {error}"]
    images = lock.get("images")
    if not isinstance(images, dict):
        return ["solc lock has no images map"]
    required = sorted({str(spec.get("solc")) for spec in LINEAGE_SPECS.values()})
    errors: list[str] = []
    for version in required:
        image = images.get(version)
        if not isinstance(image, str):
            errors.append(f"solc lock is missing version {version}")
            continue
        if not image.startswith("ghcr.io/argotorg/solc@") or not _DIGEST_REF.search(image):
            errors.append(f"solc image for {version} must be digest-pinned")
    return errors


def solc_image_for_version(version: str, path: Path = SOLC_LOCK_PATH) -> str:
    """Resolve one version to its digest-pinned compiler image."""
    with path.open(encoding="utf-8") as handle:
        lock = json.load(handle)
    image = lock.get("images", {}).get(version)
    if not isinstance(image, str) or not image.startswith("ghcr.io/argotorg/solc@"):
        raise RuntimeError(f"no digest-pinned solc image is locked for {version}")
    if not _DIGEST_REF.search(image):
        raise RuntimeError(f"solc image for {version} is not digest-pinned")
    return image


def run_forge_inspect(
    repo_path: Path,
    contract_spec: str,
    inspect_kind: str,
    as_json: bool = False,
    subpath: str = "",
    docker_network: str = "none",
    solc_version: str | None = None,
    optimizer: bool = False,
    optimizer_runs: int = 200,
    compiler_cache_volume: str | None = None,
    compiler_path: str | None = None,
    dependency_root: Path | None = None,
    dependency_mounts: tuple[tuple[Path, str], ...] = (),
    remappings: tuple[tuple[str, str], ...] = (),
    scratch_mounts: tuple[str, ...] = (),
    timeout_seconds: int = 120,
) -> str:
    """Run ``forge inspect`` in a pinned container with a read-only source mount.

    The secure default is ``none``. A development probe may explicitly opt into
    ``bridge`` when the pinned Foundry image must download a matching solc into
    disposable scratch storage; the selected network is recorded in build info.
    """
    if docker_network not in {"none", "bridge"}:
        raise ValueError("docker_network must be none or bridge")
    if solc_version is not None and re.fullmatch(r"\d+\.\d+\.\d+", solc_version) is None:
        raise ValueError("solc_version must use x.y.z")
    if not isinstance(optimizer, bool):
        raise ValueError("optimizer must be boolean")
    if not isinstance(optimizer_runs, int) or isinstance(optimizer_runs, bool) or optimizer_runs <= 0:
        raise ValueError("optimizer_runs must be a positive integer")
    if compiler_cache_volume is not None and not _DOCKER_VOLUME_NAME.fullmatch(compiler_cache_volume):
        raise ValueError("compiler_cache_volume must be a valid Docker volume name")
    if compiler_path is not None and (
        compiler_cache_volume is None
        or not compiler_path.startswith("/")
        or ".." in Path(compiler_path).parts
    ):
        raise ValueError("compiler_path must be an absolute path inside compiler_cache_volume")
    if dependency_root is not None and not dependency_root.is_dir():
        raise ValueError("dependency_root must be an existing directory")
    for mount_source, mount_target in dependency_mounts:
        if not mount_source.is_dir():
            raise ValueError(f"dependency mount source must be an existing directory: {mount_source}")
        if not mount_target.startswith("/") or ".." in Path(mount_target).parts:
            raise ValueError(f"dependency mount target must be an absolute safe path: {mount_target}")
    for prefix, target in remappings:
        if not prefix or not target or "=" in prefix or not target.startswith("/"):
            raise ValueError("dependency remappings must contain a non-empty prefix and absolute target")
    for scratch_path in scratch_mounts:
        path = PurePosixPath(scratch_path)
        if (
            not scratch_path.startswith("/src/")
            or not path.is_absolute()
            or ".." in path.parts
            or scratch_path.rstrip("/") == "/src"
        ):
            raise ValueError("scratch mounts must be non-root absolute paths under /src")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive integer")
    workdir_in_container = f"/src/{subpath}".rstrip("/") if subpath else "/src"
    mount = f"{repo_path.resolve()}:/src:ro"
    container_name = (
        f"crossllm-inspect-{os.getpid()}-"
        f"{hashlib.sha256(f'{repo_path.resolve()}:{subpath}:{contract_spec}:{inspect_kind}'.encode()).hexdigest()[:12]}"
    )

    def invoke(target: str) -> subprocess.CompletedProcess[str]:
        command = [
            "docker", "run", "--rm", "--name", container_name,
            f"--network={docker_network}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit", "128",
            "--memory", "2g",
            # Foundry's cache and output paths are redirected below. Mounting
            # child tmpfs paths under a read-only source bind is not portable:
            # Docker cannot create missing /src/cache or /src/out mountpoints
            # after the read-only root has been applied.
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m",
            # Root runs are used only for the compiler cache. A lineage-scoped
            # named volume may be supplied so the four inspect calls reuse one
            # downloaded SVM compiler; it is removed by the caller after the
            # lineage completes. Without it, retain the disposable tmpfs
            # fallback used by direct/unit-test probes.
            "-u", "0:0",
            "-e", "FOUNDRY_CACHE_PATH=/tmp/foundry-cache",
            "-e", "FOUNDRY_OUT=/tmp/foundry-out",
            "--entrypoint", "forge",
            "-v", mount,
            "-w", workdir_in_container,
            DOCKER_FOUNDRY,
            "inspect",
        ]
        if compiler_cache_volume is None:
            command[command.index("-u"):command.index("-u")] = [
                "--tmpfs", "/root/.svm:rw,exec,nosuid,size=512m",
            ]
        else:
            command[command.index("-u"):command.index("-u")] = [
                "--mount", f"type=volume,source={compiler_cache_volume},target=/compiler",
            ]
        if dependency_root is not None:
            command[command.index(DOCKER_FOUNDRY):command.index(DOCKER_FOUNDRY)] = [
                "--mount",
                f"type=bind,source={dependency_root.resolve()},target=/deps/node_modules,readonly",
            ]
        for mount_source, mount_target in dependency_mounts:
            command[command.index(DOCKER_FOUNDRY):command.index(DOCKER_FOUNDRY)] = [
                "--mount",
                f"type=bind,source={mount_source.resolve()},target={mount_target},readonly",
            ]
        for scratch_path in scratch_mounts:
            command[command.index(DOCKER_FOUNDRY):command.index(DOCKER_FOUNDRY)] = [
                "--tmpfs",
                f"{scratch_path}:rw,exec,nosuid,size=512m",
            ]
        if compiler_cache_volume is not None:
            command.extend(("--use", compiler_path or _SOLC_PATH))
        elif solc_version is not None:
            command.extend(("--use", solc_version))
        for prefix, remap_target in remappings:
            command.extend(("--remappings", f"{prefix}={remap_target}"))
        command.extend(("--optimize", str(optimizer).lower(), "--optimizer-runs", str(optimizer_runs), target, inspect_kind))
        if as_json:
            command.append("--json")
        try:
            return subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_seconds
            )
        except subprocess.TimeoutExpired:
            # ``docker run --rm`` cannot remove a container while the client
            # itself is still blocked. Explicitly remove this uniquely named
            # probe so a compiler/network stall does not accumulate orphans.
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                text=True,
                check=False,
            )
            raise

    target = contract_spec
    result = invoke(target)
    if result.returncode != 0 and ":" in contract_spec:
        target = contract_spec.split(":")[-1]
        result = invoke(target)
    if result.returncode != 0:
        raise RuntimeError(
            f"forge inspect {contract_spec} {inspect_kind} failed:\n"
            f"{result.stderr}\n{result.stdout}"
        )
    return result.stdout.strip()


def _require_deployable_bytecode(contract_name: str, creation: str, deployed: str) -> None:
    """Reject interfaces/abstract targets instead of writing ``0x`` artifacts."""
    for kind, value in (("creation", creation), ("deployed", deployed)):
        normalized = value.strip()
        if normalized in {"", "0x", "0X"}:
            raise RuntimeError(
                f"{contract_name} has no deployable {kind} bytecode; "
                "the selected source target may be abstract or an interface"
            )
        if not re.fullmatch(r"0x[0-9a-fA-F]+", normalized):
            raise RuntimeError(f"{contract_name} returned malformed {kind} bytecode")


def source_snapshot(
    repo_path: Path,
    spec: dict,
    *,
    docker_archive_image: str | None = None,
    source_cache: Path | None = None,
    lineage_id: str | None = None,
) -> dict[str, object]:
    """Resolve and hash the locked source tree without trusting embedded metadata."""
    if not repo_path.is_dir():
        raise RuntimeError(f"source cache directory is missing: {repo_path}")

    def git(*args: str, binary: bool = False) -> str | bytes:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=not binary,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace") if binary else result.stderr
            raise RuntimeError(f"git {' '.join(args)} failed: {detail.strip()}")
        return result.stdout

    commit = str(git("rev-parse", "HEAD")).strip()
    remote = str(git("remote", "get-url", "origin")).strip()
    if commit != spec["commit"]:
        raise RuntimeError(
            f"source commit mismatch: {commit} != locked {spec['commit']}"
        )
    if remote.rstrip("/").removesuffix(".git").lower() != (
        str(spec["source_repo"]).rstrip("/").removesuffix(".git").lower()
    ):
        raise RuntimeError(
            f"source remote mismatch: {remote} != locked {spec['source_repo']}"
        )
    archive_result = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    archive_backend = "host"
    archive_stderr = archive_result.stderr.decode("utf-8", errors="replace").strip() or None
    if archive_result.returncode != 0 and docker_archive_image:
        if not _DIGEST_REF.search(docker_archive_image):
            raise ValueError("docker_archive_image must use an immutable @sha256 digest")
        if source_cache is None or lineage_id is None:
            raise ValueError("source_cache and lineage_id are required for Docker archive fallback")
        cache_root = source_cache.resolve()
        try:
            relative_repo = repo_path.resolve().relative_to(cache_root)
        except ValueError as error:
            raise ValueError("repo_path must be inside source_cache for Docker archive fallback") from error
        docker_result = subprocess.run(
            [
                "docker", "run", "--rm", "--network=none", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "-v", f"{cache_root}:/sources:ro", "--entrypoint", "git",
                docker_archive_image,
                "-c", f"safe.directory=/sources/{relative_repo.as_posix()}",
                "-C", f"/sources/{relative_repo.as_posix()}",
                "archive", "--format=tar", "HEAD",
            ],
            cwd=cache_root,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if docker_result.returncode == 0:
            archive_result = docker_result
            archive_backend = "docker"
        else:
            docker_stderr = docker_result.stderr.decode("utf-8", errors="replace").strip() or None
            archive_stderr = "; ".join(
                detail for detail in (
                    archive_stderr,
                    f"docker fallback: {docker_stderr}" if docker_stderr else None,
                ) if detail
            ) or None
    if archive_result.returncode != 0:
        raise RuntimeError(f"git archive failed: {archive_stderr or 'unknown error'}")
    archive = archive_result.stdout
    status = str(git("status", "--porcelain=v1", "--untracked-files=all"))
    # Package managers materialize ignored-by-provenance dependency trees in
    # the checkout (notably Windows junctions for Yarn workspaces).  Those
    # inputs are hashed separately by ``dependency_closure`` and must not turn
    # an otherwise exact locked source commit into a dirty source revision.
    # Tracked source/config changes remain dirty, as do untracked files outside
    # these explicitly generated roots.
    generated_roots = {
        "node_modules", ".yarn", "cache", "out", "out_foundry", "artifacts", "build", "dist",
        "coverage", "dependencies",
    }
    sparse_checkout_roots = tuple(
        PurePosixPath(value.replace("\\", "/"))
        for value in spec.get("sparse_checkout_roots", [])
        if isinstance(value, str) and value
    )
    relevant_status: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        change = line[:2]
        path_text = line[3:]
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        path_text = path_text.strip('"')
        posix_path = PurePosixPath(path_text.replace("\\", "/"))
        parts = Path(path_text).parts
        is_generated = any(part in generated_roots for part in parts)
        if change == "??" and is_generated:
            continue
        # Windows cannot materialize a small number of locked upstream paths
        # containing reserved characters (notably Polygon's timestamped JSON
        # files). A sparse checkout may therefore intentionally show those
        # tracked paths as deleted. They are excluded from the compiler input
        # and the archive is still computed from the immutable Git tree (using
        # the Docker fallback on Windows), so do not misclassify that layout as
        # a source mutation.
        is_sparse_omitted = bool(sparse_checkout_roots) and not any(
            posix_path == root or root in posix_path.parents
            for root in sparse_checkout_roots
        )
        if is_sparse_omitted and "D" in change:
            continue
        relevant_status.append(line)
    dirty = bool(relevant_status)
    return {
        "source_commit": commit,
        "source_repo": remote,
        "source_archive_sha256": hashlib.sha256(archive).hexdigest(),
        "archive_backend": archive_backend,
        "archive_stderr": archive_stderr if archive_result.returncode != 0 else None,
        "dirty_worktree": dirty,
        "pinned_status": "source_pinned_dirty_worktree" if dirty else "source_pinned",
        "sparse_checkout_roots": [root.as_posix() for root in sparse_checkout_roots],
    }


def existing_pack_errors(art_dir: Path, spec: dict) -> list[str]:
    """Check an existing pack before allowing the extractor to skip it."""
    receipt_path = art_dir / "source_receipt.json"
    if not receipt_path.is_file():
        return ["existing artifact pack has no source_receipt.json"]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"existing source receipt cannot be read: {error}"]
    errors = []
    if receipt.get("source_repo") != spec["source_repo"]:
        errors.append("existing artifact source repository does not match source lock")
    if receipt.get("source_commit") != spec["commit"]:
        errors.append("existing artifact source commit does not match source lock")
    return errors


def clear_generated_pack_outputs(art_dir: Path, harness_dir: Path) -> None:
    """Remove only extractor-owned contract outputs before a forced rebuild.

    A changed contract selection must not leave stale ABI/bytecode/layout files
    in the new manifest (for example, a previous ``EndpointV2`` selection next
    to the current ``SendUln302`` selection). The paths are derived from the
    explicitly selected artifact and harness roots; metadata is overwritten by
    the rebuild below.
    """
    for directory_name in ("abi", "bytecode", "storage_layout"):
        directory = art_dir / directory_name
        if not directory.is_dir():
            continue
        for child in directory.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    fixtures = harness_dir / "fixtures"
    if fixtures.is_dir():
        for child in fixtures.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()


def source_mount_layout(source_cache: Path, lineage_id: str, spec: dict) -> tuple[Path, str]:
    """Resolve a lineage root and its Solidity working directory safely.

    ``workdir`` in the historical specification is repository-relative and
    often includes the lineage directory itself.  The Docker mount must still
    expose the Git root so that archive/commit checks and monorepo imports use
    the exact locked tree.
    """
    source_root = (source_cache / lineage_id).resolve()
    raw_workdir = Path(str(spec.get("workdir", "")))
    if raw_workdir.is_absolute() or ".." in raw_workdir.parts:
        raise ValueError(f"{lineage_id}: workdir must be a relative path without '..'")
    parts = raw_workdir.parts
    if parts and parts[0] == lineage_id:
        parts = parts[1:]
    relative_workdir = Path(*parts) if parts else Path()
    raw_subpath = Path(str(spec.get("subpath", "")))
    if raw_subpath.is_absolute() or ".." in raw_subpath.parts:
        raise ValueError(f"{lineage_id}: subpath must be a relative path without '..'")
    combined = relative_workdir / raw_subpath
    return source_root, str(combined).replace("\\", "/") if str(combined) != "." else ""


def _compiler_cache_volume_name(lineage_id: str) -> str:
    """Return a unique, bounded name for one extraction's SVM cache."""
    digest = hashlib.sha256(lineage_id.encode("utf-8")).hexdigest()[:12]
    return f"crossllm-solc-{os.getpid()}-{digest}"


def create_compiler_cache_volume(lineage_id: str) -> str:
    """Create a disposable lineage-scoped Docker volume for SVM binaries."""
    name = _compiler_cache_volume_name(lineage_id)
    result = subprocess.run(
        [
            "docker", "volume", "create",
            "--label", "crossllm.scope=development-compiler-cache",
            "--label", f"crossllm.lineage={lineage_id}",
            name,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"unable to create compiler cache volume {name}: "
            f"{result.stderr.strip()}"
        )
    return name


def remove_compiler_cache_volume(name: str) -> None:
    """Remove one disposable compiler cache and fail closed on cleanup errors."""
    if not _DOCKER_VOLUME_NAME.fullmatch(name):
        raise ValueError("invalid compiler cache volume name")
    result = subprocess.run(
        ["docker", "volume", "rm", name],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"unable to remove compiler cache volume {name}: "
            f"{result.stderr.strip()}"
        )


def _compiler_container_command(volume: str, image: str, *args: str) -> list[str]:
    """Build a no-network command operating only on the compiler volume."""
    if not _DOCKER_VOLUME_NAME.fullmatch(volume):
        raise ValueError("invalid compiler cache volume name")
    if not _DIGEST_REF.search(image):
        raise ValueError("compiler image must be digest-pinned")
    if not args:
        raise ValueError("compiler command cannot be empty")
    return [
        "docker", "run", "--rm", "--pull=never", "--network=none",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit", "32", "--memory", "512m",
        "--mount", f"type=volume,source={volume},target=/compiler",
        "-u", "0:0", "--entrypoint",
        args[0], image,
        *args[1:],
    ]


def ensure_compiler_image(image: str) -> None:
    """Ensure a digest-pinned compiler image is local before no-network runs."""
    if not _DIGEST_REF.search(image):
        raise ValueError("compiler image must be digest-pinned")
    inspected = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if inspected.returncode == 0:
        return
    pulled = subprocess.run(
        ["docker", "pull", image],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if pulled.returncode != 0:
        raise RuntimeError(
            f"unable to pull locked compiler image {image}: "
            f"{pulled.stderr.strip()}"
        )


def populate_compiler_cache_volume(volume: str, solc_version: str) -> dict[str, str]:
    """Copy and verify a locked solc binary into a disposable Docker volume."""
    image = solc_image_for_version(solc_version)
    ensure_compiler_image(image)

    copy_command = _compiler_container_command(
        volume, image, "cp", "/usr/local/bin/solc", _SOLC_PATH
    )
    copy_result = subprocess.run(
        copy_command, capture_output=True, text=True, check=False, timeout=120
    )
    if copy_result.returncode != 0:
        raise RuntimeError(
            f"unable to copy solc {solc_version} from {image}: "
            f"{copy_result.stderr.strip()}"
        )

    chmod_command = _compiler_container_command(volume, image, "chmod", "0555", _SOLC_PATH)
    chmod_result = subprocess.run(
        chmod_command, capture_output=True, text=True, check=False, timeout=30
    )
    if chmod_result.returncode != 0:
        raise RuntimeError(
            f"unable to make solc {solc_version} executable: "
            f"{chmod_result.stderr.strip()}"
        )

    version_command = _compiler_container_command(volume, image, _SOLC_PATH, "--version")
    version_result = subprocess.run(
        version_command, capture_output=True, text=True, check=False, timeout=30
    )
    version_output = f"{version_result.stdout}\n{version_result.stderr}"
    if version_result.returncode != 0 or f"Version: {solc_version}+" not in version_output:
        raise RuntimeError(
            f"compiler version verification failed for {solc_version}: "
            f"{version_output.strip()}"
        )

    hash_command = _compiler_container_command(volume, image, "sha256sum", _SOLC_PATH)
    hash_result = subprocess.run(
        hash_command, capture_output=True, text=True, check=False, timeout=30
    )
    match = re.search(r"\b([0-9a-fA-F]{64})\b", hash_result.stdout)
    if hash_result.returncode != 0 or match is None:
        raise RuntimeError(
            f"compiler binary hash verification failed for {solc_version}: "
            f"{hash_result.stderr.strip()}"
        )
    return {
        "image": image,
        "path": _SOLC_PATH,
        "version": solc_version,
        "binary_sha256": match.group(1).lower(),
    }


def extract_lineage(
    lineage_id: str,
    spec: dict,
    *,
    artifacts_dir: Path = ARTIFACTS_DIR,
    harness_root: Path = HARNESS_DIR,
    source_cache: Path = PRIVATE_SOURCES,
    force: bool = False,
    docker_archive_image: str | None = None,
    docker_network: str = "none",
    compiler_cache_volume: str | None = None,
    compiler_info: dict[str, str] | None = None,
    inspect_timeout_seconds: int = 120,
):
    print(f"=== Extracting {lineage_id} ===")
    art_dir = artifacts_dir / lineage_id
    harness_dir = harness_root / lineage_id

    # If manifest and all checksums already exist, skip unless forced
    if (art_dir / "manifest.json").exists() and not force:
        errors = existing_pack_errors(art_dir, spec)
        if errors:
            raise RuntimeError(f"stale artifact pack: {'; '.join(errors)}")
        print(f"  Artifacts already present for {lineage_id}, skipping.")
        return

    abi_dir = art_dir / "abi"
    bc_dir = art_dir / "bytecode"
    sl_dir = art_dir / "storage_layout"
    
    abi_dir.mkdir(parents=True, exist_ok=True)
    bc_dir.mkdir(parents=True, exist_ok=True)
    sl_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "fixtures").mkdir(parents=True, exist_ok=True)
    
    source_root, subpath = source_mount_layout(source_cache, lineage_id, spec)
    source_info = source_snapshot(
        source_root,
        spec,
        docker_archive_image=docker_archive_image,
        source_cache=source_cache,
        lineage_id=lineage_id,
    )
    raw_dependency_roots = spec.get("dependency_roots", [])
    if not isinstance(raw_dependency_roots, list):
        raise RuntimeError(f"{lineage_id}: dependency_roots must be a list")
    dependency_info = dependency_closure(source_root, tuple(raw_dependency_roots))
    selection_info = deterministic_source_selection(source_root, subpath, spec["contracts"])

    symbols = {
        "lineage_id": lineage_id,
        "protocol": spec["protocol"],
        "contracts": {}
    }
    contract_provenance: dict[str, dict[str, object]] = {}
    extracted_contracts: dict[str, dict[str, object]] = {}
    stable_symbols: list[dict[str, object]] = []

    # Keep all compiler output in memory until every selected contract has
    # completed. A failed forced rebuild must leave the last known-good pack
    # intact instead of replacing it with a partial/stale mixture.
    for cname, cspec in spec["contracts"].items():
        print(f"  Extracting contract: {cname} ({cspec})")
        source_file = _resolve_contract_source(source_root, subpath, cspec)
        source_file_hash = _file_hash(source_file)
        source_target = require_concrete_source_target(
            source_file, _contract_declared_name(cspec)
        )
        contract_domains = spec.get("contract_domains", {})
        if not isinstance(contract_domains, dict) or cname not in contract_domains:
            raise RuntimeError(f"{lineage_id}/{cname} has no explicit contract domain assignment")
        contract_domain = contract_domains[cname]
        if contract_domain not in {"source", "destination", "shared"}:
            raise RuntimeError(f"{lineage_id}/{cname} has invalid contract domain {contract_domain!r}")
        # 1. ABI
        inspect_options = {
            "subpath": subpath,
            "docker_network": docker_network,
            "solc_version": spec.get("solc"),
            "optimizer": spec.get("optimizer", False),
            "optimizer_runs": spec.get("optimizer_runs", 200),
            "compiler_cache_volume": compiler_cache_volume,
            "compiler_path": compiler_info.get("path") if compiler_info else None,
            "timeout_seconds": inspect_timeout_seconds,
        }
        dependency_root_spec = spec.get("dependency_root")
        if dependency_root_spec is not None:
            if not isinstance(dependency_root_spec, str) or not dependency_root_spec:
                raise RuntimeError(f"{lineage_id}: dependency_root must be a non-empty relative path")
            dependency_root_path = (source_root / dependency_root_spec).resolve()
            try:
                dependency_root_path.relative_to(source_root)
            except ValueError as error:
                raise RuntimeError(f"{lineage_id}: dependency_root escapes locked checkout") from error
            inspect_options["dependency_root"] = dependency_root_path
        raw_mounts = spec.get("dependency_mounts", ())
        if raw_mounts:
            if not isinstance(raw_mounts, list):
                raise RuntimeError(f"{lineage_id}: dependency_mounts must be a list")
            mounts: list[tuple[Path, str]] = []
            for raw_mount in raw_mounts:
                if not isinstance(raw_mount, dict) or not isinstance(raw_mount.get("source"), str) or not isinstance(raw_mount.get("target"), str):
                    raise RuntimeError(f"{lineage_id}: dependency mount must contain source and target strings")
                mount_source = (source_root / raw_mount["source"]).resolve()
                try:
                    mount_source.relative_to(source_root)
                except ValueError as error:
                    raise RuntimeError(f"{lineage_id}: dependency mount escapes locked checkout") from error
                mounts.append((mount_source, raw_mount["target"]))
            inspect_options["dependency_mounts"] = tuple(mounts)
        raw_remappings = spec.get("dependency_remappings", ())
        if raw_remappings:
            if not isinstance(raw_remappings, list):
                raise RuntimeError(f"{lineage_id}: dependency_remappings must be a list")
            remapping_pairs: list[tuple[str, str]] = []
            for raw_remapping in raw_remappings:
                if not isinstance(raw_remapping, dict) or not isinstance(raw_remapping.get("prefix"), str) or not isinstance(raw_remapping.get("target"), str):
                    raise RuntimeError(f"{lineage_id}: dependency remapping must contain prefix and target strings")
                remapping_pairs.append((raw_remapping["prefix"], raw_remapping["target"]))
            inspect_options["remappings"] = tuple(remapping_pairs)
        raw_scratch_mounts = spec.get("scratch_mounts", ())
        if raw_scratch_mounts:
            if not isinstance(raw_scratch_mounts, list) or not all(
                isinstance(path, str) for path in raw_scratch_mounts
            ):
                raise RuntimeError(f"{lineage_id}: scratch_mounts must be a list of strings")
            inspect_options["scratch_mounts"] = tuple(raw_scratch_mounts)
        abi_json_str = run_forge_inspect(source_root, cspec, "abi", as_json=True, **inspect_options)
        abi_data = json.loads(abi_json_str)
        creation_bc = run_forge_inspect(source_root, cspec, "bytecode", as_json=False, **inspect_options)
        deployed_bc = run_forge_inspect(source_root, cspec, "deployedBytecode", as_json=False, **inspect_options)
        _require_deployable_bytecode(cname, creation_bc, deployed_bc)
        sl_json_str = run_forge_inspect(source_root, cspec, "storage", as_json=True, **inspect_options)
        sl_data = json.loads(sl_json_str)
        stable_symbols.extend(
            stable_abi_symbols(
                cname,
                cspec.split(":")[0],
                source_file_hash,
                abi_data,
                sl_data,
                contract_domain,
            )
        )

        extracted_contracts[cname] = {
            "source_path": cspec.split(":")[0],
            "source_file_sha256": source_file_hash,
            "source_target": source_target,
            "abi": abi_data,
            "creation_bytecode": creation_bc,
            "deployed_bytecode": deployed_bc,
            "storage_layout": sl_data,
        }

    # Only now mutate extractor-owned output paths. This is intentionally after
    # all forge probes, so timeout/compiler failures are non-destructive.
    clear_generated_pack_outputs(art_dir, harness_dir)
    for cname, extracted in extracted_contracts.items():
        abi_data = extracted["abi"]
        creation_bc = str(extracted["creation_bytecode"])
        deployed_bc = str(extracted["deployed_bytecode"])
        sl_data = extracted["storage_layout"]
        abi_path = abi_dir / f"{cname}.json"
        abi_path.write_text(json.dumps(abi_data, indent=2), encoding="utf-8")
        creation_path = bc_dir / f"{cname}.creation.hex"
        deployed_path = bc_dir / f"{cname}.deployed.hex"
        creation_path.write_text(creation_bc, encoding="utf-8")
        deployed_path.write_text(deployed_bc, encoding="utf-8")
        storage_path = sl_dir / f"{cname}.json"
        storage_path.write_text(json.dumps(sl_data, indent=2), encoding="utf-8")

        source_path = str(extracted["source_path"])
        source_file_hash = str(extracted["source_file_sha256"])
        # Collect symbols
        functions = [item["name"] for item in abi_data if item.get("type") == "function"]
        events = [item["name"] for item in abi_data if item.get("type") == "event"]
        storage_vars = [item.get("label", f"slot_{item.get('slot')}") for item in sl_data.get("storage", [])]
        
        symbols["contracts"][cname] = {
            "source_path": source_path,
            "source_file_sha256": source_file_hash,
            "source_target": extracted["source_target"],
            "function_count": len(functions),
            "functions": sorted(list(set(functions))),
            "event_count": len(events),
            "events": sorted(list(set(events))),
            "storage_slot_count": len(storage_vars),
            "storage_slots": storage_vars
        }
        contract_provenance[cname] = {
            "source_path": source_path,
            "source_file_sha256": source_file_hash,
            "source_target": extracted["source_target"],
            "abi_path": str(abi_path.relative_to(art_dir)).replace("\\", "/"),
            "abi_sha256": _file_hash(abi_path),
            "creation_bytecode_path": str(creation_path.relative_to(art_dir)).replace("\\", "/"),
            "creation_bytecode_sha256": _file_hash(creation_path),
            "deployed_bytecode_path": str(deployed_path.relative_to(art_dir)).replace("\\", "/"),
            "deployed_bytecode_sha256": _file_hash(deployed_path),
            "storage_layout_path": str(storage_path.relative_to(art_dir)).replace("\\", "/"),
            "storage_layout_sha256": _file_hash(storage_path),
        }

    # Write symbols.json
    stable_symbols.sort(key=lambda item: str(item["symbol_id"]))
    symbols["stable_symbols"] = stable_symbols
    symbols["stable_symbols_sha256"] = _canonical_hash(stable_symbols)
    symbols["domain_assignments"] = dict(
        sorted((str(key), str(value)) for key, value in spec["contract_domains"].items())
    )
    symbols["source_selection_hash"] = selection_info["selection_hash"]
    (art_dir / "symbols.json").write_text(json.dumps(symbols, indent=2), encoding="utf-8")
    (art_dir / "selection.json").write_text(json.dumps(selection_info, indent=2), encoding="utf-8")
    
    # Write source_receipt.json
    source_receipt = {
        "lineage_id": lineage_id,
        "host_id": spec["host_id"],
        "source_repo": spec["source_repo"],
        "source_commit": spec["commit"],
        "source_archive_sha256": source_info["source_archive_sha256"],
        "archive_format": "tar",
        "archive_command": "git archive --format=tar HEAD",
        "canonical_environment": "resolved from private source cache; inspect runs in pinned Docker",
        "inspect_network": docker_network,
        "archive_backend": source_info["archive_backend"],
        "dirty_worktree": source_info["dirty_worktree"],
        "pinned_status": source_info["pinned_status"],
        "sparse_checkout_roots": source_info.get("sparse_checkout_roots", []),
        "dependency_closure": dependency_info,
        "dependency_root": str(spec.get("dependency_root", "")) or None,
        "dependency_mounts": spec.get("dependency_mounts", []),
        "dependency_remappings": spec.get("dependency_remappings", []),
        "source_selection_hash": selection_info["selection_hash"],
        "artifact_admission_status": "build_probe_only"
    }
    (art_dir / "source_receipt.json").write_text(json.dumps(source_receipt, indent=2), encoding="utf-8")
    
    # Write scope.json
    scope = {
        "lineage_id": lineage_id,
        "protocol": spec["protocol"],
        "split": spec["split"],
        "in_scope_contracts": list(spec["contracts"].keys()),
        "entry_points": {cname: cspec.split(":")[0] for cname, cspec in spec["contracts"].items()},
        "channel_type": spec["channel_profile"]["channel_type"],
        "topology": spec["channel_profile"]["topology"],
        "verification_gate": "storage_layout_and_bytecode_verified"
    }
    (art_dir / "scope.json").write_text(json.dumps(scope, indent=2), encoding="utf-8")
    
    # Write build_info.json
    build_info = {
        "lineage_id": lineage_id,
        "compiler": "solc",
        "compiler_version": spec["solc"],
        "compiler_image": compiler_info.get("image") if compiler_info else None,
        "compiler_binary_path": compiler_info.get("path") if compiler_info else None,
        "compiler_binary_sha256": compiler_info.get("binary_sha256") if compiler_info else None,
        "dependency_closure": dependency_info,
        "dependency_root": str(spec.get("dependency_root", "")) or None,
        "dependency_mounts": spec.get("dependency_mounts", []),
        "dependency_remappings": spec.get("dependency_remappings", []),
        "source_selection": selection_info,
        "build_framework": "foundry",
        "docker_build_image": DOCKER_FOUNDRY,
        "docker_network": docker_network,
        "compiler_scratch": (
            "read-only source bind; /tmp/foundry-cache and /tmp/foundry-out "
            "disposable; /compiler is a lineage-scoped disposable Docker volume"
            if compiler_cache_volume is not None
            else "read-only source bind; /tmp/foundry-cache, /tmp/foundry-out and /root/.svm disposable tmpfs"
        ),
        "build_command": "forge inspect <Contract> [abi|storage|bytecode]",
        "optimizer": bool(spec.get("optimizer", False)),
        "optimizer_runs": int(spec.get("optimizer_runs", 200)),
        "compiler_settings": {
            "compiler": "solc",
            "compiler_version": spec["solc"],
            "compiler_image": compiler_info.get("image") if compiler_info else None,
            "compiler_binary_sha256": compiler_info.get("binary_sha256") if compiler_info else None,
            "optimizer": bool(spec.get("optimizer", False)),
            "optimizer_runs": int(spec.get("optimizer_runs", 200)),
            "build_framework": "foundry",
        },
        "verification_status": "inspect_probe_only",
        "verified": False
    }
    build_info["compiler_settings_sha256"] = _canonical_hash(build_info["compiler_settings"])
    (art_dir / "build_info.json").write_text(json.dumps(build_info, indent=2), encoding="utf-8")
    
    # Write channel_profile.json
    (art_dir / "channel_profile.json").write_text(json.dumps(spec["channel_profile"], indent=2), encoding="utf-8")
    
    # Write deployment.json
    deployment = {
        "lineage_id": lineage_id,
        "protocol": spec["protocol"],
        "deployment_schema": "deterministic_paired_domain",
        "mock_domains": [
            {"domain_id": 1, "domain_name": "DomainA", "network_id": 1001},
            {"domain_id": 2, "domain_name": "DomainB", "network_id": 1002}
        ],
        "contracts": {
            cname: {
                "contract_name": cname,
                **contract_provenance[cname],
                "constructor_args": [],
                "constructor_args_sha256": _canonical_hash([]),
                "initializer": "initialize" if any("initialize" in f for f in symbols["contracts"][cname]["functions"]) else None,
                "initializer_args_sha256": _canonical_hash([]),
                "is_upgradeable": any("initialize" in f for f in symbols["contracts"][cname]["functions"]),
                "proxy": {
                    "is_proxy": False,
                    "implementation_source_path": None,
                    "implementation_code_hash": None,
                },
                "linked_libraries": [],
            }
            for cname in spec["contracts"]
        }
    }
    (art_dir / "deployment.json").write_text(json.dumps(deployment, indent=2), encoding="utf-8")
    
    # Write normal_workflow.json
    first_contract = list(spec["contracts"].keys())[0]
    last_contract = list(spec["contracts"].keys())[-1]
    first_events = symbols["contracts"][first_contract]["events"]
    normal_workflow = {
        "lineage_id": lineage_id,
        "workflow_name": f"{lineage_id}_normal_dispatch_and_execution",
        "description": f"Standard cross-domain lifecycle for {spec['protocol']} from source dispatch to destination receipt.",
        "steps": [
            {
                "step_index": 1,
                "action": "deposit_or_dispatch",
                "contract": first_contract,
                "expected_event": first_events[0] if first_events else "Transfer"
            },
            {
                "step_index": 2,
                "action": "relay_or_attest",
                "actor": "relayer_or_oracle",
                "proof_type": spec["channel_profile"]["message_passing"]
            },
            {
                "step_index": 3,
                "action": "settle_or_execute",
                "contract": last_contract,
                "expected_state_transition": "message_nonce_incremented_or_executed_flag_set"
            }
        ],
        "harness_assertion": "assert_normal_workflow_completes_without_revert"
    }
    (art_dir / "normal_workflow.json").write_text(json.dumps(normal_workflow, indent=2), encoding="utf-8")
    
    # Write license.json
    license_info = {
        "lineage_id": lineage_id,
        "protocol": spec["protocol"],
        "declared_license": spec["license"],
        "source_repository": spec["source_repo"],
        "spdx_identifier": spec["license"],
        "commercial_use_restrictions": "BUSL" in spec["license"],
        "redistribution_permitted": None,
        "license_review_status": "pending_component_review"
    }
    (art_dir / "license.json").write_text(json.dumps(license_info, indent=2), encoding="utf-8")
    
    # Write harness files
    harness_config = {
        "lineage_id": lineage_id,
        "protocol": spec["protocol"],
        "split": spec["split"],
        "harness_version": "1.0.0",
        "harness_status": "generated_fixture",
        "source_backed": False,
        "source_commit": spec["commit"],
        "contracts": list(spec["contracts"].keys()),
        "test_runner": "pytest_or_foundry",
        "domain_pair": {
            "source": {"id": 1, "name": "DomainA", "type": "evm"},
            "destination": {"id": 2, "name": "DomainB", "type": "evm"}
        },
        "workflow_file": "normal_workflow_test.py"
    }
    (harness_dir / "harness_config.json").write_text(json.dumps(harness_config, indent=2), encoding="utf-8")
    
    environment_config = {
        "lineage_id": lineage_id,
        "solc_version": spec["solc"],
        "evm_version": "cancun",
        "initial_accounts": [
            {"label": "admin", "balance_wei": "1000000000000000000000"},
            {"label": "relayer", "balance_wei": "1000000000000000000000"},
            {"label": "user", "balance_wei": "1000000000000000000000"}
        ],
        "gas_limit": 30000000
    }
    (harness_dir / "environment.json").write_text(json.dumps(environment_config, indent=2), encoding="utf-8")
    
    # Harness runner is always containerized, even though the generated
    # development harness itself is not source-backed evidence.
    harness_test_py = render_harness_runner(lineage_id, spec)
    (harness_dir / "normal_workflow_test.py").write_text(harness_test_py, encoding="utf-8")
    
    # Manifest for lineage
    file_hashes = {}
    for p in sorted(art_dir.rglob("*")):
        if p.is_file() and p.name not in ("checksums.sha256", "manifest.json"):
            rel = str(p.relative_to(art_dir)).replace("\\", "/")
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            file_hashes[rel] = sha
            
    manifest = {
        "lineage_id": lineage_id,
        "protocol": spec["protocol"],
        "split": spec["split"],
        "artifact_count": len(file_hashes),
        "files": file_hashes
    }
    (art_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    
    # Checksums
    checksum_lines = [f"{sha}  {rel}" for rel, sha in sorted(file_hashes.items())]
    manifest_sha = hashlib.sha256((art_dir / "manifest.json").read_bytes()).hexdigest()
    checksum_lines.append(f"{manifest_sha}  manifest.json")
    (art_dir / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(f"  Artifacts saved to {art_dir} ({len(file_hashes)} files hashed)")


def main(
    *,
    source_cache: Path = PRIVATE_SOURCES,
    artifacts_dir: Path = ARTIFACTS_DIR,
    harness_root: Path = HARNESS_DIR,
    selected_lineages: set[str] | None = None,
    force: bool = False,
    docker_archive_image: str | None = None,
    docker_network: str = "none",
    inspect_timeout_seconds: int = 120,
) -> int:
    metadata_errors = validate_lineage_specs(LINEAGE_SPECS, load_source_lock())
    metadata_errors.extend(validate_toolchain_image())
    metadata_errors.extend(validate_solc_lock())
    if metadata_errors:
        print(
            "REFUSING extraction because generator metadata is not locked:",
            file=sys.stderr,
        )
        for error in metadata_errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    selected = {
        lineage_id: spec for lineage_id, spec in LINEAGE_SPECS.items()
        if selected_lineages is None or lineage_id in selected_lineages
    }
    unknown = (selected_lineages or set()) - set(LINEAGE_SPECS)
    if unknown:
        print(f"Unknown lineage identifiers: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    source_cache = source_cache.resolve()
    artifacts_dir = artifacts_dir.resolve()
    harness_root = harness_root.resolve()
    print(f"Starting extraction for {len(selected)} lineages...")
    errors: list[str] = []
    for lineage_id, spec in selected.items():
        compiler_cache_volume: str | None = None
        try:
            artifact_manifest = artifacts_dir / lineage_id / "manifest.json"
            if force or not artifact_manifest.exists():
                compiler_cache_volume = create_compiler_cache_volume(lineage_id)
                compiler_info = populate_compiler_cache_volume(
                    compiler_cache_volume, str(spec["solc"])
                )
            else:
                compiler_info = None
            extract_lineage(
                lineage_id,
                spec,
                artifacts_dir=artifacts_dir,
                harness_root=harness_root,
                source_cache=source_cache,
                force=force,
                docker_archive_image=docker_archive_image,
                docker_network=docker_network,
                compiler_cache_volume=compiler_cache_volume,
                compiler_info=compiler_info,
                inspect_timeout_seconds=inspect_timeout_seconds,
            )
        except Exception as e:
            print(f"ERROR extracting {lineage_id}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            errors.append(f"{lineage_id}: {e}")
        finally:
            if compiler_cache_volume is not None:
                try:
                    remove_compiler_cache_volume(compiler_cache_volume)
                except Exception as cleanup_error:
                    print(
                        f"ERROR cleaning compiler cache volume {compiler_cache_volume}: "
                        f"{cleanup_error}",
                        file=sys.stderr,
                    )
                    errors.append(f"{lineage_id}: compiler cache cleanup failed")
    if errors:
        print(f"Extraction failed for {len(errors)} lineage(s).", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-cache", type=Path, default=PRIVATE_SOURCES,
        help="private source cache root (default: %(default)s)",
    )
    parser.add_argument(
        "--artifacts-out", type=Path, default=ARTIFACTS_DIR,
        help="artifact output root (default: %(default)s)",
    )
    parser.add_argument(
        "--harness-out", type=Path, default=HARNESS_DIR,
        help="harness output root (default: %(default)s)",
    )
    parser.add_argument(
        "--lineage", action="append", dest="lineages", metavar="LINEAGE_ID",
        help="extract only this lineage; repeat for multiple lineages",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="rebuild an existing output pack after validating its locked source metadata",
    )
    parser.add_argument(
        "--docker-archive-image", default=None, metavar="IMAGE@SHA256",
        help="optional pinned Linux image for host git-archive failures",
    )
    parser.add_argument(
        "--docker-network", choices=("none", "bridge"), default="none",
        help="Foundry inspect network; bridge is an explicit development probe for downloading pinned solc",
    )
    parser.add_argument(
        "--inspect-timeout-seconds", type=int, default=120,
        help="timeout for each forge inspect probe (default: %(default)s)",
    )
    args = parser.parse_args()
    raise SystemExit(main(
        source_cache=args.source_cache,
        artifacts_dir=args.artifacts_out,
        harness_root=args.harness_out,
        selected_lineages=set(args.lineages) if args.lineages else None,
        force=args.force,
        docker_archive_image=args.docker_archive_image,
        docker_network=args.docker_network,
        inspect_timeout_seconds=args.inspect_timeout_seconds,
    ))
